"""Stub de la API de ordenes de despacho del ERP/WMS (HU-02).

Sustituye al ERP real mientras no exista acceso. Expone el unico endpoint que
el orquestador necesita en el Sprint 1, con el mismo contrato que se espera del
ERP de produccion.

Para probar el criterio 2 de HU-02 (la orden no existe), consultar cualquier
numero que no este en el catalogo: devuelve 404.
Para probar el timeout del cliente httpx, subir ERP_MOCK_DELAY_MS por encima de
ERP_TIMEOUT_SECONDS.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

DELAY_MS = int(os.getenv("ERP_MOCK_DELAY_MS", "0"))

app = FastAPI(
    title="ERP mock - ordenes de despacho QUINOR",
    description="Stub de desarrollo. No representa al ERP de produccion.",
    version="1.0.0",
)


class OrdenDespacho(BaseModel):
    numero_orden: str = Field(examples=["ORD-2026-0001"])
    cliente: str
    producto: str
    peso_esperado_kg: float = Field(description="Peso total esperado de la carga.")
    sacos_esperados: int = Field(description="Cantidad de sacos de 50 kg.")
    fecha: date


# Catalogo fijo. Todas las ordenes cumplen 50 kg por saco.
_CATALOGO: dict[str, OrdenDespacho] = {
    o.numero_orden: o
    for o in [
        OrdenDespacho(
            numero_orden="ORD-2026-0001",
            cliente="Andean Foods GmbH",
            producto="Quinua blanca organica",
            peso_esperado_kg=20000.0,
            sacos_esperados=400,
            fecha=date(2026, 9, 14),
        ),
        OrdenDespacho(
            numero_orden="ORD-2026-0002",
            cliente="Nordic Grain AB",
            producto="Quinua roja organica",
            peso_esperado_kg=13500.0,
            sacos_esperados=270,
            fecha=date(2026, 9, 15),
        ),
        OrdenDespacho(
            numero_orden="ORD-2026-0003",
            cliente="Pacific Organics Inc.",
            producto="Quinua negra convencional",
            peso_esperado_kg=9000.0,
            sacos_esperados=180,
            fecha=date(2026, 9, 16),
        ),
    ]
}


@app.get("/salud", tags=["salud"])
async def salud() -> dict[str, object]:
    return {"estado": "OK", "ordenes_disponibles": len(_CATALOGO)}


@app.get("/ordenes", response_model=list[OrdenDespacho], tags=["ordenes"])
async def listar_ordenes() -> list[OrdenDespacho]:
    return list(_CATALOGO.values())


@app.get("/ordenes/{numero}", response_model=OrdenDespacho, tags=["ordenes"])
async def obtener_orden(numero: str) -> OrdenDespacho:
    if DELAY_MS:
        await asyncio.sleep(DELAY_MS / 1000)
    orden = _CATALOGO.get(numero.upper())
    if orden is None:
        raise HTTPException(status_code=404, detail=f"Orden {numero} no existe en el ERP")
    return orden
