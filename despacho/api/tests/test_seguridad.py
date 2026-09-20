"""Tests unitarios de contrasenas y tokens. HU-15, criterios 3 y 4."""

import hashlib

import pytest

from app import seguridad


# ---------- Criterio 3: contrasenas con bcrypt ----------

def test_el_hash_es_bcrypt():
    hash_guardado = seguridad.hash_password("clave-de-prueba")
    assert hash_guardado.startswith("$2b$")
    assert len(hash_guardado) == 60


def test_dos_hashes_de_la_misma_clave_son_distintos():
    """Cada hash lleva su propia sal: dos cuentas con la misma clave no se delatan."""
    uno = seguridad.hash_password("misma-clave")
    otro = seguridad.hash_password("misma-clave")
    assert uno != otro
    assert seguridad.verificar_password("misma-clave", uno)
    assert seguridad.verificar_password("misma-clave", otro)


def test_la_clave_no_aparece_en_el_hash():
    assert "clave-secreta" not in seguridad.hash_password("clave-secreta")


@pytest.mark.parametrize("intento", ["otra-clave", "", "clave-de-prueb", "CLAVE-DE-PRUEBA"])
def test_una_clave_incorrecta_no_verifica(intento):
    hash_guardado = seguridad.hash_password("clave-de-prueba")
    assert seguridad.verificar_password(intento, hash_guardado) is False


def test_un_hash_corrupto_no_revienta():
    """Un dato danado en base es un fallo de acceso, no una caida del servicio."""
    assert seguridad.verificar_password("cualquiera", "esto-no-es-un-hash") is False
    assert seguridad.verificar_password("cualquiera", "") is False


def test_una_clave_de_mas_de_72_bytes_se_rechaza():
    """bcrypt no mira mas alla: aceptarla haria creer que la cola cuenta."""
    with pytest.raises(seguridad.ClaveDemasiadoLarga):
        seguridad.hash_password("x" * 73)


def test_el_limite_se_mide_en_bytes_y_no_en_caracteres():
    """Una enye ocupa dos bytes en UTF-8. 40 de ellas ya pasan de 72."""
    with pytest.raises(seguridad.ClaveDemasiadoLarga):
        seguridad.hash_password("ñ" * 40)
    seguridad.hash_password("ñ" * 30)       # 60 bytes, cabe


# ---------- Criterio 4: token opaco ----------

def test_el_token_tiene_entropia_suficiente():
    claro, _ = seguridad.generar_token()
    assert len(claro) >= 43          # 32 bytes en base64 url-safe


def test_dos_tokens_nunca_coinciden():
    tokens = {seguridad.generar_token()[0] for _ in range(200)}
    assert len(tokens) == 200


def test_lo_que_se_guarda_es_el_sha256_del_token():
    """Quien lea la tabla api_token no puede usar ningun token."""
    claro, guardado = seguridad.generar_token()
    assert guardado == hashlib.sha256(claro.encode()).hexdigest()
    assert len(guardado) == 64
    assert claro not in guardado


def test_el_hash_del_token_es_estable():
    """Tiene que serlo: es como se busca la fila en cada peticion."""
    claro, guardado = seguridad.generar_token()
    assert seguridad.hash_token(claro) == guardado
    assert seguridad.hash_token(claro) == seguridad.hash_token(claro)


def test_un_token_distinto_da_otro_hash():
    claro, guardado = seguridad.generar_token()
    assert seguridad.hash_token(claro + "x") != guardado


def test_el_token_no_usa_bcrypt():
    """Lo genera el sistema con 256 bits: no hay diccionario que lo alcance, y en
    cambio se verifica en cada peticion, donde bcrypt seria un lastre."""
    _, guardado = seguridad.generar_token()
    assert not guardado.startswith("$2b$")
