"""Tests de cada metodo del API, incluyendo autenticacion y errores. HU-01."""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import text

from tests.conftest import (ADMIN_CLAVE, ADMIN_CORREO, PESO_FIJO, PRODUCTO,
                            SIN_NADIE, TOLERANCIA_KG, TOLERANCIA_PCT, iniciar_sesion)

PESADA = {"numero_orden": "ORD-2026-0001"}


# ---------- GET / (info, sin autenticacion) ----------

def test_info_publica(client):
    resp = client.get("/", headers={"X-API-Key": ""})
    assert resp.status_code == 200
    body = resp.json()
    assert body["servicio"] == "Orquestador de despacho QUINOR"
    assert "X-API-Key" in body["autenticacion"]


# ---------- HU-15: autenticacion por token opaco ----------

@pytest.mark.parametrize(
    "metodo,ruta",
    [
        ("post", "/pesadas"),
        ("get", "/pesadas"),
        ("get", "/ordenes"),
        ("get", "/salud"),
        ("get", "/salud/historial"),
        ("get", "/usuarios"),
        ("get", "/auth/yo"),
        ("get", "/auth/tokens"),
        ("get", "/configuracion"),
        ("get", "/eventos"),
        ("patch", "/configuracion/Quinua%20blanca%20organica"),
    ],
)
def test_sin_token_devuelve_401(client, metodo, ruta):
    client.headers.pop("X-API-Key")
    cuerpos = {"post": PESADA, "patch": {"tolerancia_kg": 10}}
    kwargs = {"json": cuerpos[metodo]} if metodo in cuerpos else {}
    assert getattr(client, metodo)(ruta, **kwargs).status_code == 401


def test_un_token_inventado_devuelve_401(client):
    resp = client.get("/pesadas", headers={"X-API-Key": "no-es-un-token"})
    assert resp.status_code == 401
    assert "Token invalido" in resp.json()["detail"]


def test_login_devuelve_un_token_y_quien_es(client):
    resp = client.post("/auth/login",
                       json={"correo": ADMIN_CORREO, "clave": ADMIN_CLAVE})
    assert resp.status_code == 200
    cuerpo = resp.json()
    assert len(cuerpo["token"]) >= 43
    assert "no se vuelve a mostrar" in cuerpo["aviso"]
    assert cuerpo["usuario"]["rol"] == "administrador"
    assert cuerpo["detalle"]["expira_en"]


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"correo": ADMIN_CORREO, "clave": "clave-equivocada"},
        {"correo": "nadie@quinor.local", "clave": ADMIN_CLAVE},
    ],
)
def test_login_con_credenciales_malas(client, cuerpo):
    resp = client.post("/auth/login", json=cuerpo)
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Correo o contrasena incorrectos"


def test_quien_soy(client):
    cuerpo = client.get("/auth/yo").json()
    assert cuerpo["correo"] == ADMIN_CORREO
    assert cuerpo["rol"] == "administrador"
    assert "hash_password" not in cuerpo      # el hash nunca sale por la API


def test_emitir_y_listar_tokens_propios(client):
    resp = client.post("/auth/tokens", json={"nombre": "Laptop de rampa 1"})
    assert resp.status_code == 201
    assert resp.json()["detalle"]["nombre"] == "Laptop de rampa 1"
    nombres = [t["nombre"] for t in client.get("/auth/tokens").json()]
    assert "Laptop de rampa 1" in nombres


def test_un_token_emitido_sirve_para_entrar(client, app):
    from fastapi.testclient import TestClient

    nuevo = client.post("/auth/tokens", json={"nombre": "otro"}).json()["token"]
    with TestClient(app) as otro:
        otro.headers.update({"X-API-Key": nuevo})
        assert otro.get("/auth/yo").json()["correo"] == ADMIN_CORREO


def test_revocar_un_token_lo_deja_inservible_de_inmediato(client, app):
    from fastapi.testclient import TestClient

    emitido = client.post("/auth/tokens", json={"nombre": "de un dia"}).json()
    token_id, claro = emitido["detalle"]["id"], emitido["token"]

    with TestClient(app) as otro:
        otro.headers.update({"X-API-Key": claro})
        assert otro.get("/auth/yo").status_code == 200
        assert client.delete(f"/auth/tokens/{token_id}").status_code == 200
        assert otro.get("/auth/yo").status_code == 401


def test_revocar_un_token_inexistente(client):
    assert client.delete("/auth/tokens/9999").status_code == 404


def test_nadie_revoca_el_token_de_otro(client, client_supervisor):
    ajeno = client_supervisor.post("/auth/tokens", json={"nombre": "suyo"}).json()
    otro_admin = client.post("/auth/tokens", json={"nombre": "mio"}).json()

    # El supervisor no puede tocar el del administrador...
    assert client_supervisor.delete(
        f"/auth/tokens/{otro_admin['detalle']['id']}").status_code == 403
    # ...pero el administrador si puede revocar el suyo.
    assert client.delete(f"/auth/tokens/{ajeno['detalle']['id']}").status_code == 200


def test_un_token_con_vencimiento_propio(client):
    resp = client.post("/auth/tokens", json={"nombre": "corto", "ttl_horas": 1})
    assert resp.status_code == 201
    detalle = resp.json()["detalle"]
    assert detalle["expira_en"] > detalle["creado_en"]


def test_un_ttl_invalido_se_rechaza(client):
    assert client.post("/auth/tokens", json={"nombre": "x", "ttl_horas": 0}).status_code == 422
    assert client.post("/auth/tokens", json={"nombre": "x", "ttl_horas": -3}).status_code == 422


# ---------- HU-15, criterio 2: el rol Consulta no escribe ----------

def test_consulta_puede_leer(client_consulta, orden, erp_sano):
    assert client_consulta.get("/pesadas").status_code == 200
    assert client_consulta.get("/ordenes").status_code == 200
    assert client_consulta.get("/salud").status_code == 200
    assert client_consulta.get("/auth/yo").json()["rol"] == "consulta"


def test_consulta_no_puede_registrar_pesadas(client_consulta, orden):
    """Criterio 2: el rol Consulta no cambia estados ni configuraciones."""
    resp = client_consulta.post("/pesadas", json=PESADA)
    assert resp.status_code == 403
    assert "rol no permite" in resp.json()["detail"]


@pytest.mark.parametrize(
    "metodo, ruta, cuerpo",
    [
        ("get", "/usuarios", None),
        ("post", "/usuarios", {"nombre": "X", "correo": "x@q.local",
                               "rol": "consulta", "clave": "clave-larga-123"}),
        ("patch", "/usuarios/1/rol", {"rol": "administrador"}),
        ("patch", "/usuarios/1/activacion", {"activo": False}),
        ("patch", "/usuarios/1/clave", {"clave": "clave-larga-456"}),
    ],
)
def test_consulta_no_administra_usuarios(client_consulta, metodo, ruta, cuerpo):
    kwargs = {"json": cuerpo} if cuerpo is not None else {}
    assert getattr(client_consulta, metodo)(ruta, **kwargs).status_code == 403


def test_el_supervisor_si_registra_pesadas(client_supervisor, orden):
    assert client_supervisor.post("/pesadas", json=PESADA).status_code == 201


def test_el_supervisor_no_administra_usuarios(client_supervisor):
    assert client_supervisor.get("/usuarios").status_code == 403


