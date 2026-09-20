"""Presencia anomala de personal. HU-08 y RN-03.

Estas reglas son la senal que la RN-03 usa para decidir si HU-09 llama al modelo
de vision-lenguaje, y la que la RN-04 traduce a severidad Media. Cada prueba
comprueba ademas lo que la regla NO mira, porque la RN-08 prohibe identificar a
nadie y una regla que se apoyara en identidad pasaria desapercibida entre las
que si son legitimas.
"""
from __future__ import annotations

import dataclasses

import pytest

from app import anomalias
from app.anomalias import (DEMASIADA_GENTE, PERMANENCIA_LARGA, SIN_CARGA,
                           evaluar)
from app.config import Ajustes
from app.personas import PersonaObservada, Resumen


def ajustes(**cambios) -> Ajustes:
    base = Ajustes(personas_habituales=3, permanencia_maxima_s=600.0)
    return dataclasses.replace(base, **cambios) if cambios else base


def resumen(cuantas: int = 1, maximo: int = 1, mayor_s: float = 60.0) -> Resumen:
    personas = tuple(
        PersonaObservada(id_temporal=i + 1,
                         segundos_en_zona=mayor_s if i == 0 else 30.0,
                         primer_fotograma=0, ultimo_fotograma=100)
        for i in range(cuantas))
    return Resumen(personas=personas, maximo_simultaneo=maximo,
                   segundos_totales=sum(p.segundos_en_zona for p in personas),
                   zona_completa=False)


# ------------------------------------------------------- una carga normal
def test_una_carga_normal_no_dispara_nada():
    """Tres operarios cargando un camion es una carga, no un incidente. Si esto
    fallara, HU-09 llamaria al modelo de vision-lenguaje en cada despacho y la
    RN-03 existe justo para evitar ese costo."""
    resultado = evaluar(ajustes(), resumen(cuantas=3, maximo=3, mayor_s=120.0), 400)

    assert resultado.hay is False
    assert resultado.motivos == ()


def test_una_rampa_vacia_con_carga_normal_tampoco():
    vacia = Resumen(personas=(), maximo_simultaneo=0, segundos_totales=0.0,
                    zona_completa=False)
    assert evaluar(ajustes(), vacia, 400).hay is False


# ----------------------------------------------------- demasiada gente a la vez
def test_mas_personas_de_las_habituales_llama_la_atencion():
    resultado = evaluar(ajustes(personas_habituales=3),
                        resumen(cuantas=5, maximo=5), 400)

    assert resultado.hay is True
    assert DEMASIADA_GENTE in resultado.codigos
    motivo = resultado.motivos[0]
    assert motivo.medido == 5.0 and motivo.umbral == 3.0


def test_justo_en_el_umbral_todavia_es_normal():
    assert evaluar(ajustes(personas_habituales=3),
                   resumen(cuantas=3, maximo=3), 400).hay is False


def test_lo_que_cuenta_es_cuantas_a_la_vez_y_no_cuantas_en_total():
    """Cinco personas que se turnan durante la carga son un turno; cinco a la vez
    en la rampa son otra cosa."""
    por_turnos = resumen(cuantas=5, maximo=2)
    assert evaluar(ajustes(personas_habituales=3), por_turnos, 400).hay is False


def test_el_umbral_es_configurable():
    """Lo habitual en una rampa lo sabe QUINOR, no este codigo."""
    apretado = ajustes(personas_habituales=1)
    assert evaluar(apretado, resumen(cuantas=2, maximo=2), 400).hay is True


# ----------------------------------------------------------- permanencia larga
def test_quedarse_mucho_mas_que_una_carga_llama_la_atencion():
    resultado = evaluar(ajustes(permanencia_maxima_s=600.0),
                        resumen(mayor_s=900.0), 400)

    assert PERMANENCIA_LARGA in resultado.codigos
    assert resultado.motivos[0].medido == 900.0


def test_justo_en_el_umbral_de_tiempo_todavia_es_normal():
    assert evaluar(ajustes(permanencia_maxima_s=600.0),
                   resumen(mayor_s=600.0), 400).hay is False


