"""Tests de configuracion de create_app y de cargar_ajustes."""

import pytest
from fastapi.testclient import TestClient

from app.config import ADMIN_POR_DEFECTO, CLAVE_DESARROLLO, Ajustes, cargar_ajustes
from app.main import create_app
from tests.conftest import ADMIN_CLAVE, ADMIN_CORREO, URL_PRUEBAS, iniciar_sesion


# ---------- cargar_ajustes ----------

def test_los_ajustes_salen_del_entorno(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", URL_PRUEBAS)
    monkeypatch.setenv("ADMIN_EMAIL", "jefe@quinor.local")
    monkeypatch.setenv("ADMIN_PASSWORD", "clave-env-123")
    monkeypatch.setenv("TOKEN_TTL_HOURS", "4")
    monkeypatch.setenv("SCALE_HOST", "bascula-planta")
    monkeypatch.setenv("SCALE_PORT", "5030")
    monkeypatch.setenv("SCALE_UNIT_ID", "3")
    monkeypatch.setenv("SCALE_TIMEOUT_SECONDS", "7.5")
    monkeypatch.setenv("BASCULA_ID", "BASCULA-07")
    monkeypatch.setenv("ERP_BASE_URL", "http://erp-real:9000")
    monkeypatch.setenv("APP_ENV", "produccion")

    ajustes = cargar_ajustes()
    assert ajustes.admin_email == "jefe@quinor.local"
    assert ajustes.admin_password == "clave-env-123"
    assert ajustes.token_ttl_hours == 4
    assert ajustes.scale_host == "bascula-planta"
    assert ajustes.scale_port == 5030
    assert ajustes.scale_unit_id == 3
    assert ajustes.scale_timeout_seconds == 7.5
    assert ajustes.bascula_id == "BASCULA-07"
    assert ajustes.erp_base_url == "http://erp-real:9000"
    assert ajustes.app_env == "produccion"
    assert ajustes.clave_por_defecto_en_uso is False


def test_un_parametro_explicito_gana_al_entorno(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://del/entorno")
    monkeypatch.setenv("SCALE_PORT", "5030")

    ajustes = cargar_ajustes(database_url=URL_PRUEBAS, scale_port=6000)
    assert ajustes.database_url == URL_PRUEBAS
    assert ajustes.scale_port == 6000


def test_los_valores_por_defecto_son_los_del_compose(monkeypatch):
    for variable in ("ADMIN_EMAIL", "ADMIN_PASSWORD", "SCALE_HOST", "SCALE_PORT",
                     "ERP_BASE_URL", "BASCULA_ID"):
        monkeypatch.delenv(variable, raising=False)
    ajustes = cargar_ajustes(database_url=URL_PRUEBAS)
    assert ajustes.scale_host == "scale-sim"
    assert ajustes.scale_port == 5020
    assert ajustes.bascula_id == "BASCULA-01"
    assert ajustes.erp_base_url == "http://erp-mock:8001"
    assert ajustes.admin_email == ADMIN_POR_DEFECTO
    assert ajustes.clave_por_defecto_en_uso is True
    assert ajustes.sin_administrador_inicial is False


def test_una_variable_vacia_cuenta_como_ausente(monkeypatch):
    monkeypatch.setenv("SCALE_HOST", "")
    assert cargar_ajustes(database_url=URL_PRUEBAS).scale_host == "scale-sim"


def test_sin_base_de_datos_la_aplicacion_no_arranca(monkeypatch):
    """Fallar al arrancar es mejor que fallar en la primera pesada del turno."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        cargar_ajustes()


# ---------- create_app ----------

def test_create_app_con_variables_de_entorno(sesion, monkeypatch, bascula_estable):
    monkeypatch.setenv("DATABASE_URL", URL_PRUEBAS)
    monkeypatch.setenv("ADMIN_EMAIL", "jefe@quinor.local")
    monkeypatch.setenv("ADMIN_PASSWORD", "clave-env-123")
    monkeypatch.setenv("SCALE_HOST", "127.0.0.1")
    monkeypatch.setenv("SCALE_PORT", str(bascula_estable))

    app = create_app()
    with TestClient(app) as client:
        token = iniciar_sesion(client, "jefe@quinor.local", "clave-env-123")
        assert client.get("/pesadas", headers={"X-API-Key": token}).status_code == 200
        assert client.get("/pesadas", headers={"X-API-Key": "inventado"}).status_code == 401
    app.state.cerrar()


def test_el_administrador_inicial_se_crea_al_arrancar(sesion, bascula_estable):
    """Como el bloque genesis del ejemplo: sin el, no habria por donde entrar."""
    app = create_app(database_url=URL_PRUEBAS, admin_email=ADMIN_CORREO,
                     admin_password=ADMIN_CLAVE, scale_host="127.0.0.1",
                     scale_port=bascula_estable)
    with TestClient(app) as client:
        token = iniciar_sesion(client, ADMIN_CORREO, ADMIN_CLAVE)
        yo = client.get("/auth/yo", headers={"X-API-Key": token}).json()
        assert yo["rol"] == "administrador"
    app.state.cerrar()


def test_sin_clave_de_administrador_no_se_crea_ninguno(sesion):
    """Arranca igual, pero nadie puede entrar. El log lo advierte."""
    from sqlalchemy import text

    app = create_app(database_url=URL_PRUEBAS, ajustes=Ajustes(
        database_url=URL_PRUEBAS, admin_password=""))
    with TestClient(app) as client:
        assert client.post("/auth/login", json={"correo": ADMIN_CORREO,
                                                "clave": ADMIN_CLAVE}).status_code == 401
    assert sesion.execute(text("SELECT COUNT(*) FROM usuario")).scalar_one() == 0
    app.state.cerrar()


def test_create_app_avisa_de_la_clave_por_defecto(monkeypatch):
    """Arrancar con la clave de desarrollo es legal, pero no debe pasar inadvertido."""
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    app = create_app(database_url=URL_PRUEBAS)
    assert app.state.ajustes.admin_password == CLAVE_DESARROLLO
    assert app.state.ajustes.clave_por_defecto_en_uso is True
    app.state.cerrar()


def test_create_app_acepta_ajustes_ya_construidos():
    ajustes = Ajustes(database_url=URL_PRUEBAS, admin_password="otra", bascula_id="BASCULA-42")
    app = create_app(ajustes=ajustes)
    assert app.state.ajustes is ajustes
    assert app.state.ajustes.bascula_id == "BASCULA-42"
    app.state.cerrar()


def test_cada_instancia_tiene_su_propio_motor():
    """Dos aplicaciones no comparten estado: es lo que permite aislarlas en pruebas."""
    una = create_app(database_url=URL_PRUEBAS, admin_password="a")
    otra = create_app(database_url=URL_PRUEBAS, admin_password="b")
    assert una.state.motor is not otra.state.motor
    assert una.state.ajustes.admin_password != otra.state.ajustes.admin_password
    una.state.cerrar()
    otra.state.cerrar()
