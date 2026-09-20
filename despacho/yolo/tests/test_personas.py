"""Seguimiento de personas en la zona de carga. HU-08, criterios 1, 2 y 3.

Sin YOLO y sin video: el seguidor recibe posiciones con identificador y decide.
Lo que se prueba aqui es la regla, que es lo nuestro.

El criterio 3 tambien se prueba, y no solo se afirma: hay pruebas de que lo que
sale del modulo no contiene nada que permita reconocer a nadie.
"""
from __future__ import annotations

import dataclasses

import pytest

from app.conteo import Deteccion, Punto
from app.personas import (Presencia, PersonaObservada, Resumen,
                          SeguidorDePersonas, Zona)

CUADRO = Zona(0.0, 0.0, 1.0, 1.0)
# Media rampa: la zona tipica una vez calibrada en el piloto.
MEDIA_RAMPA = Zona(0.4, 0.0, 1.0, 1.0)
FPS = 10.0


def persona(identificador: int, x: float = 0.5, y: float = 0.5) -> Deteccion:
    return Deteccion(id_seguimiento=identificador, clase="person",
                     confianza=0.9, centro=Punto(x=x, y=y))


def saco(identificador: int, x: float = 0.5) -> Deteccion:
    return Deteccion(id_seguimiento=identificador, clase="saco",
                     confianza=0.9, centro=Punto(x=x, y=0.5))


def estar(seguidor: SeguidorDePersonas, identificador: int, fotogramas: int,
          x: float = 0.5, desde: int = 0) -> int:
    """Deja a una persona en el cuadro tantos fotogramas seguidos."""
    for paso in range(fotogramas):
        seguidor.procesar(desde + paso, [persona(identificador, x=x)])
    return desde + fotogramas


# --------------------------------------------------------------- la zona
def test_la_zona_por_defecto_es_el_cuadro_entero():
    """Elegir una zona mas estrecha a ciegas dejaria fuera a gente que si estuvo
    en la rampa. La calibra el piloto, como la linea."""
    assert CUADRO.es_todo_el_cuadro is True
    assert CUADRO.contiene(Punto(x=0.01, y=0.99)) is True


@pytest.mark.parametrize("x,dentro", [(0.2, False), (0.5, True), (0.99, True)])
def test_una_zona_calibrada_deja_fuera_el_resto_del_cuadro(x, dentro):
    assert MEDIA_RAMPA.contiene(Punto(x=x, y=0.5)) is dentro


def test_los_bordes_de_la_zona_cuentan_como_dentro():
    """Alguien justo en el borde de la rampa esta en la rampa."""
    assert MEDIA_RAMPA.contiene(Punto(x=0.4, y=0.0)) is True
    assert MEDIA_RAMPA.contiene(Punto(x=1.0, y=1.0)) is True


def test_la_zona_se_construye_desde_los_ajustes():
    assert Zona.desde((0.1, 0.2, 0.8, 0.9)) == Zona(0.1, 0.2, 0.8, 0.9)


# ------------------------------------------------- criterio 1: seguir a cada una
def test_cada_persona_tiene_su_identificador_durante_el_clip():
    seguidor = SeguidorDePersonas(CUADRO)
    ultimo = estar(seguidor, 1, 20)
    estar(seguidor, 2, 20, desde=ultimo)

    resumen = seguidor.resumen(FPS)

    assert resumen.cuantas == 2
    assert sorted(p.id_temporal for p in resumen.personas) == [1, 2]


def test_la_misma_persona_en_muchos_fotogramas_es_una_persona():
    """Es la diferencia entre seguir y contar fotogramas."""
    seguidor = SeguidorDePersonas(CUADRO)
    estar(seguidor, 7, 50)
    assert seguidor.resumen(FPS).cuantas == 1


def test_los_sacos_no_son_personas():
    seguidor = SeguidorDePersonas(CUADRO)
    for fotograma in range(30):
        seguidor.procesar(fotograma, [saco(1), saco(2)])
    assert seguidor.resumen(FPS).cuantas == 0


