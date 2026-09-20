"""El envio del correo. HU-10, criterios 1 y 3.

El apartado 6.4 fija la libreria: aiosmtplib. El mensaje se arma con
email.message del estandar, que es lo que garantiza que las cabeceras salgan
bien codificadas cuando un cliente se llama "Comercializadora Andina S.A.C." y
el asunto lleva tildes.

Dos decisiones que conviene explicar:

Los reintentos distinguen entre lo que se arregla esperando y lo que no. Un 421
o un 451 son "ahora no puedo, vuelve luego" y merecen un segundo intento; un 550
es "esa direccion no existe" y repetirlo tres veces solo retrasa el registro del
fallo. El criterio 3 da 60 segundos, y gastarlos insistiendo en un error
permanente es la forma de incumplirlo sin motivo.

Un fallo de envio no es una excepcion que sube. El servicio devuelve el
resultado y quien llama lo guarda en `notificacion` con estado Fallida. Un
correo que no salio tiene que quedar escrito en algun sitio, porque la pregunta
que se hace despues de un hurto es justamente "se aviso o no se aviso".
"""
from __future__ import annotations

import dataclasses
import email.utils
import time
from email.message import EmailMessage

import aiosmtplib

from app.config import SSL, STARTTLS, Ajustes
from app.destinatarios import Reparto
from app.plantilla import Mensaje

# Codigos SMTP que se arreglan esperando. El resto son definitivos: la direccion
# no existe, el buzon esta lleno, el relay rechaza al remitente.
#
#   421  servicio no disponible, cerrando el canal
#   450  buzon ocupado temporalmente
#   451  error local en el proceso
#   452  sin espacio de sistema
#   454  fallo temporal de autenticacion o de TLS
TEMPORALES = (421, 450, 451, 452, 454)


class SinConfigurar(RuntimeError):
    """No hay servidor de correo al que enviar."""


@dataclasses.dataclass(frozen=True)
class Resultado:
    """Como acabo el envio."""

    enviado: bool
    intentos: int
    segundos: float
    error: str = ""
    # Direcciones que el servidor rechazo una a una aceptando el resto. Un
    # correo con dos de tres destinatarios es un envio con matiz, no un exito.
    rechazados: tuple[str, ...] = ()

    @property
    def parcial(self) -> bool:
        return self.enviado and bool(self.rechazados)


def armar(ajustes: Ajustes, mensaje: Mensaje, reparto: Reparto,
          evento_id: int) -> EmailMessage:
    """El mensaje MIME, con la prioridad del criterio 1."""
    correo = EmailMessage()
    correo["From"] = email.utils.formataddr(
        (ajustes.nombre_del_remitente, ajustes.remitente))
    correo["To"] = ", ".join(reparto.destinatarios)
    correo["Subject"] = mensaje.asunto
    correo["Date"] = email.utils.formatdate(localtime=True)
    # Con dominio del remitente: un Message-ID inventado con el hostname del
    # contenedor hace que algunos relays marquen el correo como sospechoso.
    correo["Message-ID"] = email.utils.make_msgid(
        domain=ajustes.remitente.split("@")[-1])
    if ajustes.responder_a:
        correo["Reply-To"] = ajustes.responder_a

    # Criterio 1: la Alta sale marcada. Las tres cabeceras porque ningun cliente
    # las entiende todas: Outlook mira X-Priority, Thunderbird Importance, y
    # Priority es la del estandar.
    correo["X-Priority"] = reparto.prioridad
    correo["Importance"] = "high" if reparto.urgente else "normal"
    correo["Priority"] = "urgent" if reparto.urgente else "normal"

    # Para que el supervisor pueda filtrar por severidad en su cliente sin
    # depender de como escribamos el asunto.
    correo["X-QUINOR-Evento"] = str(evento_id)
    correo["X-QUINOR-Severidad"] = reparto.severidad

    correo.set_content(mensaje.texto, subtype="plain", charset="utf-8")
    correo.add_alternative(mensaje.html, subtype="html", charset="utf-8")
    return correo


