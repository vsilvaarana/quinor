"""Contratos de entrada y salida del servicio de notificaciones."""
from __future__ import annotations

from pydantic import BaseModel, Field


class PeticionDeAviso(BaseModel):
    """Pedir que se avise de un evento. HU-10.

    Lo unico obligatorio es el identificador del evento. El contenido del correo
    se lee de la base: el correo tiene que decir lo mismo que el dashboard, y
    dejar que quien llama mande los datos abre la puerta a que cuenten cosas
    distintas.
    """

    evento_id: int = Field(ge=1)

    # Criterio 3: "en menos de 60 s tras el analisis". Quien llama sabe cuando
    # termino el analisis; el servicio, no. Con esta marca se puede medir y
    # guardar el retraso real en lugar de suponerlo.
    segundos_desde_analisis: float | None = Field(
        default=None, ge=0,
        description="Segundos transcurridos desde que termino el analisis del "
                    "evento. Se guarda para verificar el criterio 3.")

    # Reavisar es una decision de una persona, no del sistema. Queda en el log.
    forzar: bool = Field(
        default=False,
        description="Vuelve a enviar aunque el evento ya estuviera avisado.")


class RespuestaDeAviso(BaseModel):
    """Lo que el servicio devuelve. HU-10, criterios 1, 2 y 3."""

    evento_id: int
    # False cuando no habia a quien avisar o cuando el correo no salio. En los
    # dos casos queda registrado en la tabla notificacion.
    enviado: bool
    # True cuando ya existia un aviso enviado para este evento y no se repitio.
    duplicado: bool = False

    # Criterio 1.
    severidad: str = ""
    destinatarios: list[str] = []
    roles: list[str] = []
    urgente: bool = False

    # Criterio 2: el asunto lleva orden y diferencia, y el cuerpo el enlace.
    asunto: str = ""
    enlace: str = ""

    # Criterio 3.
    intentos: int = 0
    segundos_de_envio: float = 0.0
    segundos_desde_analisis: float | None = None
    dentro_del_criterio: bool | None = None

    notificacion_id: int | None = None
    error: str = ""
    # Direcciones que el servidor rechazo aceptando el resto.
    rechazados: list[str] = []


class RespuestaDeSalud(BaseModel):
    estado: str
    servidor: str
    remitente: str
    cifrado: str
    configurado: bool
    base_de_datos: bool
    destinatarios_alta: int
    intentos: int
    mensaje: str | None = None
