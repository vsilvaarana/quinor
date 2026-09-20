"""La orden de ffmpeg. HU-05, criterio 1.

El criterio nombra tres cosas: muxer segment, segmentos de 1 min, y `-c copy`
con `-strftime 1`. Aqui se comprueba que estan y que siguen estando: es la clase
de bandera que alguien quita un dia para depurar y no vuelve a poner.
"""
from __future__ import annotations

import pathlib

import pytest

from app import ffmpeg
from app.config import Ajustes, Camara

CAMARA = Camara(id="CAMARA-01", url="rtsp://usuario:clave@10.0.0.11:554/stream")


@pytest.fixture()
def ajustes_simples(tmp_path) -> Ajustes:
    return Ajustes(database_url="mysql+pymysql://sin/base",
                   camaras=(CAMARA,), directorio_buffer=tmp_path)


def test_usa_el_muxer_segment(ajustes_simples):
    comando = ffmpeg.construir_comando(ajustes_simples, CAMARA)
    assert comando[comando.index("-f") + 1] == "segment"


def test_los_segmentos_son_de_un_minuto(ajustes_simples):
    comando = ffmpeg.construir_comando(ajustes_simples, CAMARA)
    assert comando[comando.index("-segment_time") + 1] == "60"


def test_no_reencodifica(ajustes_simples):
    """Reencodificar consumiria la GPU que HU-07 necesita para YOLO."""
    comando = ffmpeg.construir_comando(ajustes_simples, CAMARA)
    assert comando[comando.index("-c") + 1] == "copy"


def test_el_nombre_lleva_la_marca_de_tiempo(ajustes_simples):
    comando = ffmpeg.construir_comando(ajustes_simples, CAMARA)
    assert comando[comando.index("-strftime") + 1] == "1"
    assert comando[-1].endswith("camara-01_%Y%m%d-%H%M%S.mkv")


def test_la_url_de_la_camara_es_la_entrada(ajustes_simples):
    comando = ffmpeg.construir_comando(ajustes_simples, CAMARA)
    assert comando[comando.index("-i") + 1] == CAMARA.url


def test_el_transporte_es_tcp(ajustes_simples):
    """UDP pierde paquetes con ruido electrico y el video queda con saltos justo
    en el momento que habra que revisar."""
    comando = ffmpeg.construir_comando(ajustes_simples, CAMARA)
    assert comando[comando.index("-rtsp_transport") + 1] == "tcp"


def test_hay_un_limite_de_espera(ajustes_simples):
    """Sin el, una camara muda deja a ffmpeg esperando para siempre y la
    desconexion del criterio 3 no se detectaria nunca."""
    comando = ffmpeg.construir_comando(ajustes_simples, CAMARA)
    assert comando[comando.index("-timeout") + 1] == str(int(15.0 * 1_000_000))


def test_cada_camara_graba_en_su_carpeta(ajustes_simples, tmp_path):
    otra = Camara(id="camara-02", url="rtsp://otra/stream")
    assert ffmpeg.carpeta_de(ajustes_simples, CAMARA) == tmp_path / "camara-01"
    assert ffmpeg.carpeta_de(ajustes_simples, otra) == tmp_path / "camara-02"


def test_el_formato_del_segmento_sobrevive_a_un_corte(ajustes_simples):
    """Matroska y no MP4: un MP4 a medias se pierde entero."""
    comando = ffmpeg.construir_comando(ajustes_simples, CAMARA)
    assert comando[comando.index("-segment_format") + 1] == "matroska"


@pytest.mark.parametrize("nombre,esperado", [
    ("camara-01_20260914-043000.mkv", "20260914-043000"),
    ("camara-02_20261231-235959.mkv", "20261231-235959"),
    ("otra-cosa.mkv", None),
    ("camara-01_20260914.mkv", None),
    ("camara-01_20260914-043000.mp4", None),
])
def test_se_reconoce_lo_que_escribio_el_grabador(nombre, esperado):
    """La purga solo borra lo suyo: otro archivo en la carpeta no es asunto suyo."""
    assert ffmpeg.marca_de_segmento(pathlib.Path(nombre)) == esperado
