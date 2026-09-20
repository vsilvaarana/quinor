"""Ajustes del grabador.

Un unico objeto inmutable que crear_grabador construye una vez. Ningun modulo
lee variables de entorno por su cuenta: las recibe por parametro, igual que en
el orquestador. Asi una prueba apunta el grabador a otra carpeta y a otra camara
sin tocar el entorno del proceso.

Seccion 8 del documento funcional: ningun secreto vive en el codigo.
"""
from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field

# Criterio 1 de HU-05: segmentos de 1 minuto.
SEGUNDOS_POR_SEGMENTO = 60
# Criterio 2: al menos 72 h de video en disco local.
HORAS_DE_RETENCION = 72.0
# El RNF-04 preve hasta 4 camaras sin cambios de arquitectura.
MAXIMO_DE_CAMARAS = 4

# Criterio 1 de HU-06: 5 minutos antes del inicio de carga y 2 despues del cierre.
SEGUNDOS_ANTES = 300
SEGUNDOS_DESPUES = 120


@dataclass(frozen=True)
class Camara:
    """Una camara de la rampa. El id es el que aparece en salud_componente."""

    id: str
    url: str

    @property
    def componente(self) -> str:
        """Nombre con el que se registra en salud_componente, por ejemplo camara-01."""
        return self.id.lower()


@dataclass(frozen=True)
class Ajustes:
    """Configuracion resuelta de una instancia del grabador."""

    database_url: str
    camaras: tuple[Camara, ...] = field(default_factory=tuple)

    # Donde viven los segmentos. En planta es el almacenamiento local de 2 TB
    # del RNF-06; en desarrollo, un volumen del compose.
    directorio_buffer: pathlib.Path = pathlib.Path("/video")
    segundos_por_segmento: int = SEGUNDOS_POR_SEGMENTO
    horas_de_retencion: float = HORAS_DE_RETENCION

    # Cada cuanto se revisa la retencion. No hace falta mas: un segmento dura un
    # minuto y el margen de 72 h no se agota en cinco.
    segundos_entre_purgas: float = 300.0
    # Por debajo de este porcentaje libre, se borra lo mas antiguo aunque no
    # llegue a las 72 h, y se avisa. Quedarse sin grabar seria peor: se
    # perderian las cargas de hoy, que son las que todavia se pueden investigar.
    minimo_libre_pct: float = 10.0

    # Reconexion tras una caida de camara. El criterio 3 pide registrar la
    # desconexion, no rendirse: una camara vuelve cuando vuelve la red.
    segundos_entre_reintentos: float = 10.0
    segundos_de_espera_rtsp: float = 15.0

    # --- HU-06 recorte de clips ---------------------------------------------
    # Margenes de la ventana del clip, en segundos.
    segundos_antes: int = SEGUNDOS_ANTES
    segundos_despues: int = SEGUNDOS_DESPUES
    # De que camara se recorta. HU-06 habla de "el clip" en singular; con dos
    # camaras en la rampa, la que enfoca la linea de carga es la que sirve de
    # evidencia. Al llegar HU-12 conviene revisar si el detalle debe mostrar las
    # dos, y entonces esto pasa a ser una lista.
    camara_de_clips: str = "camara-01"
    # Por debajo de esta cobertura de la ventana, el clip no sirve para revisar
    # nada y el evento se marca Sin clip en lugar de guardar un trozo enganoso.
    cobertura_minima_pct: float = 50.0
    # Cada cuanto se buscan eventos sin clip. HU-17 sustituira este sondeo por
    # una cola con reintentos.
    segundos_entre_clips: float = 5.0

    # --- HU-07 conteo de sacos ----------------------------------------------
    # El servicio YOLO del apartado 6.4. Vacio deja el conteo apagado: en una
    # instalacion sin GPU el grabador sigue haciendo su trabajo de HU-05 y HU-06.
    yolo_url: str = ""
    yolo_api_key: str = ""
    # Un clip de 7 min se analiza en menos de 3 segun el RNF-01. El margen cubre
    # la cola cuando dos camiones cierran a la vez.
    yolo_timeout_s: float = 600.0
    # Intentos de conteo por evento. Si el servicio estuvo caido, el clip ya esta
    # en MinIO y se reintenta desde ahi; pero no para siempre, o un YOLO caido un
    # dia entero tendria al grabador bajando clips en bucle.
    intentos_de_conteo: int = 3
    segundos_entre_conteos: float = 15.0

    # --- HU-09 interpretacion del evento --------------------------------------
    # El servicio de vision-lenguaje del apartado 6.6. Vacio deja HU-09 apagada:
    # los eventos se quedan sin descripcion, pero el resto sigue funcionando.
    vlm_url: str = ""
    vlm_api_key: str = ""
    # El propio servicio reintenta tres veces por dentro (criterio 3), asi que
    # aqui basta con esperar a que termine.
    vlm_timeout_s: float = 420.0
    # Intentos desde este lado, contando los del servicio: si el proveedor lleva
    # horas caido, no tiene sentido bajar los mismos fotogramas cada minuto.
    intentos_de_interpretacion: int = 3
    segundos_entre_interpretaciones: float = 30.0

    # --- HU-10 aviso al supervisor --------------------------------------------
    # El servicio de notificaciones del apartado 6.4. Vacio deja HU-10 apagada:
    # los eventos se clasifican igual y se ven en el dashboard, pero nadie
    # recibe el correo.
    notificaciones_url: str = ""
    notificaciones_api_key: str = ""
    # El criterio 3 da 60 segundos para todo. El servicio reintenta por dentro
    # con esperas cortas, asi que esperar mas de medio minuto a que conteste
    # seria gastar la ventana esperando a algo que ya no llega a tiempo.
    aviso_timeout_s: float = 30.0
    # Intentos desde este lado: si el relay lleva horas caido, llamar cada vuelta
    # no cambia el resultado y llena la auditoria.
    intentos_de_aviso: int = 3
    # Mas corto que el de las interpretaciones a proposito: lo que espera aqui
    # es un correo con una ventana de 60 segundos, no una llamada a un modelo.
    segundos_entre_avisos: float = 10.0

    # --- MinIO (criterio 2 de HU-06) ----------------------------------------
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "clips"
    minio_seguro: bool = False

    app_env: str = "development"
    log_level: str = "INFO"

    @property
    def segundos_de_retencion(self) -> float:
        return self.horas_de_retencion * 3600

    @property
    def duracion_del_clip_s(self) -> int:
        """Lo que dura el clip cuando la carga es instantanea: los dos margenes."""
        return self.segundos_antes + self.segundos_despues

    @property
    def recorta_clips(self) -> bool:
        """Sin credenciales de MinIO no hay donde guardar el clip."""
        return bool(self.minio_access_key and self.minio_secret_key)

    @property
    def cuenta_sacos(self) -> bool:
        """Sin servicio YOLO configurado, HU-07 queda apagada y se dice en el log."""
        return bool(self.yolo_url)

    @property
    def interpreta_eventos(self) -> bool:
        """Sin servicio de vision-lenguaje, HU-09 queda apagada.

        Es una instalacion valida: el apartado 12 da la conectividad a internet
        como riesgo, y el sistema tiene que seguir detectando y guardando
        evidencia sin ella.
        """
        return bool(self.vlm_url)

    @property
    def avisa_eventos(self) -> bool:
        """Sin servicio de notificaciones, HU-10 queda apagada.

        Igual que HU-09: es una instalacion valida. El evento se detecta, se
        graba y se clasifica, y el supervisor lo ve en el dashboard; lo que no
        hay es el correo que le avisa sin tener que mirarlo.
        """
        return bool(self.notificaciones_url)


