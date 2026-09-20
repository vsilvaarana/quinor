"""Cliente REST del ERP/WMS. Nucleo de HU-02.

Criterio 1 de HU-02: dado un numero de orden, el sistema consulta el ERP por API
REST y obtiene peso esperado y numero de sacos.

El modulo distingue tres desenlaces, y la diferencia importa:

  OrdenNoExisteEnERP  El ERP contesta y dice que esa orden no existe. Es una
                      respuesta valida: la carga no debe registrarse (RN-02).
  ErpNoDisponible     El ERP no contesta, o contesta algo que no se entiende.
                      No sabemos si la orden existe, asi que es una incidencia
                      de integracion y no un rechazo de la orden.
  OrdenERP            Los datos de la orden.

Confundir los dos fallos llevaria a parar el despacho por un problema de red, o
a dar por buena una orden que el ERP nunca reconocio.

Como bascula.py, este modulo no lee configuracion: todo llega por parametro.
"""
from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

import httpx
import structlog
from pydantic import BaseModel, Field, ValidationError

log = structlog.get_logger("quinor.erp")

DOS_DECIMALES = Decimal("0.01")


class ErrorERP(RuntimeError):
    """Raiz de los fallos de integracion con el ERP."""


class OrdenNoExisteEnERP(ErrorERP):
    """El ERP respondio que la orden no existe. RN-02: no se registra la carga."""


class ErpNoDisponible(ErrorERP):
    """No se pudo consultar al ERP. Incidencia de integracion, no rechazo."""


class OrdenERP(BaseModel):
    """Contrato de la orden tal como la publica el ERP.

    La validacion es deliberadamente estricta: un peso en cero o unos sacos
    negativos chocarian despues contra las restricciones CHECK del esquema, y es
    mejor rechazarlos aqui, donde se puede decir de donde vino el dato.
    """

    numero_orden: str = Field(min_length=1, max_length=40)
    cliente: str = Field(min_length=1, max_length=180)
    producto: str = Field(min_length=1, max_length=120)
    peso_esperado_kg: Decimal = Field(gt=0)
    sacos_esperados: int = Field(gt=0)
    fecha: dt.date

    def peso_cuantizado(self) -> Decimal:
        """El ERP publica el peso como numero decimal; la base guarda dos cifras."""
        return Decimal(self.peso_esperado_kg).quantize(DOS_DECIMALES, rounding=ROUND_HALF_UP)


async def consultar_orden(
    base_url: str,
    numero_orden: str,
    timeout_s: float = 5.0,
) -> OrdenERP:
    """Pide una orden al ERP. Lanza OrdenNoExisteEnERP o ErpNoDisponible."""
    url = f"{base_url.rstrip('/')}/ordenes/{numero_orden.upper()}"
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as cliente:
            respuesta = await cliente.get(url)
    except httpx.HTTPError as exc:
        raise ErpNoDisponible(
            f"no se pudo consultar el ERP en {url}: {type(exc).__name__}: {exc}"
        ) from exc

    if respuesta.status_code == 404:
        raise OrdenNoExisteEnERP(f"el ERP no reconoce la orden {numero_orden}")
    if respuesta.status_code >= 400:
        raise ErpNoDisponible(
            f"el ERP respondio {respuesta.status_code} al consultar {numero_orden}"
        )

    try:
        orden = OrdenERP.model_validate(respuesta.json())
    except (ValidationError, ValueError) as exc:
        # El ERP contesto, pero con algo que no es una orden utilizable. No se
        # puede dar por buena, y tampoco es culpa de la orden: es integracion.
        raise ErpNoDisponible(
            f"el ERP devolvio una orden que no se puede interpretar: {exc}"
        ) from exc

    log.info("orden_consultada_al_erp", orden=orden.numero_orden,
             peso=str(orden.peso_cuantizado()), sacos=orden.sacos_esperados)
    return orden