# ---------- HU-15, criterio 1: gestion de usuarios ----------

def test_crear_usuario_y_entrar_con_el(client, app):
    from fastapi.testclient import TestClient

    resp = client.post("/usuarios", json={
        "nombre": "Ana Quispe", "correo": "ana@quinor.local",
        "rol": "supervisor", "clave": "clave-de-ana-123"})
    assert resp.status_code == 201
    assert resp.json()["rol"] == "supervisor"
    assert resp.json()["activo"] is True

    with TestClient(app) as suyo:
        token = iniciar_sesion(suyo, "ana@quinor.local", "clave-de-ana-123")
        suyo.headers.update({"X-API-Key": token})
        assert suyo.get("/auth/yo").json()["correo"] == "ana@quinor.local"


def test_no_se_repite_el_correo(client):
    cuerpo = {"nombre": "Ana", "correo": "ana@quinor.local",
              "rol": "consulta", "clave": "clave-de-ana-123"}
    assert client.post("/usuarios", json=cuerpo).status_code == 201
    assert client.post("/usuarios", json=cuerpo).status_code == 409


@pytest.mark.parametrize(
    "cambios",
    [
        {"rol": "root"},
        {"clave": "corta"},
        {"correo": ""},
        {"nombre": ""},
    ],
)
def test_datos_invalidos_al_crear_usuario(client, cambios):
    cuerpo = {"nombre": "Ana", "correo": "ana@quinor.local",
              "rol": "consulta", "clave": "clave-de-ana-123"}
    assert client.post("/usuarios", json={**cuerpo, **cambios}).status_code == 422


def test_una_clave_de_mas_de_72_bytes_se_rechaza(client):
    resp = client.post("/usuarios", json={
        "nombre": "Ana", "correo": "ana@quinor.local", "rol": "consulta",
        "clave": "x" * 100})
    assert resp.status_code == 422
    assert "72 bytes" in resp.json()["detail"]


def test_el_limite_de_72_bytes_tambien_aplica_al_cambiar_la_clave(client):
    """El mismo limite en los dos caminos: si no, una clave larga entraria por
    la puerta de atras y solo contarian sus 72 primeros bytes."""
    creado = client.post("/usuarios", json={
        "nombre": "Ana", "correo": "ana@quinor.local",
        "rol": "consulta", "clave": "clave-de-ana-123"}).json()
    resp = client.patch(f"/usuarios/{creado['id']}/clave", json={"clave": "y" * 100})
    assert resp.status_code == 422
    assert "72 bytes" in resp.json()["detail"]


def test_asignar_otro_rol(client):
    creado = client.post("/usuarios", json={
        "nombre": "Ana", "correo": "ana@quinor.local",
        "rol": "consulta", "clave": "clave-de-ana-123"}).json()
    resp = client.patch(f"/usuarios/{creado['id']}/rol", json={"rol": "supervisor"})
    assert resp.status_code == 200
    assert resp.json()["rol"] == "supervisor"


def test_desactivar_un_usuario_le_cierra_la_sesion(client, app):
    from fastapi.testclient import TestClient

    creado = client.post("/usuarios", json={
        "nombre": "Ana", "correo": "ana@quinor.local",
        "rol": "supervisor", "clave": "clave-de-ana-123"}).json()
    with TestClient(app) as suyo:
        suyo.headers.update(
            {"X-API-Key": iniciar_sesion(suyo, "ana@quinor.local", "clave-de-ana-123")})
        assert suyo.get("/auth/yo").status_code == 200

        assert client.patch(f"/usuarios/{creado['id']}/activacion",
                            json={"activo": False}).status_code == 200
        assert suyo.get("/auth/yo").status_code == 401


def test_un_administrador_no_se_desactiva_a_si_mismo(client):
    """Dejaria el sistema sin nadie que pueda revertirlo."""
    yo = client.get("/auth/yo").json()
    resp = client.patch(f"/usuarios/{yo['id']}/activacion", json={"activo": False})
    assert resp.status_code == 409
    assert "tu propia cuenta" in resp.json()["detail"]


def test_cambiar_la_clave_de_otro(client, app):
    from fastapi.testclient import TestClient

    creado = client.post("/usuarios", json={
        "nombre": "Ana", "correo": "ana@quinor.local",
        "rol": "consulta", "clave": "clave-de-ana-123"}).json()
    assert client.patch(f"/usuarios/{creado['id']}/clave",
                        json={"clave": "clave-nueva-456"}).status_code == 200
    with TestClient(app) as suyo:
        assert suyo.post("/auth/login", json={"correo": "ana@quinor.local",
                                              "clave": "clave-de-ana-123"}).status_code == 401
        assert suyo.post("/auth/login", json={"correo": "ana@quinor.local",
                                              "clave": "clave-nueva-456"}).status_code == 200


def test_operaciones_sobre_un_usuario_inexistente(client):
    assert client.patch("/usuarios/9999/rol", json={"rol": "consulta"}).status_code == 404
    assert client.patch("/usuarios/9999/activacion", json={"activo": True}).status_code == 404
    assert client.patch("/usuarios/9999/clave", json={"clave": "clave-larga-123"}).status_code == 404


def test_listar_usuarios_puede_excluir_inactivos(client):
    creado = client.post("/usuarios", json={
        "nombre": "Ana", "correo": "ana@quinor.local",
        "rol": "consulta", "clave": "clave-de-ana-123"}).json()
    client.patch(f"/usuarios/{creado['id']}/activacion", json={"activo": False})
    assert len(client.get("/usuarios").json()) == 2
    assert len(client.get("/usuarios",
                          params={"incluir_inactivos": False}).json()) == 1


# ---------- POST /pesadas (criterios 1 y 3) ----------

def test_crear_pesada(client, orden):
    resp = client.post("/pesadas", json=PESADA)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["numero_orden"] == "ORD-2026-0001"
    assert body["cliente"] == "Andean Foods GmbH"
    assert body["bascula_id"] == "BASCULA-01"
    assert body["origen"] == "bascula"
    assert Decimal(body["peso_real_kg"]) == PESO_FIJO
    assert Decimal(body["peso_esperado_kg"]) == Decimal("20000.00")
    assert body["fecha_hora"]


def test_crear_pesada_persiste_con_dos_decimales(client, orden, sesion):
    """Criterio 3: lo que llega a MySQL es DECIMAL(10,2), no coma flotante."""
    creada = client.post("/pesadas", json=PESADA).json()
    guardado = sesion.execute(
        text("SELECT peso_real_kg, fecha_hora, bascula_id, orden_id FROM pesada WHERE id = :i"),
        {"i": creada["id"]},
    ).mappings().one()
    assert isinstance(guardado["peso_real_kg"], Decimal)
    assert guardado["peso_real_kg"].as_tuple().exponent == -2
    assert guardado["fecha_hora"].microsecond != 0      # milisegundos para el video
    assert guardado["bascula_id"] == "BASCULA-01"
    assert guardado["orden_id"] == orden.id             # ID de carga


def test_crear_pesada_con_bascula_indicada(client, orden):
    resp = client.post("/pesadas", json={**PESADA, "bascula_id": "BASCULA-02"})
    assert resp.json()["bascula_id"] == "BASCULA-02"


def test_crear_pesada_orden_desconocida(client, erp_sin_orden):
    """Criterio 2 de HU-02: el ERP no la reconoce, se avisa y no se registra."""
    resp = client.post("/pesadas", json={"numero_orden": "ORD-NO-EXISTE"})
    assert resp.status_code == 404
    assert "no reconoce" in resp.json()["detail"]


