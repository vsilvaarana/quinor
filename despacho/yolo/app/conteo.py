"""Conteo de sacos que cruzan la linea de carga. HU-07, criterio 1.

Detectar sacos no es contarlos. Un saco aparece en decenas de fotogramas
seguidos, y sumar detecciones daria cientos por carga. Lo que se cuenta es otra
cosa: cuantos objetos, cada uno con su identificador de seguimiento, pasaron de
un lado de la linea de carga al otro.

Ese planteamiento es tambien lo que hace el conteo robusto a las oclusiones que
el apartado 11 senala como riesgo. Si una persona tapa un saco tres fotogramas,
el identificador sobrevive y el cruce se cuenta una sola vez.

Este modulo no sabe nada de YOLO ni de video: recibe posiciones con
identificador y decide. Asi la regla se puede probar sin GPU y sin un solo
fotograma, y lo que se prueba es la regla, no la libreria de terceros.
"""
from __future__ import annotations

import dataclasses

# Un objeto tiene que estar claramente a un lado antes de que su paso cuente.
# Sin esta banda, un saco parado justo encima de la linea contaria una vez por
# cada temblor de la caja delimitadora.
MARGEN_DE_LA_LINEA = 0.01


@dataclasses.dataclass(frozen=True)
class Punto:
    x: float
    y: float


@dataclasses.dataclass(frozen=True)
class Deteccion:
    """Un objeto visto en un fotograma, ya seguido por el rastreador."""

    id_seguimiento: int
    clase: str
    confianza: float
    centro: Punto


@dataclasses.dataclass(frozen=True)
class Cruce:
    """Un saco que paso la linea."""

    id_seguimiento: int
    fotograma: int
    sentido: int          # +1 entra al camion, -1 sale


@dataclasses.dataclass
class _Rastro:
    """Lo que el contador recuerda de un identificador."""

    lado: int             # ultimo lado confirmado: +1, -1, o 0 si aun sobre la linea
    visto_en: int
    cruces: int = 0


class ContadorDeLinea:
    """Cuenta cruces de una linea recta, por identificador de seguimiento.

    La linea va en coordenadas relativas (0 a 1), asi que el contador no depende
    de la resolucion: cambiar la camara por otra de mas pixeles no obliga a
    recalibrar, que es justo lo que el apartado 9.1 quiere evitar.
    """

    def __init__(
        self,
        linea: tuple[float, float, float, float],
        clase: str,
        invertir: bool = False,
        memoria: int = 30,
    ):
        self.x1, self.y1, self.x2, self.y2 = linea
        self.clase = clase
        self.signo = -1 if invertir else 1
        self.memoria = memoria
        self.rastros: dict[int, _Rastro] = {}
        self.cruces: list[Cruce] = []

    # ------------------------------------------------------------------ geometria
    def lado_de(self, punto: Punto) -> int:
        """De que lado de la linea cae un punto: +1, -1, o 0 si esta encima.

        Es el signo del producto vectorial entre la linea y el vector al punto.
        """
        # El signo se elige para que, con la linea vertical por defecto, el lado
        # derecho sea el positivo: una camara que mira la rampa de costado ve al
        # camion a la derecha, y asi "entrante" es lo que va hacia el camion sin
        # tener que invertir nada.
        producto = ((self.y2 - self.y1) * (punto.x - self.x1)
                    - (self.x2 - self.x1) * (punto.y - self.y1))
        if abs(producto) < MARGEN_DE_LA_LINEA:
            return 0
        return 1 if producto > 0 else -1

    # -------------------------------------------------------------------- conteo
    def procesar(self, fotograma: int, detecciones: list[Deteccion]) -> list[Cruce]:
        """Alimenta un fotograma y devuelve los cruces que ocurrieron en el."""
        nuevos: list[Cruce] = []
        for deteccion in detecciones:
            if deteccion.clase != self.clase:
                continue
            lado = self.lado_de(deteccion.centro)
            rastro = self.rastros.get(deteccion.id_seguimiento)

            if rastro is None:
                # Primera vez que se ve: se anota de que lado aparecio y ya esta.
                # Un saco que entra en cuadro ya pasada la linea no cruzo nada.
                self.rastros[deteccion.id_seguimiento] = _Rastro(
                    lado=lado, visto_en=fotograma)
                continue

            rastro.visto_en = fotograma
            if lado == 0:
                # Justo encima de la linea: todavia no se sabe. Se espera.
                continue
            if rastro.lado == 0:
                rastro.lado = lado
                continue
            if lado != rastro.lado:
                cruce = Cruce(id_seguimiento=deteccion.id_seguimiento,
                              fotograma=fotograma,
                              sentido=self.signo * lado)
                self.cruces.append(cruce)
                nuevos.append(cruce)
                rastro.cruces += 1
                rastro.lado = lado

        self._olvidar(fotograma)
        return nuevos

    def _olvidar(self, fotograma: int) -> None:
        """Suelta los identificadores que llevan mucho sin aparecer.

        Sin esto, un clip largo acumularia miles de rastros. Y con memoria de
        sobra, un identificador reutilizado por el rastreador heredaria el lado
        de otro objeto y inventaria un cruce.
        """
        caducados = [i for i, r in self.rastros.items()
                     if fotograma - r.visto_en > self.memoria]
        for identificador in caducados:
            del self.rastros[identificador]

    # ------------------------------------------------------------------ resultado
    @property
    def entrantes(self) -> int:
        """Sacos que cruzaron hacia el camion. Es el conteo del criterio 1."""
        return sum(1 for c in self.cruces if c.sentido > 0)

    @property
    def salientes(self) -> int:
        """Sacos que cruzaron en sentido contrario.

        La RN-04 los trata como senal de severidad Alta: un saco que sale de la
        zona de carga hacia fuera del camion no es un error de conteo.
        """
        return sum(1 for c in self.cruces if c.sentido < 0)

    @property
    def total(self) -> int:
        """Conteo neto: lo que entro menos lo que volvio a salir."""
        return self.entrantes - self.salientes


def precision_de_conteo(contados: int, reales: int) -> float:
    """Precision de una carga, en porcentaje. Criterio 2 y KPI del apartado 3.

    Se mide como el error relativo respecto a lo que habia que contar. Contar
    99 de 100 es un 99 %; contar 90, un 90 %. Pasarse cuenta igual que quedarse
    corto: un saco de mas manda a alguien a la rampa para nada.
    """
    if reales <= 0:
        return 100.0 if contados == 0 else 0.0
    error = abs(contados - reales) / reales
    return max(0.0, (1.0 - error) * 100.0)