def _env(nombre: str, por_defecto):
    valor = os.environ.get(nombre)
    return por_defecto if valor is None or valor == "" else valor


def parsear_camaras(crudo: str) -> tuple[Camara, ...]:
    """Lee CAMERAS con el formato 'id=url,id=url'.

    Un catalogo en base de datos seria mas comodo de editar, pero el apartado
    6.5 no define tabla de camaras y HU-05 no pide una pantalla para darlas de
    alta. Mientras sean cuatro y se toquen una vez al instalar, la variable de
    entorno es honesta: se ve en el compose y no hay estado escondido.
    """
    camaras = []
    vistos = set()
    for trozo in crudo.split(","):
        trozo = trozo.strip()
        if not trozo:
            continue
        if "=" not in trozo:
            raise ValueError(
                f"Camara mal definida: '{trozo}'. El formato es id=url, por ejemplo "
                f"camara-01=rtsp://usuario:clave@10.0.0.11:554/stream")
        identificador, url = (p.strip() for p in trozo.split("=", 1))
        if not identificador or not url:
            raise ValueError(f"Camara mal definida: '{trozo}'. Falta el id o la url.")
        if identificador.lower() in vistos:
            raise ValueError(f"La camara '{identificador}' esta repetida en CAMERAS.")
        vistos.add(identificador.lower())
        camaras.append(Camara(id=identificador, url=url))

    if len(camaras) > MAXIMO_DE_CAMARAS:
        raise ValueError(
            f"Se configuraron {len(camaras)} camaras y el RNF-04 dimensiona "
            f"{MAXIMO_DE_CAMARAS}. Revisar antes de seguir.")
    return tuple(camaras)