@pytest.mark.parametrize(
    "cambios",
    [
        {"peso_real_kg": -5},
        {"numero_orden": ""},
        {"numero_orden": "X" * 41},
        {"bascula_id": "X" * 21},
    ],
)
def test_crear_pesada_datos_invalidos(client, orden, cambios):
    resp = client.post("/pesadas", json={**PESADA, **cambios})
    assert resp.status_code == 422


def test_crear_pesada_faltan_campos(client):
    resp = client.post("/pesadas", json={})
    assert resp.status_code == 422


def test_crear_pesada_manual_queda_marcada(client, orden, sesion):
    resp = client.post("/pesadas", json={
        **PESADA,
        "peso_real_kg": "19912.456",
        "motivo_manual": "bascula en mantenimiento programado",
    })
    assert resp.status_code == 201
    assert resp.json()["origen"] == "manual"
    assert Decimal(resp.json()["peso_real_kg"]) == Decimal("19912.46")
    detalle = sesion.execute(
        text("SELECT detalle FROM auditoria WHERE entidad = 'pesada'")
    ).scalar_one()
    assert "mantenimiento" in str(detalle)


def test_crear_pesada_bascula_caida(crear_cliente, orden, sesion):
    """Criterio 2: 503 y el fallo queda en salud_componente."""
    cliente = crear_cliente(scale_port=SIN_NADIE)
    resp = cliente.post("/pesadas", json=PESADA)

    assert resp.status_code == 503
    assert "no respondio" in resp.json()["detail"]
    assert sesion.execute(text("SELECT COUNT(*) FROM pesada")).scalar_one() == 0
    estado = sesion.execute(
        text("SELECT estado FROM salud_componente WHERE componente = 'bascula'")
    ).scalar_one()
    assert estado == "error"


def test_crear_pesada_con_peso_en_movimiento(crear_cliente, bascula_inestable, orden, sesion):
    """Mientras la bascula oscila el numero no es un dato: 409 y no se guarda."""
    cliente = crear_cliente(scale_port=bascula_inestable)
    resp = cliente.post("/pesadas", json=PESADA)

    assert resp.status_code == 409
    assert "movimiento" in resp.json()["detail"]
    assert sesion.execute(text("SELECT COUNT(*) FROM pesada")).scalar_one() == 0


# ---------- GET /pesadas ----------

def test_listar_pesadas_vacio(client, orden):
    resp = client.get("/pesadas")
    assert resp.status_code == 200
    assert resp.json() == []


def test_listar_pesadas(client, orden):
    client.post("/pesadas", json=PESADA)
    client.post("/pesadas", json={**PESADA, "peso_real_kg": "100.00"})
    resp = client.get("/pesadas")
    assert len(resp.json()) == 2
    assert {p["origen"] for p in resp.json()} == {"bascula", "manual"}


def test_listar_pesadas_filtra_por_orden(client, orden):
    client.post("/pesadas", json=PESADA)
    assert len(client.get("/pesadas", params={"numero_orden": "ORD-2026-0001"}).json()) == 1
    assert client.get("/pesadas", params={"numero_orden": "ORD-OTRA"}).json() == []


def test_listar_pesadas_limite_invalido(client):
    assert client.get("/pesadas", params={"limite": 0}).status_code == 422
    assert client.get("/pesadas", params={"limite": 501}).status_code == 422


# ---------- HU-02: GET /ordenes/{numero} ----------

def test_obtener_orden_la_trae_del_erp(client, erp_sano):
    resp = client.get("/ordenes/ORD-2026-0001")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["numero_orden"] == "ORD-2026-0001"
    assert Decimal(body["peso_esperado_kg"]) == Decimal("20000.00")
    assert body["sacos_esperados"] == 400
    assert body["cliente"] == "Andean Foods GmbH"
    assert body["sincronizado_en"]


def test_obtener_orden_inexistente_devuelve_404(client, erp_sin_orden):
    resp = client.get("/ordenes/ORD-FANTASMA")
    assert resp.status_code == 404
    assert "no reconoce" in resp.json()["detail"]


def test_obtener_orden_sin_erp_ni_copia_local_devuelve_404(client, erp_caido):
    resp = client.get("/ordenes/ORD-2026-0001")
    assert resp.status_code == 404
    assert "No hay copia local" in resp.json()["detail"]


def test_refrescar_vuelve_a_consultar_al_erp(client, orden, erp_sano):
    """La copia local existe y esta vigente, pero el supervisor fuerza el refresco."""
    client.get("/ordenes/ORD-2026-0001")
    llamadas = erp_sano.calls.call_count
    resp = client.get("/ordenes/ORD-2026-0001", params={"refrescar": True})
    assert resp.status_code == 200
    assert erp_sano.calls.call_count > llamadas


def test_listar_ordenes(client, erp_sano):
    assert client.get("/ordenes").json() == []
    client.get("/ordenes/ORD-2026-0001")
    assert len(client.get("/ordenes").json()) == 1


def test_los_endpoints_de_ordenes_exigen_la_clave(client):
    client.headers.pop("X-API-Key")
    assert client.get("/ordenes").status_code == 401
    assert client.get("/ordenes/ORD-2026-0001").status_code == 401


def test_una_pesada_sin_copia_local_resuelve_la_orden_por_el_erp(client, erp_sano, sesion):
    """Criterios 1 y 3 juntos: sin sembrar nada, la orden llega del ERP."""
    from sqlalchemy import text

    resp = client.post("/pesadas", json=PESADA)
    assert resp.status_code == 201, resp.text
    assert Decimal(resp.json()["peso_esperado_kg"]) == Decimal("20000.00")
    # La respuesta del ERP quedo junto a la pesada.
    detalle = sesion.execute(
        text("SELECT detalle FROM auditoria WHERE accion = 'registrar_pesada'")
    ).scalar_one()
    assert "20000.00" in str(detalle)
    assert "orden_sincronizada_en" in str(detalle)
    assert "400" in str(detalle)


# ---------- HU-06: marca de inicio de carga ----------

def test_marcar_el_inicio_de_una_carga(client, orden, erp_sano):
    resp = client.post("/cargas/ORD-2026-0001/inicio")
    assert resp.status_code == 201
    cuerpo = resp.json()
    assert cuerpo["numero_orden"] == "ORD-2026-0001"
    assert cuerpo["inicio"]
    assert cuerpo["consumida_en"] is None


def test_la_pesada_consume_la_marca_y_se_queda_con_el_inicio(client, orden, erp_sano):
    """Es lo que da origen a la ventana del clip de HU-06."""
    marcado = client.post("/cargas/ORD-2026-0001/inicio").json()
    pesada = client.post("/pesadas", json=PESADA).json()

    evento = pesada["evento"]
    assert evento["inicio_carga"] is not None
    assert evento["inicio_carga"][:19] == marcado["inicio"][:19]

    cerrada = client.get("/cargas").json()[0]
    assert cerrada["consumida_en"] is not None
    assert cerrada["pesada_id"] == pesada["id"]
    assert cerrada["duracion_s"] >= 0


def test_sin_marca_la_pesada_se_registra_igual(client, orden, erp_sano):
    """El peso del camion no puede perderse porque nadie anoto el inicio."""
    pesada = client.post("/pesadas", json=PESADA)
    assert pesada.status_code == 201
    assert pesada.json()["evento"]["inicio_carga"] is None


