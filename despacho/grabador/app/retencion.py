"""Buffer circular: que se conserva y que se borra. HU-05, criterio 2.

"Se conservan al menos 72 h de video en disco local."

El buffer es circular por esta funcion, no por ffmpeg: el muxer segment escribe
sin parar y alguien tiene que cerrar el circulo. Se purga por antiguedad y,
cuando el disco aprieta, tambien por espacio.

La decision al quedarse sin disco es seguir grabando y avisar. Dejar de grabar
protegeria el video viejo a costa de perder las cargas de hoy, que son las que
todavia se pueden investigar: el camion sigue en planta. Por eso se borra lo mas
antiguo aunque no llegue a las 72 h, y el componente disco queda en error para
que no pase inadvertido.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import shutil
from dataclasses import dataclass

import structlog

from app import ffmpeg
from app.config import Ajustes

log = structlog.get_logger("quinor.retencion")


@dataclass(frozen=True)
class ResultadoDePurga:
    """Lo que hizo una pasada de purga, para poder registrarlo y probarlo."""

    borrados_por_antiguedad: int = 0
    borrados_por_espacio: int = 0
    bytes_liberados: int = 0
    libre_pct: float = 100.0
    # True cuando hubo que borrar video que todavia no cumplia las 72 h.
    bajo_la_retencion_minima: bool = False

    @property
    def total_borrados(self) -> int:
        return self.borrados_por_antiguedad + self.borrados_por_espacio


def segmentos(directorio: pathlib.Path) -> list[pathlib.Path]:
    """Segmentos del buffer, del mas antiguo al mas reciente.

    Solo los que siguen el patron de nombre del grabador: si alguien deja otro
    archivo en la carpeta, no es asunto de la purga borrarlo.
    """
    if not directorio.exists():
        return []
    encontrados = [ruta for ruta in directorio.rglob(f"*{ffmpeg.EXTENSION}")
                   if ruta.is_file() and ffmpeg.marca_de_segmento(ruta)]
    # Por nombre y no por mtime: el nombre lleva la marca que puso -strftime, y
    # copiar o restaurar la carpeta cambiaria las fechas del sistema de archivos.
    return sorted(encontrados, key=lambda r: (r.name, r))


def _libre_pct(directorio: pathlib.Path) -> float:
    uso = shutil.disk_usage(directorio)
    return uso.free / uso.total * 100 if uso.total else 100.0


def _borrar(ruta: pathlib.Path) -> int:
    """Borra un segmento y devuelve cuantos bytes libero."""
    try:
        tamano = ruta.stat().st_size
        ruta.unlink()
        return tamano
    except FileNotFoundError:
        # Otra pasada lo borro primero, o ffmpeg rota justo ahora. No es un error.
        return 0


def _es_antiguo(ruta: pathlib.Path, limite: dt.datetime) -> bool:
    marca = ffmpeg.marca_de_segmento(ruta)
    try:
        return dt.datetime.strptime(marca, "%Y%m%d-%H%M%S") < limite
    except (TypeError, ValueError):
        return False


def purgar(ajustes: Ajustes, ahora: dt.datetime | None = None) -> ResultadoDePurga:
    """Cierra el circulo del buffer. Devuelve que se borro y por que."""
    directorio = ajustes.directorio_buffer
    if not directorio.exists():
        return ResultadoDePurga()

    ahora = ahora or dt.datetime.now().replace(tzinfo=None)
    limite = ahora - dt.timedelta(hours=ajustes.horas_de_retencion)

    liberados = 0
    por_antiguedad = 0
    for ruta in segmentos(directorio):
        if _es_antiguo(ruta, limite):
            liberados += _borrar(ruta)
            por_antiguedad += 1

    # Segunda vuelta: si el disco sigue apretado, se borra lo mas antiguo que
    # queda aunque todavia no cumpla las 72 h. Grabar es lo primero.
    por_espacio = 0
    bajo_minimo = False
    restantes = segmentos(directorio)
    while (_libre_pct(directorio) < ajustes.minimo_libre_pct
           and len(restantes) > 1):        # nunca el que ffmpeg esta escribiendo
        liberados += _borrar(restantes.pop(0))
        por_espacio += 1
        bajo_minimo = True

    libre = _libre_pct(directorio)
    resultado = ResultadoDePurga(
        borrados_por_antiguedad=por_antiguedad,
        borrados_por_espacio=por_espacio,
        bytes_liberados=liberados,
        libre_pct=round(libre, 2),
        bajo_la_retencion_minima=bajo_minimo,
    )
    if resultado.total_borrados:
        log.info("purga", borrados=resultado.total_borrados,
                 mb_liberados=round(liberados / 1_048_576, 1),
                 libre_pct=resultado.libre_pct,
                 bajo_retencion=bajo_minimo)
    return resultado


def horas_en_buffer(ajustes: Ajustes, ahora: dt.datetime | None = None) -> float:
    """Cuanto video queda, en horas, medido del segmento mas viejo a ahora.

    Es la cifra que responde al criterio 2 sin tener que abrir un solo archivo.
    """
    encontrados = segmentos(ajustes.directorio_buffer)
    if not encontrados:
        return 0.0
    marca = ffmpeg.marca_de_segmento(encontrados[0])
    try:
        primero = dt.datetime.strptime(marca, "%Y%m%d-%H%M%S")
    except (TypeError, ValueError):        # pragma: no cover - filtrado antes
        return 0.0
    ahora = ahora or dt.datetime.now().replace(tzinfo=None)
    return max(0.0, (ahora - primero).total_seconds() / 3600)