def test_quien_pasa_por_el_fondo_no_estuvo_en_la_rampa():
    """Con la zona calibrada, el operario de la nave de al lado deja de ser un
    dato: contarlo convertiria el registro en ruido justo cuando hay que decidir
    si bajar a mirar."""
    seguidor = SeguidorDePersonas(MEDIA_RAMPA)
    estar(seguidor, 1, 30, x=0.1)          # fuera de la zona
    estar(seguidor, 2, 30, x=0.7, desde=30)  # dentro

    resumen = seguidor.resumen(FPS)

    assert resumen.cuantas == 1
    assert resumen.personas[0].id_temporal == 2


# --------------------------------------- criterio 2: cuantas y cuanto tiempo
def test_se_registra_el_tiempo_de_permanencia():
    seguidor = SeguidorDePersonas(CUADRO)
    estar(seguidor, 1, 45)      # 45 fotogramas a 10 fps son 4.5 s

    assert seguidor.resumen(FPS).personas[0].segundos_en_zona == pytest.approx(4.5)


def test_la_permanencia_cuenta_el_tiempo_en_zona_y_no_el_transcurrido():
    """Alguien que entra, se va y vuelve no estuvo todo ese rato en la rampa."""
    seguidor = SeguidorDePersonas(MEDIA_RAMPA)
    estar(seguidor, 1, 20, x=0.7)                 # 2 s dentro
    estar(seguidor, 1, 200, x=0.1, desde=20)      # 20 s fuera
    estar(seguidor, 1, 20, x=0.7, desde=220)      # 2 s dentro

    persona_vista = seguidor.resumen(FPS).personas[0]

    assert persona_vista.segundos_en_zona == pytest.approx(4.0)
    # Los fotogramas si abarcan todo el tramo: es lo que HU-12 usara para saltar
    # al momento del clip.
    assert persona_vista.primer_fotograma == 0
    assert persona_vista.ultimo_fotograma == 239


def test_se_registra_cuantas_estuvieron_y_el_total():
    seguidor = SeguidorDePersonas(CUADRO)
    ultimo = estar(seguidor, 1, 30)
    estar(seguidor, 2, 20, desde=ultimo)

    resumen = seguidor.resumen(FPS)

    assert resumen.cuantas == 2
    assert resumen.segundos_totales == pytest.approx(5.0)
    assert resumen.permanencia_maxima_s == pytest.approx(3.0)
    assert resumen.permanencia_media_s == pytest.approx(2.5)


def test_el_maximo_simultaneo_no_es_lo_mismo_que_el_total():
    """Cuatro personas que se turnan no son lo mismo que cuatro a la vez, y la
    segunda es la que llama la atencion."""
    seguidor = SeguidorDePersonas(CUADRO)
    for fotograma in range(20):
        seguidor.procesar(fotograma, [persona(1), persona(2), persona(3)])
    for fotograma in range(20, 40):
        seguidor.procesar(fotograma, [persona(4)])

    resumen = seguidor.resumen(FPS)

    assert resumen.cuantas == 4
    assert resumen.maximo_simultaneo == 3


def test_un_parpadeo_del_detector_no_es_una_persona():
    """Sin el minimo, una deteccion suelta inflaria el conteo de la carga."""
    seguidor = SeguidorDePersonas(CUADRO, permanencia_minima_s=1.0)
    estar(seguidor, 1, 3)          # 0.3 s
    estar(seguidor, 2, 30, desde=10)

    resumen = seguidor.resumen(FPS)

    assert resumen.cuantas == 1
    assert resumen.personas[0].id_temporal == 2


def test_el_minimo_se_puede_bajar_a_cero():
    seguidor = SeguidorDePersonas(CUADRO, permanencia_minima_s=0.0)
    estar(seguidor, 1, 1)
    assert seguidor.resumen(FPS).cuantas == 1


def test_la_permanencia_se_mide_en_segundos_de_reloj_y_no_de_inferencia():
    """Con salto 2 se mira un fotograma de cada dos, y cada uno vale por dos de
    reloj. Sin corregirlo, toda permanencia saldria a la mitad y una carga larga
    pareceria corta."""
    seguidor = SeguidorDePersonas(CUADRO)
    for paso in range(30):
        seguidor.procesar(paso * 2, [persona(1)])

    assert seguidor.resumen(FPS, salto=2).personas[0].segundos_en_zona == pytest.approx(6.0)


