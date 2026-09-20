"""Recorte del clip de una ventana de tiempo. HU-06, criterios 1 y 3.

El buffer de HU-05 son segmentos de un minuto con la marca de inicio en el
nombre. Recortar una ventana es, entonces, tres pasos: elegir los segmentos que
la tocan, pegarlos y quedarse con el tramo pedido. Nada de eso reencodifica, asi
que un clip de siete minutos sale en segundos.

El criterio 3 pide distinguir "hay clip" de "no hay video para ese rango". Por
eso este modulo no devuelve solo un archivo: devuelve tambien que parte de la
ventana estaba cubierta, que es lo que permite decidir entre guardar el clip y
marcar el evento como Sin clip.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import pathlib
import subprocess

import structlog

from app import ffmpeg, retencion
from app.config import Ajustes

log = structlog.get_logger("quinor.recorte")

FORMATO_MARCA = "%Y%m%d-%H%M%S"


class SinVideoEnLaVentana(RuntimeError):
    """No hay ni un segmento que toque la ventana. Criterio 3: evento Sin clip."""


class RecorteFallido(RuntimeError):
    """ffmpeg no pudo producir el clip."""


@dataclasses.dataclass(frozen=True)
class Ventana:
    """Tramo de video que pide un evento."""

    desde: dt.datetime
    hasta: dt.datetime

    @property
    def duracion_s(self) -> float:
        return max(0.0, (self.hasta - self.desde).total_seconds())


@dataclasses.dataclass(frozen=True)
class Clip:
    """Resultado del recorte."""

    ruta: pathlib.Path
    ventana: Ventana
    camara: str
    segmentos_usados: int
    segundos_cubiertos: float

    @property
    def cobertura_pct(self) -> float:
        if not self.ventana.duracion_s:
            return 0.0
        return min(100.0, self.segundos_cubiertos / self.ventana.duracion_s * 100)

    @property
    def completo(self) -> bool:
        """Con un margen de un segundo: los segmentos no empiezan al milisegundo."""
        return self.segundos_cubiertos + 1 >= self.ventana.duracion_s


def ventana_de(inicio_carga: dt.datetime | None, fecha_hora: dt.datetime,
               ajustes: Ajustes) -> Ventana:
    """Criterio 1: desde 5 min antes del inicio de carga hasta 2 min despues del cierre.

    Cuando nadie marco el inicio, el origen es el propio cierre. El clip queda
    mas corto de lo que la historia pretende, pero sigue cubriendo los minutos
    que preceden a la pesada, que es donde ocurre lo que hay que mirar.
    """
    origen = inicio_carga or fecha_hora
    return Ventana(
        desde=origen - dt.timedelta(seconds=ajustes.segundos_antes),
        hasta=fecha_hora + dt.timedelta(seconds=ajustes.segundos_despues),
    )


def _inicio_de(ruta: pathlib.Path) -> dt.datetime | None:
    marca = ffmpeg.marca_de_segmento(ruta)
    try:
        return dt.datetime.strptime(marca, FORMATO_MARCA)
    except (TypeError, ValueError):
        return None


def segmentos_de_la_ventana(
    ajustes: Ajustes, camara: str, ventana: Ventana
) -> list[tuple[pathlib.Path, dt.datetime]]:
    """Segmentos de esa camara que tocan la ventana, en orden.

    Un segmento entra si su tramo se solapa con la ventana. El ultimo segmento
    anterior al inicio cuenta tambien: la ventana suele empezar a mitad de el.
    """
    carpeta = ajustes.directorio_buffer / camara
    candidatos = []
    for ruta in retencion.segmentos(carpeta):
        inicio = _inicio_de(ruta)
        if inicio is None:
            continue
        fin = inicio + dt.timedelta(seconds=ajustes.segundos_por_segmento)
        if fin > ventana.desde and inicio < ventana.hasta:
            candidatos.append((ruta, inicio))
    return candidatos


def _segundos_cubiertos(
    segmentos: list[tuple[pathlib.Path, dt.datetime]], ventana: Ventana,
    duracion_segmento: int,
) -> float:
    """Cuanto de la ventana cubren realmente esos segmentos.

    Se suman los solapes, no los segmentos: si falta un minuto por el medio
    porque la camara se cayo, la cuenta lo refleja y el criterio 3 puede actuar.
    """
    total = 0.0
    for _ruta, inicio in segmentos:
        fin = inicio + dt.timedelta(seconds=duracion_segmento)
        desde = max(inicio, ventana.desde)
        hasta = min(fin, ventana.hasta)
        if hasta > desde:
            total += (hasta - desde).total_seconds()
    return total


def recortar(
    ajustes: Ajustes,
    camara: str,
    ventana: Ventana,
    destino: pathlib.Path,
) -> Clip:
    """Produce el clip de esa ventana. Levanta SinVideoEnLaVentana si no hay nada.

    Se concatena con el demuxer concat y se recorta con `-ss` relativo al primer
    segmento. Todo con `-c copy`: reencodificar aqui consumiria la GPU que HU-07
    necesita, y el clip es evidencia, no una vista previa.
    """
    segmentos = segmentos_de_la_ventana(ajustes, camara, ventana)
    if not segmentos:
        raise SinVideoEnLaVentana(
            f"No hay video de {camara} entre {ventana.desde.isoformat()} y "
            f"{ventana.hasta.isoformat()}")

    cubiertos = _segundos_cubiertos(segmentos, ventana, ajustes.segundos_por_segmento)
    primer_inicio = segmentos[0][1]
    # Desplazamiento dentro del primer segmento. Nunca negativo: si la ventana
    # empieza antes de que hubiera video, el clip empieza donde empieza el video.
    desplazamiento = max(0.0, (ventana.desde - primer_inicio).total_seconds())

    destino.parent.mkdir(parents=True, exist_ok=True)
    lista = destino.parent / f"{destino.stem}_segmentos.txt"
    lista.write_text(
        "".join(f"file '{ruta.as_posix()}'\n" for ruta, _ in segmentos),
        encoding="utf-8")

    comando = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "concat", "-safe", "0", "-i", str(lista),
        # -ss despues de -i: mas lento que antes, pero corta donde se le pide y
        # no en el fotograma clave anterior. En un clip que es evidencia, que el
        # tramo sea el correcto importa mas que un segundo de proceso.
        "-ss", f"{desplazamiento:.3f}",
        "-t", f"{ventana.duracion_s:.3f}",
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        str(destino),
    ]
    resultado = subprocess.run(comando, capture_output=True, text=True, check=False)
    lista.unlink(missing_ok=True)

    if resultado.returncode != 0 or not destino.exists() or destino.stat().st_size == 0:
        raise RecorteFallido(
            f"ffmpeg no pudo recortar el clip de {camara}: "
            f"{(resultado.stderr or '').strip()[:300]}")

    clip = Clip(ruta=destino, ventana=ventana, camara=camara,
                segmentos_usados=len(segmentos), segundos_cubiertos=cubiertos)
    log.info("clip_recortado", camara=camara, segmentos=clip.segmentos_usados,
             segundos=round(ventana.duracion_s, 1),
             cobertura_pct=round(clip.cobertura_pct, 1),
             mb=round(destino.stat().st_size / 1_048_576, 2))
    return clip


def nombre_de_objeto(numero_orden: str, evento_id: int, camara: str,
                     ventana: Ventana) -> str:
    """Ruta del clip dentro del bucket.

    Por fecha y orden: un supervisor que busque a mano encuentra el dia, y el
    ciclo de vida de 12 meses del RNF-06 se aplica por prefijo sin mirar la base.
    """
    dia = ventana.desde.strftime("%Y/%m/%d")
    marca = ventana.desde.strftime(FORMATO_MARCA)
    return f"{dia}/{numero_orden}/evento-{evento_id}_{camara}_{marca}.mkv"
