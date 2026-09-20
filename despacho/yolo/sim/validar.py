"""Medida de la precision del conteo. HU-07, criterio 2.

"La precision del conteo en el set de validacion es igual o mayor a 95 %."

El set de validacion son cargas sinteticas de `sim/rampa_sim.py`, cada una con
un numero conocido de sacos. Este script las analiza con el servicio y compara
lo contado con lo que habia, carga por carga.

Que mide y que no. Mide el contador completo: deteccion, seguimiento,
oclusiones por personas que pasan delante, sacos que vuelven atras y cruces a
distinta velocidad. No mide como se comportara el modelo con sacos de yute
reales, polvo y contraluz. Esa cifra sale del piloto de 4 semanas con el dataset
de HU-19, y el criterio de salida del piloto es el mismo 95 %.

    python -m sim.validar --pesos modelos/sacos.pt
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import pathlib
import statistics
import tempfile

from app.analisis import analizar
from app.config import PRECISION_MINIMA_PCT, Ajustes
from app.conteo import precision_de_conteo

RAIZ = pathlib.Path(__file__).resolve().parent.parent

# RNF-01: un clip de 7 min se analiza en menos de 3, o sea 3/7 del tiempo que
# dura el video.
RNF01_VECES_EL_VIDEO = 3 / 7

# Las cargas del set. Cada tupla es (sacos que cruzan, sacos que vuelven,
# personas que pasan por delante, semilla). La variedad es deliberada: una carga
# sin nada que la complique no diria si el contador aguanta una rampa real.
CARGAS = (
    (4, 0, 0, 11),      # carga limpia, sin nadie en cuadro
    (6, 0, 1, 12),      # con un operario tapando sacos
    (8, 0, 2, 13),      # dos operarios: mas oclusiones
    (10, 0, 1, 14),     # carga larga
    (5, 1, 1, 15),      # un saco cruza y vuelve: no debe contar (RN-04)
    (7, 0, 2, 16),
    (3, 0, 1, 17),      # carga corta
    (9, 1, 2, 18),      # larga, con oclusiones y un saco que vuelve
)


@dataclasses.dataclass(frozen=True)
class Medicion:
    """Resultado de una carga del set."""

    sacos_reales: int
    sacos_contados: int
    sacos_que_vuelven: int
    personas: int
    precision_pct: float
    segundos_de_proceso: float
    duracion_del_clip_s: float


@dataclasses.dataclass(frozen=True)
class Informe:
    """Lo que el criterio 2 pide poder mirar."""

    mediciones: tuple[Medicion, ...]
    precision_media_pct: float
    precision_minima_pct: float
    cargas_exactas: int
    error_medio_sacos: float
    umbral_pct: float
    dispositivo: str = "cpu"

    @property
    def veces_el_video(self) -> float:
        """Cuanto tarda el analisis por cada segundo de clip.

        Por debajo de 1 el analisis va mas rapido que el video. El RNF-01 pide
        analizar un clip de 7 min en menos de 3, o sea 0.43.
        """
        video = sum(m.duracion_del_clip_s for m in self.mediciones)
        proceso = sum(m.segundos_de_proceso for m in self.mediciones)
        return round(proceso / video, 2) if video else 0.0

    @property
    def cumple_rnf01(self) -> bool:
        return self.veces_el_video <= RNF01_VECES_EL_VIDEO

    @property
    def cumple(self) -> bool:
        """El criterio mide la precision del conteo en el set, que es la media."""
        return self.precision_media_pct >= self.umbral_pct

    @property
    def total_cargas(self) -> int:
        return len(self.mediciones)


def validar(ajustes: Ajustes, carpeta: pathlib.Path | None = None,
            cargas=CARGAS, modelo=None) -> Informe:
    """Genera el set, lo analiza y devuelve el informe."""
    from sim.rampa_sim import generar_carga

    temporal = None
    if carpeta is None:
        temporal = tempfile.TemporaryDirectory(prefix="quinor-validacion-")
        carpeta = pathlib.Path(temporal.name)

    try:
        mediciones = []
        for sacos, vuelven, personas, semilla in cargas:
            clip = carpeta / f"carga_{semilla}_{sacos}sacos.mp4"
            generar_carga(clip, sacos=sacos, semilla=semilla,
                          con_personas=personas, sacos_que_vuelven=vuelven)
            resultado = analizar(ajustes, clip, modelo=modelo)
            mediciones.append(Medicion(
                sacos_reales=sacos,
                sacos_contados=resultado.sacos_contados,
                sacos_que_vuelven=vuelven,
                personas=personas,
                precision_pct=round(
                    precision_de_conteo(resultado.sacos_contados, sacos), 2),
                segundos_de_proceso=resultado.segundos_de_proceso,
                duracion_del_clip_s=resultado.duracion_del_clip_s,
            ))
    finally:
        if temporal is not None:
            temporal.cleanup()

    precisiones = [m.precision_pct for m in mediciones]
    errores = [abs(m.sacos_contados - m.sacos_reales) for m in mediciones]
    return Informe(
        mediciones=tuple(mediciones),
        precision_media_pct=round(statistics.fmean(precisiones), 2),
        precision_minima_pct=round(min(precisiones), 2),
        cargas_exactas=sum(1 for e in errores if e == 0),
        error_medio_sacos=round(statistics.fmean(errores), 3),
        umbral_pct=PRECISION_MINIMA_PCT,
        dispositivo=ajustes.dispositivo,
    )


def formatear(informe: Informe, pesos: pathlib.Path) -> str:
    """El reporte que se guarda junto al codigo, con su advertencia."""
    lineas = [
        "Validacion del conteo de sacos - HU-07, criterio 2",
        f"Generado: {dt.date.today().isoformat()}",
        f"Modelo:   {pesos}",
        "",
        "ADVERTENCIA: el set de validacion es sintetico. QUINOR todavia no ha",
        "entregado fotogramas de la rampa, y el dataset propio etiquetado es",
        "HU-19. Esta cifra mide el contador (deteccion, seguimiento, oclusiones,",
        "cruces y retornos), no el comportamiento del modelo con sacos de yute",
        "reales, polvo y contraluz. La cifra de planta sale del piloto.",
        "",
        f"{'sacos':>6} {'contados':>9} {'vuelven':>8} {'personas':>9} "
        f"{'precision':>10} {'clip s':>8} {'proceso s':>10}",
    ]
    for m in informe.mediciones:
        lineas.append(
            f"{m.sacos_reales:>6} {m.sacos_contados:>9} {m.sacos_que_vuelven:>8} "
            f"{m.personas:>9} {m.precision_pct:>9.2f}% {m.duracion_del_clip_s:>8.1f} "
            f"{m.segundos_de_proceso:>10.1f}")
    lineas += [
        "",
        f"Cargas evaluadas:        {informe.total_cargas}",
        f"Cargas exactas:          {informe.cargas_exactas}",
        f"Error medio:             {informe.error_medio_sacos} sacos por carga",
        f"Precision media:         {informe.precision_media_pct} %",
        f"Precision de la peor:    {informe.precision_minima_pct} %",
        f"Umbral del criterio 2:   {informe.umbral_pct} %",
        f"Resultado:               {'CUMPLE' if informe.cumple else 'NO CUMPLE'}",
        "",
        "Velocidad (RNF-01, informativo: el criterio 2 mide precision)",
        f"  Dispositivo:           {informe.dispositivo}",
        f"  Analisis por segundo de clip: {informe.veces_el_video} s",
        f"  Objetivo del RNF-01:   {RNF01_VECES_EL_VIDEO:.2f} s "
        f"(7 min de clip en menos de 3)",
        f"  En este dispositivo:   "
        f"{'cumple' if informe.cumple_rnf01 else 'NO cumple, hace falta la GPU del RNF-06'}",
    ]
    return "\n".join(lineas) + "\n"


def main() -> int:      # pragma: no cover - punto de entrada
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--pesos", type=pathlib.Path,
                            default=RAIZ / "modelos" / "sacos.pt")
    analizador.add_argument("--dispositivo", default="cpu")
    analizador.add_argument("--salida", type=pathlib.Path,
                            default=RAIZ / "reporte_validacion.txt")
    argumentos = analizador.parse_args()

    ajustes = Ajustes(ruta_pesos=argumentos.pesos, dispositivo=argumentos.dispositivo)
    informe = validar(ajustes)
    texto = formatear(informe, argumentos.pesos)
    print(texto)
    argumentos.salida.write_text(texto, encoding="utf-8")
    return 0 if informe.cumple else 1


if __name__ == "__main__":      # pragma: no cover
    raise SystemExit(main())
