import pytest
from fastapi.testclient import TestClient

from app.main import create_app

API_KEY = "clave-de-prueba"

DESPACHO = {
    "producto": "Quinua blanca",
    "cantidad": 500,
    "unidad": "kg",
    "origen": "Puno, Perú",
    "destino": "Rotterdam, Países Bajos",
    "transportista": "Transportes Andinos SAC",
    "conductor": "Juan Pérez",
    "placa_vehiculo": "ABC-123",
    "observaciones": "Contenedor refrigerado",
}


@pytest.fixture()
def app(tmp_path):
    application = create_app(data_dir=str(tmp_path), api_key=API_KEY)
    yield application
    application.state.network.close()


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        test_client.headers.update({"X-API-Key": API_KEY})
        yield test_client
