"""Los ajustes del servicio.

Aqui el fallo caro no es un valor raro: es arrancar apuntando al proveedor
equivocado, o sin clave, y descubrirlo con el primer evento. Por eso lo que mas
se prueba es que una configuracion mala no arranque en silencio.
"""
from __future__ import annotations

import pytest

from app.config import (ANTHROPIC, CONCORDANCIA_MINIMA_PCT, INTENTOS, STUB,
                        Ajustes, cargar_ajustes)


def test_sin_entorno_queda_el_stub_y_no_un_proveedor_de_pago():
    """Un valor por defecto que saliera a internet convertiria un despliegue mal
    configurado en una factura."""
    ajustes = cargar_ajustes()

    assert ajustes.proveedor == STUB
    assert ajustes.intentos == INTENTOS == 3


def test_el_entorno_manda(monkeypatch):
    monkeypatch.setenv("VLM_PROVIDER", "anthropic")
    monkeypatch.setenv("VLM_API_KEY", "sk-de-prueba")
    monkeypatch.setenv("VLM_MODEL", "un-modelo")
    monkeypatch.setenv("VLM_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("VLM_TEMPERATURE", "0.0")

    ajustes = cargar_ajustes()

    assert ajustes.proveedor == ANTHROPIC
    assert ajustes.api_key == "sk-de-prueba"
    assert ajustes.modelo == "un-modelo"
    assert ajustes.intentos == 5
    assert ajustes.temperatura == 0.0


def test_el_proveedor_no_distingue_mayusculas(monkeypatch):
    monkeypatch.setenv("VLM_PROVIDER", "Anthropic")
    assert cargar_ajustes().proveedor == ANTHROPIC


def test_un_proveedor_sin_adaptador_no_arranca(monkeypatch):
    """Mejor no arrancar que arrancar y fallar con el primer evento."""
    monkeypatch.setenv("VLM_PROVIDER", "inventado")
    with pytest.raises(ValueError, match="no tiene adaptador"):
        cargar_ajustes()


def test_el_stub_no_necesita_clave():
    assert Ajustes(proveedor=STUB, api_key="").configurado is True


def test_un_proveedor_real_sin_clave_no_esta_configurado():
    """Apartado 8: la clave vive en el entorno o en secretos de Docker. Sin ella
    el servicio arranca, pero /salud lo dice y el analisis responde 503."""
    assert Ajustes(proveedor=ANTHROPIC, api_key="").configurado is False
    assert Ajustes(proveedor=ANTHROPIC, api_key="sk-x").configurado is True


@pytest.mark.parametrize("valor", ["0", "-1"])
def test_sin_intentos_no_habria_llamada(monkeypatch, valor):
    monkeypatch.setenv("VLM_MAX_ATTEMPTS", valor)
    with pytest.raises(ValueError, match="1 o mas"):
        cargar_ajustes()


def test_una_espera_negativa_se_rechaza(monkeypatch):
    monkeypatch.setenv("VLM_BACKOFF_SECONDS", "-2")
    with pytest.raises(ValueError, match="negativo"):
        cargar_ajustes()


@pytest.mark.parametrize("valor", ["0", "-10"])
def test_un_timeout_imposible_se_rechaza(monkeypatch, valor):
    monkeypatch.setenv("VLM_TIMEOUT_SECONDS", valor)
    with pytest.raises(ValueError, match="mayor que cero"):
        cargar_ajustes()


@pytest.mark.parametrize("valor", ["-0.1", "2.5"])
def test_una_temperatura_fuera_de_rango_se_rechaza(monkeypatch, valor):
    monkeypatch.setenv("VLM_TEMPERATURE", valor)
    with pytest.raises(ValueError, match="entre 0 y 2"):
        cargar_ajustes()


def test_una_variable_vacia_cuenta_como_ausente(monkeypatch):
    """docker-compose deja variables vacias cuando el .env no las define."""
    monkeypatch.setenv("VLM_MODEL", "")
    assert cargar_ajustes().modelo == "claude-sonnet-4-5"


def test_lo_que_se_pasa_por_parametro_manda_sobre_el_entorno(monkeypatch):
    monkeypatch.setenv("VLM_PROVIDER", "anthropic")
    monkeypatch.setenv("VLM_API_KEY", "sk-x")
    assert cargar_ajustes(proveedor="stub").proveedor == STUB


def test_un_parametro_en_none_no_pisa_el_entorno(monkeypatch):
    monkeypatch.setenv("VLM_MODEL", "del-entorno")
    assert cargar_ajustes(modelo=None).modelo == "del-entorno"


def test_el_contexto_de_planta_es_configurable(monkeypatch):
    """Apartado 9.2: el prompt necesita saber como es una carga normal, y eso lo
    sabe QUINOR. Se ajusta en el piloto."""
    monkeypatch.setenv("PLANTA_SACOS_POR_CAMION", "500")
    monkeypatch.setenv("PLANTA_DURACION_CARGA_MIN", "60")
    monkeypatch.setenv("PLANTA_PRODUCTO", "quinua roja en sacos de 25 kg")

    ajustes = cargar_ajustes()

    assert ajustes.sacos_por_camion == 500
    assert ajustes.duracion_tipica_min == 60
    assert "25 kg" in ajustes.producto


def test_el_umbral_de_concordancia_es_el_del_apartado_92():
    assert CONCORDANCIA_MINIMA_PCT == 85.0