def _es_temporal(excepcion: Exception) -> bool:
    codigo = getattr(excepcion, "code", None)
    if isinstance(codigo, int):
        return codigo in TEMPORALES
    # Un timeout o una conexion caida no traen codigo, y son justo lo que hay
    # que reintentar.
    return isinstance(excepcion, (aiosmtplib.SMTPConnectError,
                                  aiosmtplib.SMTPServerDisconnected,
                                  aiosmtplib.SMTPTimeoutError,
                                  ConnectionError, TimeoutError, OSError))


async def _enviar_una_vez(ajustes: Ajustes, correo: EmailMessage) -> dict:
    """Una conexion, un envio. Devuelve el mapa de rechazos del servidor."""
    rechazos, _ = await aiosmtplib.send(
        correo,
        hostname=ajustes.smtp_host,
        port=ajustes.smtp_port,
        username=ajustes.smtp_user or None,
        password=ajustes.smtp_password or None,
        start_tls=(ajustes.cifrado == STARTTLS),
        use_tls=(ajustes.cifrado == SSL),
        timeout=ajustes.timeout_s,
    )
    return rechazos or {}


async def enviar(ajustes: Ajustes, mensaje: Mensaje, reparto: Reparto,
                 evento_id: int, enviador=None, dormir=None) -> Resultado:
    """Manda el correo, reintentando solo lo que tiene arreglo.

    `enviador` y `dormir` se inyectan en las pruebas: es lo que permite
    comprobar los reintentos y la diferencia entre un 451 y un 550 sin montar
    tres servidores de correo distintos.
    """
    if not ajustes.configurado:
        raise SinConfigurar(
            "Falta SMTP_HOST o SMTP_FROM: el servicio no puede enviar correo.")
    if not reparto.hay_a_quien_avisar:
        # No es un fallo del correo y no tiene sentido reintentarlo. Quien llama
        # lo registra igual, porque un evento Alto sin nadie a quien avisar es
        # un problema de configuracion que hay que ver en el dashboard.
        return Resultado(enviado=False, intentos=0, segundos=0.0,
                         error="No hay destinatarios activos para esta "
                               "severidad.")

    correo = armar(ajustes, mensaje, reparto, evento_id)
    enviador = enviador or _enviar_una_vez
    dormir = dormir if dormir is not None else _dormir

    comienzo = time.monotonic()
    espera = ajustes.espera_inicial_s
    ultimo = ""
    for intento in range(1, ajustes.intentos + 1):
        try:
            rechazos = await enviador(ajustes, correo)
        except Exception as exc:          # noqa: BLE001
            ultimo = f"{type(exc).__name__}: {exc}"
            if not _es_temporal(exc) or intento == ajustes.intentos:
                return Resultado(enviado=False, intentos=intento,
                                 segundos=time.monotonic() - comienzo,
                                 error=ultimo[:500])
            await dormir(espera)
            espera *= 2
            continue

        rechazados = tuple(sorted(rechazos))
        if rechazados and len(rechazados) >= len(reparto.destinatarios):
            # Nadie lo recibio. Es un fallo, aunque el servidor no haya lanzado.
            return Resultado(
                enviado=False, intentos=intento,
                segundos=time.monotonic() - comienzo,
                error=f"El servidor rechazo todas las direcciones: "
                      f"{', '.join(rechazados)}"[:500],
                rechazados=rechazados)
        return Resultado(enviado=True, intentos=intento,
                         segundos=time.monotonic() - comienzo,
                         rechazados=rechazados)

    # Inalcanzable con intentos >= 1, pero deja el contrato cerrado.
    return Resultado(enviado=False, intentos=ajustes.intentos,       # pragma: no cover
                     segundos=time.monotonic() - comienzo, error=ultimo[:500])


async def _dormir(segundos: float) -> None:
    import asyncio

    await asyncio.sleep(segundos)
