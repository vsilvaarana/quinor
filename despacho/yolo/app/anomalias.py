"""Presencia anomala de personal, sin identificar a nadie. HU-08.

La historia habla de "personal no autorizado o movimientos anomalos", la RN-03
manda invocar el modelo de vision-lenguaje solo cuando YOLO confirma diferencia
de sacos "o presencia anomala de personal", y la RN-04 pone "personal no
habitual" en severidad Media. Hacen falta, entonces, dos cosas: una senal, y que
esa senal no venga de saber quien es nadie.

Como se resuelve sin identidad. "No autorizado" no se puede decidir sin una lista
de personas, y una lista de personas es justo lo que la RN-08 prohibe. Lo que si
se puede medir es el comportamiento del grupo y del tiempo, que es lo que estas
reglas miran:

  - cuanta gente hubo a la vez, frente a la que cabe en una rampa normal;
  - si alguien se quedo mucho mas de lo que dura una carga;
  - si hubo gente en zona mientras no cruzaba ni un saco.

Ninguna mira un rostro, ni compara una persona con otra, ni con otro clip.
Las tres son configurables, porque lo habitual en una rampa lo sabe QUINOR y no
este codigo: los valores por defecto son un punto de partida para el piloto.

Que no es esto. No es una acusacion ni una conclusion. Es un motivo para que un
supervisor mire el clip, y el disparo que la RN-03 necesita para no llamar al
modelo de vision-lenguaje en cada carga. La decision sobre una persona la toma
una persona, con la politica de RR. HH. delante (apartado 8).
"""
from __future__ import annotations

import dataclasses

from app.config import Ajustes
from app.personas import Resumen

# Motivos. Se guardan como codigo y no como frase para que el dashboard y HU-09
# los traduzcan, y para que buscar "cuantas cargas tuvieron demasiada gente" no
# dependa de como estaba redactado el mensaje aquel mes.
DEMASIADA_GENTE = "demasiadas_personas_a_la_vez"
PERMANENCIA_LARGA = "permanencia_excesiva"
SIN_CARGA = "personas_sin_movimiento_de_sacos"


@dataclasses.dataclass(frozen=True)
class Motivo:
    """Por que se marco anomala la presencia, con el numero que lo sostiene."""

    codigo: str
    detalle: str
    medido: float
    umbral: float


@dataclasses.dataclass(frozen=True)
class Anomalia:
    """El resultado de aplicar las reglas a una carga."""

    motivos: tuple[Motivo, ...]

    @property
    def hay(self) -> bool:
        """La senal que la RN-03 usa para decidir si invocar a HU-09."""
        return bool(self.motivos)

    @property
    def codigos(self) -> tuple[str, ...]:
        return tuple(m.codigo for m in self.motivos)


def evaluar(ajustes: Ajustes, resumen: Resumen, sacos_contados: int) -> Anomalia:
    """Aplica las reglas. Nada de lo que entra aqui identifica a nadie."""
    motivos: list[Motivo] = []

    if resumen.maximo_simultaneo > ajustes.personas_habituales:
        motivos.append(Motivo(
            codigo=DEMASIADA_GENTE,
            detalle=(f"Hubo {resumen.maximo_simultaneo} personas a la vez en la "
                     f"zona de carga y lo habitual son "
                     f"{ajustes.personas_habituales}."),
            medido=float(resumen.maximo_simultaneo),
            umbral=float(ajustes.personas_habituales)))

    if resumen.permanencia_maxima_s > ajustes.permanencia_maxima_s:
        motivos.append(Motivo(
            codigo=PERMANENCIA_LARGA,
            detalle=(f"Alguien estuvo {resumen.permanencia_maxima_s:.0f} s en la "
                     f"zona de carga, por encima de los "
                     f"{ajustes.permanencia_maxima_s:.0f} s de una carga normal."),
            medido=resumen.permanencia_maxima_s,
            umbral=ajustes.permanencia_maxima_s))

    if resumen.cuantas > 0 and sacos_contados == 0:
        # Gente en la rampa y ningun saco cruzando la linea. Puede ser una
        # limpieza o una revision, y puede ser lo otro; en los dos casos merece
        # que alguien mire el clip antes de archivar la carga.
        motivos.append(Motivo(
            codigo=SIN_CARGA,
            detalle=(f"Hubo {resumen.cuantas} persona(s) en la zona de carga y "
                     f"ningun saco cruzo la linea."),
            medido=float(resumen.cuantas),
            umbral=0.0))

    return Anomalia(motivos=tuple(motivos))
