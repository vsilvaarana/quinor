"""Seguimiento de las personas presentes en la zona de carga. HU-08.

Como supervisor de despacho, quiero que el sistema haga seguimiento de las
personas presentes en la zona de carga durante el evento, para identificar si
hubo personal no autorizado o movimientos anomalos.

Criterios de aceptacion:
  1. Se detecta y sigue a cada persona con un ID temporal durante el clip.
  2. Se registra cuantas personas estuvieron en zona y el tiempo de permanencia.
  3. No se realiza identificacion facial ni se guardan datos biometricos.

El criterio 3 no es una restriccion que se cumpla por omision, es la forma del
modulo. Aqui no entra ni sale una imagen: lo que se recibe son posiciones con un
numero de seguimiento, y lo que se devuelve son ese numero, dos instantes y unos
segundos. No hay rostro, ni huella, ni descriptor, ni nada que permita reconocer
a la misma persona en otro clip. El identificador lo asigna ByteTrack, vale solo
dentro de este video y se reinicia con el siguiente, tal como dice el apartado 8
del documento y exige la Ley 29733.

Ese diseno tiene una consecuencia que conviene decir en voz alta: si un mismo
operario sale del cuadro y vuelve, el rastreador le da otro numero y este modulo
lo cuenta como dos presencias. Es el precio de no identificar a nadie, y es el
lado correcto en el que equivocarse.

Como HU-07, este modulo no sabe nada de YOLO ni de video, asi que su regla se
prueba sin GPU y sin un solo fotograma.
"""
from __future__ import annotations

import dataclasses

from app.conteo import Deteccion, Punto


@dataclasses.dataclass(frozen=True)
class Zona:
    """La zona de carga, en coordenadas relativas.

    Rectangulo de esquina superior izquierda a inferior derecha. Relativo y no
    en pixeles por lo mismo que la linea de HU-07: cambiar la camara por otra de
    mas resolucion no deberia obligar a recalibrar (apartado 9.1).
    """

    x1: float
    y1: float
    x2: float
    y2: float

    @classmethod
    def desde(cls, valores: tuple[float, float, float, float]) -> "Zona":
        return cls(*valores)

    def contiene(self, punto: Punto) -> bool:
        return self.x1 <= punto.x <= self.x2 and self.y1 <= punto.y <= self.y2

    @property
    def es_todo_el_cuadro(self) -> bool:
        return (self.x1, self.y1, self.x2, self.y2) == (0.0, 0.0, 1.0, 1.0)


@dataclasses.dataclass
class Presencia:
    """Una persona en la zona, durante este clip y solo durante este clip.

    `id_temporal` es el numero que puso el rastreador. No identifica a nadie: no
    se puede cruzar con otro clip, con una nomina ni con un control de acceso.
    """

    id_temporal: int
    primer_fotograma: int
    ultimo_fotograma: int
    fotogramas_en_zona: int = 0

    def segundos(self, fps: float) -> float:
        """Tiempo de permanencia. Criterio 2.

        Se mide sobre los fotogramas en los que estuvo dentro de la zona, no
        sobre la distancia entre el primero y el ultimo: alguien que entra, se va
        y vuelve no estuvo todo ese rato en la rampa.
        """
        return round(self.fotogramas_en_zona / fps, 2) if fps else 0.0


@dataclasses.dataclass(frozen=True)
class PersonaObservada:
    """Lo que se informa de una persona. Es todo lo que se guarda de ella."""

    id_temporal: int
    segundos_en_zona: float
    primer_fotograma: int
    ultimo_fotograma: int


@dataclasses.dataclass(frozen=True)
class Resumen:
    """Lo que HU-08 pide registrar, y lo que HU-09 recibira como entrada."""

    personas: tuple[PersonaObservada, ...]
    maximo_simultaneo: int
    segundos_totales: float
    zona_completa: bool

    @property
    def cuantas(self) -> int:
        """Criterio 2: cuantas personas estuvieron en zona."""
        return len(self.personas)

    @property
    def permanencia_maxima_s(self) -> float:
        return max((p.segundos_en_zona for p in self.personas), default=0.0)

    @property
    def permanencia_media_s(self) -> float:
        if not self.personas:
            return 0.0
        return round(self.segundos_totales / len(self.personas), 2)


class SeguidorDePersonas:
    """Sigue a las personas por su identificador temporal. Criterios 1 y 2.

    Recibe las detecciones de cada fotograma, ya con identificador puesto por el
    rastreador, y lleva la cuenta de quien estuvo dentro de la zona y cuanto.
    """

    def __init__(self, zona: Zona, clase: str = "person",
                 permanencia_minima_s: float = 1.0):
        self.zona = zona
        self.clase = clase
        self.permanencia_minima_s = permanencia_minima_s
        self.presencias: dict[int, Presencia] = {}
        self.maximo_simultaneo = 0

    def procesar(self, fotograma: int, detecciones: list[Deteccion]) -> int:
        """Alimenta un fotograma y devuelve cuantas personas habia en zona."""
        en_zona = 0
        for deteccion in detecciones:
            if deteccion.clase != self.clase:
                continue
            if not self.zona.contiene(deteccion.centro):
                # Visible pero fuera de la zona: alguien que pasa por el fondo
                # del cuadro no estuvo en la rampa, y contarlo convertiria el
                # dato en ruido justo cuando hay que decidir si bajar a mirar.
                continue
            en_zona += 1
            presencia = self.presencias.get(deteccion.id_seguimiento)
            if presencia is None:
                self.presencias[deteccion.id_seguimiento] = Presencia(
                    id_temporal=deteccion.id_seguimiento,
                    primer_fotograma=fotograma, ultimo_fotograma=fotograma,
                    fotogramas_en_zona=1)
                continue
            presencia.ultimo_fotograma = fotograma
            presencia.fotogramas_en_zona += 1

        self.maximo_simultaneo = max(self.maximo_simultaneo, en_zona)
        return en_zona

    def resumen(self, fps: float, salto: int = 1) -> Resumen:
        """Lo observado, ya en segundos.

        `salto` son los fotogramas de video que hay entre dos mirados: con salto
        2 cada fotograma visto vale por dos de reloj, y sin eso la permanencia
        saldria a la mitad.
        """
        fps_efectivo = fps / salto if salto else fps
        observadas = []
        for presencia in sorted(self.presencias.values(),
                                key=lambda p: p.primer_fotograma):
            segundos = presencia.segundos(fps_efectivo)
            if segundos < self.permanencia_minima_s:
                # Un parpadeo del detector no es una persona que estuvo en la
                # rampa. Sin este minimo, el conteo de la carga se infla solo.
                continue
            observadas.append(PersonaObservada(
                id_temporal=presencia.id_temporal,
                segundos_en_zona=segundos,
                primer_fotograma=presencia.primer_fotograma,
                ultimo_fotograma=presencia.ultimo_fotograma))

        return Resumen(
            personas=tuple(observadas),
            maximo_simultaneo=self.maximo_simultaneo,
            segundos_totales=round(sum(p.segundos_en_zona for p in observadas), 2),
            zona_completa=self.zona.es_todo_el_cuadro,
        )
