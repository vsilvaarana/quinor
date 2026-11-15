"""Ajustes del servicio YOLO.

Un unico objeto inmutable que create_app construye una vez y guarda en
app.state.ajustes, igual que en el orquestador y en el grabador. Ningun modulo
lee variables de entorno por su cuenta.

Seccion 8 del documento funcional: ningun secreto vive en el codigo.
"""
from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass

# Criterio 2 de HU-07 y KPI del apartado 3: precision del conteo por carga.
PRECISION_MINIMA_PCT = 95.0

# La linea de carga se expresa en coordenadas relativas (0 a 1) para que no
# dependa de la resolucion de la camara: el apartado 9.1 avisa de que la linea
# se calibra en el piloto, y una camara que se cambie por otra de mas pixeles no
# deberia obligar a recalibrar.
LINEA_POR_DEFECTO = (0.5, 0.0, 0.5, 1.0)     # vertical, por el centro del cuadro

# HU-08: la zona de carga donde se mide la permanencia de las personas. Tambien
# en coordenadas relativas, x1,y1,x2,y2 de esquina a esquina. El cuadro entero
# por defecto: cualquier zona mas estrecha es una decision de planta, y elegirla
# aqui a ciegas dejaria fuera a gente que si estuvo en la rampa.
ZONA_POR_DEFECTO = (0.0, 0.0, 1.0, 1.0)

# Como se cuentan los sacos. "linea" es el conteo de HU-07: cada saco que cruza
# la linea de carga. "pallets" cuenta los pallets que llegan a la zona de carga
# y multiplica por los sacos de un pallet completo. Se agrego el 13/11/2026 con
# el primer video real de la rampa: la camara de planta esta alta y lejos, un
# saco suelto ocupa unos pocos pixeles y ni el modelo sintetico ni uno generico
# lo encuentran, mientras que un pallet si se ve.
MODOS_DE_CONTEO = ("linea", "pallets")


@dataclass(frozen=True)
class Ajustes:
    """Configuracion resuelta de una instancia del servicio."""

    # Pesos del modelo activo. HU-19 versionara esto en la tabla modelo_version;
    # aqui es una ruta y el servicio la informa en cada respuesta.
    ruta_pesos: pathlib.Path = pathlib.Path("modelos/sacos.pt")
    # Nombre de la clase que cuenta como saco. Con el modelo propio es "saco";
    # con un modelo preentrenado de COCO habria que apuntar a otra.
    clase_saco: str = "saco"
    clase_persona: str = "person"

    # Umbral de confianza. Por debajo, la deteccion no cuenta: un saco fantasma
    # inventaria una discrepancia y mandaria a alguien a la rampa para nada.
    confianza_minima: float = 0.35
    # IoU del supresor de no-maximos.
    iou: float = 0.5
    # Lado mayor al que se redimensiona cada fotograma antes de inferir.
    tamano_inferencia: int = 640
    # 1 procesa todos los fotogramas, y es el valor por defecto por una razon
    # que se midio: saltando uno de cada dos, el conteo daba cero.
    #
    # No era el detector, que veia los sacos igual de bien; era el rastreador.
    # ByteTrack asocia por solapamiento, y un saco que avanza mas que su propio
    # ancho entre dos fotogramas mirados no solapa con su prediccion, asi que
    # nunca llega a tener identificador y ningun cruce se cuenta. Subir el salto
    # obliga a repetir la validacion del criterio 2 con la velocidad real de la
    # rampa, no a suponer que "se vera igual".
    #
    # El coste cabe: el RNF-01 da 3 min para un clip de 7, y en la GPU del
    # RNF-06 la inferencia va en milisegundos por fotograma.
    salto_de_fotogramas: int = 1

    # Linea de carga, en coordenadas relativas.
    linea: tuple[float, float, float, float] = LINEA_POR_DEFECTO
    # Un saco cuenta cuando cruza de un lado al otro. Si la camara mira la rampa
    # desde el otro costado, se invierte aqui en lugar de recablear nada.
    invertir_sentido: bool = False
    # Fotogramas que un identificador puede desaparecer sin perder su historia.
    # Una oclusion tipica, una persona que pasa por delante, dura menos.
    memoria_de_seguimiento: int = 30

    # --- HU-08 seguimiento de personas ---------------------------------------
    # Zona de carga, en coordenadas relativas. Dentro de ella se mide la
    # permanencia; quien solo cruza el fondo del cuadro no cuenta como presente.
    zona: tuple[float, float, float, float] = ZONA_POR_DEFECTO
    # Personas que caben en la rampa sin que sea raro. Por encima, la presencia
    # se marca anomala. No es una identidad: es un conteo.
    personas_habituales: int = 3
    # Permanencia por encima de la cual una persona se considera anomala. Una
    # carga dura minutos; quien se queda mucho mas que el resto destaca sin que
    # haga falta saber quien es.
    permanencia_maxima_s: float = 600.0
    # Por debajo de esto, un parpadeo del detector no cuenta como una persona.
    # Sin este minimo, una deteccion suelta inflaria el conteo de la carga.
    permanencia_minima_s: float = 1.0

    # --- HU-09 fotogramas clave ----------------------------------------------
    # Cuantos fotogramas se devuelven. Pocos a proposito: van a una API externa
    # que cobra por imagen, y con mas de cuatro el modelo se pierde en lugar de
    # centrarse en lo que importa.
    fotogramas_clave: int = 4
    calidad_jpeg: int = 80

    # --- Conteo por pallets ---------------------------------------------------
    # "linea" (por defecto, HU-07) o "pallets". Ver MODOS_DE_CONTEO.
    modo_conteo: str = "linea"
    clase_pallet: str = "pallet"
    # Sacos de un pallet completo. Es un dato de QUINOR, no del video: el
    # estandar de planta es 40 sacos de 50 kg. Lo que la camara no puede ver es
    # un pallet al que le faltan sacos por dentro; eso lo sigue cazando la
    # bascula, que es la que dispara el evento.
    sacos_por_pallet: int = 40
    # Zona donde el montacargas deja los pallets junto al camion. No es la zona
    # de personas de HU-08: la gente se mueve por toda la rampa y los pallets se
    # dejan en un sitio concreto. Por defecto el cuadro entero, por la misma
    # razon que la otra: elegirla a ciegas dejaria fuera pallets que si llegaron.
    zona_pallets: tuple[float, float, float, float] = ZONA_POR_DEFECTO
    # Un pallet cuenta cuando se queda este tiempo en la zona. Uno que el
    # montacargas solo cruza camino de otra rampa no se cargo aqui.
    permanencia_pallet_s: float = 2.0
    # Los pallets que ya estaban en la zona al empezar el clip no llegaron en
    # esta carga, o llegaron antes de que empezara el recorte.
    ignorar_inicio_s: float = 3.0
    # Distancia, en coordenadas relativas, por debajo de la cual un identificador
    # nuevo se toma como el mismo pallet que el rastreador perdio. Un operario
    # que pasa por delante basta para que ByteTrack le cambie el numero, y sin
    # esto ese pallet se contaria dos veces: 40 sacos inventados.
    radio_pallet: float = 0.06
    memoria_pallet_s: float = 6.0

    # GPU del RNF-06. "cpu" en desarrollo; "0" o "cuda:0" en planta.
    dispositivo: str = "cpu"

    app_env: str = "development"
    log_level: str = "INFO"

    @property
    def linea_valida(self) -> bool:
        x1, y1, x2, y2 = self.linea
        return (x1, y1) != (x2, y2) and all(0.0 <= v <= 1.0 for v in self.linea)

    @property
    def por_pallets(self) -> bool:
        return self.modo_conteo == "pallets"

    @property
    def zona_valida(self) -> bool:
        x1, y1, x2, y2 = self.zona
        return x2 > x1 and y2 > y1 and all(0.0 <= v <= 1.0 for v in self.zona)


