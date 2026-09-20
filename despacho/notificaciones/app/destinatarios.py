"""A quien se avisa de cada evento. HU-10, criterio 1.

  1. La notificacion se envia por correo en los tres niveles. Alta: a
     supervisores y administradores, con asunto marcado y prioridad alta;
     Media: a supervisores; Baja: a supervisores, con prioridad normal.

Cambio de alcance del 18/09/2026. El criterio original repartia por canal:
Alta a SMS y Slack, Media a Slack y correo, Baja a correo. Slack salio porque
se esta evaluando Teams en su lugar, y el SMS salio con el. Las tres
severidades quedan en un solo canal.

Eso deja una pregunta que hay que contestar bien: si todo va por correo, que
distingue una Alta de una Baja. La respuesta es lo que hace este modulo: la
severidad decide **a quien** se avisa y **con que urgencia**, en lugar de por
donde. Sin eso, el criterio 1 se quedaria sin contenido y las tres alertas
serian el mismo correo, que es la forma mas rapida de que un supervisor deje de
abrirlos.

Los correos salen de la tabla `usuario` de HU-15 y no de una lista en el
entorno. Dar de alta a alguien en el dashboard basta para que empiece a recibir
alertas, y darlo de baja lo corta de inmediato: una lista en una variable habria
que acordarse de tocarla el dia que alguien se va, y nadie se acuerda.
"""
from __future__ import annotations

import dataclasses

ALTA = "alta"
MEDIA = "media"
BAJA = "baja"

ADMINISTRADOR = "administrador"
SUPERVISOR = "supervisor"
CONSULTA = "consulta"

# Quien recibe cada nivel. El rol Consulta no aparece a proposito: es de solo
# lectura del dashboard (apartado 4) y no le corresponde actuar sobre una carga.
ROLES_POR_SEVERIDAD = {
    ALTA: (SUPERVISOR, ADMINISTRADOR),
    MEDIA: (SUPERVISOR,),
    BAJA: (SUPERVISOR,),
}

# Cabecera de prioridad del correo. Solo la Alta la lleva: si todas fueran
# urgentes, ninguna lo seria, y el cliente de correo dejaria de resaltarlas.
PRIORIDAD_ALTA = "1"
PRIORIDAD_NORMAL = "3"


@dataclasses.dataclass(frozen=True)
class Persona:
    """Un usuario que puede recibir avisos."""

    nombre: str
    correo: str
    rol: str
    activo: bool = True


@dataclasses.dataclass(frozen=True)
class Reparto:
    """A quien se avisa de este evento y con que urgencia."""

    severidad: str
    destinatarios: tuple[str, ...]
    roles: tuple[str, ...]
    urgente: bool

    @property
    def hay_a_quien_avisar(self) -> bool:
        return bool(self.destinatarios)

    @property
    def prioridad(self) -> str:
        return PRIORIDAD_ALTA if self.urgente else PRIORIDAD_NORMAL


def roles_de(severidad: str | None) -> tuple[str, ...]:
    """Los roles que reciben ese nivel.

    Una severidad desconocida se trata como Alta y no como Baja: si el sistema
    no sabe clasificar algo, es mejor que lo vea quien puede actuar.
    """
    if severidad not in ROLES_POR_SEVERIDAD:
        return ROLES_POR_SEVERIDAD[ALTA]
    return ROLES_POR_SEVERIDAD[severidad]


def repartir(severidad: str | None, personas: list[Persona]) -> Reparto:
    """Decide a quien se le manda el correo de este evento."""
    roles = roles_de(severidad)
    correos = []
    for persona in personas:
        if not persona.activo:
            # Un usuario dado de baja deja de recibir alertas el mismo dia. Es
            # la mitad util de que los usuarios se desactiven en lugar de
            # borrarse.
            continue
        if persona.rol not in roles:
            continue
        correo = persona.correo.strip().lower()
        if correo and correo not in correos:
            correos.append(correo)

    return Reparto(
        severidad=severidad or ALTA,
        destinatarios=tuple(correos),
        roles=roles,
        urgente=(severidad == ALTA or severidad not in ROLES_POR_SEVERIDAD),
    )
