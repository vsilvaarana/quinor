"""Servicio YOLO de QUINOR S.A.C. HU-07 y HU-08.

HU-07. Como supervisor de despacho, quiero que el sistema cuente los sacos
cargados al camion a partir del video, para contrastar el conteo visual con el
peso y la orden.
  1. El servicio YOLO procesa el clip y devuelve el numero de sacos que cruzan
     la linea de carga.
  2. La precision del conteo en el set de validacion es igual o mayor a 95 %.
  3. El conteo y la diferencia con la orden se guardan en el evento.

HU-08. Como supervisor de despacho, quiero que el sistema haga seguimiento de
las personas presentes en la zona de carga durante el evento, para identificar
si hubo personal no autorizado o movimientos anomalos.
  1. Se detecta y sigue a cada persona con un ID temporal durante el clip.
  2. Se registra cuantas personas estuvieron en zona y el tiempo de permanencia.
  3. No se realiza identificacion facial ni se guardan datos biometricos.

Los criterios que hablan de guardar los cumple el grabador, que es quien tiene el
clip y la conexion a la base; este servicio solo mira el video. El apartado 6.4
del documento lo describe asi: un contenedor propio con GPU que expone
POST /analisis/yolo.

El criterio 3 de HU-08 se cumple por construccion y no por omision: por aqui no
sale ni un rostro ni un descriptor. De cada persona se informan un numero de
seguimiento que solo vale en este clip, dos fotogramas y unos segundos.

Va aparte porque PyTorch y CUDA son varios gigas que ni el orquestador ni el
grabador necesitan, y porque en planta la GPU se le asigna solo a el.

La aplicacion se construye con create_app, que recibe su configuracion por
parametro y cae al entorno solo cuando no se le pasa nada, igual que los otros
dos servicios.
"""
from __future__ import annotations

import base64
import contextlib
import logging
import pathlib

import structlog
from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader

from app import analisis
from app.config import Ajustes, cargar_ajustes
from app.schemas import (FotogramaClaveLeido, MotivoDeAnomalia, PersonaEnZona,
                         PeticionDeAnalisis, PresenciaDePersonal,
                         RespuestaDeAnalisis, RespuestaDeSalud)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Lo que se devuelve cuando el rastreador no siguio nada de lo que el detector
# vio. El conteo sale cero y sin este aviso pareceria una carga vacia.
AVISO_SEGUIMIENTO = (
    "Se detectaron objetos pero ninguno llego a tener identificador de "
    "seguimiento, asi que este conteo no es fiable. Suele ser un salto de "
    "fotogramas demasiado alto para la velocidad de la rampa: bajar "
    "YOLO_FRAME_STRIDE y repetir la validacion del criterio 2.")


