"""Eleccion de los fotogramas clave. HU-09, y el criterio 3 de HU-12.

Sin video: el selector recibe indices, imagenes y lo que paso en cada fotograma,
y decide. Las imagenes son cadenas, porque lo que se prueba es la regla de
seleccion y no la codificacion en JPEG, que la hace cv2.
"""
from __future__ import annotations

import pytest

from app.conteo import Cruce
from app.fotogramas import (CENTRO_DEL_CLIP, PICO_DE_PERSONAS, PRIMER_SACO,
                            SACO_SALIENTE, ULTIMO_SACO, Momento,
                            SelectorDeFotogramas, momentos_del_fotograma)


def falso(imagen, calidad=80) -> bytes:
    """Codificador de mentira: devuelve la imagen tal cual para poder mirarla."""
    return str(imagen).encode()


def entrante(identificador: int, fotograma: int) -> Cruce:
    return Cruce(id_seguimiento=identificador, fotograma=fotograma, sentido=1)


def saliente(identificador: int, fotograma: int) -> Cruce:
    return Cruce(id_seguimiento=identificador, fotograma=fotograma, sentido=-1)


# ------------------------------------------------ que se considera un momento
def test_un_saco_que_sale_es_lo_primero_que_hay_que_ver():
    """Es lo unico de la lista que por si solo ya es severidad Alta (RN-04)."""
    momentos = momentos_del_fotograma([saliente(1, 40)], personas_en_zona=0,
                                      pico_previo=0, es_primer_cruce=False)

    assert [m.motivo for m in momentos] == [SACO_SALIENTE]
    assert "RN-04" in momentos[0].detalle


def test_el_primer_cruce_se_marca_una_sola_vez():
    primero = momentos_del_fotograma([entrante(1, 10)], 0, 0, es_primer_cruce=True)
    siguiente = momentos_del_fotograma([entrante(2, 30)], 0, 0, es_primer_cruce=False)

    assert PRIMER_SACO in [m.motivo for m in primero]
    assert PRIMER_SACO not in [m.motivo for m in siguiente]


def test_cada_cruce_entrante_opta_a_ser_el_ultimo():
    momentos = momentos_del_fotograma([entrante(5, 90)], 0, 0, es_primer_cruce=False)
    assert ULTIMO_SACO in [m.motivo for m in momentos]


def test_el_pico_de_personas_solo_cuenta_si_iguala_o_supera_el_anterior():
    subiendo = momentos_del_fotograma([], personas_en_zona=3, pico_previo=2,
                                      es_primer_cruce=False)
    bajando = momentos_del_fotograma([], personas_en_zona=1, pico_previo=3,
                                     es_primer_cruce=False)

    assert PICO_DE_PERSONAS in [m.motivo for m in subiendo]
    assert bajando == []


def test_una_rampa_vacia_no_genera_momentos():
    assert momentos_del_fotograma([], 0, 0, es_primer_cruce=False) == []


# ------------------------------------------------------------ la seleccion
def test_se_guarda_una_imagen_por_motivo():
    selector = SelectorDeFotogramas(maximo=4, fps=10.0)
    selector.considerar(10, "a", [Momento(PRIMER_SACO, "primero", 1.0)])
    selector.considerar(50, "b", [Momento(PICO_DE_PERSONAS, "gente", 3.0)])

    claves = selector.claves(codificar=falso)

    assert [c.motivo for c in claves] == [PRIMER_SACO, PICO_DE_PERSONAS]
    assert [c.jpeg for c in claves] == [b"a", b"b"]


def test_del_mismo_motivo_gana_el_de_mayor_magnitud():
    """Con dos picos de personas se guarda el mayor, no el primero que llego."""
    selector = SelectorDeFotogramas(fps=10.0)
    selector.considerar(20, "dos", [Momento(PICO_DE_PERSONAS, "2", 2.0)])
    selector.considerar(60, "cinco", [Momento(PICO_DE_PERSONAS, "5", 5.0)])
    selector.considerar(90, "tres", [Momento(PICO_DE_PERSONAS, "3", 3.0)])

    claves = selector.claves(codificar=falso)

    assert len(claves) == 1
    assert claves[0].jpeg == b"cinco"


def test_del_ultimo_saco_gana_el_mas_tardio():
    """"El ultimo" no es el mayor: es el ultimo."""
    selector = SelectorDeFotogramas(fps=10.0)
    selector.considerar(20, "pronto", [Momento(ULTIMO_SACO, "x", 1.0)])
    selector.considerar(200, "tarde", [Momento(ULTIMO_SACO, "x", 1.0)])

    assert selector.claves(codificar=falso)[0].jpeg == b"tarde"


