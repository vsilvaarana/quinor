"""Tests de cada método del API, incluyendo autenticación y errores."""

import json

import pytest

from app.blockchain import _block_key
from tests.conftest import DESPACHO


def _adulterar_bloque(node, index):
    """Modifica los datos de un bloque directamente en LevelDB."""
    raw = json.loads(node.db.get(_block_key(index)))
    raw["data"]["cantidad"] = 999999
    node.db.put(_block_key(index), json.dumps(raw).encode())


# ---------- GET / (info, sin autenticación) ----------

def test_info_publica(client):
    resp = client.get("/", headers={"X-API-Key": ""})
    assert resp.status_code == 200
    body = resp.json()
    assert body["nodos"] == ["nodo1", "nodo2"]
    assert "X-API-Key" in body["autenticacion"]


# ---------- Autenticación ----------

@pytest.mark.parametrize(
    "metodo,ruta",
    [
        ("post", "/despachos"),
        ("get", "/despachos"),
        ("get", "/despachos/abc"),
        ("get", "/nodos"),
        ("get", "/nodos/nodo1/cadena"),
        ("get", "/nodos/nodo1/validar"),
        ("get", "/consenso"),
    ],
)
def test_sin_api_key_devuelve_401(client, metodo, ruta):
    client.headers.pop("X-API-Key")
    kwargs = {"json": DESPACHO} if metodo == "post" else {}
    resp = getattr(client, metodo)(ruta, **kwargs)
    assert resp.status_code == 401


def test_api_key_incorrecta_devuelve_401(client):
    resp = client.get("/despachos", headers={"X-API-Key": "clave-mala"})
    assert resp.status_code == 401
    assert "API key" in resp.json()["detail"]


# ---------- POST /despachos ----------

def test_crear_despacho(client):
    resp = client.post("/despachos", json=DESPACHO)
    assert resp.status_code == 201
    body = resp.json()
    assert body["bloque"] == 1
    assert len(body["hash"]) == 64
    assert body["despacho"]["producto"] == "Quinua blanca"
    assert body["despacho"]["id_despacho"] == body["id_despacho"]
    assert "fecha_registro" in body["despacho"]


def test_crear_despacho_replica_en_ambos_nodos(client, app):
    resp = client.post("/despachos", json=DESPACHO)
    hash_bloque = resp.json()["hash"]
    for node in app.state.network.nodes.values():
        assert node.height == 2
        assert node.last_block.hash == hash_bloque


@pytest.mark.parametrize(
    "cambios",
    [
        {"cantidad": -10},
        {"cantidad": 0},
        {"producto": ""},
        {"origen": None},
    ],
)
def test_crear_despacho_datos_invalidos(client, cambios):
    payload = {**DESPACHO, **cambios}
    resp = client.post("/despachos", json=payload)
    assert resp.status_code == 422


def test_crear_despacho_faltan_campos(client):
    resp = client.post("/despachos", json={"producto": "Quinua"})
    assert resp.status_code == 422


def test_crear_despacho_campos_opcionales(client):
    payload = {
        "producto": "Quinua roja",
        "cantidad": 100,
        "origen": "Puno",
        "destino": "Lima",
        "transportista": "TransAndes",
    }
    resp = client.post("/despachos", json=payload)
    assert resp.status_code == 201
    assert resp.json()["despacho"]["unidad"] == "kg"
    assert resp.json()["despacho"]["conductor"] is None


# ---------- GET /despachos ----------

def test_listar_despachos_vacio(client):
    resp = client.get("/despachos")
    assert resp.status_code == 200
    assert resp.json() == {"total": 0, "despachos": []}


def test_listar_despachos(client):
    client.post("/despachos", json=DESPACHO)
    client.post("/despachos", json={**DESPACHO, "producto": "Quinua negra"})
    resp = client.get("/despachos")
    body = resp.json()
    assert body["total"] == 2
    productos = [d["producto"] for d in body["despachos"]]
    assert productos == ["Quinua blanca", "Quinua negra"]


# ---------- GET /despachos/{id} ----------

def test_obtener_despacho(client):
    creado = client.post("/despachos", json=DESPACHO).json()
    resp = client.get(f"/despachos/{creado['id_despacho']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["bloque"] == 1
    assert body["despacho"]["id_despacho"] == creado["id_despacho"]


def test_obtener_despacho_no_existe(client):
    resp = client.get("/despachos/no-existe")
    assert resp.status_code == 404
    assert "no encontrado" in resp.json()["detail"]


# ---------- GET /nodos ----------

def test_listar_nodos(client):
    client.post("/despachos", json=DESPACHO)
    resp = client.get("/nodos")
    body = resp.json()
    assert set(body.keys()) == {"nodo1", "nodo2"}
    assert body["nodo1"]["altura"] == 2
    assert body["nodo1"]["ultimo_hash"] == body["nodo2"]["ultimo_hash"]


# ---------- GET /nodos/{id}/cadena ----------

def test_obtener_cadena(client):
    client.post("/despachos", json=DESPACHO)
    resp = client.get("/nodos/nodo2/cadena")
    body = resp.json()
    assert body["nodo"] == "nodo2"
    assert body["altura"] == 2
    assert body["cadena"][0]["data"] == {"genesis": True}
    assert body["cadena"][1]["previous_hash"] == body["cadena"][0]["hash"]


def test_obtener_cadena_nodo_no_existe(client):
    resp = client.get("/nodos/nodo9/cadena")
    assert resp.status_code == 404
    assert "no existe" in resp.json()["detail"]


# ---------- GET /nodos/{id}/validar ----------

def test_validar_cadena_integra(client):
    client.post("/despachos", json=DESPACHO)
    resp = client.get("/nodos/nodo1/validar")
    assert resp.json() == {"nodo": "nodo1", "valida": True}


def test_validar_cadena_adulterada(client, app):
    client.post("/despachos", json=DESPACHO)
    _adulterar_bloque(app.state.network.get_node("nodo2"), 1)
    resp = client.get("/nodos/nodo2/validar")
    assert resp.json() == {"nodo": "nodo2", "valida": False}


def test_validar_nodo_no_existe(client):
    resp = client.get("/nodos/nodo9/validar")
    assert resp.status_code == 404


# ---------- GET /consenso ----------

def test_consenso_ok(client):
    client.post("/despachos", json=DESPACHO)
    resp = client.get("/consenso")
    body = resp.json()
    assert body["consenso"] is True
    assert body["nodos"]["nodo1"]["valida"] is True


def test_consenso_roto_por_adulteracion(client, app):
    client.post("/despachos", json=DESPACHO)
    _adulterar_bloque(app.state.network.get_node("nodo2"), 1)
    resp = client.get("/consenso")
    body = resp.json()
    assert body["consenso"] is False
    assert body["nodos"]["nodo2"]["valida"] is False


def test_consenso_roto_por_altura_distinta(client, app):
    client.post("/despachos", json=DESPACHO)
    app.state.network.get_node("nodo2").add_block({"extra": True})
    resp = client.get("/consenso")
    assert resp.json()["consenso"] is False
