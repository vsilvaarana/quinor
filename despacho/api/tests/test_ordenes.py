"""Tests del caso de uso de HU-02 contra MySQL real: cache, refresco e incidencias."""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app import ordenes, salud
from app.config import Ajustes
from app.models import Auditoria, OrdenDespacho
from tests.conftest import ORDEN_ERP, URL_PRUEBAS


@pytest.fixture()
def ajustes() -> Ajustes:
    from tests.conftest import ERP_URL

    return Ajustes(database_url=URL_PRUEBAS, erp_base_url=ERP_URL,
                   erp_timeout_seconds=2.0, erp_cache_ttl_seconds=900.0)


def _envejecer(sesion, numero: str, segundos: int) -> None:
    """Retrasa sincronizado_en para simular una copia local vieja."""
    sesion.execute(
        text("UPDATE orden_despacho SET sincronizado_en = :m WHERE numero_orden = :n"),
        {"m": dt.datetime.now() - dt.timedelta(seconds=segundos), "n": numero},
    )
    sesion.commit()


# ---------- Criterio 1: consulta al ERP y obtiene peso y sacos ----------

async def test_una_orden_nueva_se_trae_del_erp_y_se_guarda(sesion, ajustes, erp_sano):
    orden = await ordenes.obtener_orden(sesion, ajustes, "ORD-2026-0001")

    assert orden.id is not None
    assert orden.peso_esperado_kg == Decimal("20000.00")
    assert orden.sacos_esperados == 400
    assert orden.cliente == "Andean Foods GmbH"
    assert orden.fecha == dt.date(2026, 9, 14)
    assert orden.sincronizado_en is not None
    # Y quedo en la copia local del apartado 6.5.
    assert sesion.execute(text("SELECT COUNT(*) FROM orden_despacho")).scalar_one() == 1


async def test_el_numero_se_normaliza_a_mayusculas(sesion, ajustes, erp_sano):
    orden = await ordenes.obtener_orden(sesion, ajustes, "ord-2026-0001")
    assert orden.numero_orden == "ORD-2026-0001"


async def test_la_sincronizacion_queda_en_auditoria(sesion, ajustes, erp_sano):
    orden = await ordenes.obtener_orden(sesion, ajustes, "ORD-2026-0001")
    fila = sesion.scalars(
        select(Auditoria).where(Auditoria.accion == "sincronizar_orden")
    ).one()
    assert fila.entidad_id == orden.id
    assert fila.detalle["peso_esperado_kg"] == "20000.00"
    assert fila.detalle["sacos_esperados"] == 400
    assert fila.detalle["anterior"] is None     # era nueva


# ---------- Cache: no preguntar al ERP en cada pesada ----------

async def test_una_copia_vigente_no_vuelve_a_consultar_al_erp(sesion, ajustes, erp_sano):
    """Una rampa cargando no deberia depender de una llamada de red por pesada."""
    await ordenes.obtener_orden(sesion, ajustes, "ORD-2026-0001")
    llamadas = erp_sano.calls.call_count

    await ordenes.obtener_orden(sesion, ajustes, "ORD-2026-0001")
    await ordenes.obtener_orden(sesion, ajustes, "ORD-2026-0001")

    assert erp_sano.calls.call_count == llamadas


async def test_una_copia_vencida_se_refresca(sesion, ajustes, erp_sano):
    await ordenes.obtener_orden(sesion, ajustes, "ORD-2026-0001")
    llamadas = erp_sano.calls.call_count
    _envejecer(sesion, "ORD-2026-0001", 1800)      # el TTL son 900 s

    await ordenes.obtener_orden(sesion, ajustes, "ORD-2026-0001")
    assert erp_sano.calls.call_count > llamadas


async def test_refrescar_fuerza_la_consulta_aunque_este_vigente(sesion, ajustes, erp_sano):
    await ordenes.obtener_orden(sesion, ajustes, "ORD-2026-0001")
    llamadas = erp_sano.calls.call_count

    await ordenes.obtener_orden(sesion, ajustes, "ORD-2026-0001", refrescar=True)
    assert erp_sano.calls.call_count > llamadas


async def test_con_ttl_en_cero_se_consulta_siempre(sesion, erp_sano):
    from tests.conftest import ERP_URL

    sin_cache = Ajustes(database_url=URL_PRUEBAS, erp_base_url=ERP_URL,
                        erp_cache_ttl_seconds=0)
    await ordenes.obtener_orden(sesion, sin_cache, "ORD-2026-0001")
    llamadas = erp_sano.calls.call_count
    await ordenes.obtener_orden(sesion, sin_cache, "ORD-2026-0001")
    assert erp_sano.calls.call_count > llamadas


