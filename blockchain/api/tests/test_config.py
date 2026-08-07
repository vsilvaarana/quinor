"""Tests de configuración por variables de entorno de create_app."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_create_app_con_variables_de_entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "datos"))
    monkeypatch.setenv("API_KEY", "clave-env")
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/nodos", headers={"X-API-Key": "clave-env"})
        assert resp.status_code == 200
        assert resp.json()["nodo1"]["altura"] == 1
    app.state.network.close()


def test_create_app_api_key_por_defecto(tmp_path, monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "datos"))
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/nodos", headers={"X-API-Key": "quinor-secret-key"})
        assert resp.status_code == 200
    app.state.network.close()
