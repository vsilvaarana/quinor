"""La severidad de un evento. RN-04.

La regla esta escrita con umbrales exactos, asi que se prueba con numeros. Esta
es la cifra que decide si suena un SMS a las tres de la madrugada (HU-10) y en
que orden se revisa la cola (HU-11): no puede depender de un modelo.
"""
from __future__ import annotations

import pytest

from app.severidad import (ALTA, BAJA, MEDIA, SACOS_PARA_ALTA, calcular,
                           es_valida, mayor)


# --------------------------------------------------------------- severidad Alta
@pytest.mark.parametrize("diferencia", [-2, -3, -50, 2, 7])
def test_dos_sacos_o_mas_de_diferencia_son_alta(diferencia):
    """La RN-04 no distingue si faltan o sobran: las dos cosas son graves."""
    assert calcular(diferencia_sacos=diferencia).nivel == ALTA


def test_un_saco_que_sale_es_alta_aunque_el_conteo_cuadre():
    """No es un error de conteo: es alguien sacando un saco del camion."""
    resultado = calcular(diferencia_sacos=0, sacos_salientes=1)

    assert resultado.nivel == ALTA
    assert "salieron de la zona de carga" in resultado.motivo


def test_el_saco_saliente_manda_sobre_todo_lo_demas():
    """Aunque la diferencia sea de uno, que por si sola seria Media."""
    assert calcular(diferencia_sacos=-1, sacos_salientes=2).nivel == ALTA


def test_el_umbral_es_el_que_dice_la_regla():
    assert SACOS_PARA_ALTA == 2
    assert calcular(diferencia_sacos=-1).nivel == MEDIA
    assert calcular(diferencia_sacos=-2).nivel == ALTA


# -------------------------------------------------------------- severidad Media
def test_un_saco_de_diferencia_es_media():
    resultado = calcular(diferencia_sacos=-1)

    assert resultado.nivel == MEDIA
    assert "-1" in resultado.motivo


def test_personal_no_habitual_es_media():
    resultado = calcular(diferencia_sacos=0, personal_anomalo=True)

    assert resultado.nivel == MEDIA
    assert "personal" in resultado.motivo


def test_la_diferencia_de_sacos_manda_sobre_el_personal():
    """Con tres sacos de menos y gente de mas, lo grave son los sacos."""
    assert calcular(diferencia_sacos=-3, personal_anomalo=True).nivel == ALTA


# --------------------------------------------------------------- severidad Baja
def test_el_peso_sin_diferencia_de_sacos_es_baja():
    """El caso que motiva el proyecto: los bultos estan y pesan menos. Apunta a
    producto sustituido, que es grave, pero la RN-04 lo clasifica asi."""
    resultado = calcular(diferencia_sacos=0, hay_diferencia_de_peso=True)

    assert resultado.nivel == BAJA
    assert "sustituido" in resultado.motivo


def test_sin_nada_que_explicar_tambien_es_baja():
    resultado = calcular(diferencia_sacos=0, hay_diferencia_de_peso=False)

    assert resultado.nivel == BAJA
    assert "ninguna diferencia" in resultado.motivo


def test_un_clip_sin_analizar_no_inventa_gravedad():
    """`None` no es cero: significa que no se pudo mirar el video. Se sabe que el
    peso no cuadra y nada mas, que es exactamente la definicion de Baja. Subirlo
    a Alta por las dudas llenaria el turno de noche de SMS."""
    resultado = calcular(diferencia_sacos=None, hay_diferencia_de_peso=True)

    assert resultado.nivel == BAJA


# ------------------------------------------------------------- poder explicarla
def test_cada_severidad_viene_con_su_motivo():
    """"Alta porque la diferencia fue de 3 sacos" se puede comprobar; "Alta
    porque el modelo lo dijo" no."""
    for resultado in (calcular(-3), calcular(-1), calcular(0),
                      calcular(0, sacos_salientes=1),
                      calcular(0, personal_anomalo=True)):
        assert resultado.motivo
        assert resultado.regla == "RN-04"


# ----------------------------------------------------------------- comparaciones
def test_se_comparan_por_gravedad_y_no_por_orden_alfabetico():
    """Alfabeticamente seria alta < baja < media, que es justo al reves."""
    assert mayor(ALTA, BAJA) == ALTA
    assert mayor(BAJA, MEDIA) == MEDIA
    assert mayor(MEDIA, ALTA) == ALTA
    assert mayor(MEDIA, MEDIA) == MEDIA


def test_una_severidad_ausente_es_la_menos_grave():
    assert mayor(None, MEDIA) == MEDIA
    assert mayor(ALTA, None) == ALTA
    assert mayor(None, None) is None


@pytest.mark.parametrize("nivel,valida", [
    (ALTA, True), (MEDIA, True), (BAJA, True),
    ("critica", False), ("urgente", False), ("", False), (None, False),
])
def test_solo_valen_las_tres_de_la_regla(nivel, valida):
    """"Critica" o "urgente" no son ninguna de las tres, y adivinar cual quiso
    decir seria inventarse la severidad de un evento."""
    assert es_valida(nivel) is valida