def test_se_mira_la_mas_larga_y_no_la_suma():
    """Cuatro operarios de diez minutos cada uno suman cuarenta, y eso es una
    carga normal de cuatro personas, no alguien que se quedo de mas."""
    normal = Resumen(
        personas=tuple(PersonaObservada(i, 500.0, 0, 100) for i in range(1, 5)),
        maximo_simultaneo=3, segundos_totales=2000.0, zona_completa=False)
    assert evaluar(ajustes(permanencia_maxima_s=600.0), normal, 400).hay is False


# ------------------------------------------------- gente sin movimiento de sacos
def test_gente_en_rampa_y_ningun_saco_cruzando():
    """Puede ser una limpieza o una revision, y puede ser lo otro. En los dos
    casos merece que alguien mire el clip antes de archivar la carga."""
    resultado = evaluar(ajustes(), resumen(cuantas=2, maximo=2), sacos_contados=0)

    assert SIN_CARGA in resultado.codigos


def test_sin_gente_y_sin_sacos_no_hay_nada_que_mirar():
    """Un camion que no se cargo y una rampa vacia son coherentes entre si."""
    vacia = Resumen(personas=(), maximo_simultaneo=0, segundos_totales=0.0,
                    zona_completa=True)
    assert evaluar(ajustes(), vacia, 0).hay is False


def test_con_sacos_cruzando_la_presencia_es_lo_esperado():
    assert SIN_CARGA not in evaluar(ajustes(), resumen(cuantas=2, maximo=2), 5).codigos


# --------------------------------------------------------- varios a la vez
def test_se_informan_todos_los_motivos_y_no_solo_el_primero():
    """El supervisor decide con lo que ve; quedarse con el primero le escondaria
    la mitad del caso."""
    resultado = evaluar(ajustes(personas_habituales=2, permanencia_maxima_s=100.0),
                        resumen(cuantas=5, maximo=5, mayor_s=900.0),
                        sacos_contados=0)

    assert set(resultado.codigos) == {DEMASIADA_GENTE, PERMANENCIA_LARGA, SIN_CARGA}


def test_cada_motivo_lleva_el_numero_que_lo_sostiene():
    """Un aviso sin cifra obliga a creerselo; con la cifra se puede discutir."""
    resultado = evaluar(ajustes(personas_habituales=2),
                        resumen(cuantas=4, maximo=4), 400)

    for motivo in resultado.motivos:
        assert motivo.medido > motivo.umbral or motivo.umbral == 0.0
        assert motivo.detalle and motivo.codigo


def test_el_codigo_es_estable_y_la_frase_es_para_leer():
    """Buscar "cuantas cargas tuvieron demasiada gente" no puede depender de como
    estaba redactado el mensaje aquel mes."""
    resultado = evaluar(ajustes(personas_habituales=1),
                        resumen(cuantas=2, maximo=2), 400)
    assert resultado.codigos == (DEMASIADA_GENTE,)
    assert "personas a la vez" in resultado.motivos[0].detalle


# ------------------------------------------ criterio 3: nada de esto es identidad
def test_ninguna_regla_mira_quien_es_nadie():
    """Las tres reglas se calculan con cuantos, cuanto tiempo y si hubo carga.
    Si alguien anadiera una que dependiera de la identidad, tendria que anadir
    tambien un campo aqui, y esta prueba lo diria."""
    campos = {c.name for c in dataclasses.fields(Resumen)}
    assert campos == {"personas", "maximo_simultaneo", "segundos_totales",
                      "zona_completa"}


def test_los_motivos_no_nombran_a_nadie():
    resultado = evaluar(ajustes(personas_habituales=1, permanencia_maxima_s=10.0),
                        resumen(cuantas=3, maximo=3, mayor_s=900.0), 0)

    for motivo in resultado.motivos:
        texto = motivo.detalle.lower()
        assert "id" not in texto.split()
        assert "persona(s)" in texto or "personas" in texto or "alguien" in texto


@pytest.mark.parametrize("codigo", [DEMASIADA_GENTE, PERMANENCIA_LARGA, SIN_CARGA])
def test_los_codigos_describen_comportamiento_y_no_personas(codigo):
    assert "identidad" not in codigo and "rostro" not in codigo
    assert codigo in {anomalias.DEMASIADA_GENTE, anomalias.PERMANENCIA_LARGA,
                      anomalias.SIN_CARGA}
