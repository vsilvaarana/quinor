"""Analisis de un clip con YOLO. HU-07 y HU-08.

"El servicio YOLO procesa el clip y devuelve el numero de sacos que cruzan la
linea de carga" (HU-07, criterio 1), y "se detecta y sigue a cada persona con un
ID temporal durante el clip" (HU-08, criterio 1).

Una sola pasada por el video para las dos cosas. El clip ya esta abierto, y
ultralytics devuelve sacos y personas en la misma inferencia: separarlas en dos
recorridos doblaria el coste sin ganar nada, y el RNF-01 no tiene ese margen de
sobra.

El trabajo se reparte en capas: ultralytics detecta y sigue objetos fotograma a
fotograma, `app/conteo.py` decide que sacos cruzaron y `app/personas.py` quien
estuvo en la zona de carga y cuanto. Esa separacion es lo que permite probar las
dos reglas sin GPU y sin video, y cambiar de modelo o de version de ultralytics
sin tocarlas.

El seguimiento lo hace ByteTrack, el que trae ultralytics, tal como dice el
apartado 6.4. Es lo que asigna el identificador temporal que el apartado 8 exige
para no vincular nada a personas concretas: vale dentro de este clip y se pierde
con el.
"""
from __future__ import annotations

import dataclasses
import pathlib
import time

import structlog

from app.anomalias import Anomalia, evaluar
from app.conteo import ContadorDeLinea, Deteccion, Punto
from app.config import Ajustes
from app.fotogramas import (CENTRO_DEL_CLIP, FotogramaClave, Momento,
                            SelectorDeFotogramas, momentos_del_fotograma)
from app.personas import Resumen, SeguidorDePersonas, Zona

log = structlog.get_logger("quinor.analisis")


class ClipIlegible(RuntimeError):
    """El archivo no existe o no se puede abrir como video."""


class ModeloNoDisponible(RuntimeError):
    """Faltan los pesos del modelo. Sin modelo no hay conteo que dar."""


@dataclasses.dataclass(frozen=True)
class Resultado:
    """Lo que el servicio devuelve de un clip."""

    sacos_contados: int
    sacos_entrantes: int
    sacos_salientes: int
    personas_detectadas: int
    fotogramas_procesados: int
    fotogramas_totales: int
    duracion_del_clip_s: float
    segundos_de_proceso: float
    modelo: str
    detecciones_de_saco: int
    # HU-08: quien estuvo en la zona de carga y cuanto. Identificadores
    # temporales del rastreador, nada que permita reconocer a nadie (RN-08).
    personas: Resumen | None = None
    anomalia: Anomalia | None = None
    # HU-09: los pocos fotogramas que explican la carga. Van al modelo de
    # vision-lenguaje y, guardados, son el fotograma que HU-12 mostrara.
    fotogramas_clave: tuple[FotogramaClave, ...] = ()
    # Fotogramas en los que hubo detecciones pero ninguna llego a tener
    # identificador de seguimiento. Ver `seguimiento_perdido`.
    fotogramas_sin_seguimiento: int = 0

    @property
    def mas_rapido_que_el_video(self) -> bool:
        """RNF-01: un clip de 7 min se analiza en menos de 3 en planta."""
        return self.segundos_de_proceso < self.duracion_del_clip_s

    @property
    def seguimiento_perdido(self) -> bool:
        """El detector vio sacos y el rastreador no siguio ninguno.

        Es el fallo silencioso de este servicio: el conteo sale cero y todo
        parece correcto. Pasa cuando se miran fotogramas demasiado separados y
        un saco avanza mas que su propio ancho entre uno y otro, de modo que no
        solapa con su prediccion y nunca recibe identificador. Sin esta senal,
        un YOLO_FRAME_STRIDE mal puesto se descubriria con el primer camion que
        alguien reclamase.
        """
        return self.detecciones_de_saco == 0 and self.fotogramas_sin_seguimiento > 0


def _cargar_modelo(ajustes: Ajustes):
    """Carga los pesos una vez. Importar ultralytics tarda, asi que se hace aqui.

    Con el modelo en el arranque, un servicio que nunca recibe una peticion
    seguiria pagando el arranque de PyTorch; y con el import arriba, las pruebas
    de la regla de conteo cargarian torch sin necesitarlo.
    """
    if not ajustes.ruta_pesos.exists():
        raise ModeloNoDisponible(
            f"No estan los pesos en {ajustes.ruta_pesos}. Entrenar con "
            f"sim/entrenar.py o apuntar YOLO_WEIGHTS al modelo activo.")
    from ultralytics import YOLO

    return YOLO(str(ajustes.ruta_pesos))


