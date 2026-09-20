"""Fotogramas clave del clip. HU-09, y el criterio 3 de HU-12.

El apartado 6.4 dice que el servicio YOLO devuelve "conteo de sacos, personas y
fotogramas clave", y el 9.2 que al modelo de vision-lenguaje se le envian
imagenes ademas de los datos. HU-12 pedira ademas mostrar "el fotograma donde se
detecto la anomalia".

Un clip de 7 minutos a 15 fps son 6300 fotogramas. Mandarlos todos al modelo
seria imposible y caro; mandar uno cualquiera seria inutil. Lo que hace este
modulo es quedarse con los pocos que explican la carga, elegidos por lo que
ocurrio en ellos y no por su posicion en el video.

El orden de prioridad es el de la RN-04, que es la que decide la severidad:

  1. un saco que sale de la zona de carga hacia fuera del camion, que es
     severidad Alta por si solo;
  2. el momento de mayor presencia de personal, que es lo que sostiene el
     "personal no habitual" de la severidad Media;
  3. el primer y el ultimo saco que cruzan, que acotan la carga;
  4. el centro del clip, para que nunca se devuelva una lista vacia: un evento
     sin ninguna imagen deja al supervisor sin nada que mirar.

Este modulo no sabe nada de YOLO. Recibe indices, imagenes y lo que paso en cada
fotograma, y decide. Asi la regla de seleccion se prueba sin GPU y sin video.
"""
from __future__ import annotations

import dataclasses

# Motivos por los que un fotograma se guarda. Codigo estable: el dashboard y
# HU-12 los traducen, y buscar "cuantos eventos tuvieron un saco saliente" no
# puede depender de como estaba redactado el mensaje aquel mes.
SACO_SALIENTE = "saco_saliente"
PICO_DE_PERSONAS = "pico_de_personas"
PRIMER_SACO = "primer_saco"
ULTIMO_SACO = "ultimo_saco"
CENTRO_DEL_CLIP = "centro_del_clip"

# Mayor gana. El saco que sale es lo primero que hay que ver, porque es lo unico
# de esta lista que por si solo ya es severidad Alta.
PRIORIDAD = {
    SACO_SALIENTE: 100,
    PICO_DE_PERSONAS: 80,
    PRIMER_SACO: 60,
    ULTIMO_SACO: 50,
    CENTRO_DEL_CLIP: 10,
}

CALIDAD_JPEG = 80


@dataclasses.dataclass(frozen=True)
class Momento:
    """Algo que paso en un fotograma y que merece guardarlo."""

    motivo: str
    detalle: str
    # Desempata entre fotogramas del mismo motivo: con dos picos de personas se
    # guarda el mayor, no el primero que llego.
    magnitud: float = 0.0

    @property
    def prioridad(self) -> int:
        return PRIORIDAD.get(self.motivo, 0)


@dataclasses.dataclass
class _Candidato:
    fotograma: int
    momento: Momento
    imagen: object


@dataclasses.dataclass(frozen=True)
class FotogramaClave:
    """Un fotograma elegido, ya codificado en JPEG."""

    fotograma: int
    motivo: str
    detalle: str
    segundo: float
    jpeg: bytes

    @property
    def nombre(self) -> str:
        """Nombre del objeto en el almacen, legible en un listado de MinIO."""
        return f"f{self.fotograma:06d}_{self.motivo}.jpg"


def _codificar(imagen, calidad: int = CALIDAD_JPEG) -> bytes:
    """JPEG y no PNG: un fotograma de rampa comprime diez veces mejor y la
    diferencia no se ve. Estas imagenes viajan a una API externa."""
    import cv2

    ok, buffer = cv2.imencode(".jpg", imagen,
                              [int(cv2.IMWRITE_JPEG_QUALITY), calidad])
    if not ok:      # pragma: no cover - cv2 solo falla con una imagen invalida
        raise ValueError("No se pudo codificar el fotograma como JPEG")
    return bytes(buffer)


