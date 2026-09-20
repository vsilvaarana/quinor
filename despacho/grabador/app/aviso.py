"""Aviso al supervisor cuando el evento ya tiene severidad. HU-10, criterio 3.

  3. La notificacion se envia en menos de 60 s tras el analisis.

Mandar el correo es trabajo del servicio de notificaciones, que decide a quien
avisa y que dice el mensaje. Lo que pasa aqui es lo otro: darse cuenta de que un
evento acaba de quedar clasificado y pedir el aviso en el acto.

Por que el reloj se mide aqui y no alli. El servicio de notificaciones no sabe
cuando termino el analisis; sabe cuando le pidieron el correo. El unico sitio
donde consta el instante en que la severidad quedo escrita es este, que es quien
la escribio, asi que de aqui sale el `segundos_desde_analisis` que el criterio 3
necesita para poder medirse en lugar de suponerse.

Por eso tambien el aviso sale en la misma pasada que la interpretacion y no en
la siguiente vuelta del sondeo. Con un bucle cada 30 segundos, esperar a la
vuelta siguiente gastaria media ventana del criterio sin hacer nada. La pasada
de reintento existe igual, pero es para lo que fallo, no el camino normal.

Por que aqui y no en el orquestador: por lo mismo que HU-09. El apartado 6.4
dice que quien llama es el worker, que es HU-17 y todavia no existe; mientras
tanto el bucle de sondeo de este servicio hace de worker. Cuando llegue HU-17,
lo unico que cambia es quien llama a `avisar`.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import time

import httpx
import structlog
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from app import tablas
from app.config import Ajustes

log = structlog.get_logger("quinor.aviso")

RUTA_DE_AVISO = "/notificaciones"
ACCION_OK = "notificar_evento"
ACCION_FALLO = "notificacion_fallida"

# Estados finales o en curso que no se avisan: si un supervisor ya abrio el caso
# o lo cerro, un aviso tardio solo le haria volver sobre algo resuelto.
ESTADOS_QUE_NO_SE_AVISAN = ("en_revision", "confirmado", "falso_positivo")


class ServicioNoDisponible(RuntimeError):
    """El servicio de notificaciones no respondio o respondio con error."""


@dataclasses.dataclass(frozen=True)
class Aviso:
    """Lo que devolvio el servicio de notificaciones."""

    evento_id: int
    enviado: bool
    duplicado: bool = False
    severidad: str | None = None
    destinatarios: tuple[str, ...] = ()
    segundos_desde_analisis: float | None = None
    dentro_del_criterio: bool | None = None
    error: str = ""

    @property
    def hubo_que_hacer_algo(self) -> bool:
        return self.enviado or not self.duplicado


def pedir(ajustes: Ajustes, cuerpo: dict) -> dict:
    """Una llamada al servicio de notificaciones.

    Los reintentos del correo son suyos, no de aqui: el servicio sabe cuales
    merecen otro intento (un relay saturado) y cuales no (una direccion que no
    existe), y duplicarlos aqui solo gastaria la ventana de 60 segundos.
    """
    if not ajustes.avisa_eventos:
        raise ServicioNoDisponible(
            "NOTIFY_URL esta vacio: el aviso de HU-10 esta apagado en esta "
            "instalacion.")

    cabeceras = ({"X-API-Key": ajustes.notificaciones_api_key}
                 if ajustes.notificaciones_api_key else {})
    destino = ajustes.notificaciones_url.rstrip("/") + RUTA_DE_AVISO
    try:
        respuesta = httpx.post(destino, json=cuerpo, headers=cabeceras,
                               timeout=ajustes.aviso_timeout_s)
        respuesta.raise_for_status()
        return respuesta.json()
    except httpx.HTTPStatusError as exc:
        raise ServicioNoDisponible(
            f"El servicio de notificaciones respondio "
            f"{exc.response.status_code}: {exc.response.text[:200]}") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise ServicioNoDisponible(
            f"No se pudo hablar con el servicio de notificaciones: "
            f"{exc}") from exc


def _anotar(motor: Engine, evento_id: int, accion: str, detalle: dict) -> None:
    with motor.begin() as conexion:
        conexion.execute(tablas.auditoria.insert().values(
            entidad="evento", entidad_id=evento_id, accion=accion,
            usuario_id=None, detalle=detalle,
            fecha=dt.datetime.now().replace(tzinfo=None)))


# --------------------------------------------------------------- el caso de uso
def avisar(motor: Engine, ajustes: Ajustes, evento_id: int,
           analizado_en: float | None = None, peticion=None) -> Aviso | None:
    """Pide el aviso del evento y deja constancia. Criterio 3.

    `analizado_en` es una marca de `time.monotonic()` tomada cuando la severidad
    quedo escrita. Sin ella el aviso sale igual, pero sin poder medir el
    criterio: es lo que pasa en la pasada de reintento, donde el analisis fue en
    otro momento y decir "cero segundos" seria mentir.

    Devuelve None cuando el aviso esta apagado en esta instalacion.
    """
    if not ajustes.avisa_eventos:
        return None
    peticion = peticion or pedir

    cuerpo = {"evento_id": int(evento_id)}
    if analizado_en is not None:
        cuerpo["segundos_desde_analisis"] = round(
            max(0.0, time.monotonic() - analizado_en), 3)

    try:
        datos = peticion(ajustes, cuerpo)
    except ServicioNoDisponible as exc:
        _anotar(motor, evento_id, ACCION_FALLO, {"motivo": str(exc)})
        log.error("aviso_fallido", evento_id=evento_id, motivo=str(exc))
        return Aviso(evento_id=evento_id, enviado=False, error=str(exc))

    aviso = Aviso(
        evento_id=evento_id,
        enviado=bool(datos.get("enviado")),
        duplicado=bool(datos.get("duplicado")),
        severidad=datos.get("severidad"),
        destinatarios=tuple(datos.get("destinatarios") or ()),
        segundos_desde_analisis=datos.get("segundos_desde_analisis"),
        dentro_del_criterio=datos.get("dentro_del_criterio"),
        error=str(datos.get("error", "")),
    )

    if aviso.duplicado:
        # Ya se aviso en una vuelta anterior. No es un fallo y no se anota: la
        # auditoria es para lo que paso, no para lo que no hizo falta repetir.
        log.info("aviso_ya_enviado", evento_id=evento_id)
        return aviso

    if not aviso.enviado:
        # El correo no salio. Queda en auditoria ademas de en la tabla
        # notificacion, porque es aqui donde se cuentan los intentos para no
        # quedarse llamando en bucle a un servicio caido.
        _anotar(motor, evento_id, ACCION_FALLO, {
            "motivo": aviso.error, "severidad": aviso.severidad})
        log.error("aviso_no_enviado", evento_id=evento_id,
                  severidad=aviso.severidad, motivo=aviso.error)
        return aviso

    _anotar(motor, evento_id, ACCION_OK, {
        "severidad": aviso.severidad,
        "destinatarios": list(aviso.destinatarios),
        "segundos_desde_analisis": aviso.segundos_desde_analisis,
        "dentro_del_criterio": aviso.dentro_del_criterio,
    })
    if aviso.dentro_del_criterio is False:
        # El criterio 3 se mide con lo que pasa de verdad. Un aviso tardio hay
        # que verlo antes de que sea costumbre.
        log.warning("aviso_tardio", evento_id=evento_id,
                    segundos=aviso.segundos_desde_analisis)
    else:
        log.info("evento_avisado", evento_id=evento_id,
                 severidad=aviso.severidad,
                 destinatarios=len(aviso.destinatarios),
                 segundos=aviso.segundos_desde_analisis)
    return aviso


# ------------------------------------------------------------- los reintentos
def pendientes_de_avisar(motor: Engine, ajustes: Ajustes,
                         limite: int = 10) -> list[int]:
    """Eventos ya clasificados de los que todavia no ha salido el correo.

    Se excluyen los que agotaron los intentos, contando sus filas de auditoria,
    por lo mismo que en HU-07 y HU-09: un servicio de correo caido un dia entero
    tendria al grabador llamando en bucle sin que el resultado cambiara.
    """
    fallos = (
        select(func.count())
        .select_from(tablas.auditoria)
        .where(tablas.auditoria.c.entidad == "evento",
               tablas.auditoria.c.entidad_id == tablas.evento.c.id,
               tablas.auditoria.c.accion == ACCION_FALLO)
        .scalar_subquery())
    # Un aviso enviado cierra el asunto. Uno fallido no: el evento sigue sin
    # avisar y su fila se reemplaza en el siguiente intento.
    ya_enviado = (
        select(func.count())
        .select_from(tablas.notificacion)
        .where(tablas.notificacion.c.evento_id == tablas.evento.c.id,
               tablas.notificacion.c.estado == "enviada")
        .scalar_subquery())
    consulta = (
        select(tablas.evento.c.id)
        .where(tablas.evento.c.severidad.is_not(None),
               tablas.evento.c.estado.not_in(ESTADOS_QUE_NO_SE_AVISAN),
               ya_enviado == 0,
               fallos < ajustes.intentos_de_aviso)
        .order_by(tablas.evento.c.creado_en.asc())
        .limit(limite))
    with motor.connect() as conexion:
        return [int(f[0]) for f in conexion.execute(consulta).all()]


def procesar_pendientes(motor: Engine, ajustes: Ajustes,
                        limite: int = 10, peticion=None) -> list[Aviso]:
    """Una pasada por los eventos clasificados de los que no salio el correo.

    Aqui no se pasa `analizado_en`: el analisis fue en otra vuelta y puede haber
    sido hace horas. Decir "cero segundos" daria por cumplido el criterio 3 sin
    haberlo comprobado, que es peor que no medirlo.
    """
    if not ajustes.avisa_eventos:
        return []
    hechos = []
    for evento_id in pendientes_de_avisar(motor, ajustes, limite):
        try:
            resultado = avisar(motor, ajustes, evento_id, peticion=peticion)
        except Exception as exc:      # noqa: BLE001
            log.error("aviso_reintento_fallido", evento_id=evento_id,
                      error=str(exc))
            continue
        if resultado is not None:
            hechos.append(resultado)
    return hechos
