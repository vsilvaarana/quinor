"""El recorrido de un clip. HU-07, criterio 1.

Con modelo inyectado: lo que se prueba es la traduccion entre lo que entrega
ultralytics y lo que el contador entiende, y lo que se informa del clip. La
inferencia de verdad se prueba en test_modelo.py con los pesos entrenados.
"""
from __future__ import annotations

import pathlib

import pytest

from app import analisis
from app.analisis import (ClipIlegible, ModeloNoDisponible, Resultado, _abrir,
                          _detecciones_del_fotograma, analizar)
from app.config import Ajustes
from tests.conftest import CLASES, ModeloFalso, _Fotograma, sacos_cruzando


def ajustes_de(pesos: pathlib.Path, **cambios) -> Ajustes:
    return Ajustes(ruta_pesos=pesos, **cambios)


# ------------------------------------------------------------------- el video
def test_un_clip_inexistente_es_ilegible(tmp_path):
    with pytest.raises(ClipIlegible, match="No existe"):
        _abrir(tmp_path / "no-esta.mkv")


def test_un_archivo_que_no_es_video_es_ilegible(tmp_path):
    """Un segmento a medio escribir por el grabador acaba aqui."""
    roto = tmp_path / "roto.mkv"
    roto.write_bytes(b"no soy un video")
    with pytest.raises(ClipIlegible, match="No se pudo abrir"):
        _abrir(roto)


def test_del_clip_se_saca_su_duracion(clip):
    video = _abrir(clip)
    assert video.fotogramas > 0
    assert video.fps > 0
    assert video.duracion_s == pytest.approx(video.fotogramas / video.fps)


def test_un_video_sin_fps_no_divide_por_cero():
    assert analisis._Video(fotogramas=100, fps=0.0).duracion_s == 0.0


# ------------------------------------------------------------------- el modelo
def test_sin_pesos_el_modelo_no_se_carga(tmp_path):
    """Y el mensaje dice que hacer, que es lo que alguien necesita a las 6 a.m."""
    with pytest.raises(ModeloNoDisponible, match="YOLO_WEIGHTS"):
        analisis._cargar_modelo(ajustes_de(tmp_path / "no-esta.pt"))


def test_con_pesos_se_le_pasa_la_ruta_a_ultralytics(tmp_path, monkeypatch):
    pesos = tmp_path / "sacos.pt"
    pesos.write_bytes(b"x")
    recibido = {}

    class YOLOFalso:
        def __init__(self, ruta):
            recibido["ruta"] = ruta

    import sys
    import types

    modulo = types.ModuleType("ultralytics")
    modulo.YOLO = YOLOFalso
    monkeypatch.setitem(sys.modules, "ultralytics", modulo)

    modelo = analisis._cargar_modelo(ajustes_de(pesos))

    assert isinstance(modelo, YOLOFalso)
    assert recibido["ruta"] == str(pesos)


# ------------------------------------------- de ultralytics a las detecciones
def test_un_fotograma_sin_seguimiento_no_aporta_detecciones():
    """Sin identificador no se puede cruzar con el fotograma anterior: contar
    sin seguir es contar fotogramas, no sacos."""
    fotograma = _Fotograma([])
    assert _detecciones_del_fotograma(fotograma, CLASES) == []


def test_un_resultado_sin_cajas_tampoco():
    class SinCajas:
        boxes = None

    assert _detecciones_del_fotograma(SinCajas(), CLASES) == []


def test_las_clases_se_traducen_por_su_nombre():
    fotograma = _Fotograma([(7, 0, 0.9, 0.3, 0.4), (9, 1, 0.8, 0.6, 0.5)])
    detecciones = _detecciones_del_fotograma(fotograma, CLASES)

    assert [d.clase for d in detecciones] == ["saco", "person"]
    assert detecciones[0].id_seguimiento == 7
    assert detecciones[0].centro.x == pytest.approx(0.3)


def test_una_clase_desconocida_no_revienta_el_analisis():
    """Si alguien apunta YOLO_WEIGHTS a un modelo con otras clases, mejor un
    conteo de cero que una excepcion con el camion en la rampa."""
    fotograma = _Fotograma([(1, 44, 0.9, 0.3, 0.4)])
    assert _detecciones_del_fotograma(fotograma, CLASES)[0].clase == "44"


# ------------------------------------------------------------- criterio 1
def test_analizar_cuenta_los_sacos_que_cruzan(clip, tmp_path):
    resultado = analizar(ajustes_de(tmp_path / "sacos.pt", salto_de_fotogramas=1),
                         clip, modelo=ModeloFalso(sacos_cruzando(4)))

    assert resultado.sacos_contados == 4
    assert resultado.sacos_entrantes == 4
    assert resultado.sacos_salientes == 0
    assert resultado.fotogramas_procesados == 3


def test_analizar_informa_del_modelo_con_el_que_conto(clip, tmp_path):
    resultado = analizar(ajustes_de(tmp_path / "v3.pt"), clip,
                         modelo=ModeloFalso(sacos_cruzando(1)))
    assert resultado.modelo == "v3.pt"


def test_las_personas_se_cuentan_por_identificador_y_no_por_aparicion(clip, tmp_path):
    """La misma persona en treinta fotogramas es una persona.

    Con el minimo de permanencia en cero porque el clip de prueba son tres
    fotogramas: lo que se mide aqui es que no se cuente por aparicion.
    """
    resultado = analizar(
        ajustes_de(tmp_path / "sacos.pt", permanencia_minima_s=0.0), clip,
        modelo=ModeloFalso(sacos_cruzando(2, personas=3)))

    assert resultado.personas_detectadas == 3
    assert resultado.personas.maximo_simultaneo == 3