def test_no_se_puede_marcar_dos_veces_la_misma_orden(client, orden, erp_sano):
    assert client.post("/cargas/ORD-2026-0001/inicio").status_code == 201
    resp = client.post("/cargas/ORD-2026-0001/inicio")
    assert resp.status_code == 409
    assert "ya tiene una carga abierta" in resp.json()["detail"]


def test_marcar_una_orden_que_el_ERP_no_reconoce(client, erp_sin_orden):
    assert client.post("/cargas/ORD-9999/inicio").status_code == 404


def test_consulta_no_marca_cargas(client_consulta, orden, erp_sano):
    assert client_consulta.post("/cargas/ORD-2026-0001/inicio").status_code == 403


def test_el_supervisor_si_marca_cargas(client_supervisor, orden, erp_sano):
    assert client_supervisor.post("/cargas/ORD-2026-0001/inicio").status_code == 201


def test_listar_solo_las_cargas_abiertas(client, orden, erp_sano):
    client.post("/cargas/ORD-2026-0001/inicio")
    assert len(client.get("/cargas", params={"solo_abiertas": True}).json()) == 1
    client.post("/pesadas", json=PESADA)
    assert client.get("/cargas", params={"solo_abiertas": True}).json() == []


def test_se_puede_elegir_la_bascula_al_marcar(client, orden, erp_sano):
    resp = client.post("/cargas/ORD-2026-0001/inicio", json={"bascula_id": "BASCULA-02"})
    assert resp.json()["bascula_id"] == "BASCULA-02"


def test_el_evento_todavia_no_tiene_clip(client, orden, erp_sano):
    """El recorte lo hace el grabador, que tiene el buffer. Aqui el evento nace
    con clip_url vacio y el grabador lo rellena."""
    evento = client.post("/pesadas", json=PESADA).json()["evento"]
    assert evento["clip_url"] is None
    assert evento["clip_desde"] is None


# ---------- HU-07: el conteo de sacos en el evento ----------

def test_el_evento_nace_sin_conteo(client, orden, erp_sano):
    """El conteo lo escribe el grabador cuando el servicio YOLO analiza el clip.
    Hasta entonces es None, que no es lo mismo que cero sacos."""
    evento = client.post("/pesadas", json=PESADA).json()["evento"]
    assert evento["sacos_contados"] is None
    assert evento["diferencia_sacos"] is None
    # Los de la orden si se saben desde el principio: son contra lo que se
    # comparara, y ver solo el conteo sin el esperado no dice nada.
    assert evento["sacos_esperados"] == 400


def test_el_conteo_del_grabador_se_ve_en_el_evento(client, sesion, orden, erp_sano):
    """Criterio 3 de HU-07 visto desde el otro lado: el grabador escribe en la
    tabla y el supervisor lo tiene que ver sin abrir la base de datos."""
    from app.models import Evento

    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    evento = sesion.get(Evento, creado["id"])
    evento.sacos_contados = 394
    evento.diferencia_sacos = -6
    evento.personas_detectadas = 3
    sesion.commit()

    detalle = client.get(f"/eventos/{creado['id']}").json()

    assert detalle["sacos_contados"] == 394
    assert detalle["sacos_esperados"] == 400
    # Negativa es faltante, el mismo criterio de signo que la diferencia de peso.
    assert detalle["diferencia_sacos"] == -6
    assert detalle["personas_detectadas"] == 3


def test_un_conteo_de_cero_no_se_confunde_con_sin_conteo(client, sesion, orden,
                                                         erp_sano):
    """Cero sacos en el video es un dato grave; sin analizar es la ausencia de
    dato. En JSON los dos serian falsy, asi que se comprueba el tipo."""
    from app.models import Evento

    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    evento = sesion.get(Evento, creado["id"])
    evento.sacos_contados = 0
    evento.diferencia_sacos = -400
    sesion.commit()

    detalle = client.get(f"/eventos/{creado['id']}").json()

    assert detalle["sacos_contados"] == 0
    assert detalle["sacos_contados"] is not None
    assert detalle["diferencia_sacos"] == -400


# ---------- HU-08: las personas de la zona de carga ----------

def sembrar_personas(sesion, evento_id, filas):
    """Escribe lo que el grabador habria escrito tras analizar el clip."""
    from app.models import Evento, PersonaEnEvento

    for id_temporal, segundos, primero, ultimo in filas:
        sesion.add(PersonaEnEvento(
            evento_id=evento_id, id_temporal=id_temporal,
            segundos_en_zona=Decimal(str(segundos)),
            primer_fotograma=primero, ultimo_fotograma=ultimo,
            creado_en=dt.datetime.now()))
    evento = sesion.get(Evento, evento_id)
    evento.personas_detectadas = len(filas)
    sesion.commit()


def test_un_evento_recien_creado_no_tiene_personas(client, orden, erp_sano):
    """El clip todavia no se analizo. Cero personas no es lo mismo que no
    haberlo mirado, y por eso personal_anomalo viaja en None."""
    creado = client.post("/pesadas", json=PESADA).json()["evento"]

    cuerpo = client.get(f"/eventos/{creado['id']}/personas").json()

    assert cuerpo["cuantas"] == 0
    assert cuerpo["personas"] == []
    assert cuerpo["personal_anomalo"] is None


def test_se_consulta_quien_estuvo_en_zona_y_cuanto(client, sesion, orden, erp_sano):
    """Criterio 2 de HU-08 visto desde el dashboard."""
    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    sembrar_personas(sesion, creado["id"],
                     [(1, 320.5, 10, 3200), (2, 150.0, 400, 1900)])

    cuerpo = client.get(f"/eventos/{creado['id']}/personas").json()

    assert cuerpo["cuantas"] == 2
    assert Decimal(cuerpo["segundos_totales"]) == Decimal("470.50")
    assert Decimal(cuerpo["permanencia_maxima_s"]) == Decimal("320.50")
    assert cuerpo["personas"][0]["id_temporal"] == 1


def test_de_cada_persona_solo_se_devuelven_un_numero_y_unos_segundos(
        client, sesion, orden, erp_sano):
    """RN-08: si alguien anadiera una foto o un descriptor al contrato, esta
    prueba lo diria antes de que llegara a una pantalla."""
    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    sembrar_personas(sesion, creado["id"], [(1, 60.0, 0, 600)])

    persona = client.get(f"/eventos/{creado['id']}/personas").json()["personas"][0]

    assert set(persona) == {"id_temporal", "segundos_en_zona",
                            "primer_fotograma", "ultimo_fotograma"}


def test_la_respuesta_avisa_de_que_los_identificadores_son_temporales(
        client, sesion, orden, erp_sano):
    """Quien lea "persona 1" tiene que saber que ese 1 no es nadie en concreto y
    no vale fuera de este clip. El aviso viaja con el dato, no en un manual."""
    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    sembrar_personas(sesion, creado["id"], [(1, 60.0, 0, 600)])

    nota = client.get(f"/eventos/{creado['id']}/personas").json()["nota"]

    assert "temporales" in nota
    assert "biometricos" in nota