def _env(nombre: str, por_defecto):
    valor = os.environ.get(nombre)
    return por_defecto if valor is None or valor == "" else valor


def parsear_linea(crudo: str) -> tuple[float, float, float, float]:
    """Lee LINEA_CARGA con el formato 'x1,y1,x2,y2' en coordenadas relativas."""
    partes = [p.strip() for p in str(crudo).split(",") if p.strip() != ""]
    if len(partes) != 4:
        raise ValueError(
            f"La linea de carga necesita cuatro numeros 'x1,y1,x2,y2' entre 0 y 1; "
            f"se recibio '{crudo}'")
    try:
        valores = tuple(float(p) for p in partes)
    except ValueError as exc:
        raise ValueError(f"La linea de carga tiene valores no numericos: '{crudo}'") from exc
    if not all(0.0 <= v <= 1.0 for v in valores):
        raise ValueError(
            f"La linea de carga va en coordenadas relativas de 0 a 1; se recibio '{crudo}'")
    if (valores[0], valores[1]) == (valores[2], valores[3]):
        raise ValueError("Los dos extremos de la linea de carga no pueden coincidir.")
    return valores


def parsear_zona(crudo: str) -> tuple[float, float, float, float]:
    """Lee ZONA_CARGA con el formato 'x1,y1,x2,y2' en coordenadas relativas.

    Es un rectangulo de esquina superior izquierda a inferior derecha, no dos
    puntos cualesquiera: un rectangulo escrito al reves dejaria una zona vacia y
    todas las cargas saldrian sin nadie en rampa, que es un fallo que no se ve.
    """
    partes = [p.strip() for p in str(crudo).split(",") if p.strip() != ""]
    if len(partes) != 4:
        raise ValueError(
            f"La zona de carga necesita cuatro numeros 'x1,y1,x2,y2' entre 0 y 1; "
            f"se recibio '{crudo}'")
    try:
        valores = tuple(float(p) for p in partes)
    except ValueError as exc:
        raise ValueError(f"La zona de carga tiene valores no numericos: '{crudo}'") from exc
    if not all(0.0 <= v <= 1.0 for v in valores):
        raise ValueError(
            f"La zona de carga va en coordenadas relativas de 0 a 1; se recibio '{crudo}'")
    if valores[2] <= valores[0] or valores[3] <= valores[1]:
        raise ValueError(
            f"La zona de carga se escribe de la esquina superior izquierda a la "
            f"inferior derecha, y x2,y2 tienen que ser mayores que x1,y1; "
            f"se recibio '{crudo}'")
    return valores


