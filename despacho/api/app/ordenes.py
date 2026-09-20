"""Caso de uso de HU-02: obtener la orden de despacho del ERP/WMS.

Como operador de despacho, quiero que el sistema obtenga del ERP/WMS el peso y
cantidad de sacos esperados de la orden de despacho, para comparar lo cargado
contra lo planificado.

Criterios de aceptacion:
  1. Dado un numero de orden, el sistema consulta el ERP por API REST y obtiene
     peso esperado y numero de sacos.
  2. Si la orden no existe se muestra un mensaje y no se crea evento.
  3. La respuesta se guarda junto a la pesada.

La tabla orden_despacho es la copia local de la que habla el apartado 6.5, y
sincronizado_en marca cuando se leyo del ERP. Mientras esa copia sea reciente no
se vuelve a preguntar: una rampa cargando no deberia depender de una llamada de
red por cada pesada.
"""
from __future__ import annotations

import datetime as dt

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auditoria, erp, salud
from app.config import Ajustes
from app.models import OrdenDespacho

log = structlog.get_logger("quinor.ordenes")

COMPONENTE_ERP = "erp"


class OrdenNoDisponible(LookupError):
    """No hay orden utilizable: ni el ERP la reconoce, ni hay copia local."""


def buscar_local(sesion: Session, numero_orden: str) -> OrdenDespacho | None:
    return sesion.scalars(
        select(OrdenDespacho).where(OrdenDespacho.numero_orden == numero_orden.upper())
    ).first()


def esta_vigente(orden: OrdenDespacho, ttl_s: float) -> bool:
    if ttl_s <= 0:
        return False
    edad = (dt.datetime.now() - orden.sincronizado_en).total_seconds()
    return edad < ttl_s


def _guardar(sesion: Session, datos: erp.OrdenERP, local: OrdenDespacho | None) -> OrdenDespacho:
    """Crea o actualiza la copia local con lo que acaba de decir el ERP."""
    ahora = dt.datetime.now().replace(tzinfo=None)
    if local is None:
        local = OrdenDespacho(numero_orden=datos.numero_orden.upper())
        sesion.add(local)
    local.cliente = datos.cliente
    local.producto = datos.producto
    local.peso_esperado_kg = datos.peso_cuantizado()
    local.sacos_esperados = datos.sacos_esperados
    local.fecha = datos.fecha
    local.sincronizado_en = ahora
    sesion.flush()
    return local


async def obtener_orden(
    sesion: Session,
    ajustes: Ajustes,
    numero_orden: str,
    refrescar: bool = False,
    usuario_id: int | None = None,
) -> OrdenDespacho:
    """Devuelve la orden, consultando al ERP cuando la copia local no sirve.

    refrescar=True fuerza la consulta aunque la copia este vigente, que es lo que
    necesita un supervisor cuando sabe que el ERP acaba de corregir la orden.
    """
    local = buscar_local(sesion, numero_orden)

    if local is not None and not refrescar and esta_vigente(local, ajustes.erp_cache_ttl_seconds):
        log.info("orden_desde_cache", orden=local.numero_orden,
                 sincronizado_en=local.sincronizado_en.isoformat())
        return local

    try:
        datos = await erp.consultar_orden(
            ajustes.erp_base_url, numero_orden, ajustes.erp_timeout_seconds
        )
    except erp.OrdenNoExisteEnERP as exc:
        # Criterio 2 y RN-02: el ERP contesto y no la reconoce. No hay carga que
        # registrar. El ERP esta sano, asi que su estado no cambia.
        salud.registrar_si_cambia(sesion, COMPONENTE_ERP, salud.OK,
                                  f"{ajustes.erp_base_url} responde")
        auditoria.registrar(
            sesion, entidad="orden_despacho", accion="orden_rechazada_por_erp",
            usuario_id=usuario_id,
            detalle={"numero_orden": numero_orden.upper(), "motivo": str(exc)},
        )
        sesion.commit()
        raise OrdenNoDisponible(str(exc)) from exc

    except erp.ErpNoDisponible as exc:
        # RN-02 pide registrar una incidencia de integracion. No sabemos si la
        # orden existe, asi que no la rechazamos: si hay copia local se sigue
        # con ella, y si no la hay, la carga se detiene.
        salud.registrar_si_cambia(sesion, COMPONENTE_ERP, salud.ERROR, str(exc))
        auditoria.registrar(
            sesion, entidad="orden_despacho", accion="incidencia_integracion_erp",
            usuario_id=usuario_id,
            detalle={"numero_orden": numero_orden.upper(), "motivo": str(exc),
                     "hubo_copia_local": local is not None},
        )
        sesion.commit()
        if local is not None:
            log.warning("orden_desde_copia_vencida", orden=local.numero_orden,
                        sincronizado_en=local.sincronizado_en.isoformat(), error=str(exc))
            return local
        raise OrdenNoDisponible(
            f"{exc}. No hay copia local de {numero_orden.upper()} con la que continuar."
        ) from exc

    anterior = None
    if local is not None:
        anterior = {"peso_esperado_kg": str(local.peso_esperado_kg),
                    "sacos_esperados": local.sacos_esperados}

    orden = _guardar(sesion, datos, local)
    salud.registrar_si_cambia(sesion, COMPONENTE_ERP, salud.OK,
                              f"{ajustes.erp_base_url} responde")
    auditoria.registrar(
        sesion, entidad="orden_despacho", entidad_id=orden.id,
        accion="sincronizar_orden", usuario_id=usuario_id,
        detalle={
            "numero_orden": orden.numero_orden,
            "peso_esperado_kg": str(orden.peso_esperado_kg),
            "sacos_esperados": orden.sacos_esperados,
            "anterior": anterior,
        },
    )
    sesion.commit()
    sesion.refresh(orden)
    log.info("orden_sincronizada", orden=orden.numero_orden, creada=anterior is None)
    return orden


def listar_ordenes(sesion: Session, limite: int = 50) -> list[OrdenDespacho]:
    return list(sesion.scalars(
        select(OrdenDespacho).order_by(OrdenDespacho.fecha.desc(),
                                       OrdenDespacho.id.desc()).limit(limite)
    ).all())
