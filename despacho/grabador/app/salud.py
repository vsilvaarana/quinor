"""Registro del estado de las camaras y del disco. HU-05, criterio 3.

"Si una camara se desconecta se registra en la tabla salud_componente, expuesto
por GET /salud."

El grabador escribe en la misma tabla que el orquestador, con la misma regla:
solo se inserta cuando el estado o el mensaje cambian. Una camara caida durante
la noche generaria miles de filas identicas y enterraria justo lo que interesa,
que es el minuto en que se cayo y el minuto en que volvio.

No hay endpoint aqui: el `GET /salud` del orquestador ya lee esta tabla, asi que
la camara aparece en la misma respuesta que la bascula y el ERP sin que el
grabador tenga que exponer nada.
"""
from __future__ import annotations

import datetime as dt

import structlog
from sqlalchemy import (BigInteger, Column, Enum, MetaData, String, Table,
                        select)
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy.engine import Engine

log = structlog.get_logger("quinor.salud")

OK = "ok"
ADVERTENCIA = "advertencia"
ERROR = "error"

COMPONENTE_DISCO = "disco-video"

# La tabla la crea db/01_esquema.sql del orquestador, que es la fuente de
# verdad. Aqui se declara solo lo que este servicio necesita escribir: el
# grabador no define el esquema, lo usa.
_metadatos = MetaData()
salud_componente = Table(
    "salud_componente", _metadatos,
    Column("id", BigInteger, primary_key=True),
    Column("componente", String(60), nullable=False),
    Column("estado", Enum("ok", "advertencia", "error"), nullable=False),
    Column("mensaje", String(500)),
    Column("verificado_en", MySQLDateTime(fsp=6), nullable=False),
)


def _ahora() -> dt.datetime:
    return dt.datetime.now().replace(tzinfo=None)


def ultimo(motor: Engine, componente: str) -> dict | None:
    consulta = (select(salud_componente)
                .where(salud_componente.c.componente == componente)
                .order_by(salud_componente.c.verificado_en.desc(),
                          salud_componente.c.id.desc())
                .limit(1))
    with motor.connect() as conexion:
        fila = conexion.execute(consulta).mappings().first()
    return dict(fila) if fila else None


def registrar_si_cambia(
    motor: Engine, componente: str, estado: str, mensaje: str | None = None
) -> bool:
    """Inserta una fila solo si el estado o el mensaje difieren del ultimo.

    Devuelve True si hubo cambio. Cada llamada usa su propia transaccion corta:
    el grabador es un proceso que vive semanas y no debe sostener una conexion
    abierta entre segmento y segmento.
    """
    previo = ultimo(motor, componente)
    if previo and previo["estado"] == estado and (previo["mensaje"] or "") == (mensaje or ""):
        return False

    with motor.begin() as conexion:
        conexion.execute(salud_componente.insert().values(
            componente=componente,
            estado=estado,
            mensaje=(mensaje or "")[:500] or None,
            verificado_en=_ahora(),
        ))
    log.info("salud_cambio", componente=componente, estado=estado, mensaje=mensaje)
    return True


def camara_conectada(motor: Engine, componente: str, detalle: str) -> bool:
    return registrar_si_cambia(motor, componente, OK, detalle)


def camara_desconectada(motor: Engine, componente: str, motivo: str) -> bool:
    """Criterio 3. El motivo es el stderr de ffmpeg, que es lo que explica que paso."""
    return registrar_si_cambia(
        motor, componente, ERROR,
        motivo or "la camara dejo de responder y el grabador no pudo reconectar")
