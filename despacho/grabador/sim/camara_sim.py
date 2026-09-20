"""Simulador de camara IP. Sprint 2.

No hay acceso a las camaras de la rampa mientras el proyecto este en desarrollo,
igual que no lo hay a la bascula ni al ERP. Este proceso publica una senal
sintetica con el identificador de camara y el reloj impresos en la imagen, de
modo que al abrir un segmento se ve de que camara es y de que minuto.

Una camara IP es un servidor RTSP, asi que el simulador necesita uno delante: el
servicio `rtsp-server` del compose (mediamtx). Este proceso publica contra el, y
el grabador se conecta como lo haria contra la camara real, sin saber que hay un
simulador al otro lado.

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


def main() -> int:                       # pragma: no cover - punto de entrada
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    comando = construir_comando()
    log.info("camara simulada %s publicando en %s", CAMARA_ID, DESTINO)
    # Se reintenta sola: el servidor RTSP puede tardar en levantarse y una
    # camara de verdad tampoco se rinde a la primera.
    while True:
        resultado = subprocess.run(comando, check=False)
        log.warning("la publicacion termino (codigo %s), reintentando en %s s",
                    resultado.returncode, SEGUNDOS_ENTRE_REINTENTOS)
        time.sleep(SEGUNDOS_ENTRE_REINTENTOS)


if __name__ == "__main__":               # pragma: no cover
    sys.exit(main())
