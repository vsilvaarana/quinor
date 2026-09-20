"""Marca de inicio de carga. Apoyo de HU-06.

El apartado 5.2 dice que "las camaras graban de forma continua; el sistema marca
el inicio de la ventana de carga", y el criterio 1 de HU-06 mide el clip "desde
5 min antes del inicio de carga". Hasta aqui el modelo solo guardaba el instante
de la pesada, asi que la ventana no tenia de donde empezar.

Este modulo abre esa marca cuando el camion entra a la rampa y la cierra cuando
la pesada registra el peso. La pesada se queda con el instante, de modo que el
recorte del clip no depende de que esta fila siga existiendo.

Si nadie marca el inicio, la carga se registra igual y el clip cubre solo los
5 minutos previos al cierre. Es peor, pero es mejor que rechazar la pesada: el
peso del camion no puede perderse porque falte una marca de video.
"""
from __future__ import annotations

import datetime as dt

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auditoria
from app.models import Carga, OrdenDespacho

log = structlog.get_logger("quinor.cargas")


class CargaYaAbierta(ValueError):
    """Esa orden ya tiene una carga abierta.

    El esquema tambien lo impide, con un indice unico parcial. Aqui se detecta
    antes para poder decirlo con un mensaje util.
    """


def abierta_de(sesion: Session, orden_id: int) -> Carga | None:
    return sesion.scalars(
        select(Carga).where(Carga.orden_id == orden_id, Carga.consumida_en.is_(None))
    ).first()


def abrir(
    sesion: Session,
    orden: OrdenDespacho,
    bascula_id: str,
    usuario_id: int | None = None,
    momento: dt.datetime | None = None,
) -> Carga:
    """Marca que empieza la carga de una orden."""
    existente = abierta_de(sesion, orden.id)
    if existente is not None:
        raise CargaYaAbierta(
            f"La orden {orden.numero_orden} ya tiene una carga abierta desde "
            f"{existente.inicio.isoformat()}")

    carga = Carga(
        orden_id=orden.id,
        bascula_id=bascula_id,
        inicio=momento or dt.datetime.now().replace(tzinfo=None),
        usuario_id=usuario_id,
    )
    sesion.add(carga)
    sesion.flush()
    auditoria.registrar(
        sesion, entidad="carga", entidad_id=carga.id, accion="abrir_carga",
        usuario_id=usuario_id,
        detalle={"numero_orden": orden.numero_orden, "bascula_id": bascula_id,
                 "inicio": carga.inicio.isoformat()},
    )
    sesion.commit()
    sesion.refresh(carga)
    log.info("carga_abierta", orden=orden.numero_orden, bascula=bascula_id,
             inicio=carga.inicio.isoformat())
    return carga


def cerrar(sesion: Session, orden_id: int, pesada) -> dt.datetime | None:
    """Cierra la carga abierta de una orden con la pesada que la termina.

    Devuelve el instante de inicio, que es lo que la pesada guarda. No hace
    commit: forma parte de la misma transaccion que la pesada, de modo que nunca
    queda una carga cerrada por una pesada que al final no se registro.
    """
    carga = abierta_de(sesion, orden_id)
    if carga is None:
        return None
    carga.consumida_en = dt.datetime.now().replace(tzinfo=None)
    carga.pesada_id = pesada.id
    sesion.flush()
    log.info("carga_cerrada", carga_id=carga.id, pesada_id=pesada.id,
             duracion_s=round((pesada.fecha_hora - carga.inicio).total_seconds(), 1))
    return carga.inicio


def listar(sesion: Session, solo_abiertas: bool = False, limite: int = 50) -> list[Carga]:
    consulta = select(Carga).order_by(Carga.inicio.desc(), Carga.id.desc()).limit(limite)
    if solo_abiertas:
        consulta = consulta.where(Carga.consumida_en.is_(None))
    return list(sesion.scalars(consulta).all())