def _configurar_logging(nivel: str) -> None:
    logging.basicConfig(format="%(message)s",
                        level=getattr(logging, nivel.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )


def create_app(
    ruta_pesos: pathlib.Path = None,
    clase_saco: str = None,
    confianza_minima: float = None,
    linea: tuple = None,
    dispositivo: str = None,
    api_key: str = None,
    ajustes: Ajustes = None,
    modelo=None,
    # HU-08. La zona y los umbrales de personal tambien se pueden inyectar, que
    # es lo que permite probar una rampa calibrada sin tocar el entorno.
    zona: tuple = None,
    personas_habituales: int = None,
    permanencia_maxima_s: float = None,
    permanencia_minima_s: float = None,
) -> FastAPI:
    """Construye una instancia del servicio.

    `modelo` se puede inyectar: es lo que permite probar el endpoint completo
    sin cargar PyTorch ni esperar a una inferencia de verdad.
    """
    ajustes = ajustes or cargar_ajustes(
        ruta_pesos=ruta_pesos, clase_saco=clase_saco,
        confianza_minima=confianza_minima, linea=linea, dispositivo=dispositivo,
        zona=zona, personas_habituales=personas_habituales,
        permanencia_maxima_s=permanencia_maxima_s,
        permanencia_minima_s=permanencia_minima_s)
    _configurar_logging(ajustes.log_level)
    log = structlog.get_logger("quinor.yolo")

    # Este servicio no tiene base de datos ni usuarios: vive en la red interna
    # segmentada del apartado 8 y solo lo llama el grabador. La clave compartida
    # evita que cualquier cosa de esa red le mande clips a analizar.
    clave = api_key if api_key is not None else ajustes_api_key()

    @contextlib.asynccontextmanager
    async def ciclo_de_vida(app_: FastAPI):
        # El modelo se carga al arrancar y no en la primera peticion: asi el
        # primer clip del dia no paga los segundos de cargar PyTorch, que es
        # justo cuando el camion esta esperando.
        app_.state.modelo = modelo
        if modelo is None and ajustes.ruta_pesos.exists():
            try:
                app_.state.modelo = analisis._cargar_modelo(ajustes)
                log.info("modelo_cargado", pesos=str(ajustes.ruta_pesos))
            except Exception as exc:      # noqa: BLE001
                log.error("modelo_no_cargado", error=str(exc))
        elif modelo is None:
            log.warning("sin_modelo",
                        detalle=f"No estan los pesos en {ajustes.ruta_pesos}. "
                                f"El servicio responde 503 hasta que existan.")
        yield

    app = FastAPI(
        title="QUINOR - Servicio YOLO",
        description="Conteo de sacos que cruzan la linea de carga (HU-07) y "
                    "seguimiento de las personas en la zona de carga (HU-08). "
                    "Sin identificacion facial ni datos biometricos (RN-08).",
        version="1.1.0",
        lifespan=ciclo_de_vida,
    )
    app.state.ajustes = ajustes
    app.state.modelo = modelo

    def requiere_clave(entregada: str = Security(api_key_header)) -> None:
        if not clave:
            return          # sin clave configurada, el servicio queda abierto
        import secrets as _secrets

        if not entregada or not _secrets.compare_digest(entregada, clave):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                                detail="Clave de servicio invalida")

    @app.get("/", tags=["servicio"])
    def info():
        """Lo unico publico: sirve de healthcheck sin analizar nada."""
        return {
            "servicio": "Servicio YOLO de QUINOR",
            "version": app.version,
            "historia": "HU-07 conteo de sacos y HU-08 seguimiento de personas",
            "documentacion": "/docs",
        }

    @app.get("/salud", response_model=RespuestaDeSalud, tags=["servicio"],
             dependencies=[Depends(requiere_clave)])
    def salud() -> RespuestaDeSalud:
        """Si el modelo no esta cargado, mejor saberlo antes del primer camion."""
        cargado = app.state.modelo is not None
        return RespuestaDeSalud(
            estado="ok" if cargado else "error",
            modelo=ajustes.ruta_pesos.name,
            modelo_cargado=cargado,
            dispositivo=ajustes.dispositivo,
            linea=list(ajustes.linea),
            zona=list(ajustes.zona),
            mensaje=None if cargado else
            f"Sin modelo en {ajustes.ruta_pesos}: el analisis respondera 503",
        )

    @app.post("/analisis/yolo", response_model=RespuestaDeAnalisis,
              tags=["analisis"], dependencies=[Depends(requiere_clave)],
              summary="Cuenta los sacos que cruzan la linea (HU-07) y sigue a "
                      "las personas en la zona de carga (HU-08)")
    def analizar_clip(cuerpo: PeticionDeAnalisis) -> RespuestaDeAnalisis:
        """Criterio 1. El clip llega por ruta, no por el cuerpo de la peticion.

        Un clip de 7 min son cientos de megas: subirlo por HTTP para que el
        servicio lo escriba otra vez en disco seria copiar gigas al dia sin
        motivo. Los dos contenedores comparten el volumen del buffer.
        """
        if app.state.modelo is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"El modelo no esta cargado ({ajustes.ruta_pesos}). "
                       f"Entrenarlo o apuntar YOLO_WEIGHTS al modelo activo.")
        try:
            resultado = analisis.analizar(
                _con_linea(ajustes, cuerpo), pathlib.Path(cuerpo.clip),
                modelo=app.state.modelo)
        except analisis.ClipIlegible as exc:
            raise HTTPException(404, str(exc)) from exc

        diferencia = None
        if cuerpo.sacos_esperados is not None:
            # Criterio 3: la diferencia con la orden. Negativa es faltante, el
            # mismo criterio de signo que la diferencia de peso de HU-03.
            diferencia = resultado.sacos_contados - cuerpo.sacos_esperados

        return RespuestaDeAnalisis(
            sacos_contados=resultado.sacos_contados,
            sacos_entrantes=resultado.sacos_entrantes,
            sacos_salientes=resultado.sacos_salientes,
            sacos_esperados=cuerpo.sacos_esperados,
            diferencia_sacos=diferencia,
            personas_detectadas=resultado.personas_detectadas,
            fotogramas_procesados=resultado.fotogramas_procesados,
            duracion_del_clip_s=resultado.duracion_del_clip_s,
            segundos_de_proceso=resultado.segundos_de_proceso,
            modelo=resultado.modelo,
            aviso=AVISO_SEGUIMIENTO if resultado.seguimiento_perdido else None,
            presencia=_presencia(resultado),
            fotogramas_clave=[
                FotogramaClaveLeido(
                    fotograma=f.fotograma, segundo=f.segundo, motivo=f.motivo,
                    detalle=f.detalle,
                    jpeg_base64=base64.b64encode(f.jpeg).decode("ascii"))
                for f in resultado.fotogramas_clave],
            anomalia_de_personal=bool(resultado.anomalia and resultado.anomalia.hay),
            motivos_de_anomalia=[
                MotivoDeAnomalia(codigo=m.codigo, detalle=m.detalle,
                                 medido=m.medido, umbral=m.umbral)
                for m in (resultado.anomalia.motivos if resultado.anomalia else ())],
        )

    return app


