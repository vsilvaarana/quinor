"""Tests unitarios del cliente REST del ERP. HU-02, criterios 1 y 2."""

import datetime as dt
from decimal import Decimal

import httpx
import pytest
import respx

from app import erp
from tests.conftest import ERP_URL, ORDEN_ERP


# ---------- Criterio 1: consulta y obtiene peso y sacos ----------

async def test_obtiene_peso_esperado_y_numero_de_sacos():
    with respx.mock:
        respx.get(f"{ERP_URL}/ordenes/ORD-2026-0001").respond(200, json=ORDEN_ERP)
        orden = await erp.consultar_orden(ERP_URL, "ORD-2026-0001")

    assert orden.numero_orden == "ORD-2026-0001"
    assert orden.cliente == "Andean Foods GmbH"
    assert orden.producto == "Quinua blanca organica"
    assert orden.peso_esperado_kg == Decimal("20000.0")
    assert orden.sacos_esperados == 400
    assert orden.fecha == dt.date(2026, 9, 14)


async def test_el_numero_de_orden_se_consulta_en_mayusculas():
    """El operador escribe como quiere; el ERP indexa en mayusculas."""
    with respx.mock:
        ruta = respx.get(f"{ERP_URL}/ordenes/ORD-2026-0001").respond(200, json=ORDEN_ERP)
        await erp.consultar_orden(ERP_URL, "ord-2026-0001")
    assert ruta.called


async def test_la_barra_final_de_la_url_base_no_duplica_separadores():
    with respx.mock:
        ruta = respx.get(f"{ERP_URL}/ordenes/ORD-2026-0001").respond(200, json=ORDEN_ERP)
        await erp.consultar_orden(f"{ERP_URL}/", "ORD-2026-0001")
    assert ruta.called


def test_el_peso_se_cuantiza_a_dos_decimales():
    """El ERP publica el peso como decimal libre; la base guarda dos cifras."""
    orden = erp.OrdenERP(**{**ORDEN_ERP, "peso_esperado_kg": 19850.456})
    assert orden.peso_cuantizado() == Decimal("19850.46")
    assert orden.peso_cuantizado().as_tuple().exponent == -2


# ---------- Criterio 2: la orden no existe ----------

async def test_un_404_significa_que_la_orden_no_existe():
    """Respuesta valida del ERP: la orden no esta. No es un fallo de integracion."""
    with respx.mock:
        respx.get(f"{ERP_URL}/ordenes/ORD-FANTASMA").respond(404, json={"detail": "no existe"})
        with pytest.raises(erp.OrdenNoExisteEnERP) as exc:
            await erp.consultar_orden(ERP_URL, "ORD-FANTASMA")
    assert "ORD-FANTASMA" in str(exc.value)


# ---------- Fallos de integracion ----------

@pytest.mark.parametrize("codigo", [400, 401, 500, 502, 503])
async def test_otros_codigos_son_fallo_de_integracion(codigo):
    """500 no dice que la orden no exista: dice que el ERP no pudo contestar."""
    with respx.mock:
        respx.get(f"{ERP_URL}/ordenes/ORD-2026-0001").respond(codigo)
        with pytest.raises(erp.ErpNoDisponible) as exc:
            await erp.consultar_orden(ERP_URL, "ORD-2026-0001")
    assert str(codigo) in str(exc.value)


async def test_sin_red_el_erp_no_esta_disponible():
    with respx.mock:
        respx.get(f"{ERP_URL}/ordenes/ORD-2026-0001").mock(
            side_effect=httpx.ConnectError("sin ruta"))
        with pytest.raises(erp.ErpNoDisponible) as exc:
            await erp.consultar_orden(ERP_URL, "ORD-2026-0001")
    assert "ConnectError" in str(exc.value)


async def test_un_timeout_es_fallo_de_integracion():
    with respx.mock:
        respx.get(f"{ERP_URL}/ordenes/ORD-2026-0001").mock(
            side_effect=httpx.ReadTimeout("tardo demasiado"))
        with pytest.raises(erp.ErpNoDisponible):
            await erp.consultar_orden(ERP_URL, "ORD-2026-0001", timeout_s=0.5)


@pytest.mark.parametrize(
    "cuerpo, motivo",
    [
        ({"numero_orden": "ORD-1"}, "faltan campos"),
        ({**ORDEN_ERP, "peso_esperado_kg": 0}, "peso en cero"),
        ({**ORDEN_ERP, "peso_esperado_kg": -5}, "peso negativo"),
        ({**ORDEN_ERP, "sacos_esperados": 0}, "sin sacos"),
        ({**ORDEN_ERP, "fecha": "no-es-fecha"}, "fecha invalida"),
        ({**ORDEN_ERP, "cliente": ""}, "cliente vacio"),
    ],
)
async def test_una_orden_inutilizable_se_rechaza_como_integracion(cuerpo, motivo):
    """Mejor rechazarla aqui, donde se puede decir de donde vino el dato, que
    dejar que choque contra las restricciones CHECK del esquema."""
    with respx.mock:
        respx.get(f"{ERP_URL}/ordenes/ORD-2026-0001").respond(200, json=cuerpo)
        with pytest.raises(erp.ErpNoDisponible) as exc:
            await erp.consultar_orden(ERP_URL, "ORD-2026-0001")
    assert "no se puede interpretar" in str(exc.value), motivo


async def test_una_respuesta_que_no_es_json_se_rechaza():
    with respx.mock:
        respx.get(f"{ERP_URL}/ordenes/ORD-2026-0001").respond(
            200, content=b"<html>portal de mantenimiento</html>",
            headers={"Content-Type": "text/html"})
        with pytest.raises(erp.ErpNoDisponible):
            await erp.consultar_orden(ERP_URL, "ORD-2026-0001")


def test_las_dos_familias_de_fallo_comparten_raiz():
    """Quien quiera tratarlos igual puede capturar ErrorERP; quien no, no."""
    assert issubclass(erp.OrdenNoExisteEnERP, erp.ErrorERP)
    assert issubclass(erp.ErpNoDisponible, erp.ErrorERP)
    assert not issubclass(erp.OrdenNoExisteEnERP, erp.ErpNoDisponible)