def cargar_ajustes(**sobrescrituras) -> Ajustes:
    """Construye los ajustes desde el entorno, con sobrescrituras explicitas."""
    base = {
        "database_url": _env("DATABASE_URL", ""),
        "camaras": parsear_camaras(_env("CAMERAS", "")),
        "directorio_buffer": pathlib.Path(_env("VIDEO_DIR", "/video")),
        "segundos_por_segmento": int(_env("SEGMENT_SECONDS", SEGUNDOS_POR_SEGMENTO)),
        "horas_de_retencion": float(_env("RETENTION_HOURS", HORAS_DE_RETENCION)),
        "segundos_entre_purgas": float(_env("PURGE_INTERVAL_SECONDS", 300.0)),
        "minimo_libre_pct": float(_env("MIN_FREE_PCT", 10.0)),
        "segundos_entre_reintentos": float(_env("RETRY_SECONDS", 10.0)),
        "segundos_de_espera_rtsp": float(_env("RTSP_TIMEOUT_SECONDS", 15.0)),
        "segundos_antes": int(_env("CLIP_PRE_SECONDS", SEGUNDOS_ANTES)),
        "segundos_despues": int(_env("CLIP_POST_SECONDS", SEGUNDOS_DESPUES)),
        "camara_de_clips": _env("CLIP_CAMERA", "camara-01"),
        "cobertura_minima_pct": float(_env("CLIP_MIN_COVERAGE_PCT", 50.0)),
        "segundos_entre_clips": float(_env("CLIP_POLL_SECONDS", 5.0)),
        "yolo_url": _env("YOLO_URL", ""),
        "yolo_api_key": _env("YOLO_API_KEY", ""),
        "yolo_timeout_s": float(_env("YOLO_TIMEOUT_SECONDS", 600.0)),
        "intentos_de_conteo": int(_env("COUNT_MAX_ATTEMPTS", 3)),
        "segundos_entre_conteos": float(_env("COUNT_POLL_SECONDS", 15.0)),
        "vlm_url": _env("VLM_URL", ""),
        "vlm_api_key": _env("VLM_SERVICE_API_KEY", ""),
        "vlm_timeout_s": float(_env("VLM_TIMEOUT_SECONDS", 420.0)),
        "intentos_de_interpretacion": int(_env("VLM_MAX_ATTEMPTS", 3)),
        "segundos_entre_interpretaciones": float(_env("VLM_POLL_SECONDS", 30.0)),
        "notificaciones_url": _env("NOTIFY_URL", ""),
        "notificaciones_api_key": _env("NOTIFY_SERVICE_API_KEY", ""),
        "aviso_timeout_s": float(_env("NOTIFY_TIMEOUT_SECONDS", 30.0)),
        "intentos_de_aviso": int(_env("NOTIFY_MAX_ATTEMPTS", 3)),
        "segundos_entre_avisos": float(_env("NOTIFY_POLL_SECONDS", 10.0)),
        "minio_endpoint": _env("MINIO_ENDPOINT", "minio:9000"),
        "minio_access_key": _env("MINIO_ACCESS_KEY", ""),
        "minio_secret_key": _env("MINIO_SECRET_KEY", ""),
        "minio_bucket": _env("MINIO_BUCKET", "clips"),
        "minio_seguro": _env("MINIO_SECURE", "false").lower() in ("1", "true", "si", "yes"),
        "app_env": _env("APP_ENV", "development"),
        "log_level": _env("LOG_LEVEL", "INFO"),
    }
    base.update({k: v for k, v in sobrescrituras.items() if v is not None})
    if not base["database_url"]:
        raise ValueError(
            "Falta DATABASE_URL: el grabador no sabe donde registrar la salud de las camaras.")
    if base["horas_de_retencion"] < HORAS_DE_RETENCION:
        raise ValueError(
            f"RETENTION_HOURS es {base['horas_de_retencion']} y el criterio 2 de HU-05 "
            f"exige al menos {HORAS_DE_RETENCION} horas.")
    if base["segundos_por_segmento"] <= 0:
        raise ValueError("SEGMENT_SECONDS tiene que ser mayor que cero.")
    if base["segundos_antes"] < 0 or base["segundos_despues"] < 0:
        raise ValueError("Los margenes del clip no pueden ser negativos.")
    if base["intentos_de_conteo"] < 1:
        raise ValueError("COUNT_MAX_ATTEMPTS tiene que ser 1 o mas.")
    if base["intentos_de_interpretacion"] < 1:
        raise ValueError("VLM_MAX_ATTEMPTS tiene que ser 1 o mas.")
    if base["intentos_de_aviso"] < 1:
        raise ValueError("NOTIFY_MAX_ATTEMPTS tiene que ser 1 o mas.")
    if base["aviso_timeout_s"] <= 0:
        raise ValueError("NOTIFY_TIMEOUT_SECONDS tiene que ser mayor que cero.")
    return Ajustes(**base)
