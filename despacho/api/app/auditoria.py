"""Escritura en la tabla de auditoria.

La tabla es de solo insercion: los triggers trg_auditoria_no_update y
trg_auditoria_no_delete del esquema rechazan cualquier otra operacion, incluso
desde una conexion con privilegios de mas. Este modulo solo sabe insertar, que
es todo lo que la aplicacion puede hacer.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.orm import Session

from app.models import Auditoria


def registrar(
    sesion: Session,
    entidad: str,
    accion: str,
    entidad_id: int | None = None,
    usuario_id: int | None = None,
    detalle: dict[str, Any] | None = None,
) -> Auditoria:
    """Deja constancia de una accion. usuario_id en None marca al sistema.

    No hace commit: la entrada de auditoria forma parte de la misma transaccion
    que la accion que describe, de modo que nunca queda registrada una operacion
    que al final no ocurrio.
    """
    fila = Auditoria(
        entidad=entidad,
        entidad_id=entidad_id,
        accion=accion,
        usuario_id=usuario_id,
        detalle=detalle,
        fecha=dt.datetime.now().replace(tzinfo=None),
    )
    sesion.add(fila)
    return fila
