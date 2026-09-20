"""Invocacion de ffmpeg para el buffer circular. HU-05, criterio 1.

"Cada camara RTSP se graba en segmentos de 1 min con el muxer segment de ffmpeg
(-c copy, -strftime 1), que no reencodifica."

Reencodificar consumiria la GPU que el servicio YOLO necesita para HU-07 y
degradaria la imagen que luego sirve de evidencia. Con `-c copy` los paquetes
pasan tal cual del RTSP al archivo: la carga de CPU es la de copiar bytes.

Este modulo solo construye el comando y lo arranca. Vigilar el proceso y
reaccionar a sus caidas es cosa de app/grabador.py, de modo que la orden de
ffmpeg se puede revisar y probar sin lanzar un solo proceso.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
from dataclasses import dataclass

from app.config import Ajustes, Camara

# Nombre de cada segmento: camara-01_20260914-043000.mkv. La marca la escribe
# ffmpeg con -strftime 1, asi que el nombre dice cuando empieza el segmento sin
# tener que abrir el archivo. HU-06 buscara por ese nombre.
PATRON_DE_NOMBRE = "%Y%m%d-%H%M%S"
EXTENSION = ".mkv"

# Matroska y no MP4: un MP4 solo queda reproducible cuando se cierra bien. Si se
# corta la luz en mitad de un segmento, el .mp4 en curso se pierde entero y el
# .mkv se puede leer hasta donde llego, que es justo lo que hara falta.
FORMATO_DE_SEGMENTO = "matroska"

_NOMBRE = re.compile(r"^(?P<camara>.+)_(?P<marca>\d{8}-\d{6})" + re.escape(EXTENSION) + r"$")


@dataclass(frozen=True)
class Grabacion:
    """Un ffmpeg vivo grabando una camara."""

    camara: Camara
    proceso: subprocess.Popen
    comando: tuple[str, ...]

    def sigue_viva(self) -> bool:
        return self.proceso.poll() is None

    def detener(self, espera_s: float = 5.0) -> None:
        """Termina con SIGTERM para que ffmpeg cierre el segmento en curso."""
        if not self.sigue_viva():
            return
        self.proceso.terminate()
        try:
            self.proceso.wait(timeout=espera_s)
        except subprocess.TimeoutExpired:
            self.proceso.kill()
            self.proceso.wait(timeout=espera_s)


def carpeta_de(ajustes: Ajustes, camara: Camara) -> pathlib.Path:
    """Una carpeta por camara: purgar o revisar una no afecta a las demas."""
    return ajustes.directorio_buffer / camara.componente


def plantilla_de_salida(ajustes: Ajustes, camara: Camara) -> str:
    return str(carpeta_de(ajustes, camara) /
               f"{camara.componente}_{PATRON_DE_NOMBRE}{EXTENSION}")


def construir_comando(ajustes: Ajustes, camara: Camara) -> list[str]:
    """Arma la orden de ffmpeg para una camara."""
    espera_us = int(ajustes.segundos_de_espera_rtsp * 1_000_000)
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "warning",
        "-nostdin",
        # TCP y no UDP: en una planta con ruido electrico, UDP pierde paquetes y
        # el video queda con saltos justo en el momento que habra que revisar.
        "-rtsp_transport", "tcp",
        # Sin esto, una camara que deja de enviar deja a ffmpeg esperando para
        # siempre y la desconexion del criterio 3 no se detectaria nunca.
        # En ffmpeg 6 la opcion del demuxer RTSP se llama -timeout y se mide en
        # microsegundos; en las ramas 4.x se llamaba -stimeout.
        "-timeout", str(espera_us),
        "-i", camara.url,
        "-an",                      # el audio no aporta evidencia y ocupa
        "-c", "copy",               # criterio 1: no se reencodifica
        "-f", "segment",            # criterio 1: muxer segment
        "-segment_time", str(ajustes.segundos_por_segmento),
        "-segment_format", FORMATO_DE_SEGMENTO,
        # Corta en fotograma clave: sin esto el primer fotograma de un segmento
        # puede depender del segmento anterior y el clip de HU-06 empezaria roto.
        "-reset_timestamps", "1",
        "-strftime", "1",           # criterio 1
        plantilla_de_salida(ajustes, camara),
    ]


def iniciar(ajustes: Ajustes, camara: Camara) -> Grabacion:
    """Lanza ffmpeg para una camara y devuelve el proceso vivo."""
    carpeta_de(ajustes, camara).mkdir(parents=True, exist_ok=True)
    comando = construir_comando(ajustes, camara)
    proceso = subprocess.Popen(
        comando,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        # El error de ffmpeg es lo que explica por que se cayo una camara, asi
        # que se captura para dejarlo en salud_componente tal cual.
        stderr=subprocess.PIPE,
        text=True,
    )
    return Grabacion(camara=camara, proceso=proceso, comando=tuple(comando))


def ultimo_error(grabacion: Grabacion, lineas: int = 3) -> str:
    """Ultimas lineas de stderr, que es donde ffmpeg dice que fallo."""
    if grabacion.proceso.stderr is None:
        return ""
    texto = grabacion.proceso.stderr.read() or ""
    utiles = [linea.strip() for linea in texto.splitlines() if linea.strip()]
    return " | ".join(utiles[-lineas:])


def marca_de_segmento(ruta: pathlib.Path) -> str | None:
    """Extrae la marca de tiempo del nombre, o None si no sigue el patron.

    Se usa para no purgar por error un archivo que no puso el grabador.
    """
    encontrado = _NOMBRE.match(ruta.name)
    return encontrado.group("marca") if encontrado else None
