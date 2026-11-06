"""Simulador de camara con videos reales.

Lo que se vigila es lo que se rompe sin hacer ruido: que un archivo que no es
video entre en la lista, que un nombre con comilla rompa el formato del demuxer
concat, que un video ilegible tumbe la camara, o que se vuelva a convertir lo
que ya estaba convertido.
"""
from __future__ import annotations

import os
import subprocess
from types import SimpleNamespace

import pytest

from sim import camara_sim as cam


def _crear(ruta, contenido=b"x"):
    ruta.write_bytes(contenido)
    return str(ruta)


def test_sin_carpeta_o_vacia_no_hay_videos(tmp_path):
    assert cam.buscar_videos("") == []
    assert cam.buscar_videos(str(tmp_path / "no-existe")) == []
    assert cam.buscar_videos(str(tmp_path)) == []


def test_solo_videos_en_orden_y_sin_ocultos_ni_subcarpetas(tmp_path):
    _crear(tmp_path / "b.MP4")
    _crear(tmp_path / "a.mkv")
    _crear(tmp_path / "notas.txt")
    _crear(tmp_path / "._a.mp4")          # basura de macOS
    (tmp_path / "sub.mp4").mkdir()         # una carpeta con nombre de video
    nombres = [os.path.basename(v) for v in cam.buscar_videos(str(tmp_path))]
    assert nombres == ["a.mkv", "b.MP4"]


def test_la_lista_escapa_comillas_simples(tmp_path):
    ruta = cam.escribir_lista(["/v/carga d'Ana.mp4", "/v/b.mp4"],
                              str(tmp_path / "lista.txt"))
    assert open(ruta, encoding="utf-8").read().splitlines() == [
        "file '/v/carga d'\\''Ana.mp4'",
        "file '/v/b.mp4'",
    ]


def test_normalizar_deja_lo_que_pide_el_grabador():
    comando = cam.comando_normalizar("in.mov", "out.mp4", camara_id="camara-09",
                                     fps=15, resolucion="1280x720", gop=15)
    filtros = comando[comando.index("-vf") + 1]
    assert "scale=1280:720:force_original_aspect_ratio=decrease" in filtros
    assert "pad=1280:720" in filtros and "fps=15" in filtros
    assert "camara-09" in filtros
    # Un fotograma clave por segundo, y sin claves extra por cambio de escena.
    assert comando[comando.index("-g") + 1] == "15"
    assert comando[comando.index("-sc_threshold") + 1] == "0"
    assert comando[comando.index("-c:v") + 1] == "libx264"
    assert comando[-1] == "out.mp4"


def test_convierte_una_sola_vez_y_salta_lo_ilegible(tmp_path):
    bueno = _crear(tmp_path / "bueno.mp4")
    roto = _crear(tmp_path / "roto.mp4")
    llamadas = []

    def ejecutar(comando, check):
        llamadas.append(comando)
        destino = comando[-1]
        if comando[comando.index("-i") + 1] == roto:
            open(destino, "wb").write(b"a medias")   # ffmpeg deja un parcial
            return SimpleNamespace(returncode=1)
        open(destino, "wb").write(b"convertido")
        return SimpleNamespace(returncode=0)

    cache = str(tmp_path / "cache")
    listos = cam.normalizar([bueno, roto], cache, ejecutar=ejecutar)
    assert len(listos) == 1 and listos[0].startswith(os.path.join(cache, "bueno-"))
    assert not [f for f in os.listdir(cache) if f.endswith(".parcial")]

    # Segunda pasada: el bueno ya esta convertido; solo se reintenta el roto.
    llamadas.clear()
    assert cam.normalizar([bueno, roto], cache, ejecutar=ejecutar) == listos
    assert [c[c.index("-i") + 1] for c in llamadas] == [roto]


def test_un_video_reemplazado_se_vuelve_a_convertir(tmp_path):
    video = tmp_path / "carga.mp4"
    _crear(video, b"uno")
    ok = lambda comando, check: (open(comando[-1], "wb").write(b"c"),  # noqa: E731
                                 SimpleNamespace(returncode=0))[1]
    cache = str(tmp_path / "cache")
    primero = cam.normalizar([str(video)], cache, ejecutar=ok)
    _crear(video, b"otro contenido mas largo")
    segundo = cam.normalizar([str(video)], cache, ejecutar=ok)
    assert primero != segundo


def test_publicar_videos_no_recodifica_y_da_vueltas():
    comando = cam.construir_comando_videos("/tmp/lista.txt", "rtsp://x:8554/rampa-01")
    assert comando[comando.index("-stream_loop") + 1] == "-1"
    assert comando[comando.index("-f") + 1] == "concat"
    assert comando[comando.index("-c") + 1] == "copy"
    assert comando[-1] == "rtsp://x:8554/rampa-01"
    assert "-re" in comando


def test_elegir_usa_videos_si_hay_y_sintetica_si_no(tmp_path, monkeypatch):
    monkeypatch.setattr(cam, "LISTA_REPRODUCCION", str(tmp_path / "lista.txt"))
    monkeypatch.setattr(cam, "normalizar", lambda videos: [v + ".conv" for v in videos])
    _crear(tmp_path / "a.mp4")
    con_videos = cam.elegir_comando(str(tmp_path))
    assert "concat" in con_videos
    vacia = tmp_path / "vacia"
    vacia.mkdir()
    assert "lavfi" in cam.elegir_comando(str(vacia))
    assert "lavfi" in cam.elegir_comando("")


def test_si_ningun_video_se_puede_leer_vuelve_a_la_sintetica(tmp_path, monkeypatch):
    monkeypatch.setattr(cam, "normalizar", lambda videos: [])
    _crear(tmp_path / "roto.mp4")
    assert "lavfi" in cam.elegir_comando(str(tmp_path))


@pytest.mark.skipif(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode,
                    reason="sin ffmpeg")
def test_videos_distintos_quedan_iguales_y_se_encadenan(tmp_path):
    """Con ffmpeg de verdad: H.265 1080p a 30 fps y H.264 480p a 25 fps salen
    iguales, y la lista se publica en bucle sin recodificar."""
    origen = tmp_path / "origen"
    origen.mkdir()
    for nombre, fuente, codec in (("a.mp4", "testsrc2=size=1920x1080:rate=30", "libx265"),
                                  ("b.mov", "testsrc=size=640x480:rate=25", "libx264")):
        r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            fuente, "-t", "2", "-c:v", codec, str(origen / nombre)])
        if r.returncode:
            pytest.skip(f"este ffmpeg no tiene {codec}")
    listos = cam.normalizar(cam.buscar_videos(str(origen)), str(tmp_path / "cache"))
    salida = tmp_path / "salida.mkv"
    comando = cam.construir_comando_videos(
        cam.escribir_lista(listos, str(tmp_path / "lista.txt")))
    comando = comando[:comando.index("-an")] + ["-t", "7", "-y", str(salida)]
    comando.remove("-re")
    assert subprocess.run(comando).returncode == 0

    def sonda(*args):
        return subprocess.run(["ffprobe", "-v", "error", *args, str(salida)],
                              capture_output=True, text=True).stdout.split()

    assert sonda("-select_streams", "v", "-show_entries", "stream=codec_name,width,height",
                 "-of", "csv=p=0") == ["h264,1280,720"]
    # 4 s de videos dan 7 s de salida: el bucle funciona.
    assert float(sonda("-show_entries", "format=duration", "-of", "csv=p=0")[0]) >= 6.5
