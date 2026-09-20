"""Fixtures del servicio de vision-lenguaje.

Todo se prueba contra el stub por HTTP de verdad. Contra un mock del cliente no
se comprobaria lo que de verdad falla en planta: que la clave viaja en la
cabecera correcta, que un 429 se reintenta y un 401 no, que el JSON llega dentro
de un bloque de codigo. El contenido de la respuesta si es de mentira, porque
aqui no hay ningun modelo mirando imagenes.
"""
from __future__ import annotations

import base64

import pytest

from app.config import Ajustes
from sim.vlm_stub import Estado, arrancar

# Un JPEG minimo de verdad: cabecera, cuerpo y fin de imagen. Lo que importa es
# que sea base64 valido y que se pueda comprobar que llego entero.
JPEG = base64.b64encode(
    bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9")).decode()


@pytest.fixture()
def stub():
    """Proveedor de mentira, por HTTP de verdad."""
    servidor, estado, url = arrancar()
    estado.url = url
    yield estado
    servidor.shutdown()
    servidor.server_close()


def stub_que(fallar: int = 0, veces: int = -1, basura: bool = False,
             clave: str = ""):
    """Un stub con un comportamiento concreto, para provocar fallos."""
    servidor, estado, url = arrancar(
        estado=Estado(fallar=fallar, veces=veces, basura=basura, clave=clave))
    estado.url = url
    estado.servidor = servidor
    return estado


@pytest.fixture()
def ajustes(stub) -> Ajustes:
    """Ajustes apuntando al stub, sin esperas entre reintentos."""
    return Ajustes(proveedor="stub", api_key="", base_url=stub.url,
                   modelo="modelo-de-prueba", espera_inicial_s=0.0,
                   timeout_s=5.0)


def ajustes_de(estado, **cambios) -> Ajustes:
    import dataclasses

    base = Ajustes(proveedor="stub", api_key="", base_url=estado.url,
                   modelo="modelo-de-prueba", espera_inicial_s=0.0,
                   timeout_s=5.0)
    return dataclasses.replace(base, **cambios) if cambios else base


# Un evento con una discrepancia de verdad: dos sacos de menos y un saco que
# salio de la zona de carga. Es el caso que la RN-04 llama Alta.
EVENTO = {
    "evento_id": 42,
    "numero_orden": "ORD-2026-0101",
    "producto": "Quinua blanca organica",
    "peso_esperado_kg": 20000.0,
    "peso_real_kg": 19850.0,
    "diferencia_kg": -150.0,
    "diferencia_pct": -0.75,
    "sacos_esperados": 400,
    "sacos_contados": 397,
    "diferencia_sacos": -3,
    "sacos_salientes": 1,
    "personas_detectadas": 4,
    "maximo_simultaneo": 4,
    "permanencia_maxima_s": 320.5,
    "personal_anomalo": True,
    "motivos_de_anomalia": ["demasiadas_personas_a_la_vez"],
    "duracion_del_clip_s": 420.0,
}

# Una carga que cuadra: el peso no da pero los sacos si. La RN-03 no llama al
# modelo en este caso.
EVENTO_QUE_CUADRA = {
    **EVENTO,
    "sacos_contados": 400,
    "diferencia_sacos": 0,
    "sacos_salientes": 0,
    "personal_anomalo": False,
    "motivos_de_anomalia": [],
}


def fotogramas(cuantos: int = 2) -> list[dict]:
    return [{"jpeg_base64": JPEG, "motivo": "saco_saliente",
             "detalle": "Un saco cruza hacia fuera.", "segundo": 12.0 * (i + 1),
             "fotograma": 120 * (i + 1)} for i in range(cuantos)]


@pytest.fixture()
def cliente(stub):
    """El servicio completo, apuntando al stub."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(proveedor="stub", base_url=stub.url,
                     modelo="modelo-de-prueba", espera_inicial_s=0.0,
                     api_key="")
    with TestClient(app) as test_client:
        yield test_client
