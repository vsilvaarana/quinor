"""Los adaptadores por proveedor.

Cambiar de proveedor tiene que ser cambiar VLM_PROVIDER. Estas pruebas son las
que sostienen esa promesa: si alguien mete un detalle de un proveedor en el
codigo comun, el otro deja de armar bien su peticion y se ve aqui.
"""
from __future__ import annotations

import dataclasses

import pytest

from app.config import Ajustes
from app.proveedores import (URLS, VERSION_ANTHROPIC, Imagen,
                             ProveedorDesconocido, construir,
                             texto_de_la_respuesta)

IMAGENES = [Imagen(base64="AAAA", pie="[segundo 12 - saco_saliente]")]


def ajustes(**cambios) -> Ajustes:
    base = Ajustes(proveedor="anthropic", api_key="clave", modelo="un-modelo",
                   max_tokens=512, temperatura=0.2)
    return dataclasses.replace(base, **cambios) if cambios else base


# ------------------------------------------------------------------ anthropic
def test_anthropic_manda_la_clave_en_su_cabecera():
    peticion = construir(ajustes(), "sistema", "datos", IMAGENES)

    assert peticion.url == URLS["anthropic"]
    assert peticion.cabeceras["x-api-key"] == "clave"
    assert peticion.cabeceras["anthropic-version"] == VERSION_ANTHROPIC


def test_anthropic_separa_el_sistema_del_mensaje():
    peticion = construir(ajustes(), "contexto de planta", "datos", IMAGENES)

    assert peticion.cuerpo["system"] == "contexto de planta"
    assert peticion.cuerpo["messages"][0]["role"] == "user"


def test_anthropic_empaqueta_la_imagen_como_base64():
    contenido = construir(ajustes(), "s", "d", IMAGENES).cuerpo["messages"][0]["content"]
    imagen = [b for b in contenido if b["type"] == "image"][0]

    assert imagen["source"] == {"type": "base64", "media_type": "image/jpeg",
                                "data": "AAAA"}


# --------------------------------------------------------------------- openai
def test_openai_manda_la_clave_como_bearer():
    peticion = construir(ajustes(proveedor="openai"), "s", "d", IMAGENES)

    assert peticion.url == URLS["openai"]
    assert peticion.cabeceras["Authorization"] == "Bearer clave"
    assert "x-api-key" not in peticion.cabeceras


def test_openai_mete_el_sistema_como_un_mensaje_mas():
    """Es la diferencia de formato que justifica tener adaptadores."""
    cuerpo = construir(ajustes(proveedor="openai"), "contexto", "d", IMAGENES).cuerpo

    assert cuerpo["messages"][0] == {"role": "system", "content": "contexto"}
    assert cuerpo["messages"][1]["role"] == "user"


def test_openai_empaqueta_la_imagen_como_data_url():
    cuerpo = construir(ajustes(proveedor="openai"), "s", "d", IMAGENES).cuerpo
    contenido = cuerpo["messages"][1]["content"]
    imagen = [b for b in contenido if b["type"] == "image_url"][0]

    assert imagen["image_url"]["url"] == "data:image/jpeg;base64,AAAA"


def test_openai_respeta_la_base_url():
    peticion = construir(ajustes(proveedor="openai", base_url="http://pasarela:9000/"),
                         "s", "d", IMAGENES)

    assert peticion.url == "http://pasarela:9000/v1/chat/completions"


# ------------------------------------------------------------------ lo comun
def test_los_dos_mandan_el_modelo_y_los_limites():
    for proveedor in ("anthropic", "openai"):
        cuerpo = construir(ajustes(proveedor=proveedor), "s", "d", IMAGENES).cuerpo

        assert cuerpo["model"] == "un-modelo"
        assert cuerpo["max_tokens"] == 512
        assert cuerpo["temperature"] == 0.2


def test_cada_imagen_va_precedida_de_su_pie():
    """En los dos formatos, para que el modelo sepa que mira."""
    varias = [Imagen(base64="A", pie="primero"), Imagen(base64="B", pie="segundo")]
    contenido = construir(ajustes(), "s", "d", varias).cuerpo["messages"][0]["content"]
    textos = [b["text"] for b in contenido if b["type"] == "text"]

    assert textos == ["d", "primero", "segundo"]


def test_el_stub_habla_el_formato_de_anthropic():
    """Hace falta un formato concreto para poder probar de verdad, y elegir el
    del proveedor por defecto evita mantener un cuarto dialecto."""
    peticion = construir(ajustes(proveedor="stub", base_url="http://stub:1"),
                         "s", "d", IMAGENES)

    assert peticion.url == "http://stub:1/v1/messages"
    assert "system" in peticion.cuerpo


def test_un_proveedor_sin_adaptador_se_avisa():
    with pytest.raises(ProveedorDesconocido):
        construir(ajustes(proveedor="inventado"), "s", "d", IMAGENES)


def test_el_stub_sin_base_url_no_sabe_a_donde_ir():
    """Es un fallo de configuracion y se dice, en lugar de llamar al proveedor
    real por accidente con una clave de desarrollo."""
    with pytest.raises(ProveedorDesconocido, match="VLM_BASE_URL"):
        construir(ajustes(proveedor="stub", base_url=""), "s", "d", IMAGENES)


# ---------------------------------------------------- sacar el texto del sobre
def test_de_anthropic_se_saca_el_texto_de_los_bloques():
    sobre = {"content": [{"type": "text", "text": '{"a": 1}'}]}
    assert texto_de_la_respuesta(ajustes(), sobre) == '{"a": 1}'


def test_de_anthropic_se_juntan_varios_bloques_de_texto():
    sobre = {"content": [{"type": "text", "text": '{"a":'},
                         {"type": "thinking", "text": "ignorame"},
                         {"type": "text", "text": ' 1}'}]}
    assert texto_de_la_respuesta(ajustes(), sobre) == '{"a": 1}'


def test_de_openai_se_saca_el_contenido_del_mensaje():
    sobre = {"choices": [{"message": {"content": '{"a": 1}'}}]}
    assert texto_de_la_respuesta(ajustes(proveedor="openai"), sobre) == '{"a": 1}'


def test_un_sobre_de_anthropic_sin_contenido_se_rechaza():
    """No es un fallo de red: es una respuesta que no sirve, y se trata como tal
    para que el reintento del criterio 3 la vuelva a pedir."""
    with pytest.raises(ValueError, match="content"):
        texto_de_la_respuesta(ajustes(), {"id": "msg", "content": []})


def test_un_sobre_de_openai_sin_opciones_se_rechaza():
    with pytest.raises(ValueError, match="choices"):
        texto_de_la_respuesta(ajustes(proveedor="openai"), {"choices": []})


def test_un_mensaje_de_openai_sin_contenido_devuelve_vacio():
    sobre = {"choices": [{"message": {}}]}
    assert texto_de_la_respuesta(ajustes(proveedor="openai"), sobre) == ""