class SelectorDeFotogramas:
    """Se queda con los pocos fotogramas que explican la carga.

    Guarda una imagen por motivo, la de mayor magnitud, y al final devuelve las
    `maximo` de mas prioridad. Las demas se sueltan segun pasan: un clip de 7
    minutos a 1080p no cabe en memoria entero, que es la misma razon por la que
    el analisis va en flujo.
    """

    def __init__(self, maximo: int = 4, fps: float = 15.0, calidad: int = CALIDAD_JPEG):
        self.maximo = maximo
        self.fps = fps
        self.calidad = calidad
        self.mejores: dict[str, _Candidato] = {}

    def considerar(self, fotograma: int, imagen, momentos: list[Momento]) -> None:
        """Ofrece un fotograma con lo que paso en el."""
        if imagen is None:
            return
        for momento in momentos:
            actual = self.mejores.get(momento.motivo)
            if actual is None or momento.magnitud > actual.momento.magnitud:
                self.mejores[momento.motivo] = _Candidato(
                    fotograma=fotograma, momento=momento, imagen=imagen)
            elif momento.motivo == ULTIMO_SACO:
                # El ultimo es el ultimo: aqui gana el mas tardio, no el mayor.
                self.mejores[momento.motivo] = _Candidato(
                    fotograma=fotograma, momento=momento, imagen=imagen)

    def claves(self, codificar=_codificar) -> list[FotogramaClave]:
        """Los elegidos, ya en JPEG y ordenados como ocurrieron.

        Se eligen por prioridad y se devuelven por orden cronologico: elegir por
        importancia es lo que hace util la lista, y ordenarla por tiempo es lo
        que hace que se lea como la carga.
        """
        elegidos = sorted(self.mejores.values(),
                          key=lambda c: (-c.momento.prioridad, c.fotograma))
        elegidos = elegidos[:self.maximo]
        elegidos.sort(key=lambda c: c.fotograma)

        claves = []
        for candidato in elegidos:
            claves.append(FotogramaClave(
                fotograma=candidato.fotograma,
                motivo=candidato.momento.motivo,
                detalle=candidato.momento.detalle,
                segundo=round(candidato.fotograma / self.fps, 2) if self.fps else 0.0,
                jpeg=codificar(candidato.imagen, self.calidad),
            ))
        return claves


def momentos_del_fotograma(cruces, personas_en_zona: int, pico_previo: int,
                           es_primer_cruce: bool) -> list[Momento]:
    """Traduce lo que paso en un fotograma a motivos para guardarlo.

    `cruces` son los del contador de HU-07 y `personas_en_zona` lo que devolvio
    el seguidor de HU-08 en ese mismo fotograma: los dos salen de la pasada que
    ya se estaba haciendo, sin mirar el video una segunda vez.
    """
    momentos = []

    salientes = [c for c in cruces if c.sentido < 0]
    if salientes:
        momentos.append(Momento(
            motivo=SACO_SALIENTE,
            detalle=(f"{len(salientes)} saco(s) cruzaron la linea hacia fuera de "
                     f"la zona de carga. La RN-04 lo trata como severidad Alta."),
            magnitud=float(len(salientes))))

    entrantes = [c for c in cruces if c.sentido > 0]
    if entrantes and es_primer_cruce:
        momentos.append(Momento(
            motivo=PRIMER_SACO,
            detalle="Primer saco que cruza la linea de carga.",
            magnitud=1.0))
    if entrantes:
        momentos.append(Momento(
            motivo=ULTIMO_SACO,
            detalle="Ultimo saco que cruza la linea de carga.",
            magnitud=float(len(entrantes))))

    if personas_en_zona > 0 and personas_en_zona >= pico_previo:
        momentos.append(Momento(
            motivo=PICO_DE_PERSONAS,
            detalle=(f"{personas_en_zona} persona(s) a la vez en la zona de "
                     f"carga, el maximo del clip."),
            magnitud=float(personas_en_zona)))

    return momentos