def test_un_parpadeo_del_detector_no_llega_a_ser_una_persona(clip, tmp_path):
    """Con el minimo por defecto, tres fotogramas sueltos no son alguien que
    estuvo en la rampa. Es lo que evita que una deteccion perdida infle el
    registro de la carga."""
    resultado = analizar(ajustes_de(tmp_path / "sacos.pt"), clip,
                         modelo=ModeloFalso(sacos_cruzando(2, personas=3)))
    assert resultado.personas_detectadas == 0


def test_el_salto_de_fotogramas_llega_a_ultralytics(clip, tmp_path):
    modelo = ModeloFalso(sacos_cruzando(1))
    analizar(ajustes_de(tmp_path / "sacos.pt", salto_de_fotogramas=4), clip,
             modelo=modelo)
    assert modelo.llamadas[0]["vid_stride"] == 4


def test_la_memoria_del_contador_se_mide_en_fotogramas_de_video(clip, tmp_path):
    """La misma secuencia, mirada con salto 1 y con salto 2.

    Con salto 2 el cuarto fotograma mirado es el sexto del video, asi que el
    rastro lleva 6 fotogramas sin aparecer y ya caduco. Si la memoria se contara
    en fotogramas mirados, duraria el doble de lo configurado y un identificador
    reutilizado por el rastreador heredaria el lado de otro objeto.
    """
    secuencia = [[(1, 0, 0.9, 0.2, 0.5)], [], [], [(1, 0, 0.9, 0.8, 0.5)]]

    seguido = analizar(
        ajustes_de(tmp_path / "sacos.pt", salto_de_fotogramas=1,
                   memoria_de_seguimiento=3),
        clip, modelo=ModeloFalso(secuencia))
    caducado = analizar(
        ajustes_de(tmp_path / "sacos.pt", salto_de_fotogramas=2,
                   memoria_de_seguimiento=3),
        clip, modelo=ModeloFalso(secuencia))

    assert seguido.sacos_contados == 1
    assert caducado.sacos_contados == 0


def test_un_clip_ilegible_no_llega_a_cargar_el_modelo(tmp_path):
    with pytest.raises(ClipIlegible):
        analizar(ajustes_de(tmp_path / "no-esta.pt"), tmp_path / "tampoco.mkv")


def test_se_informa_cuanto_tardo_frente_a_lo_que_dura_el_clip(clip, tmp_path):
    """RNF-01: un clip de 7 min se analiza en menos de 3. Sin la cifra, nadie
    sabria si se esta cumpliendo."""
    resultado = analizar(ajustes_de(tmp_path / "sacos.pt"), clip,
                         modelo=ModeloFalso(sacos_cruzando(1)))
    assert resultado.duracion_del_clip_s > 0
    assert resultado.segundos_de_proceso >= 0
    assert resultado.mas_rapido_que_el_video is True


def test_un_analisis_mas_lento_que_el_video_se_nota():
    lento = Resultado(sacos_contados=0, sacos_entrantes=0, sacos_salientes=0,
                      personas_detectadas=0, fotogramas_procesados=1,
                      fotogramas_totales=1, duracion_del_clip_s=10.0,
                      segundos_de_proceso=30.0, modelo="x.pt",
                      detecciones_de_saco=0)
    assert lento.mas_rapido_que_el_video is False


# ----------------------------------------------- el fallo silencioso del salto
def test_detecciones_sin_seguimiento_no_pasan_por_cero_calladas(clip, tmp_path):
    """El fallo que aparecio midiendo el criterio 2: con salto 2, el detector
    veia los sacos y el rastreador no seguia ninguno, asi que el conteo daba cero
    y la carga parecia vacia. Cero es una respuesta grave; tiene que venir con su
    aviso o nadie sabria distinguirlo de un camion que no se cargo."""
    fotogramas = [[(None, 0, 0.9, 0.2, 0.5)], [(None, 0, 0.9, 0.5, 0.5)],
                  [(None, 0, 0.9, 0.8, 0.5)]]
    resultado = analizar(ajustes_de(tmp_path / "sacos.pt"), clip,
                         modelo=ModeloFalso(fotogramas, con_id=False))

    assert resultado.sacos_contados == 0
    assert resultado.fotogramas_sin_seguimiento == 3
    assert resultado.seguimiento_perdido is True


def test_un_clip_realmente_vacio_no_da_falsa_alarma(clip, tmp_path):
    """Un camion que no se cargo tambien cuenta cero, y ahi no hay nada que avisar."""
    resultado = analizar(ajustes_de(tmp_path / "sacos.pt"), clip,
                         modelo=ModeloFalso([[], [], []]))

    assert resultado.sacos_contados == 0
    assert resultado.seguimiento_perdido is False


def test_un_conteo_normal_no_da_falsa_alarma(clip, tmp_path):
    resultado = analizar(ajustes_de(tmp_path / "sacos.pt"), clip,
                         modelo=ModeloFalso(sacos_cruzando(2)))
    assert resultado.seguimiento_perdido is False


def test_se_cuentan_las_detecciones_ademas_de_los_cruces(clip, tmp_path):
    """Un clip con cruces en cero y miles de detecciones apunta a la linea mal
    calibrada; con los dos en cero, a que el modelo no ve los sacos."""
    resultado = analizar(ajustes_de(tmp_path / "sacos.pt"), clip,
                         modelo=ModeloFalso(sacos_cruzando(2)))
    assert resultado.detecciones_de_saco == 6      # 2 sacos en 3 fotogramas