def test_las_personas_salen_en_el_orden_en_que_aparecieron(client, sesion, orden,
                                                           erp_sano):
    """Para que el detalle se lea como se vio el clip."""
    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    sembrar_personas(sesion, creado["id"],
                     [(9, 30.0, 2000, 2400), (3, 40.0, 100, 900)])

    ids = [p["id_temporal"]
           for p in client.get(f"/eventos/{creado['id']}/personas").json()["personas"]]

    assert ids == [3, 9]


def test_las_personas_de_un_evento_inexistente_dan_404(client):
    assert client.get("/eventos/9999/personas").status_code == 404


def test_la_senal_de_personal_anomalo_se_ve_en_el_evento(client, sesion, orden,
                                                         erp_sano):
    """Es lo que HU-09 consultara para decidir si invoca al modelo de
    vision-lenguaje (RN-03), y lo que HU-11 podra filtrar."""
    from app.models import Evento

    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    assert creado["personal_anomalo"] is None

    evento = sesion.get(Evento, creado["id"])
    evento.personal_anomalo = True
    evento.personas_detectadas = 6
    sesion.commit()

    detalle = client.get(f"/eventos/{creado['id']}").json()

    assert detalle["personal_anomalo"] is True
    assert detalle["personas_detectadas"] == 6


def test_una_carga_normal_deja_la_senal_en_falso_y_no_en_nulo(client, sesion,
                                                              orden, erp_sano):
    """Nulo significa que no se analizo. HU-09 no puede confundir "no se miro"
    con "se miro y estaba bien"."""
    from app.models import Evento

    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    evento = sesion.get(Evento, creado["id"])
    evento.personal_anomalo = False
    sesion.commit()

    assert client.get(f"/eventos/{creado['id']}").json()["personal_anomalo"] is False


def test_las_personas_no_viajan_en_la_lista_de_eventos(client, sesion, orden,
                                                       erp_sano):
    """Una carga larga puede tener decenas de presencias, y la lista de HU-11
    tiene 2 s para responder: arrastrarlas en cada fila la haria pesada para
    quien solo quiere ver las diferencias de peso."""
    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    sembrar_personas(sesion, creado["id"], [(1, 60.0, 0, 600)])

    fila = client.get("/eventos").json()[0]

    assert "personas" not in fila
    assert fila["personas_detectadas"] == 1


# ---------- HU-09: descripcion y severidad ----------

def sembrar_analisis(sesion, evento_id, severidad="alta", severidad_ia="alta",
                     fotogramas=None):
    """Escribe lo que el grabador habria escrito tras interpretar el clip."""
    from app.models import Evento

    evento = sesion.get(Evento, evento_id)
    evento.severidad = severidad
    evento.descripcion_ia = {
        "descripcion": "Un operario retira un saco de la zona de carga.",
        "severidad_ia": severidad_ia,
        "evidencia": ["Se observa un saco saliendo hacia fuera del camion."],
        "confianza": 0.8, "modelo": "un-modelo", "proveedor": "anthropic",
        "intentos": 1, "segundos": 3.2,
    }
    evento.fotogramas_clave = fotogramas if fotogramas is not None else [
        {"url": "s3://clips/evento-1/fotogramas/f000120_saco_saliente.jpg",
         "motivo": "saco_saliente", "detalle": "Un saco cruza hacia fuera.",
         "segundo": 12.0, "fotograma": 120}]
    sesion.commit()


def test_un_evento_recien_creado_no_tiene_analisis(client, orden, erp_sano):
    """La severidad la escribe el grabador cuando el modelo responde. Hasta
    entonces la columna esta vacia, que es lo que HU-11 esperaba encontrar."""
    evento = client.post("/pesadas", json=PESADA).json()["evento"]

    assert evento["severidad"] is None
    assert evento["descripcion_ia"] is None
    assert evento["fotogramas_clave"] == []


def test_la_descripcion_y_la_severidad_se_ven_en_el_evento(client, sesion, orden,
                                                           erp_sano):
    """Criterio 2 visto desde el dashboard."""
    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    sembrar_analisis(sesion, creado["id"])

    detalle = client.get(f"/eventos/{creado['id']}").json()

    assert detalle["severidad"] == "alta"
    assert detalle["descripcion_ia"]["descripcion"]
    assert detalle["descripcion_ia"]["evidencia"]


def test_se_distinguen_la_severidad_de_la_regla_y_la_del_modelo(client, sesion,
                                                                orden, erp_sano):
    """De comparar las dos sale la concordancia semanal del apartado 9.2. Si la
    API devolviera solo una, esa medicion no se podria hacer desde fuera."""
    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    sembrar_analisis(sesion, creado["id"], severidad="alta", severidad_ia="media")

    detalle = client.get(f"/eventos/{creado['id']}").json()

    assert detalle["severidad"] == "alta"
    assert detalle["descripcion_ia"]["severidad_ia"] == "media"


def test_se_sabe_con_que_modelo_se_describio(client, sesion, orden, erp_sano):
    """Cuando un caso se discuta dentro de seis meses."""
    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    sembrar_analisis(sesion, creado["id"])

    analisis = client.get(f"/eventos/{creado['id']}").json()["descripcion_ia"]

    assert analisis["modelo"] == "un-modelo"
    assert analisis["proveedor"] == "anthropic"


def test_los_fotogramas_clave_llegan_con_su_motivo(client, sesion, orden, erp_sano):
    """HU-12 pedira mostrar el fotograma de la anomalia y saltar a ese punto del
    clip: por eso viajan el motivo y el segundo, no solo la imagen."""
    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    sembrar_analisis(sesion, creado["id"])

    fotogramas = client.get(f"/eventos/{creado['id']}").json()["fotogramas_clave"]

    assert len(fotogramas) == 1
    assert fotogramas[0]["motivo"] == "saco_saliente"
    assert fotogramas[0]["segundo"] == 12.0
    assert fotogramas[0]["url"].startswith("s3://")


def test_un_evento_sin_fotogramas_devuelve_una_lista_vacia(client, sesion, orden,
                                                           erp_sano):
    """Y no null: quien pinte la pantalla no deberia tener que distinguir."""
    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    sembrar_analisis(sesion, creado["id"], fotogramas=[])

    assert client.get(f"/eventos/{creado['id']}").json()["fotogramas_clave"] == []


def test_un_evento_en_pendiente_de_analisis_se_ve_como_tal(client, sesion, orden,
                                                           erp_sano):
    """Criterio 3 y apartado 5.3: el analisis fallo tras los reintentos, y eso no
    es lo mismo que no haberlo intentado."""
    from app.models import Evento

    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    evento = sesion.get(Evento, creado["id"])
    evento.estado = "pendiente_analisis"
    evento.severidad = "alta"          # la RN-04 no depende del modelo
    sesion.commit()

    detalle = client.get(f"/eventos/{creado['id']}").json()

    assert detalle["estado"] == "pendiente_analisis"
    assert detalle["severidad"] == "alta"
    assert detalle["descripcion_ia"] is None


def test_la_severidad_se_puede_filtrar_por_estado_de_analisis(client, sesion,
                                                              orden, erp_sano):
    """El estado del apartado 5.3 es el que permite encontrar los eventos que se
    quedaron sin describir."""
    from app.models import Evento

    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    evento = sesion.get(Evento, creado["id"])
    evento.estado = "pendiente_analisis"
    sesion.commit()

    filtrados = client.get("/eventos", params={"estado": "pendiente_analisis"}).json()

    assert [e["id"] for e in filtrados] == [creado["id"]]


