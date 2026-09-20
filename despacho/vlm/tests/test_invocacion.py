"""Cuando se llama al modelo. HU-09 criterio 1, y RN-03.

"Solo se invoca cuando YOLO confirma diferencia de sacos o presencia anomala de
personal, para controlar el costo."
"""
from __future__ import annotations

import pytest

from app.invocacion import (DIFERENCIA_DE_SACOS, NADA_QUE_EXPLICAR,
                            PERSONAL_ANOMALO, SACOS_SALIENTES,
                            SIN_ANALISIS_DE_VIDEO, decidir)


# --------------------------------------------------------- cuando si se invoca
@pytest.mark.parametrize("diferencia", [-1, -5, 1, 3])
def test_una_diferencia_de_sacos_lo_justifica(diferencia):
    decision = decidir(diferencia_sacos=diferencia)

    assert decision.invocar is True
    assert DIFERENCIA_DE_SACOS in decision.motivos


def test_un_saco_que_sale_lo_justifica_aunque_el_conteo_cuadre():
    decision = decidir(diferencia_sacos=0, sacos_salientes=1)

    assert decision.invocar is True
    assert decision.codigo == SACOS_SALIENTES


def test_el_personal_anomalo_lo_justifica_por_si_solo():
    """Es la otra mitad de la RN-03, y lo que HU-08 dejo preparado."""
    decision = decidir(diferencia_sacos=0, personal_anomalo=True)

    assert decision.invocar is True
    assert PERSONAL_ANOMALO in decision.motivos


def test_se_informan_todos_los_motivos():
    decision = decidir(diferencia_sacos=-3, sacos_salientes=2,
                       personal_anomalo=True)

    assert set(decision.motivos) == {SACOS_SALIENTES, DIFERENCIA_DE_SACOS,
                                     PERSONAL_ANOMALO}


def test_manda_el_saco_que_sale_sobre_los_demas_motivos():
    """El codigo es el primero, y el primero tiene que ser el mas grave."""
    assert decidir(-1, sacos_salientes=1, personal_anomalo=True).codigo == SACOS_SALIENTES


# --------------------------------------------------------- cuando no se invoca
def test_una_carga_que_cuadra_no_llama_al_modelo():
    """La mayoria de los eventos de peso son ajustes de bascula o humedad, no
    hurtos. Llamar en todos seria pagar por describir cargas normales."""
    decision = decidir(diferencia_sacos=0, sacos_salientes=0,
                       personal_anomalo=False)

    assert decision.invocar is False
    assert decision.codigo == NADA_QUE_EXPLICAR
    assert "controlar el costo" in decision.explicacion


def test_sin_analisis_de_video_se_espera_en_lugar_de_llamar_a_ciegas():
    """`None` significa que el clip aun no se analizo. La RN-03 pide que YOLO
    confirme, y sin conteo no hay nada confirmado."""
    decision = decidir(diferencia_sacos=None, personal_anomalo=None)

    assert decision.invocar is False
    assert decision.codigo == SIN_ANALISIS_DE_VIDEO
    assert "RN-03" in decision.explicacion


def test_con_conteo_pero_sin_dato_de_personal_se_decide_igual():
    """El grabador puede escribir el conteo y no el personal si el servicio YOLO
    es de una version anterior. Con el conteo ya hay con que decidir."""
    assert decidir(diferencia_sacos=-2, personal_anomalo=None).invocar is True
    assert decidir(diferencia_sacos=0, personal_anomalo=None).invocar is False


# ------------------------------------------------------------- la explicacion
def test_cuando_no_se_invoca_se_dice_por_que():
    """Un evento sin analisis y sin explicacion parece un fallo del sistema, y
    alguien acabara reintentandolo a mano."""
    for decision in (decidir(0, 0, False), decidir(None, 0, None)):
        assert decision.invocar is False
        assert decision.explicacion


def test_cuando_si_se_invoca_la_explicacion_trae_las_cifras():
    decision = decidir(diferencia_sacos=-3, sacos_salientes=2)

    assert "2 saco(s) salieron" in decision.explicacion
    assert "-3" in decision.explicacion


def test_sin_motivos_no_hay_codigo_de_invocacion():
    assert decidir(0, 0, False).codigo == NADA_QUE_EXPLICAR