def test_un_clip_sin_fps_no_divide_por_cero():
    seguidor = SeguidorDePersonas(CUADRO, permanencia_minima_s=0.0)
    estar(seguidor, 1, 10)
    assert seguidor.resumen(0.0).personas[0].segundos_en_zona == 0.0


def test_una_rampa_vacia_no_inventa_a_nadie():
    seguidor = SeguidorDePersonas(CUADRO)
    for fotograma in range(30):
        seguidor.procesar(fotograma, [])

    resumen = seguidor.resumen(FPS)

    assert resumen.cuantas == 0
    assert resumen.maximo_simultaneo == 0
    assert resumen.permanencia_maxima_s == 0.0
    assert resumen.permanencia_media_s == 0.0


def test_las_personas_salen_en_el_orden_en_que_aparecieron():
    """Para que el detalle de HU-12 se lea como se vio el clip."""
    seguidor = SeguidorDePersonas(CUADRO)
    ultimo = estar(seguidor, 9, 20)
    ultimo = estar(seguidor, 3, 20, desde=ultimo)
    estar(seguidor, 5, 20, desde=ultimo)

    assert [p.id_temporal for p in seguidor.resumen(FPS).personas] == [9, 3, 5]


def test_se_dice_si_la_zona_no_estaba_calibrada():
    """Con el cuadro entero, "en zona" incluye a quien solo pasaba por el fondo.
    Quien lea el dato tiene que poder saberlo."""
    assert SeguidorDePersonas(CUADRO).resumen(FPS).zona_completa is True
    assert SeguidorDePersonas(MEDIA_RAMPA).resumen(FPS).zona_completa is False


# ------------------------- criterio 3: ni identificacion facial ni biometria
def test_de_una_persona_solo_se_guardan_un_numero_y_unos_segundos():
    """La RN-08 no se cumple por omision: se cumple porque no hay nada mas que
    guardar. Si alguien anadiera un recorte de imagen o un descriptor, esta
    prueba lo diria."""
    campos = {c.name for c in dataclasses.fields(PersonaObservada)}
    assert campos == {"id_temporal", "segundos_en_zona",
                      "primer_fotograma", "ultimo_fotograma"}


def test_lo_que_entra_al_seguidor_tampoco_lleva_imagen():
    """El modulo no recibe fotogramas: recibe posiciones. No hay de donde sacar
    un rostro aunque alguien quisiera."""
    campos = {c.name for c in dataclasses.fields(Deteccion)}
    assert campos == {"id_seguimiento", "clase", "confianza", "centro"}


def test_el_identificador_no_sobrevive_al_clip():
    """Dos clips distintos son dos seguidores distintos, y el numero 1 de uno no
    tiene nada que ver con el 1 del otro. Es lo que hace que el identificador sea
    temporal y no una identidad."""
    primero = SeguidorDePersonas(CUADRO)
    estar(primero, 1, 30)
    segundo = SeguidorDePersonas(CUADRO)
    estar(segundo, 1, 30)

    assert primero.presencias.keys() == segundo.presencias.keys()
    assert primero is not segundo
    assert primero.presencias[1] is not segundo.presencias[1]


def test_una_persona_que_sale_y_vuelve_con_otro_id_se_cuenta_dos_veces():
    """El precio de no identificar a nadie, y el lado correcto en el que
    equivocarse: el sistema prefiere contar de mas a reconocer a alguien."""
    seguidor = SeguidorDePersonas(CUADRO)
    ultimo = estar(seguidor, 1, 30)
    estar(seguidor, 2, 30, desde=ultimo)     # la misma persona, otro numero

    assert seguidor.resumen(FPS).cuantas == 2


def test_el_resumen_es_serializable_sin_perder_nada():
    """Viaja por HTTP y acaba en la base: si llevara un objeto raro, se veria
    aqui antes que en planta."""
    seguidor = SeguidorDePersonas(CUADRO)
    estar(seguidor, 1, 30)

    como_dict = dataclasses.asdict(seguidor.resumen(FPS))

    assert set(como_dict) == {"personas", "maximo_simultaneo",
                              "segundos_totales", "zona_completa"}
    assert all(isinstance(v, (int, float, str)) for v in como_dict["personas"][0].values())