# ---------- HU-03: evento de discrepancia ----------

def test_la_pesada_fuera_de_tolerancia_devuelve_su_evento(client, orden, erp_sano):
    """El aviso viaja en la misma respuesta: esperar a que alguien mire el
    dashboard seria repetir el problema que la historia intenta resolver."""
    resp = client.post("/pesadas", json=PESADA)
    assert resp.status_code == 201
    evento = resp.json()["evento"]
    assert evento is not None
    assert evento["estado"] == "pendiente"                       # criterio 1
    # Criterio 2: orden, los dos pesos y la diferencia en kg y en porcentaje.
    assert evento["numero_orden"] == "ORD-2026-0001"
    assert evento["cliente"]
    assert Decimal(evento["peso_esperado_kg"]) == Decimal("20000.00")
    assert Decimal(evento["peso_real_kg"]) == PESO_FIJO
    assert Decimal(evento["diferencia_kg"]) == PESO_FIJO - Decimal("20000.00")
    assert Decimal(evento["diferencia_pct"]) == Decimal("-0.75")
    assert Decimal(evento["tolerancia_aplicada_kg"]) == TOLERANCIA_KG


def test_una_pesada_dentro_de_tolerancia_no_trae_evento(client, orden, erp_sano):
    """El peso manual permite fijar la cifra sin depender de la bascula."""
    resp = client.post("/pesadas", json={
        "numero_orden": "ORD-2026-0001", "peso_real_kg": "19970.00",
        "motivo_manual": "prueba dentro de tolerancia"})
    assert resp.status_code == 201
    assert resp.json()["evento"] is None
    assert client.get("/eventos").json() == []


def test_el_evento_se_crea_en_menos_de_10_segundos(client, orden, erp_sano):
    """Criterio 3. Se mide el tiempo de la peticion y, ademas, la distancia entre
    la marca de la pesada y la del evento, que es lo que vera un auditor."""
    import time

    inicio = time.monotonic()
    resp = client.post("/pesadas", json=PESADA)
    transcurrido = time.monotonic() - inicio
    assert transcurrido < 10

    evento = resp.json()["evento"]
    pesada_en = dt.datetime.fromisoformat(evento["pesada_fecha_hora"])
    evento_en = dt.datetime.fromisoformat(evento["creado_en"])
    assert (evento_en - pesada_en).total_seconds() < 10


def test_el_evento_aparece_en_el_listado(client, orden, erp_sano):
    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    listado = client.get("/eventos").json()
    assert [e["id"] for e in listado] == [creado["id"]]


def test_filtrar_los_eventos(client, orden, erp_sano):
    client.post("/pesadas", json=PESADA)
    assert len(client.get("/eventos", params={"estado": "pendiente"}).json()) == 1
    assert client.get("/eventos", params={"estado": "confirmado"}).json() == []
    assert len(client.get("/eventos",
                          params={"numero_orden": "ORD-2026-0001"}).json()) == 1
    assert client.get("/eventos", params={"numero_orden": "ORD-2026-9999"}).json() == []


def test_detalle_de_un_evento(client, orden, erp_sano):
    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    detalle = client.get(f"/eventos/{creado['id']}").json()
    assert detalle["id"] == creado["id"]
    assert detalle["bascula_id"] == "BASCULA-01"
    # Las columnas de los sprints siguientes llegan vacias.
    assert detalle["severidad"] is None
    assert detalle["sacos_contados"] is None
    assert detalle["clip_url"] is None


def test_un_evento_inexistente_devuelve_404(client):
    assert client.get("/eventos/9999").status_code == 404


def test_subir_la_tolerancia_evita_el_evento(client, orden, erp_sano):
    """La sensibilidad se ajusta desde HU-04 y se nota en la siguiente pesada.

    Hay que subir los dos campos: por la RN-01 manda el mas restrictivo, y
    dejar el porcentaje en 0,5 % seguiria topando en 100 kg.
    """
    client.patch(f"/configuracion/{PRODUCTO}",
                 json={"tolerancia_kg": 500, "tolerancia_pct": 5})
    assert client.post("/pesadas", json=PESADA).json()["evento"] is None


def test_reevaluar_una_pesada(client, orden, erp_sano):
    pesada = client.post("/pesadas", json={
        "numero_orden": "ORD-2026-0001", "peso_real_kg": "19990.00",
        "motivo_manual": "dentro de tolerancia"}).json()
    assert pesada["evento"] is None

    client.patch(f"/configuracion/{PRODUCTO}", json={"tolerancia_kg": 5})
    evento = client.post(f"/pesadas/{pesada['id']}/evaluar").json()
    assert evento["estado"] == "pendiente"
    assert Decimal(evento["diferencia_kg"]) == Decimal("-10.00")


def test_reevaluar_no_duplica(client, orden, erp_sano):
    pesada = client.post("/pesadas", json=PESADA).json()
    primero = pesada["evento"]["id"]
    assert client.post(f"/pesadas/{pesada['id']}/evaluar").json()["id"] == primero
    assert len(client.get("/eventos").json()) == 1


def test_reevaluar_una_pesada_inexistente(client):
    assert client.post("/pesadas/9999/evaluar").status_code == 404


def test_consulta_no_reevalua(client_consulta, orden, erp_sano):
    assert client_consulta.post("/pesadas/1/evaluar").status_code == 403


def test_una_pesada_sin_tolerancia_no_pasa_por_limpia(client, sesion, orden, erp_sano):
    """No es lo mismo "entro dentro de la tolerancia" que "no se pudo comparar".
    Sin esa diferencia, un hueco de configuracion se leeria como carga limpia."""
    sesion.execute(text("DELETE FROM configuracion WHERE producto = :p"),
                   {"p": PRODUCTO})
    sesion.commit()

    resp = client.post("/pesadas", json={
        "numero_orden": "ORD-2026-0001", "peso_real_kg": "19850.00",
        "motivo_manual": "producto sin tolerancia"})
    cuerpo = resp.json()
    assert resp.status_code == 201            # la pesada se registra igual
    assert cuerpo["evento"] is None
    assert cuerpo["evaluada"] is False
    assert "no tiene tolerancia configurada" in cuerpo["motivo_sin_evaluar"]

    # Y el hueco se ve en GET /salud, no solo en el log.
    componentes = {c["componente"]: c for c in client.get("/salud").json()["componentes"]}
    assert componentes["configuracion"]["estado"] == "error"

    # Reevaluar sin haber configurado nada dice que falta configuracion, no 200.
    assert client.post(f"/pesadas/{cuerpo['id']}/evaluar").status_code == 409


def test_una_pesada_evaluada_lo_dice(client, orden, erp_sano):
    assert client.post("/pesadas", json=PESADA).json()["evaluada"] is True


def test_consulta_si_lee_los_eventos(client_consulta):
    """Enterarse es justo lo que la historia quiere para el supervisor."""
    assert client_consulta.get("/eventos").status_code == 200


# ---------- HU-04: tolerancias por producto ----------

RUTA = f"/configuracion/{PRODUCTO}"


def test_listar_las_tolerancias_configuradas(client):
    """Criterio 1: la pantalla necesita los dos campos, en kg y en porcentaje."""
    resp = client.get("/configuracion")
    assert resp.status_code == 200
    filas = resp.json()
    assert len(filas) == 3
    mia = next(f for f in filas if f["producto"] == PRODUCTO)
    assert Decimal(mia["tolerancia_kg"]) == TOLERANCIA_KG
    assert Decimal(mia["tolerancia_pct"]) == TOLERANCIA_PCT
    # Los canales de la RN-04 se muestran, pero los edita HU-10 en el Sprint 4.
    assert "alta" in mia["canales_por_severidad"]