def _presencia(resultado) -> PresenciaDePersonal | None:
    """Traduce lo observado de las personas al contrato. HU-08, criterio 2.

    Lo que sale de aqui es lo unico que el servicio dice de ellas: un numero de
    seguimiento, dos fotogramas y unos segundos. Nada mas, por la RN-08.
    """
    quienes = resultado.personas
    if quienes is None:
        return None
    return PresenciaDePersonal(
        cuantas=quienes.cuantas,
        maximo_simultaneo=quienes.maximo_simultaneo,
        segundos_totales=quienes.segundos_totales,
        permanencia_maxima_s=quienes.permanencia_maxima_s,
        permanencia_media_s=quienes.permanencia_media_s,
        zona_completa=quienes.zona_completa,
        personas=[PersonaEnZona(
            id_temporal=p.id_temporal,
            segundos_en_zona=p.segundos_en_zona,
            primer_fotograma=p.primer_fotograma,
            ultimo_fotograma=p.ultimo_fotograma) for p in quienes.personas],
    )


def _con_linea(ajustes: Ajustes, cuerpo: PeticionDeAnalisis) -> Ajustes:
    """Permite a quien llama pasar su propia linea de carga y su propia zona.

    Con dos camaras enfocando rampas distintas, ni la linea ni la zona son las
    mismas. Sin esto haria falta un servicio por camara.
    """
    import dataclasses

    cambios = {}
    if cuerpo.linea is not None:
        cambios["linea"] = tuple(cuerpo.linea)
    if cuerpo.zona is not None:
        cambios["zona"] = tuple(cuerpo.zona)
    if cuerpo.invertir_sentido is not None:
        cambios["invertir_sentido"] = cuerpo.invertir_sentido
    return dataclasses.replace(ajustes, **cambios) if cambios else ajustes


def ajustes_api_key() -> str:
    import os

    return os.environ.get("YOLO_API_KEY", "")


if __name__ == "__main__":      # pragma: no cover
    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=8002)
