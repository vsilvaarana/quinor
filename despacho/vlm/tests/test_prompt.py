"""El prompt. Apartado 9.2.

El apartado manda revisar el prompt cuando la concordancia con el supervisor baje
del 85 %. Estas pruebas fijan lo que no puede desaparecer en esa revision: el
contexto de planta, la prohibicion de identificar a nadie y la instruccion de
llamar normal a lo normal.
"""
from __future__ import annotations

import pytest

from app.config import Ajustes
from app.prompt import ESQUEMA, datos_del_evento, pie_de_imagen, sistema


@pytest.fixture()
def ajustes() -> Ajustes:
    return Ajustes(producto="quinua en sacos de 50 kg", sacos_por_camion=400,
                   duracion_tipica_min=45, personas_habituales=3)


# ------------------------------------------------------- el contexto de planta
def test_el_prompt_describe_como_es_una_carga_normal(ajustes):
    """Un modelo que no sabe como es una carga normal no puede decir que algo no
    lo fue: describiria un camion y unos sacos."""
    texto = sistema(ajustes)

    assert "400" in texto
    assert "45" in texto
    assert "quinua en sacos de 50 kg" in texto


def test_el_contexto_sale_de_los_ajustes_y_no_esta_escrito_a_mano(ajustes):
    import dataclasses

    otro = dataclasses.replace(ajustes, sacos_por_camion=500,
                               duracion_tipica_min=90)
    texto = sistema(otro)

    assert "500" in texto and "90" in texto


def test_el_prompt_lleva_los_criterios_de_severidad(ajustes):
    """Apartado 9.2: "criterios explicitos de severidad". Sin ellos, el modelo
    inventa su propia escala y la concordancia no significa nada."""
    texto = sistema(ajustes)

    assert "RN-04" in texto
    assert "alta" in texto and "media" in texto and "baja" in texto
    assert "2 sacos o mas" in texto


def test_el_prompt_explica_que_un_saco_que_sale_no_es_normal(ajustes):
    assert "no es parte del proceso" in sistema(ajustes)


def test_el_prompt_avisa_de_que_las_oclusiones_son_normales(ajustes):
    """Si no, describiria como sospechoso que alguien tape la camara al pasar,
    que es lo que hacen los operarios todo el dia."""
    assert "tapen sacos es normal" in sistema(ajustes)


# ------------------------------------------------- lo que el prompt prohibe
def test_se_le_prohibe_describir_a_las_personas(ajustes):
    """RN-08 y Ley 29733. El modelo recibe imagenes con personas: hay que
    decirselo explicitamente, porque por defecto las describiria."""
    texto = sistema(ajustes)

    assert "Ley 29733" in texto
    assert "rostro" in texto
    assert "un operario" in texto


def test_se_le_pide_que_no_acuse_a_nadie(ajustes):
    assert "No acuses a nadie" in sistema(ajustes)


def test_se_le_pide_llamar_normal_a_lo_normal(ajustes):
    """Un modelo que siempre encuentra algo sospechoso manda a alguien a la
    rampa cada dia hasta que dejan de hacerle caso."""
    texto = sistema(ajustes)

    assert "se describe como normal" in texto
    assert "deja de leerse" in texto


def test_se_le_pide_decir_cuando_los_datos_no_concuerdan(ajustes):
    assert "en lugar de inventar" in sistema(ajustes)


# --------------------------------------------------------------- el contrato
def test_el_prompt_pide_el_json_del_criterio_2(ajustes):
    texto = sistema(ajustes)

    assert ESQUEMA in texto
    assert "descripcion" in ESQUEMA
    assert "severidad" in ESQUEMA
    assert "evidencia" in ESQUEMA


def test_se_le_pide_json_sin_bloques_de_codigo(ajustes):
    """Se pide, y ademas se perdona si lo manda igual: las dos cosas."""
    seguido = " ".join(sistema(ajustes).split())
    assert "sin bloques de codigo" in seguido


def test_se_le_pide_no_rellenar_la_evidencia(ajustes):
    """Una evidencia inventada es peor que ninguna."""
    assert "en lugar de rellenarla" in sistema(ajustes)


# ------------------------------------------------- los datos estructurados
def test_los_datos_llevan_los_pesos_y_el_conteo():
    """Apartado 9.2: ademas de las imagenes se envian peso esperado, peso real,
    sacos contados y personas detectadas."""
    texto = datos_del_evento({
        "numero_orden": "ORD-1", "peso_esperado_kg": 20000.0,
        "peso_real_kg": 19850.0, "diferencia_kg": -150.0,
        "sacos_contados": 397, "sacos_esperados": 400, "diferencia_sacos": -3,
        "personas_detectadas": 4, "maximo_simultaneo": 4})

    assert "ORD-1" in texto
    assert "20000.0" in texto and "19850.0" in texto
    assert "397 de 400" in texto
    assert "Personas en la zona de carga: 4" in texto


def test_un_clip_sin_analizar_se_dice_y_no_se_finge_un_cero():
    """Cero sacos contados y "no se pudo analizar" son cosas muy distintas, y el
    modelo tiene que poder distinguirlas."""
    texto = datos_del_evento({"sacos_contados": None})

    assert "no se pudo analizar el video" in texto
    assert "0 de" not in texto


def test_los_sacos_salientes_se_destacan():
    texto = datos_del_evento({"sacos_contados": 400, "sacos_salientes": 2})
    assert "SALIERON de la zona de carga: 2" in texto


def test_sin_sacos_salientes_no_se_menciona():
    texto = datos_del_evento({"sacos_contados": 400, "sacos_salientes": 0})
    assert "SALIERON" not in texto


def test_los_motivos_de_anomalia_llegan_al_modelo():
    texto = datos_del_evento({
        "sacos_contados": 400,
        "motivos_de_anomalia": ["demasiadas_personas_a_la_vez"]})

    assert "demasiadas_personas_a_la_vez" in texto


def test_un_evento_sin_datos_no_revienta():
    """Puede llegar asi si YOLO no llego a analizar el clip."""
    texto = datos_del_evento({})

    assert "desconocida" in texto
    assert "no se pudo analizar" in texto


def test_se_le_dice_que_las_imagenes_vienen_con_su_motivo():
    assert "el motivo por el que se guardo" in datos_del_evento({})


# --------------------------------------------------------- el pie de imagen
def test_el_pie_situa_el_fotograma_en_el_clip():
    """Un fotograma suelto sin contexto no dice si ese saco iba o venia."""
    pie = pie_de_imagen({"segundo": 42.0, "motivo": "saco_saliente",
                         "detalle": "Un saco cruza hacia fuera."})

    assert "segundo 42" in pie
    assert "saco_saliente" in pie
    assert "Un saco cruza hacia fuera." in pie


def test_un_pie_sin_datos_sigue_siendo_legible():
    assert "sin motivo" in pie_de_imagen({})