def test_cuando_sobran_candidatos_se_quedan_los_de_mas_prioridad():
    """Van a una API externa que cobra por imagen: hay que elegir bien."""
    selector = SelectorDeFotogramas(maximo=2, fps=10.0)
    selector.considerar(10, "primero", [Momento(PRIMER_SACO, "x", 1.0)])
    selector.considerar(30, "centro", [Momento(CENTRO_DEL_CLIP, "x", 1.0)])
    selector.considerar(50, "saliente", [Momento(SACO_SALIENTE, "x", 1.0)])
    selector.considerar(70, "gente", [Momento(PICO_DE_PERSONAS, "x", 4.0)])

    motivos = [c.motivo for c in selector.claves(codificar=falso)]

    assert set(motivos) == {SACO_SALIENTE, PICO_DE_PERSONAS}


def test_se_devuelven_en_el_orden_en_que_ocurrieron():
    """Se eligen por importancia y se leen como la carga."""
    selector = SelectorDeFotogramas(maximo=4, fps=10.0)
    selector.considerar(90, "tarde", [Momento(SACO_SALIENTE, "x", 1.0)])
    selector.considerar(10, "pronto", [Momento(PRIMER_SACO, "x", 1.0)])
    selector.considerar(50, "medio", [Momento(PICO_DE_PERSONAS, "x", 2.0)])

    assert [c.fotograma for c in selector.claves(codificar=falso)] == [10, 50, 90]


def test_un_fotograma_sin_imagen_no_se_guarda():
    """ultralytics puede no traer orig_img segun como se le pida el flujo. Mejor
    una clave de menos que una excepcion con el camion en la rampa."""
    selector = SelectorDeFotogramas(fps=10.0)
    selector.considerar(10, None, [Momento(SACO_SALIENTE, "x", 1.0)])

    assert selector.claves(codificar=falso) == []


def test_el_segundo_del_clip_sale_del_fotograma_y_los_fps():
    """Para que HU-12 pueda saltar ahi en el reproductor."""
    selector = SelectorDeFotogramas(fps=10.0)
    selector.considerar(155, "x", [Momento(SACO_SALIENTE, "x", 1.0)])

    assert selector.claves(codificar=falso)[0].segundo == pytest.approx(15.5)


def test_un_clip_sin_fps_no_divide_por_cero():
    selector = SelectorDeFotogramas(fps=0.0)
    selector.considerar(100, "x", [Momento(SACO_SALIENTE, "x", 1.0)])

    assert selector.claves(codificar=falso)[0].segundo == 0.0


def test_el_nombre_del_objeto_se_lee_en_un_listado():
    """Es como se vera en MinIO cuando alguien busque la evidencia de un caso."""
    selector = SelectorDeFotogramas(fps=10.0)
    selector.considerar(155, "x", [Momento(SACO_SALIENTE, "x", 1.0)])

    assert selector.claves(codificar=falso)[0].nombre == "f000155_saco_saliente.jpg"


def test_sin_nada_que_guardar_la_lista_queda_vacia():
    assert SelectorDeFotogramas().claves(codificar=falso) == []


def test_la_calidad_configurada_llega_al_codificador():
    recibidas = []

    def espia(imagen, calidad):
        recibidas.append(calidad)
        return b""

    selector = SelectorDeFotogramas(fps=10.0, calidad=55)
    selector.considerar(10, "x", [Momento(SACO_SALIENTE, "x", 1.0)])
    selector.claves(codificar=espia)

    assert recibidas == [55]


# ------------------------------------------------------------ la codificacion
def test_una_imagen_de_verdad_se_codifica_como_jpeg():
    """Aqui si se usa cv2: el resto de las pruebas mira la regla, esta mira que
    lo que viaja a la API externa sea un JPEG y no otra cosa."""
    import numpy as np

    from app.fotogramas import _codificar

    imagen = np.full((120, 160, 3), 128, dtype=np.uint8)
    jpeg = _codificar(imagen, calidad=70)

    assert jpeg.startswith(b"\xff\xd8\xff")      # cabecera JPEG
    assert len(jpeg) > 100


def test_menos_calidad_pesa_menos():
    """Estas imagenes se pagan por byte en la API del modelo."""
    import numpy as np

    from app.fotogramas import _codificar

    generador = np.random.default_rng(3)
    imagen = generador.integers(0, 255, (240, 320, 3), dtype=np.uint8)

    assert len(_codificar(imagen, 30)) < len(_codificar(imagen, 95))
