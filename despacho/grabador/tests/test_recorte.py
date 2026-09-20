"""Recorte de la ventana de un evento. HU-06, criterios 1 y 3.

La eleccion de segmentos y la cuenta de cobertura son aritmetica de fechas y se
prueban con segmentos sembrados. El recorte de verdad, con ffmpeg y video real,
esta al final.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import subprocess

import pytest

from app import recorte
from tests.conftest import CAMARA_PRUEBA, segmento

CIERRE = dt.datetime(2026, 9, 14, 10, 30, 0)


def marca(momento: dt.datetime) -> str:
    return momento.strftime("%Y%m%d-%H%M%S")


@pytest.fixture()
def ajustes_reales(ajustes):
    """Segmentos de 60 s y margenes de 5 y 2 minutos, como en planta."""
    return dataclasses.replace(ajustes, segundos_por_segmento=60,
                               segundos_antes=300, segundos_despues=120)


# ----------------------------------------------- criterio 1: la ventana
def test_la_ventana_empieza_5_min_antes_del_inicio_de_carga(ajustes_reales):
    inicio = CIERRE - dt.timedelta(minutes=12)
    ventana = recorte.ventana_de(inicio, CIERRE, ajustes_reales)

    assert ventana.desde == inicio - dt.timedelta(minutes=5)
    assert ventana.hasta == CIERRE + dt.timedelta(minutes=2)
    # Carga de 12 min mas los dos margenes.
    assert ventana.duracion_s == pytest.approx(19 * 60)


def test_sin_marca_de_inicio_la_ventana_arranca_en_el_cierre(ajustes_reales):
    """Peor clip, pero sigue cubriendo los minutos que preceden a la pesada."""
    ventana = recorte.ventana_de(None, CIERRE, ajustes_reales)

    assert ventana.desde == CIERRE - dt.timedelta(minutes=5)
    assert ventana.hasta == CIERRE + dt.timedelta(minutes=2)
    assert ventana.duracion_s == pytest.approx(7 * 60)


def test_una_carga_larga_cabe_entera_en_la_ventana(ajustes_reales):
    """Es justo lo que se gana registrando el inicio: un clip de 40 minutos si
    la carga duro 40 minutos, en lugar de los ultimos cinco."""
    inicio = CIERRE - dt.timedelta(minutes=40)
    ventana = recorte.ventana_de(inicio, CIERRE, ajustes_reales)
    assert ventana.duracion_s == pytest.approx(47 * 60)


def test_los_margenes_son_configurables(ajustes):
    otros = dataclasses.replace(ajustes, segundos_antes=30, segundos_despues=10)
    ventana = recorte.ventana_de(None, CIERRE, otros)
    assert ventana.duracion_s == pytest.approx(40)


# ----------------------------------------- eleccion de segmentos y cobertura
def test_se_eligen_los_segmentos_que_tocan_la_ventana(ajustes_reales, buffer):
    for minutos in range(0, 12):
        segmento(buffer, CAMARA_PRUEBA, marca(CIERRE - dt.timedelta(minutes=minutos)))

    ventana = recorte.ventana_de(None, CIERRE, ajustes_reales)
    elegidos = recorte.segmentos_de_la_ventana(ajustes_reales, CAMARA_PRUEBA, ventana)

    # Los seis minutos desde el cierre hacia atras: 10:25 a 10:30 mas el propio.
    assert len(elegidos) == 6
    assert elegidos[0][1] == CIERRE - dt.timedelta(minutes=5)


def test_el_segmento_anterior_al_inicio_tambien_entra(ajustes_reales, buffer):
    """La ventana suele empezar a mitad de un segmento; sin el, el clip empezaria
    tarde."""
    inicio_segmento = CIERRE - dt.timedelta(minutes=5, seconds=30)
    segmento(buffer, CAMARA_PRUEBA, marca(inicio_segmento))

    ventana = recorte.ventana_de(None, CIERRE, ajustes_reales)
    elegidos = recorte.segmentos_de_la_ventana(ajustes_reales, CAMARA_PRUEBA, ventana)
    assert len(elegidos) == 1


def test_no_se_eligen_segmentos_fuera_de_la_ventana(ajustes_reales, buffer):
    segmento(buffer, CAMARA_PRUEBA, marca(CIERRE - dt.timedelta(hours=3)))
    segmento(buffer, CAMARA_PRUEBA, marca(CIERRE + dt.timedelta(hours=1)))

    ventana = recorte.ventana_de(None, CIERRE, ajustes_reales)
    assert recorte.segmentos_de_la_ventana(ajustes_reales, CAMARA_PRUEBA, ventana) == []


def test_solo_se_miran_los_segmentos_de_esa_camara(ajustes_reales, buffer):
    segmento(buffer, "camara-02", marca(CIERRE - dt.timedelta(minutes=1)))
    ventana = recorte.ventana_de(None, CIERRE, ajustes_reales)
    assert recorte.segmentos_de_la_ventana(ajustes_reales, CAMARA_PRUEBA, ventana) == []


def test_la_cobertura_suma_solapes_y_no_segmentos(ajustes_reales, buffer):
    """Si falta un minuto por el medio porque la camara se cayo, la cuenta lo
    refleja y el criterio 3 puede actuar."""
    for minutos in (5, 4, 1, 0):          # faltan los minutos 3 y 2
        segmento(buffer, CAMARA_PRUEBA, marca(CIERRE - dt.timedelta(minutes=minutos)))

    ventana = recorte.ventana_de(None, CIERRE, ajustes_reales)
    elegidos = recorte.segmentos_de_la_ventana(ajustes_reales, CAMARA_PRUEBA, ventana)
    cubiertos = recorte._segundos_cubiertos(elegidos, ventana, 60)

    assert cubiertos == pytest.approx(4 * 60)     # cuatro minutos de siete


def test_un_archivo_con_nombre_ajeno_no_se_considera(ajustes_reales, buffer):
    carpeta = buffer / CAMARA_PRUEBA
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "grabacion.mkv").write_bytes(b"\0" * 100)

    ventana = recorte.ventana_de(None, CIERRE, ajustes_reales)
    assert recorte.segmentos_de_la_ventana(ajustes_reales, CAMARA_PRUEBA, ventana) == []


# ------------------------------------------------- criterio 3: no hay video
def test_sin_segmentos_se_avisa_en_lugar_de_devolver_un_clip_vacio(
        ajustes_reales, buffer, tmp_path):
    ventana = recorte.ventana_de(None, CIERRE, ajustes_reales)
    with pytest.raises(recorte.SinVideoEnLaVentana):
        recorte.recortar(ajustes_reales, CAMARA_PRUEBA, ventana, tmp_path / "x.mkv")


def test_un_segmento_ilegible_no_produce_un_clip_roto(ajustes_reales, buffer, tmp_path):
    """Un archivo con el nombre correcto pero sin video dentro."""
    segmento(buffer, CAMARA_PRUEBA, marca(CIERRE - dt.timedelta(minutes=1)))
    ventana = recorte.ventana_de(None, CIERRE, ajustes_reales)
    with pytest.raises(recorte.RecorteFallido):
        recorte.recortar(ajustes_reales, CAMARA_PRUEBA, ventana, tmp_path / "x.mkv")


# ------------------------------------------------------ nombre en el bucket
def test_el_objeto_se_guarda_por_fecha_y_orden():
    ventana = recorte.Ventana(desde=dt.datetime(2026, 9, 14, 10, 25),
                              hasta=dt.datetime(2026, 9, 14, 10, 32))
    nombre = recorte.nombre_de_objeto("ORD-2026-0001", 7, "camara-01", ventana)

    assert nombre.startswith("2026/09/14/ORD-2026-0001/")
    assert "evento-7" in nombre
    assert nombre.endswith(".mkv")


def test_dos_eventos_no_pisan_el_mismo_objeto():
    ventana = recorte.Ventana(desde=dt.datetime(2026, 9, 14, 10, 25),
                              hasta=dt.datetime(2026, 9, 14, 10, 32))
    uno = recorte.nombre_de_objeto("ORD-A", 1, "camara-01", ventana)
    otro = recorte.nombre_de_objeto("ORD-A", 2, "camara-01", ventana)
    assert uno != otro


# ------------------------------------------------- recorte real con ffmpeg
def test_recorta_video_de_verdad(ajustes, buffer, camara_rtsp, tmp_path):
    """De punta a punta: se graba con el grabador de HU-05 y se recorta de ahi."""
    from app.grabador import Grabador
    from app.config import Camara
    import time

    reales = dataclasses.replace(
        ajustes, segundos_por_segmento=2, segundos_antes=4, segundos_despues=2,
        camaras=(Camara(id=CAMARA_PRUEBA, url=camara_rtsp.url),))
    grabador = Grabador(reales, None)
    grabador.arrancar_camara(grabador.camaras[0])
    time.sleep(10)
    grabador.cerrar()

    cierre = dt.datetime.now().replace(tzinfo=None) - dt.timedelta(seconds=2)
    ventana = recorte.ventana_de(None, cierre, reales)
    destino = tmp_path / "clip.mkv"
    clip = recorte.recortar(reales, CAMARA_PRUEBA, ventana, destino)

    assert destino.exists() and destino.stat().st_size > 0
    assert clip.segmentos_usados >= 2
    duracion = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(destino)],
        capture_output=True, text=True, check=True).stdout.strip())
    assert duracion == pytest.approx(ventana.duracion_s, abs=2.0)


def test_el_clip_no_esta_reencodificado(ajustes, buffer, camara_rtsp, tmp_path):
    """`-c copy` tambien aqui: el clip es evidencia, no una vista previa."""
    from app.grabador import Grabador
    from app.config import Camara
    import time

    reales = dataclasses.replace(
        ajustes, segundos_por_segmento=2, segundos_antes=4, segundos_despues=2,
        camaras=(Camara(id=CAMARA_PRUEBA, url=camara_rtsp.url),))
    grabador = Grabador(reales, None)
    grabador.arrancar_camara(grabador.camaras[0])
    time.sleep(8)
    grabador.cerrar()

    cierre = dt.datetime.now().replace(tzinfo=None) - dt.timedelta(seconds=2)
    destino = tmp_path / "clip.mkv"
    recorte.recortar(reales, CAMARA_PRUEBA,
                     recorte.ventana_de(None, cierre, reales), destino)

    codec = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name", "-of", "csv=p=0", str(destino)],
        capture_output=True, text=True, check=True).stdout.strip()
    assert codec == "h264"


def test_no_queda_basura_junto_al_clip(ajustes, buffer, camara_rtsp, tmp_path):
    """La lista de concatenacion es temporal y no debe sobrevivir al recorte."""
    from app.grabador import Grabador
    from app.config import Camara
    import time

    reales = dataclasses.replace(
        ajustes, segundos_por_segmento=2, segundos_antes=4, segundos_despues=2,
        camaras=(Camara(id=CAMARA_PRUEBA, url=camara_rtsp.url),))
    grabador = Grabador(reales, None)
    grabador.arrancar_camara(grabador.camaras[0])
    time.sleep(8)
    grabador.cerrar()

    # Carpeta propia: tmp_path tambien tiene el buffer y la configuracion del
    # servidor RTSP, que no son basura del recorte.
    carpeta = tmp_path / "salida"
    destino = carpeta / "clip.mkv"
    cierre = dt.datetime.now().replace(tzinfo=None) - dt.timedelta(seconds=2)
    recorte.recortar(reales, CAMARA_PRUEBA,
                     recorte.ventana_de(None, cierre, reales), destino)

    assert [r.name for r in carpeta.iterdir()] == ["clip.mkv"]


def test_un_nombre_con_fecha_imposible_no_se_toma_como_segmento(ajustes_reales, buffer):
    """20260931 no existe. Antes que adivinar la fecha, se deja fuera."""
    segmento(buffer, CAMARA_PRUEBA, "20260931-120000")
    ventana = recorte.ventana_de(None, CIERRE, ajustes_reales)
    assert recorte.segmentos_de_la_ventana(ajustes_reales, CAMARA_PRUEBA, ventana) == []