@dataclasses.dataclass
class _Video:
    """Datos del clip que hacen falta antes de empezar."""

    fotogramas: int
    fps: float

    @property
    def duracion_s(self) -> float:
        return self.fotogramas / self.fps if self.fps else 0.0


def _abrir(ruta: pathlib.Path) -> _Video:
    import cv2

    if not ruta.exists():
        raise ClipIlegible(f"No existe el clip {ruta}")
    captura = cv2.VideoCapture(str(ruta))
    try:
        if not captura.isOpened():
            raise ClipIlegible(f"No se pudo abrir {ruta} como video")
        return _Video(
            fotogramas=int(captura.get(cv2.CAP_PROP_FRAME_COUNT)) or 0,
            fps=float(captura.get(cv2.CAP_PROP_FPS)) or 0.0,
        )
    finally:
        captura.release()


def _detecciones_del_fotograma(resultado, nombres: dict[int, str]) -> list[Deteccion]:
    """Traduce la salida de ultralytics a las detecciones que el contador entiende.

    Solo lo que trae identificador de seguimiento: una deteccion sin id no se
    puede cruzar con la del fotograma anterior, y contar sin seguir es contar
    fotogramas, no sacos.
    """
    cajas = getattr(resultado, "boxes", None)
    if cajas is None or cajas.id is None:
        return []

    detecciones = []
    identificadores = cajas.id.int().tolist()
    clases = cajas.cls.int().tolist()
    confianzas = cajas.conf.tolist()
    centros = cajas.xywhn.tolist()          # normalizado: x, y, ancho, alto
    for identificador, clase, confianza, (x, y, _w, _h) in zip(
            identificadores, clases, confianzas, centros):
        detecciones.append(Deteccion(
            id_seguimiento=int(identificador),
            clase=nombres.get(int(clase), str(clase)),
            confianza=float(confianza),
            centro=Punto(x=float(x), y=float(y)),
        ))
    return detecciones


def _sin_seguimiento(resultado) -> bool:
    """Hubo detecciones en el fotograma pero ninguna con identificador.

    Un fotograma asi no aporta nada al conteo. Uno suelto es normal, el
    rastreador necesita ver un objeto dos veces antes de darle identificador.
    Todos seguidos significan otra cosa, y de eso avisa `seguimiento_perdido`.
    """
    cajas = getattr(resultado, "boxes", None)
    if cajas is None or cajas.id is not None:
        return False
    return len(cajas.cls.int().tolist()) > 0


