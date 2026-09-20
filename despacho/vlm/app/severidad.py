"""Severidad de un evento. RN-04.

"Severidad Alta: diferencia de sacos igual o mayor a 2, o sacos que salen de la
zona de carga hacia fuera del camion. Media: diferencia de 1 saco o personal no
habitual. Baja: diferencia de peso sin diferencia de sacos."

Por que la decide una regla y no el modelo. El criterio 2 de HU-09 dice que la
respuesta del modelo trae severidad, y asi se pide y asi se guarda. Pero la
severidad del evento, la que HU-10 usa para decidir si suena un SMS a las tres
de la madrugada y la que HU-11 usa para ordenar la cola de revision, sale de
aqui. Tres razones:

  - la RN-04 ya la define con umbrales exactos, y una regla escrita no se
    negocia con la temperatura de un modelo;
  - es reproducible: el mismo clip da la misma severidad hoy y dentro de seis
    meses, que es lo que hace falta cuando un caso se discute;
  - se puede explicar. "Alta porque la diferencia fue de 3 sacos" es algo que un
    supervisor puede comprobar; "Alta porque el modelo lo dijo" no lo es.

La del modelo se guarda aparte, como `severidad_ia`, y de comparar las dos sale
la concordancia semanal que pide el apartado 9.2. Si el modelo acierta mejor que
la regla, eso se vera en esa medicion y entonces se decide, con datos delante.

Este modulo no llama a nadie ni sabe que es HTTP: recibe numeros y devuelve una
palabra. Por eso la RN-04 se puede probar entera sin levantar nada.
"""
from __future__ import annotations

import dataclasses

ALTA = "alta"
MEDIA = "media"
BAJA = "baja"

SEVERIDADES = (BAJA, MEDIA, ALTA)
# Para comparar dos severidades sin depender del orden alfabetico, que las
# dejaria como alta < baja < media.
ORDEN = {BAJA: 1, MEDIA: 2, ALTA: 3}

# RN-04: a partir de esta diferencia de sacos, la severidad es Alta.
SACOS_PARA_ALTA = 2


@dataclasses.dataclass(frozen=True)
class Severidad:
    """El nivel y por que, que es lo que hace que se pueda discutir."""

    nivel: str
    motivo: str
    regla: str = "RN-04"

    def __str__(self) -> str:      # pragma: no cover - comodidad al depurar
        return f"{self.nivel} ({self.motivo})"


def mayor(uno: str | None, otro: str | None) -> str | None:
    """La mas grave de dos severidades. None cuenta como la menos grave."""
    if uno is None:
        return otro
    if otro is None:
        return uno
    return uno if ORDEN.get(uno, 0) >= ORDEN.get(otro, 0) else otro


def es_valida(nivel: str | None) -> bool:
    return nivel in SEVERIDADES


def calcular(diferencia_sacos: int | None, sacos_salientes: int = 0,
             personal_anomalo: bool = False,
             hay_diferencia_de_peso: bool = True) -> Severidad:
    """Aplica la RN-04 tal como esta escrita.

    `diferencia_sacos` en None significa que el clip no se pudo analizar. No es
    lo mismo que cero, y se trata como lo que es: se sabe que el peso no cuadra y
    nada mas, que es exactamente la definicion de Baja.
    """
    diferencia = abs(diferencia_sacos) if diferencia_sacos is not None else 0

    if sacos_salientes > 0:
        # Un saco que sale de la zona de carga hacia fuera del camion no es un
        # error de conteo: es alguien sacando un saco.
        return Severidad(
            nivel=ALTA,
            motivo=(f"{sacos_salientes} saco(s) salieron de la zona de carga "
                    f"hacia fuera del camion."))

    if diferencia >= SACOS_PARA_ALTA:
        return Severidad(
            nivel=ALTA,
            motivo=f"La diferencia de sacos es {diferencia_sacos:+d}.")

    if diferencia == 1:
        return Severidad(
            nivel=MEDIA,
            motivo=f"La diferencia de sacos es {diferencia_sacos:+d}.")

    if personal_anomalo:
        return Severidad(
            nivel=MEDIA,
            motivo="La presencia de personal en la zona de carga no fue la habitual.")

    if hay_diferencia_de_peso:
        return Severidad(
            nivel=BAJA,
            motivo=("El peso no cuadra pero el conteo de sacos si: apunta a "
                    "producto sustituido o a un error de bascula, no a bultos "
                    "que falten."))

    return Severidad(
        nivel=BAJA,
        motivo="No se encontro ninguna diferencia que explicar.")