def test_obtener_la_tolerancia_de_un_producto(client):
    resp = client.get(RUTA)
    assert resp.status_code == 200
    assert resp.json()["producto"] == PRODUCTO


def test_un_producto_sin_configurar_devuelve_404(client):
    assert client.get("/configuracion/Kiwicha").status_code == 404


def test_editar_la_tolerancia_como_administrador(client):
    resp = client.patch(RUTA, json={"tolerancia_kg": 80, "tolerancia_pct": 1.25})
    assert resp.status_code == 200
    cuerpo = resp.json()
    assert Decimal(cuerpo["tolerancia_kg"]) == Decimal("80.00")
    assert Decimal(cuerpo["tolerancia_pct"]) == Decimal("1.25")


def test_el_cambio_se_ve_en_la_siguiente_lectura(client):
    client.patch(RUTA, json={"tolerancia_kg": 65})
    assert Decimal(client.get(RUTA).json()["tolerancia_kg"]) == Decimal("65.00")


def test_editar_un_solo_campo(client):
    resp = client.patch(RUTA, json={"tolerancia_pct": 2})
    assert Decimal(resp.json()["tolerancia_kg"]) == TOLERANCIA_KG
    assert Decimal(resp.json()["tolerancia_pct"]) == Decimal("2.00")


def test_un_cuerpo_vacio_no_es_un_cambio(client):
    resp = client.patch(RUTA, json={})
    assert resp.status_code == 422
    assert "al menos" in resp.json()["detail"]


@pytest.mark.parametrize("cuerpo", [
    {"tolerancia_kg": -1},
    {"tolerancia_pct": -0.5},
    {"tolerancia_pct": 100.5},
    {"tolerancia_kg": "mucho"},
])
def test_valores_invalidos_se_rechazan(client, cuerpo):
    assert client.patch(RUTA, json=cuerpo).status_code == 422


def test_editar_un_producto_inexistente_devuelve_404(client):
    assert client.patch("/configuracion/Kiwicha",
                        json={"tolerancia_kg": 10}).status_code == 404


# ---------- HU-04, criterio 2: solo el Administrador edita ----------

def test_el_supervisor_lee_pero_no_edita_la_tolerancia(client_supervisor):
    """Necesita saber contra que umbral se mide su rampa, aunque no pueda moverlo."""
    assert client_supervisor.get("/configuracion").status_code == 200
    resp = client_supervisor.patch(RUTA, json={"tolerancia_kg": 10})
    assert resp.status_code == 403
    assert "rol no permite" in resp.json()["detail"]


def test_consulta_tampoco_edita_la_tolerancia(client_consulta):
    assert client_consulta.get("/configuracion").status_code == 200
    assert client_consulta.patch(RUTA, json={"tolerancia_kg": 10}).status_code == 403


def test_un_intento_rechazado_no_cambia_nada(client, client_consulta):
    client_consulta.patch(RUTA, json={"tolerancia_kg": 10})
    assert Decimal(client.get(RUTA).json()["tolerancia_kg"]) == TOLERANCIA_KG


# ---------- HU-04, criterio 3: cada cambio con usuario y fecha ----------

def test_la_respuesta_dice_quien_hizo_el_ultimo_cambio(client):
    antes = client.get(RUTA).json()
    assert antes["actualizado_por"] is None

    despues = client.patch(RUTA, json={"tolerancia_kg": 90}).json()
    assert despues["actualizado_por_nombre"] == "Administrador"
    assert despues["fecha"] >= antes["fecha"]


def test_el_historial_trae_los_valores_de_antes_y_despues(client):
    client.patch(RUTA, json={"tolerancia_kg": 60})
    client.patch(RUTA, json={"tolerancia_kg": 70})

    cambios = client.get(f"{RUTA}/historial").json()
    assert len(cambios) == 2
    assert cambios[0]["detalle"]["despues"]["kg"] == "70.00"
    assert cambios[0]["detalle"]["antes"]["kg"] == "60.00"
    assert cambios[0]["usuario_id"] is not None
    # El nombre y no solo el id: un numero en la pantalla no le dice nada a nadie.
    assert cambios[0]["usuario_nombre"] == "Administrador"
    assert cambios[0]["fecha"]


def test_el_historial_de_un_producto_inexistente(client):
    assert client.get("/configuracion/Kiwicha/historial").status_code == 404


def test_el_supervisor_puede_leer_el_historial(client_supervisor):
    """El criterio 3 es para poder auditar, no solo para el que edita."""
    assert client_supervisor.get(f"{RUTA}/historial").status_code == 200


# ---------- HU-04 con RN-01: la tolerancia mas restrictiva ----------

@pytest.mark.parametrize("peso,efectiva,manda", [
    (20000, "50.00", "kg"),           # 0,5 % serian 100 kg: manda el tope en kg
    (5000, "25.00", "porcentaje"),    # 0,5 % son 25 kg: manda el porcentaje
])
def test_la_tolerancia_aplicada_dice_cual_manda(client, peso, efectiva, manda):
    resp = client.get(f"{RUTA}/aplicada", params={"peso_esperado_kg": peso})
    assert resp.status_code == 200
    cuerpo = resp.json()
    assert Decimal(cuerpo["tolerancia_efectiva_kg"]) == Decimal(efectiva)
    assert cuerpo["manda"] == manda


def test_la_tolerancia_aplicada_exige_un_peso_positivo(client):
    assert client.get(f"{RUTA}/aplicada",
                      params={"peso_esperado_kg": 0}).status_code == 422


def test_la_tolerancia_aplicada_de_un_producto_inexistente(client):
    assert client.get("/configuracion/Kiwicha/aplicada",
                      params={"peso_esperado_kg": 1000}).status_code == 404


def test_editar_el_porcentaje_cambia_la_tolerancia_aplicada(client):
    """El objetivo de la historia: ajustar la sensibilidad sin tocar el codigo."""
    ruta = f"{RUTA}/aplicada"
    antes = client.get(ruta, params={"peso_esperado_kg": 5000}).json()
    client.patch(RUTA, json={"tolerancia_pct": 0.10})
    despues = client.get(ruta, params={"peso_esperado_kg": 5000}).json()
    assert Decimal(despues["tolerancia_efectiva_kg"]) < Decimal(antes["tolerancia_efectiva_kg"])
    assert Decimal(despues["tolerancia_efectiva_kg"]) == Decimal("5.00")


# ---------- GET /salud ----------

def test_salud_todo_correcto(client, orden, erp_sano):
    resp = client.get("/salud")
    assert resp.status_code == 200
    body = resp.json()
    componentes = {c["componente"]: c for c in body["componentes"]}
    assert body["estado"] == "ok"
    assert componentes["mysql"]["estado"] == "ok"
    assert componentes["erp"]["estado"] == "ok"
    assert componentes["bascula"]["estado"] == "ok"
    assert str(PESO_FIJO) in componentes["bascula"]["mensaje"]
    # HU-18 mostrara la ultima verificacion: tiene que venir en la respuesta.
    assert all(c["verificado_en"] for c in body["componentes"])


