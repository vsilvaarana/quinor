"""Simulador de camara IP. Sprint 2.

No hay acceso a las camaras de la rampa mientras el proyecto este en desarrollo,
igual que no lo hay a la bascula ni al ERP. Este proceso publica una senal
sintetica con el identificador de camara y el reloj impresos en la imagen, de
modo que al abrir un segmento se ve de que camara es y de que minuto.

Una camara IP es un servidor RTSP, asi que el simulador necesita uno delante: el
servicio `rtsp-server` del compose (mediamtx). Este proceso publica contra el, y
el grabador se conecta como lo haria contra la camara real, sin saber que hay un
simulador al otro lado.

Videos reales: si CAMERA_VIDEO_DIR apunta a una carpeta con videos (.mp4, .mkv,
.avi, .mov, .m4v, .ts), el simulador los publica en bucle, uno tras otro y en
orden alfabetico, en lugar de la senal sintetica. Sirve para probar el sistema
con grabaciones de la rampa sin tener las camaras conectadas. La carpeta se
vuelve a leer cada vez que la publicacion se reinicia, asi que al agregar o
quitar videos basta con reiniciar el servicio:
    docker compose restart camara-sim-01

Para probar el criterio 3 de HU-05, basta con parar este proceso:
    docker compose stop camara-sim-01
El grabador pierde la fuente, lo registra en salud_componente y la camara
aparece en error en GET /salud.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time

log = logging.getLogger("quinor.camara_sim")

CAMARA_ID = os.getenv("CAMERA_ID", "camara-01")
DESTINO = os.getenv("CAMERA_PUBLISH_URL", "rtsp://rtsp-server:8554/rampa-01")
FPS = int(os.getenv("CAMERA_FPS", "15"))
RESOLUCION = os.getenv("CAMERA_SIZE", "640x360")
# Intervalo entre fotogramas clave, en fotogramas. El muxer segment del grabador
# corta en fotograma clave: con un GOP de un segundo, los segmentos salen del
# minuto pedido y no de minuto y pico.
GOP = int(os.getenv("CAMERA_GOP", str(FPS)))
SEGUNDOS_ENTRE_REINTENTOS = float(os.getenv("CAMERA_RETRY_SECONDS", "5"))
# Carpeta con videos reales. Vacia o sin videos: senal sintetica.
CARPETA_VIDEOS = os.getenv("CAMERA_VIDEO_DIR", "")
# Las grabaciones reales se llevan a un tamano fijo: si dos archivos tienen
# resoluciones distintas, la camara no cambia de tamano a mitad del flujo.
RESOLUCION_VIDEO = os.getenv("CAMERA_VIDEO_SIZE", "1280x720")
EXTENSIONES_VIDEO = (".mp4", ".mkv", ".avi", ".mov", ".m4v", ".ts")
LISTA_REPRODUCCION = os.getenv("CAMERA_PLAYLIST", "/tmp/quinor-lista-videos.txt")
# Copias convertidas de los videos (ver normalizar). Viven dentro del contenedor:
# si se recrea, se vuelven a convertir.
CARPETA_CACHE = os.getenv("CAMERA_VIDEO_CACHE", "/tmp/quinor-videos-convertidos")


def texto_superpuesto(camara_id: str) -> str:
    """Identificador y reloj quemados en la imagen.

    Sin esto, todos los segmentos de prueba son el mismo patron de barras y no
    hay forma de comprobar a ojo que cada camara graba lo suyo.
    """
    # La hora va con puntos y no con dos puntos. Dentro de un filtro de ffmpeg
    # los dos puntos separan opciones y hay que escaparlos dos veces, una para
    # el filtro y otra para la expansion de texto; con puntos se lee igual de
    # bien y no hay escapes que se rompan al cambiar de shell.
    reloj = r"%{localtime\:%Y-%m-%d %H.%M.%S}"
    return (f"drawtext=text='{camara_id} {reloj}':x=10:y=10:"
            f"fontsize=18:fontcolor=white:box=1:boxcolor=black@0.5")


def construir_comando(destino: str = DESTINO, camara_id: str = CAMARA_ID,
                      fps: int = FPS, resolucion: str = RESOLUCION,
                      gop: int = GOP) -> list[str]:
    """Comando de publicacion RTSP de la camara simulada."""
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "warning",
        "-nostdin",
        # -re: emite a velocidad real, como una camara. Sin esto generaria horas
        # de video en segundos y el buffer no se pareceria en nada al real.
        "-re",
        "-f", "lavfi",
        "-i", f"testsrc=size={resolucion}:rate={fps}",
        "-vf", texto_superpuesto(camara_id),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-g", str(gop),
        "-pix_fmt", "yuv420p",
        "-an",
        "-f", "rtsp",
        "-rtsp_transport", "tcp",
        destino,
    ]


def buscar_videos(carpeta: str) -> list[str]:
    """Videos de la carpeta, en orden alfabetico. Sin carpeta o vacia: lista vacia.

    No baja a subcarpetas: cada camara tiene la suya y asi no se mezclan.
    Los archivos ocultos se saltan (los "._video.mp4" que deja macOS no son video).
    """
    if not carpeta or not os.path.isdir(carpeta):
        return []
    return sorted(
        os.path.join(carpeta, nombre) for nombre in os.listdir(carpeta)
        if not nombre.startswith(".")
        and nombre.lower().endswith(EXTENSIONES_VIDEO)
        and os.path.isfile(os.path.join(carpeta, nombre))
    )


def escribir_lista(videos: list[str], ruta: str = LISTA_REPRODUCCION) -> str:
    """Lista para el demuxer concat de ffmpeg: una linea `file '...'` por video.

    Las comillas simples del nombre se escapan como pide el formato, para que un
    archivo llamado "carga d'Ana.mp4" no rompa la lista.
    """
    with open(ruta, "w", encoding="utf-8") as lista:
        for video in videos:
            escapado = video.replace("'", "'\\''")
            lista.write(f"file '{escapado}'\n")
    return ruta


def comando_normalizar(origen: str, destino: str, camara_id: str = CAMARA_ID,
                       fps: int = FPS, resolucion: str = RESOLUCION_VIDEO,
                       gop: int = GOP) -> list[str]:
    """Convierte un video real a lo que entregaria la camara de planta.

    Las grabaciones llegan como sea: H.265, fotogramas clave cada varios
    segundos, otra resolucion u otros fps. El grabador necesita H.264 con un
    fotograma clave por segundo para cortar segmentos exactos, y el demuxer
    concat solo puede encadenar archivos con los mismos parametros. Por eso
    cada video se convierte una vez, al arrancar, y despues se publica sin
    volver a codificar.
    """
    ancho, alto = resolucion.lower().split("x")
    filtros = ",".join([
        # Encaja el video en el tamano fijo sin deformarlo; lo que sobra va negro.
        f"scale={ancho}:{alto}:force_original_aspect_ratio=decrease",
        f"pad={ancho}:{alto}:(ow-iw)/2:(oh-ih)/2",
        f"fps={fps}",
        # Solo el identificador: el reloj quedaria congelado en la hora de la
        # conversion. La hora real la pone el grabador en cada segmento.
        f"drawtext=text='{camara_id}':x=10:y=10:"
        f"fontsize=18:fontcolor=white:box=1:boxcolor=black@0.5",
    ])
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", origen,
        "-vf", filtros,
        "-c:v", "libx264", "-preset", "veryfast",
        "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
        "-pix_fmt", "yuv420p",
        "-an",
        "-f", "mp4",
        destino,
    ]


def normalizar(videos: list[str], carpeta_cache: str = CARPETA_CACHE,
               ejecutar=subprocess.run) -> list[str]:
    """Convierte cada video una sola vez y devuelve las copias listas.

    El nombre de la copia lleva el tamano y la fecha del original: si alguien
    reemplaza un video por otro con el mismo nombre, se vuelve a convertir.
    Un video que ffmpeg no puede leer se salta con un aviso, sin tumbar la camara.
    """
    os.makedirs(carpeta_cache, exist_ok=True)
    listos = []
    for video in videos:
        datos = os.stat(video)
        base = os.path.splitext(os.path.basename(video))[0]
        copia = os.path.join(carpeta_cache,
                             f"{base}-{datos.st_size}-{int(datos.st_mtime)}.mp4")
        if not os.path.exists(copia):
            log.info("convirtiendo %s (solo la primera vez)", os.path.basename(video))
            temporal = copia + ".parcial"
            resultado = ejecutar(comando_normalizar(video, temporal), check=False)
            if resultado.returncode != 0:
                log.warning("no se pudo leer %s, se salta", os.path.basename(video))
                if os.path.exists(temporal):
                    os.remove(temporal)
                continue
            os.replace(temporal, copia)
        listos.append(copia)
    return listos


def construir_comando_videos(lista: str, destino: str = DESTINO) -> list[str]:
    """Publica los videos ya convertidos, en bucle, como si fueran la camara."""
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "warning",
        "-nostdin",
        "-re",
        # Bucle infinito sobre la lista entera: al terminar el ultimo video
        # vuelve al primero, y la camara nunca "se apaga".
        "-stream_loop", "-1",
        "-f", "concat",
        "-safe", "0",
        "-i", lista,
        # Sin recodificar: ya vienen convertidos, asi la camara casi no usa CPU.
        "-c", "copy",
        "-an",
        "-f", "rtsp",
        "-rtsp_transport", "tcp",
        destino,
    ]


def elegir_comando(carpeta: str = CARPETA_VIDEOS) -> list[str]:
    """Videos reales si hay en la carpeta; si no, la senal sintetica de siempre."""
    videos = buscar_videos(carpeta)
    if videos:
        log.info("camara %s: %d video(s) real(es) de %s, en bucle: %s",
                 CAMARA_ID, len(videos), carpeta,
                 ", ".join(os.path.basename(v) for v in videos))
        listos = normalizar(videos)
        if listos:
            return construir_comando_videos(escribir_lista(listos))
    if carpeta:
        log.info("camara %s: no hay videos utilizables en %s, se usa la senal sintetica",
                 CAMARA_ID, carpeta)
    return construir_comando()


def main() -> int:                       # pragma: no cover - punto de entrada
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("camara simulada %s publicando en %s", CAMARA_ID, DESTINO)
    # Se reintenta sola: el servidor RTSP puede tardar en levantarse y una
    # camara de verdad tampoco se rinde a la primera. La carpeta de videos se
    # relee en cada intento, para tomar los que se hayan agregado.
    while True:
        comando = elegir_comando()
        resultado = subprocess.run(comando, check=False)
        log.warning("la publicacion termino (codigo %s), reintentando en %s s",
                    resultado.returncode, SEGUNDOS_ENTRE_REINTENTOS)
        time.sleep(SEGUNDOS_ENTRE_REINTENTOS)


if __name__ == "__main__":               # pragma: no cover
    sys.exit(main())