def cargar_ajustes(**sobrescrituras) -> Ajustes:
    """Construye los ajustes desde el entorno, con sobrescrituras explicitas."""
    base = {
        "ruta_pesos": pathlib.Path(_env("YOLO_WEIGHTS", "modelos/sacos.pt")),
        "clase_saco": _env("YOLO_CLASE_SACO", "saco"),
        "clase_persona": _env("YOLO_CLASE_PERSONA", "person"),
        "confianza_minima": float(_env("YOLO_CONF", 0.35)),
        "iou": float(_env("YOLO_IOU", 0.5)),
        "tamano_inferencia": int(_env("YOLO_IMGSZ", 640)),
        "salto_de_fotogramas": int(_env("YOLO_FRAME_STRIDE", 1)),
        "linea": parsear_linea(_env("LINEA_CARGA", "0.5,0.0,0.5,1.0")),
        "invertir_sentido": str(_env("LINEA_INVERTIDA", "false")).lower()
        in ("1", "true", "si", "yes"),
        "memoria_de_seguimiento": int(_env("YOLO_MEMORIA", 30)),
        "zona": parsear_zona(_env("ZONA_CARGA", "0.0,0.0,1.0,1.0")),
        "personas_habituales": int(_env("PERSONAS_HABITUALES", 3)),
        "permanencia_maxima_s": float(_env("PERMANENCIA_MAX_SEGUNDOS", 600.0)),
        "permanencia_minima_s": float(_env("PERMANENCIA_MIN_SEGUNDOS", 1.0)),
        "modo_conteo": str(_env("YOLO_MODO_CONTEO", "linea")).strip().lower(),
        "clase_pallet": _env("YOLO_CLASE_PALLET", "pallet"),
        "sacos_por_pallet": int(_env("SACOS_POR_PALLET", 40)),
        "zona_pallets": parsear_zona(_env("ZONA_PALLETS", "0.0,0.0,1.0,1.0")),
        "permanencia_pallet_s": float(_env("PALLET_PERMANENCIA_SEGUNDOS", 2.0)),
        "ignorar_inicio_s": float(_env("PALLET_IGNORAR_INICIO_SEGUNDOS", 3.0)),
        "radio_pallet": float(_env("PALLET_RADIO", 0.06)),
        "memoria_pallet_s": float(_env("PALLET_MEMORIA_SEGUNDOS", 6.0)),
        "fotogramas_clave": int(_env("FOTOGRAMAS_CLAVE", 4)),
        "calidad_jpeg": int(_env("CALIDAD_JPEG", 80)),
        "dispositivo": _env("YOLO_DEVICE", "cpu"),
        "app_env": _env("APP_ENV", "development"),
        "log_level": _env("LOG_LEVEL", "INFO"),
    }
    base.update({k: v for k, v in sobrescrituras.items() if v is not None})
    if base["salto_de_fotogramas"] < 1:
        raise ValueError("YOLO_FRAME_STRIDE tiene que ser 1 o mas.")
    if not 0.0 < base["confianza_minima"] <= 1.0:
        raise ValueError("YOLO_CONF va entre 0 y 1.")
    if base["personas_habituales"] < 0:
        raise ValueError("PERSONAS_HABITUALES no puede ser negativo.")
    if base["permanencia_maxima_s"] <= 0:
        raise ValueError("PERMANENCIA_MAX_SEGUNDOS tiene que ser mayor que cero.")
    if base["permanencia_minima_s"] < 0:
        raise ValueError("PERMANENCIA_MIN_SEGUNDOS no puede ser negativo.")
    if base["fotogramas_clave"] < 1:
        raise ValueError(
            "FOTOGRAMAS_CLAVE tiene que ser 1 o mas: un evento sin ninguna "
            "imagen deja al supervisor sin nada que mirar.")
    if base["modo_conteo"] not in MODOS_DE_CONTEO:
        raise ValueError(
            f"YOLO_MODO_CONTEO es 'linea' o 'pallets'; se recibio "
            f"'{base['modo_conteo']}'.")
    if base["sacos_por_pallet"] < 1:
        raise ValueError(
            "SACOS_POR_PALLET tiene que ser 1 o mas: con cero, cada pallet que "
            "llega contaria como una carga vacia.")
    if base["permanencia_pallet_s"] < 0 or base["ignorar_inicio_s"] < 0 \
            or base["memoria_pallet_s"] < 0:
        raise ValueError("Los tiempos de PALLET_* no pueden ser negativos.")
    if not 0.0 <= base["radio_pallet"] <= 1.0:
        raise ValueError("PALLET_RADIO va en coordenadas relativas, de 0 a 1.")
    if not 1 <= base["calidad_jpeg"] <= 100:
        raise ValueError("CALIDAD_JPEG va de 1 a 100.")
    return Ajustes(**base)