async def test_un_cambio_en_el_erp_actualiza_la_copia_y_deja_rastro(sesion, ajustes, erp_sano):
    """Si el ERP corrige la orden, la copia local sigue el cambio y se ve cual era."""
    await ordenes.obtener_orden(sesion, ajustes, "ORD-2026-0001")
    erp_sano.get(f"{ajustes.erp_base_url}/ordenes/ORD-2026-0001").respond(
        200, json={**ORDEN_ERP, "peso_esperado_kg": 19500.0, "sacos_esperados": 390})

    orden = await ordenes.obtener_orden(sesion, ajustes, "ORD-2026-0001", refrescar=True)

    assert orden.peso_esperado_kg == Decimal("19500.00")
    assert orden.sacos_esperados == 390
    ultima = sesion.scalars(
        select(Auditoria).where(Auditoria.accion == "sincronizar_orden")
        .order_by(Auditoria.id.desc())
    ).first()
    assert ultima.detalle["anterior"]["peso_esperado_kg"] == "20000.00"
    assert ultima.detalle["anterior"]["sacos_esperados"] == 400
    # Sigue habiendo una sola fila: se actualiza, no se duplica.
    assert sesion.execute(text("SELECT COUNT(*) FROM orden_despacho")).scalar_one() == 1


# ---------- Criterio 2: la orden no existe ----------

async def test_si_el_erp_no_reconoce_la_orden_no_se_guarda_nada(sesion, ajustes, erp_sin_orden):
    """RN-02: sin orden valida en el ERP no hay carga que registrar."""
    with pytest.raises(ordenes.OrdenNoDisponible) as exc:
        await ordenes.obtener_orden(sesion, ajustes, "ORD-FANTASMA")

    assert "no reconoce" in str(exc.value)
    assert sesion.scalars(select(OrdenDespacho)).all() == []
    fila = sesion.scalars(
        select(Auditoria).where(Auditoria.accion == "orden_rechazada_por_erp")
    ).one()
    assert fila.detalle["numero_orden"] == "ORD-FANTASMA"
    # El ERP esta sano: contestar que algo no existe es contestar.
    assert salud.ultimo(sesion, "erp").estado == salud.OK


# ---------- Incidencia de integracion (RN-02) ----------

async def test_sin_erp_y_sin_copia_local_la_carga_se_detiene(sesion, ajustes, erp_caido):
    with pytest.raises(ordenes.OrdenNoDisponible) as exc:
        await ordenes.obtener_orden(sesion, ajustes, "ORD-2026-0001")

    assert "No hay copia local" in str(exc.value)
    assert salud.ultimo(sesion, "erp").estado == salud.ERROR
    fila = sesion.scalars(
        select(Auditoria).where(Auditoria.accion == "incidencia_integracion_erp")
    ).one()
    assert fila.detalle["hubo_copia_local"] is False


async def test_sin_erp_pero_con_copia_local_se_sigue_con_ella(sesion, ajustes, erp_sano,
                                                              erp_caido):
    """Un corte de red no debe parar una rampa si ya sabemos que dice la orden.

    Se registra la incidencia de integracion, y la pesada continua contra los
    valores conocidos. Es preferible a detener el despacho por un fallo que no
    dice nada sobre la orden.
    """
    # erp_sano se monta primero y deja la copia local; erp_caido lo sustituye.
    with erp_sano:
        await ordenes.obtener_orden(sesion, ajustes, "ORD-2026-0001")
    _envejecer(sesion, "ORD-2026-0001", 1800)

    orden = await ordenes.obtener_orden(sesion, ajustes, "ORD-2026-0001")

    assert orden.peso_esperado_kg == Decimal("20000.00")
    assert salud.ultimo(sesion, "erp").estado == salud.ERROR
    fila = sesion.scalars(
        select(Auditoria).where(Auditoria.accion == "incidencia_integracion_erp")
    ).one()
    assert fila.detalle["hubo_copia_local"] is True


# ---------- Consultas locales ----------

async def test_listar_ordenes_devuelve_la_copia_local(sesion, ajustes, erp_sano):
    assert ordenes.listar_ordenes(sesion) == []
    await ordenes.obtener_orden(sesion, ajustes, "ORD-2026-0001")
    assert [o.numero_orden for o in ordenes.listar_ordenes(sesion)] == ["ORD-2026-0001"]


def test_buscar_local_no_distingue_mayusculas(sesion, orden):
    assert ordenes.buscar_local(sesion, "ord-2026-0001").id == orden.id
    assert ordenes.buscar_local(sesion, "ORD-OTRA") is None


def test_una_copia_recien_leida_esta_vigente(sesion, orden):
    assert ordenes.esta_vigente(orden, ttl_s=900) is True
    assert ordenes.esta_vigente(orden, ttl_s=0) is False
