"""Simulador Modbus TCP de la bascula de despacho (HU-01).

Sustituye la bascula fisica mientras no exista acceso a planta. Publica el peso
como float32 en dos registros holding consecutivos, tal como lo hace una bascula
industrial con salida Modbus.

Mapa de registros holding:
    0-1  peso en kg, float32 big-endian
    2    contador de pesadas, se incrementa en cada nueva lectura estable
    3    estado: 0 = en movimiento, 1 = peso estable

Para probar el criterio 2 de HU-01 (la bascula no responde en 5 s):
    docker compose stop scale-sim
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import struct

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)
from pymodbus.server import StartAsyncTcpServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scale-sim")

UNIT_ID = int(os.getenv("SCALE_UNIT_ID", "1"))
PORT = int(os.getenv("SCALE_SIM_PORT", "5020"))
INTERVALO_S = float(os.getenv("SCALE_SIM_INTERVAL", "15"))

# Una carga tipica: 400 sacos de 50 kg = 20 000 kg.
PESO_NOMINAL_KG = float(os.getenv("SCALE_SIM_NOMINAL_KG", "20000"))
# Proporcion de pesadas que simulan un faltante, para ejercitar HU-03 despues.
PROB_FALTANTE = float(os.getenv("SCALE_SIM_PROB_FALTANTE", "0.3"))

HOLDING = 3  # codigo de funcion de registros holding


def float_a_registros(valor: float) -> list[int]:
    """Empaqueta un float32 big-endian en dos registros de 16 bits."""
    crudo = struct.pack(">f", valor)
    return [
        int.from_bytes(crudo[0:2], "big"),
        int.from_bytes(crudo[2:4], "big"),
    ]


def generar_peso() -> float:
    """Devuelve un peso realista: nominal, o con uno a tres sacos de menos."""
    if random.random() < PROB_FALTANTE:
        sacos_faltantes = random.randint(1, 3)
        peso = PESO_NOMINAL_KG - sacos_faltantes * 50
    else:
        peso = PESO_NOMINAL_KG
    # Ruido de +/- 5 kg propio de una bascula de plataforma.
    return round(peso + random.uniform(-5, 5), 2)


async def actualizar(contexto: ModbusServerContext) -> None:
    """Publica una nueva pesada estable cada INTERVALO_S segundos."""
    contador = 0
    esclavo = contexto[UNIT_ID]
    while True:
        # Fase en movimiento: el peso oscila y el estado es 0.
        esclavo.setValues(HOLDING, 3, [0])
        await asyncio.sleep(min(3.0, INTERVALO_S / 3))

        peso = generar_peso()
        contador = (contador + 1) % 65535
        esclavo.setValues(HOLDING, 0, float_a_registros(peso) + [contador, 1])
        log.info("pesada estable numero %s: %.2f kg", contador, peso)

        await asyncio.sleep(INTERVALO_S)


async def main() -> None:
    bloque = ModbusSequentialDataBlock(0, [0] * 16)
    esclavo = ModbusSlaveContext(hr=bloque, zero_mode=True)
    contexto = ModbusServerContext(slaves={UNIT_ID: esclavo}, single=False)

    # Valor inicial para que una lectura inmediata no devuelva 0 kg.
    esclavo.setValues(HOLDING, 0, float_a_registros(PESO_NOMINAL_KG) + [0, 1])

    asyncio.create_task(actualizar(contexto))
    log.info("simulador de bascula escuchando en 0.0.0.0:%s, unidad %s", PORT, UNIT_ID)
    await StartAsyncTcpServer(context=contexto, address=("0.0.0.0", PORT))


if __name__ == "__main__":
    asyncio.run(main())