def analizar(ajustes: Ajustes, clip: pathlib.Path, modelo=None) -> Resultado:
    """Cuenta los sacos que cruzan la linea en ese clip.

    `modelo` se puede inyectar para las pruebas, igual que los ajustes: es lo
    que permite comprobar el recorrido completo sin cargar PyTorch.
    """
    video = _abrir(clip)
    modelo = modelo if modelo is not None else _cargar_modelo(ajustes)
    contador = ContadorDeLinea(
        linea=ajustes.linea, clase=ajustes.clase_saco,
        invertir=ajustes.invertir_sentido, memoria=ajustes.memoria_de_seguimiento)

    # HU-08 va en la misma pasada que HU-07: el video ya esta abierto y las
    # personas ya vienen detectadas y seguidas. Una segunda pasada doblaria el
    # coste de inferencia, que es justo lo que el RNF-01 no tiene de sobra.
    seguidor = SeguidorDePersonas(
        zona=Zona.desde(ajustes.zona), clase=ajustes.clase_persona,
        permanencia_minima_s=ajustes.permanencia_minima_s)
    # HU-09 tambien va en esta pasada. Guardar la imagen de un fotograma cuesta
    # una copia; volver a abrir el clip para buscarla costaria leerlo entero.
    selector = SelectorDeFotogramas(
        maximo=ajustes.fotogramas_clave, fps=video.fps,
        calidad=ajustes.calidad_jpeg)
    pico_de_personas = 0
    hubo_cruce = False
    ultimo_indice = 0
    imagen_del_centro = None

    detecciones_de_saco = 0
    sin_seguimiento = 0
    procesados = 0
    empezo = time.monotonic()

    # stream=True: ultralytics entrega fotograma a fotograma en lugar de cargar
    # el clip entero en memoria. Un clip de 7 min a 1080p no cabe de otro modo.
    flujo = modelo.track(
        source=str(clip),
        stream=True,
        persist=True,
        tracker="bytetrack.yaml",
        conf=ajustes.confianza_minima,
        iou=ajustes.iou,
        imgsz=ajustes.tamano_inferencia,
        device=ajustes.dispositivo,
        vid_stride=ajustes.salto_de_fotogramas,
        verbose=False,
    )

    for indice, resultado in enumerate(flujo):
        procesados += 1
        nombres = getattr(resultado, "names", {}) or {}
        sin_seguimiento += 1 if _sin_seguimiento(resultado) else 0
        detecciones = _detecciones_del_fotograma(resultado, nombres)
        detecciones_de_saco += sum(1 for d in detecciones if d.clase == ajustes.clase_saco)
        # El indice se multiplica por el salto para que la memoria del contador
        # se mida en fotogramas de video y no en fotogramas mirados.
        del_video = indice * ajustes.salto_de_fotogramas
        cruces = contador.procesar(del_video, detecciones)
        en_zona = seguidor.procesar(del_video, detecciones)

        imagen = getattr(resultado, "orig_img", None)
        selector.considerar(del_video, imagen, momentos_del_fotograma(
            cruces, en_zona, pico_de_personas, not hubo_cruce))
        pico_de_personas = max(pico_de_personas, en_zona)
        hubo_cruce = hubo_cruce or bool(cruces)
        ultimo_indice = del_video
        # Se guarda uno del centro por si la carga transcurre sin nada notable:
        # un evento sin ninguna imagen deja al supervisor sin nada que mirar.
        if imagen is not None and imagen_del_centro is None and \
                del_video >= video.fotogramas // 2:
            imagen_del_centro = imagen

    tardo = time.monotonic() - empezo
    quienes = seguidor.resumen(video.fps, ajustes.salto_de_fotogramas)
    anomalia = evaluar(ajustes, quienes, contador.total)

    if imagen_del_centro is not None:
        selector.considerar(min(video.fotogramas // 2, ultimo_indice),
                            imagen_del_centro,
                            [Momento(motivo=CENTRO_DEL_CLIP,
                                     detalle="Centro del clip.", magnitud=1.0)])
    claves = tuple(selector.claves())
    resultado = Resultado(
        sacos_contados=contador.total,
        sacos_entrantes=contador.entrantes,
        sacos_salientes=contador.salientes,
        personas_detectadas=quienes.cuantas,
        fotogramas_procesados=procesados,
        fotogramas_totales=video.fotogramas,
        duracion_del_clip_s=round(video.duracion_s, 2),
        segundos_de_proceso=round(tardo, 2),
        modelo=ajustes.ruta_pesos.name,
        detecciones_de_saco=detecciones_de_saco,
        fotogramas_sin_seguimiento=sin_seguimiento,
        personas=quienes,
        anomalia=anomalia,
        fotogramas_clave=claves,
    )
    if resultado.seguimiento_perdido:
        log.error(
            "seguimiento_perdido", clip=clip.name,
            fotogramas=sin_seguimiento, salto=ajustes.salto_de_fotogramas,
            detalle="Se detectaron objetos pero ninguno llego a tener "
                    "identificador de seguimiento. Con un salto de fotogramas "
                    "alto, un saco avanza mas que su propio ancho entre un "
                    "fotograma mirado y el siguiente y el rastreador lo pierde. "
                    "Bajar YOLO_FRAME_STRIDE y repetir la validacion.")
    log.info("clip_analizado", clip=clip.name, sacos=resultado.sacos_contados,
             entrantes=resultado.sacos_entrantes, salientes=resultado.sacos_salientes,
             personas=resultado.personas_detectadas,
             maximo_simultaneo=quienes.maximo_simultaneo,
             permanencia_maxima_s=quienes.permanencia_maxima_s,
             anomalia=list(anomalia.codigos),
             fotogramas_clave=[c.motivo for c in claves],
             fotogramas=procesados, segundos=resultado.segundos_de_proceso)
    return resultado
