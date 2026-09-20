"""Lectura de la bascula de despacho por Modbus TCP. Nucleo de HU-01.

Mapa de registros holding acordado con el fabricante y reproducido por el
simulador sim/scale_sim.py:

    0-1  peso en kg, float32 big-endian
    2    contador de pesadas, se incrementa en cada peso estable
    3    estado: 0 en movimiento, 1 peso estable

Criterio 2 de HU-01: si la bascula no responde en 5 s hay que dar el intento por
perdido. Ese limite es un presupuesto total, no un timeout por operacion: la
conexion, la lectura y los reintentos caben dentro de los mismos 5 s, porque al
operador le da igual en cual de las tres etapas se atasco.

El modulo no lee configuracion: todo llega por parametro. Una prueba apunta a
otra bascula pasando host y puerto, sin tocar el entorno del proceso.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import struct
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

import structlog
from pymodbus.client import AsyncModbusTcpClient
from tenacity import AsyncRetrying, stop_after_attempt, wait_fixed

log = structlog.get_logger("quinor.bascula")

REG_PESO = 0        # dos registros: 0 y 1
REG_CONTADOR = 2
REG_ESTADO = 3
REG_TOTALES = 4

DOS_DECIMALES = Decimal("0.01")


class ErrorBascula(RuntimeError):
    """La bascula no respondio, o respondio algo que no se puede interpretar."""


@dataclass(frozen=True)
class LecturaBascula:
    peso_kg: Decimal
    contador: int
    estable: bool
    leido_en: dt.datetime
    bascula_id: str


def decodificar_peso(registros: list[int]) -> Decimal:
    """Convierte dos registros de 16 bits en un peso con dos decimales.

    El redondeo es HALF_UP y no el de coma flotante de Python: 1.125 debe quedar
    en 1.13, como lo haria el ticket impreso de la bascula.
    """
    crudo = b"".join(r.to_bytes(2, "big") for r in registros[:2])
    valor = struct.unpack(">f", crudo)[0]
    return Decimal(repr(valor)).quantize(DOS_DECIMALES, rounding=ROUND_HALF_UP)


async def _leer_registros(host: str, puerto: int, unit_id: int, timeout: float) -> list[int]:
    cliente = AsyncModbusTcpClient(host, port=puerto, timeout=timeout)
    try:
        await cliente.connect()
        if not cliente.connected:
            raise ErrorBascula(f"sin conexion Modbus TCP contra {host}:{puerto}")
        respuesta = await cliente.read_holding_registers(
            REG_PESO, count=REG_TOTALES, slave=unit_id
        )
        if respuesta.isError():
            raise ErrorBascula(f"respuesta Modbus con error: {respuesta}")
        return list(respuesta.registers)
    finally:
        cliente.close()


async def leer_peso(
    host: str,
    puerto: int,
    unit_id: int = 1,
    presupuesto_s: float = 5.0,
    bascula_id: str = "BASCULA-01",
) -> LecturaBascula:
    """Lee la bascula dentro del presupuesto de tiempo. Lanza ErrorBascula si no llega.

    Los reintentos comparten el presupuesto: no lo amplian. Si se agota a mitad
    del segundo intento, el resultado es el mismo que si se hubiera agotado en el
    primero. Todo fallo nombra la bascula: con la segunda unidad del RNF-04, un
    mensaje sin identificador no dice nada.
    """
    # Timeout por operacion holgado dentro del presupuesto: deja sitio a un
    # segundo intento si el primero falla rapido, sin pasarse del total.
    timeout_op = max(1.0, presupuesto_s / 2)

    async def _intentar() -> list[int]:
        async for intento in AsyncRetrying(
            stop=stop_after_attempt(2), wait=wait_fixed(0.3), reraise=True
        ):
            with intento:
                return await _leer_registros(host, puerto, unit_id, timeout_op)
        raise AssertionError("inalcanzable")  # pragma: no cover

    try:
        registros = await asyncio.wait_for(_intentar(), timeout=presupuesto_s)
    except asyncio.TimeoutError as exc:
        raise ErrorBascula(
            f"la bascula {bascula_id} no respondio en {presupuesto_s:g} s"
        ) from exc
    except ErrorBascula as exc:
        raise ErrorBascula(f"la bascula {bascula_id} no respondio: {exc}") from exc
    except Exception as exc:
        raise ErrorBascula(
            f"fallo la lectura de la bascula {bascula_id}: {type(exc).__name__}: {exc}"
        ) from exc

    if len(registros) < REG_TOTALES:
        raise ErrorBascula(
            f"la bascula {bascula_id} devolvio {len(registros)} registros y se esperaban "
            f"{REG_TOTALES}: no se puede decodificar el peso"
        )

    lectura = LecturaBascula(
        peso_kg=decodificar_peso(registros),
        contador=registros[REG_CONTADOR],
        estable=bool(registros[REG_ESTADO]),
        # Hora local de planta, la misma referencia que usaran las camaras.
        leido_en=dt.datetime.now().replace(tzinfo=None),
        bascula_id=bascula_id,
    )
    log.info("lectura_bascula", bascula=bascula_id, peso=str(lectura.peso_kg),
             contador=lectura.contador, estable=lectura.estable)
    return lectura