def test_salud_con_la_bascula_caida(crear_cliente, erp_sano):
    """Criterio 2: el fallo registrado es visible en GET /salud."""
    cliente = crear_cliente(scale_port=SIN_NADIE)
    body = cliente.get("/salud").json()
    componentes = {c["componente"]: c for c in body["componentes"]}
    assert body["estado"] == "error"
    assert componentes["bascula"]["estado"] == "error"
    assert "BASCULA-01" in componentes["bascula"]["mensaje"]


def test_salud_con_la_bascula_en_movimiento(crear_cliente, bascula_inestable, erp_sano):
    cliente = crear_cliente(scale_port=bascula_inestable)
    componentes = {c["componente"]: c for c in cliente.get("/salud").json()["componentes"]}
    assert componentes["bascula"]["estado"] == "advertencia"
    assert "movimiento" in componentes["bascula"]["mensaje"]


def test_salud_con_el_erp_caido(client, erp_caido):
    body = client.get("/salud").json()
    componentes = {c["componente"]: c for c in body["componentes"]}
    assert body["estado"] == "error"
    assert componentes["erp"]["estado"] == "error"


# ---------- GET /salud/historial ----------

def test_historial_registra_la_caida_y_la_recuperacion(crear_cliente, client, orden, erp_sano):
    caido = crear_cliente(scale_port=SIN_NADIE)
    caido.post("/pesadas", json=PESADA)          # deja la bascula en error
    client.post("/pesadas", json=PESADA)         # la bascula sana vuelve a ok

    historial = client.get("/salud/historial", params={"componente": "bascula"}).json()
    assert [f["estado"] for f in historial] == ["ok", "error"]


def test_historial_sin_filtro_devuelve_todos_los_componentes(client, orden, erp_sano):
    client.get("/salud")
    componentes = {f["componente"] for f in client.get("/salud/historial").json()}
    assert {"erp", "bascula"} <= componentes


def test_historial_respeta_el_limite(client, orden, erp_sano):
    client.get("/salud")
    assert len(client.get("/salud/historial", params={"limite": 1}).json()) == 1


def test_una_marca_corrupta_en_auditoria_no_rompe_la_respuesta(client, orden, erp_sano, sesion):
    """El detalle de auditoria es JSON libre. Si alguna vez llega una fecha que
    no se puede leer, el evento sigue respondiendo sin ventana en lugar de
    devolver un 500 y dejar al supervisor sin el aviso."""
    evento = client.post("/pesadas", json=PESADA).json()["evento"]
    sesion.execute(text(
        "INSERT INTO auditoria (entidad, entidad_id, accion, detalle, fecha) "
        "VALUES ('evento', :i, 'recortar_clip', "
        "JSON_OBJECT('desde', 'no-es-una-fecha', 'hasta', 'tampoco'), NOW(6))"),
        {"i": evento["id"]})
    sesion.commit()

    leido = client.get(f"/eventos/{evento['id']}")
    assert leido.status_code == 200
    assert leido.json()["clip_desde"] is None


# ---------- HU-10: los avisos enviados por un evento ----------

def sembrar_aviso(sesion, evento_id, *, estado="enviada", severidad="alta",
                  destinatarios=("ana@quinor.com.pe",), segundos=12.5,
                  error=None, intentos=1):
    """Escribe lo que el servicio de notificaciones habria escrito."""
    from app.models import Notificacion

    sesion.add(Notificacion(
        evento_id=evento_id, canal="correo", severidad=severidad,
        destinatarios=list(destinatarios),
        asunto="[ALERTA ALTA] Orden ORD-2026-0001: faltan 8 sacos",
        estado=estado, intentos=intentos, error=error,
        segundos_desde_analisis=(None if segundos is None
                                 else Decimal(str(segundos))),
        enviada_en=dt.datetime.now() if estado == "enviada" else None,
        creado_en=dt.datetime.now()))
    sesion.commit()


def test_un_evento_recien_creado_no_tiene_avisos(client, orden, erp_sano):
    """Todavia no se ha analizado: sin severidad no hay a quien avisar."""
    creado = client.post("/pesadas", json=PESADA).json()["evento"]

    cuerpo = client.get(f"/eventos/{creado['id']}/avisos").json()

    assert cuerpo["avisado"] is False
    assert cuerpo["notificaciones"] == []


def test_se_consulta_si_se_aviso_de_un_evento(client, sesion, orden, erp_sano):
    """Es la pregunta que se hace cuando el cliente reclama meses despues, y la
    respuesta no puede depender de que un supervisor conserve el correo."""
    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    sembrar_aviso(sesion, creado["id"],
                  destinatarios=("ana@quinor.com.pe", "rosa@quinor.com.pe"))

    cuerpo = client.get(f"/eventos/{creado['id']}/avisos").json()

    assert cuerpo["avisado"] is True
    aviso = cuerpo["notificaciones"][0]
    assert aviso["canal"] == "correo"
    assert aviso["severidad"] == "alta"
    assert len(aviso["destinatarios"]) == 2
    assert "faltan 8 sacos" in aviso["asunto"]


def test_un_aviso_fallido_no_cuenta_como_avisado(client, sesion, orden, erp_sano):
    """Nadie lo recibio. Decir que si seria la peor respuesta posible a la unica
    pregunta que esta pantalla contesta."""
    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    sembrar_aviso(sesion, creado["id"], estado="fallida", segundos=None,
                  error="El relay no responde", intentos=3)

    cuerpo = client.get(f"/eventos/{creado['id']}/avisos").json()

    assert cuerpo["avisado"] is False
    assert cuerpo["notificaciones"][0]["estado"] == "fallida"
    assert "relay" in cuerpo["notificaciones"][0]["error"]


def test_se_ve_si_el_aviso_cumplio_los_60_segundos(client, sesion, orden,
                                                   erp_sano):
    """Criterio 3. Se mide con lo que paso de verdad, no se da por hecho."""
    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    sembrar_aviso(sesion, creado["id"], segundos=12.5)

    aviso = client.get(f"/eventos/{creado['id']}/avisos").json()["notificaciones"][0]

    assert Decimal(aviso["segundos_desde_analisis"]) == Decimal("12.50")
    assert aviso["dentro_del_criterio"] is True


def test_un_aviso_tardio_se_ve_como_tardio(client, sesion, orden, erp_sano):
    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    sembrar_aviso(sesion, creado["id"], segundos=180.0)

    aviso = client.get(f"/eventos/{creado['id']}/avisos").json()["notificaciones"][0]

    assert aviso["dentro_del_criterio"] is False


def test_sin_medida_no_se_finge_que_se_cumplio(client, sesion, orden, erp_sano):
    """NULL no es cero: un cero fingido daria el criterio por cumplido sin
    haberlo comprobado."""
    creado = client.post("/pesadas", json=PESADA).json()["evento"]
    sembrar_aviso(sesion, creado["id"], segundos=None)

    aviso = client.get(f"/eventos/{creado['id']}/avisos").json()["notificaciones"][0]

    assert aviso["segundos_desde_analisis"] is None
    assert aviso["dentro_del_criterio"] is None


def test_los_avisos_de_un_evento_que_no_existe_dan_404(client):
    assert client.get("/eventos/999999/avisos").status_code == 404


def test_los_avisos_piden_autenticacion(client):
    client.headers.pop("X-API-Key")

    assert client.get("/eventos/1/avisos").status_code == 401
