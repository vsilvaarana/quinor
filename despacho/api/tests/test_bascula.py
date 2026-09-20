"""Tests unitarios del cliente Modbus de la bascula. HU-01, criterios 1, 2 y 3."""

import struct
import time
from decimal import Decimal

import pytest

from app import bascula
from tests.conftest import CONTADOR_FIJO, PESO_FIJO, SIN_NADIE


def _a_registros(valor: float) -> list[int]:
    crudo = struct.pack(">f", valor)
    return [int.from_bytes(crudo[0:2], "big"), int.from_bytes(crudo[2:4], "big")]


# ---------- Decodificacion del peso (criterio 3) ----------

@pytest.mark.parametrize(
    "valor, esperado",
    [
        (20000.0, "20000.00"),
        (19850.0, "19850.00"),
        (19999.994, "19999.99"),
        (0.0, "0.00"),
        (123.456, "123.46"),
    ],
)
def test_el_peso_se_cuantiza_a_dos_decimales(valor, esperado):
    resultado = bascula.decodificar_peso(_a_registros(valor))
    assert resultado == Decimal(esperado)
    assert resultado.as_tuple().exponent == -2


def test_el_redondeo_es_half_up_y_no_bancario():
    """El ticket de una bascula redondea 0.005 hacia arriba, no al par mas cercano."""
    # 1.125 es exacto en binario, asi que la prueba mide el redondeo y no el
    # error de representacion de coma flotante.
    assert bascula.decodificar_peso(_a_registros(1.125)) == Decimal("1.13")


# ---------- Lectura correcta (criterio 1) ----------

async def test_lee_peso_estable_por_modbus(bascula_estable):
    lectura = await bascula.leer_peso(
        host="127.0.0.1", puerto=bascula_estable, unit_id=1, bascula_id="BASCULA-TEST"
    )
    assert lectura.peso_kg == PESO_FIJO
    assert lectura.peso_kg.as_tuple().exponent == -2
    assert lectura.contador == CONTADOR_FIJO
    assert lectura.estable is True
    assert lectura.bascula_id == "BASCULA-TEST"
    assert lectura.leido_en is not None


async def test_una_bascula_en_movimiento_se_lee_igual_pero_marcada(bascula_inestable):
    """La lectura no falla: es quien la consume el que decide no registrarla."""
    lectura = await bascula.leer_peso(host="127.0.0.1", puerto=bascula_inestable)
    assert lectura.estable is False
    assert lectura.peso_kg == Decimal("19000.00")


# ---------- Fallos (criterio 2) ----------

async def test_una_conexion_rechazada_falla_rapido_y_nombra_la_bascula():
    """Bascula apagada o cable suelto: el sistema operativo rechaza al instante.

    No hay que esperar los 5 s cuando ya se sabe que no hay nadie al otro lado.
    """
    inicio = time.monotonic()
    with pytest.raises(bascula.ErrorBascula) as exc:
        await bascula.leer_peso(
            host="127.0.0.1", puerto=SIN_NADIE, presupuesto_s=5.0, bascula_id="BASCULA-TEST"
        )
    assert time.monotonic() - inicio < 2.0
    assert "BASCULA-TEST" in str(exc.value)
    assert "no respondio" in str(exc.value)


async def test_se_rinde_dentro_del_presupuesto_de_cinco_segundos(bascula_muda):
    """Criterio 2: si la bascula no responde en 5 s, el intento se da por perdido.

    La bascula muda acepta el socket y luego calla. Sin presupuesto de tiempo la
    peticion se quedaria colgada y el operador no sabria si la carga quedo
    registrada o no.
    """
    inicio = time.monotonic()
    with pytest.raises(bascula.ErrorBascula) as exc:
        await bascula.leer_peso(
            host="127.0.0.1", puerto=bascula_muda, presupuesto_s=5.0,
            bascula_id="BASCULA-TEST",
        )
    transcurrido = time.monotonic() - inicio
    assert 4.5 <= transcurrido <= 6.5, f"tardo {transcurrido:.1f} s, el presupuesto era 5 s"
    assert "BASCULA-TEST" in str(exc.value)
    assert "5 s" in str(exc.value)


async def test_un_presupuesto_corto_se_respeta(bascula_muda):
    """El presupuesto es configurable: con 1 s no se esperan 5."""
    inicio = time.monotonic()
    with pytest.raises(bascula.ErrorBascula):
        await bascula.leer_peso(host="127.0.0.1", puerto=bascula_muda, presupuesto_s=1.0)
    transcurrido = time.monotonic() - inicio
    assert 0.8 <= transcurrido <= 2.5, f"tardo {transcurrido:.1f} s con presupuesto de 1 s"


async def test_una_respuesta_incompleta_se_rechaza(monkeypatch, bascula_estable):
    """Si llegan menos registros de los esperados, el peso no se puede decodificar."""
    async def _corta(*_args, **_kwargs):
        return [0, 0]

    monkeypatch.setattr(bascula, "_leer_registros", _corta)
    with pytest.raises(bascula.ErrorBascula) as exc:
        await bascula.leer_peso(host="127.0.0.1", puerto=bascula_estable)
    assert "registros" in str(exc.value)


async def test_un_error_inesperado_se_envuelve(monkeypatch, bascula_estable):
    """Cualquier fallo termina como ErrorBascula: quien llama trata un solo tipo."""
    async def _revienta(*_args, **_kwargs):
        raise ValueError("algo raro del driver")

    monkeypatch.setattr(bascula, "_leer_registros", _revienta)
    with pytest.raises(bascula.ErrorBascula) as exc:
        await bascula.leer_peso(host="127.0.0.1", puerto=1, bascula_id="BASCULA-TEST")
    assert "ValueError" in str(exc.value)
    assert "BASCULA-TEST" in str(exc.value)


async def test_un_error_modbus_del_equipo_se_reporta(monkeypatch, bascula_estable):
    """La bascula contesta, pero con un codigo de excepcion Modbus."""
    class _RespuestaConError:
        registers: list[int] = []

        def isError(self):
            return True

    class _ClienteFalso:
        connected = True

        def __init__(self, *_a, **_k):
            pass

        async def connect(self):
            return True

        async def read_holding_registers(self, *_a, **_k):
            return _RespuestaConError()

        def close(self):
            pass

    monkeypatch.setattr(bascula, "AsyncModbusTcpClient", _ClienteFalso)
    with pytest.raises(bascula.ErrorBascula) as exc:
        await bascula.leer_peso(host="127.0.0.1", puerto=1)
    assert "Modbus" in str(exc.value)
