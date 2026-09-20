"""La configuracion del servicio.

Apartado 8: "Las claves ... se gestionan como variables de entorno o secretos de
Docker, nunca en el codigo". Lo que se comprueba aqui es que un valor mal puesto
se descubre al arrancar y no con el primer evento en la rampa.
"""
from __future__ import annotations

import dataclasses

import pytest

from app.config import (SEGUNDOS_DEL_CRITERIO, SIN_CIFRAR, SSL, STARTTLS,
                        Ajustes, cargar_ajustes)


def test_sin_entorno_arranca_con_valores_de_desarrollo(monkeypatch):
    for nombre in ("SMTP_HOST", "SMTP_PORT", "SMTP_SECURITY", "SMTP_FROM",
                   "DASHBOARD_BASE_URL", "DATABASE_URL"):
        monkeypatch.delenv(nombre, raising=False)

    ajustes = cargar_ajustes()

    assert ajustes.smtp_host == "localhost"
    assert ajustes.cifrado == SIN_CIFRAR
    assert ajustes.intentos == 3


def test_el_entorno_manda(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "relay.quinor.com.pe")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_SECURITY", "STARTTLS")
    monkeypatch.setenv("SMTP_FROM", "alertas@quinor.com.pe")
    monkeypatch.setenv("NOTIFY_MAX_ATTEMPTS", "5")

    ajustes = cargar_ajustes()

    assert ajustes.smtp_host == "relay.quinor.com.pe"
    assert ajustes.smtp_port == 587
    assert ajustes.cifrado == STARTTLS       # se normaliza a minusculas
    assert ajustes.intentos == 5


def test_un_parametro_explicito_gana_al_entorno(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "relay.quinor.com.pe")

    assert cargar_ajustes(smtp_host="127.0.0.1").smtp_host == "127.0.0.1"


def test_una_variable_vacia_no_borra_el_valor_por_defecto(monkeypatch):
    """Un compose con SMTP_HOST= es un descuido, no una orden de quedarse sin
    servidor de correo."""
    monkeypatch.setenv("SMTP_HOST", "")

    assert cargar_ajustes().smtp_host == "localhost"


@pytest.mark.parametrize("variable,valor", [
    ("SMTP_SECURITY", "tls-raro"),
    ("SMTP_PORT", "70000"),
    ("NOTIFY_MAX_ATTEMPTS", "0"),
    ("NOTIFY_BACKOFF_SECONDS", "-1"),
    ("SMTP_TIMEOUT_SECONDS", "0"),
    ("SMTP_FROM", "no-es-un-correo"),
])
def test_un_valor_imposible_se_descubre_al_arrancar(monkeypatch, variable,
                                                    valor):
    """Mejor no arrancar que arrancar y descubrirlo con el camion en la rampa."""
    monkeypatch.setenv(variable, valor)

    with pytest.raises(ValueError):
        cargar_ajustes()


def test_los_tres_cifrados_son_validos(monkeypatch):
    for modo in (STARTTLS, SSL, SIN_CIFRAR):
        monkeypatch.setenv("SMTP_SECURITY", modo)
        assert cargar_ajustes().cifrado == modo


def test_sin_servidor_el_servicio_se_declara_no_configurado():
    assert Ajustes(smtp_host="").configurado is False
    assert Ajustes(smtp_host="relay", remitente="").configurado is False
    assert Ajustes(smtp_host="relay").configurado is True


def test_el_enlace_del_evento_es_el_del_criterio_2():
    ajustes = Ajustes(dashboard_url="http://dashboard.quinor.local:8050/")

    assert ajustes.enlace_del_evento(41) == (
        "http://dashboard.quinor.local:8050/eventos/41")


def test_la_barra_de_mas_en_la_url_no_rompe_el_enlace():
    """Una URL con barra final y otra sin ella tienen que dar el mismo enlace:
    es el error de configuracion mas facil de cometer y el mas tonto de sufrir."""
    con = Ajustes(dashboard_url="http://d:8050///")
    sin = Ajustes(dashboard_url="http://d:8050")

    assert con.enlace_del_evento(7) == sin.enlace_del_evento(7)


def test_el_correo_sin_cifrar_en_produccion_queda_senalado():
    """No se impide arrancar, porque un relay interno en una red cerrada es una
    decision defendible; pero se avisa, para que sea una decision y no un
    descubrimiento."""
    produccion = Ajustes(app_env="production", cifrado=SIN_CIFRAR)
    protegido = dataclasses.replace(produccion, cifrado=STARTTLS)
    desarrollo = Ajustes(app_env="development", cifrado=SIN_CIFRAR)

    assert produccion.viaja_en_claro is True
    assert protegido.viaja_en_claro is False
    assert desarrollo.viaja_en_claro is False


def test_las_credenciales_son_opcionales():
    """Un relay interno que confia en la red no pide usuario, y obligar a uno
    inventado solo lograria que alguien escribiera una contrasena falsa en el
    compose."""
    assert Ajustes(smtp_user="").usa_credenciales is False
    assert Ajustes(smtp_user="alertas").usa_credenciales is True


def test_el_limite_del_criterio_3_esta_escrito_en_un_solo_sitio():
    """"La notificacion se envia en menos de 60 s tras el analisis"."""
    assert SEGUNDOS_DEL_CRITERIO == 60.0


def test_la_contrasena_no_aparece_al_imprimir_los_ajustes(monkeypatch):
    """Los ajustes acaban en un log tarde o temprano. Que la contrasena viva en
    el objeto es inevitable; que se imprima sola, no."""
    monkeypatch.setenv("SMTP_PASSWORD", "clave-del-buzon")
    ajustes = cargar_ajustes()

    assert ajustes.smtp_password == "clave-del-buzon"
    assert "clave-del-buzon" not in repr(ajustes)
