"""Cuando se invoca al modelo. HU-09 criterio 1, y RN-03.

  1. Solo se invoca cuando YOLO confirma diferencia de sacos o personal anomalo.

La RN-03 lo dice con su motivo: "para controlar el costo". Cada llamada cuesta
dinero y unos segundos, y la mayoria de los eventos de peso son ajustes de
bascula o humedad, no hurtos. Llamar en todos seria pagar por describir cargas
normales.

Pero hay un segundo motivo, menos obvio y mas importante: un analisis que
aparece en todos los eventos deja de leerse. Si el supervisor ve una descripcion
de IA en cada fila, incluidas las cuarenta cargas correctas de la semana, deja de
mirarlas, y entonces tampoco mira la que importaba. Que el analisis solo aparezca
cuando algo lo justifica es lo que hace que se lea.

Este modulo es la puerta. Devuelve si se llama y, cuando no, por que no: un
evento sin analisis y sin explicacion parece un fallo del sistema, y alguien
acabara reintentandolo a mano.
"""
from __future__ import annotations

import dataclasses

# Motivos por los que si se invoca.
DIFERENCIA_DE_SACOS = "diferencia_de_sacos"
SACOS_SALIENTES = "sacos_salientes"
PERSONAL_ANOMALO = "personal_anomalo"

# Y por los que no.
SIN_ANALISIS_DE_VIDEO = "sin_analisis_de_video"
NADA_QUE_EXPLICAR = "nada_que_explicar"


@dataclasses.dataclass(frozen=True)
class Decision:
    """Si se llama al modelo y por que."""

    invocar: bool
    motivos: tuple[str, ...]
    explicacion: str

    @property
    def codigo(self) -> str:
        """El primero, que es el que manda. Vacio si no se invoca."""
        return self.motivos[0] if self.motivos else ""


def decidir(diferencia_sacos: int | None, sacos_salientes: int = 0,
            personal_anomalo: bool | None = False) -> Decision:
    """Aplica la RN-03 sobre lo que devolvio YOLO.

    `diferencia_sacos` y `personal_anomalo` en None significan que el clip aun no
    se analizo. Sin conteo no hay nada que YOLO haya confirmado, y la RN-03 pide
    justamente esa confirmacion: se espera en lugar de llamar a ciegas.
    """
    if diferencia_sacos is None and personal_anomalo is None:
        return Decision(
            invocar=False, motivos=(SIN_ANALISIS_DE_VIDEO,),
            explicacion=("El clip todavia no se ha analizado con YOLO. La RN-03 "
                         "pide que YOLO confirme antes de llamar al modelo."))

    motivos = []
    if sacos_salientes:
        motivos.append(SACOS_SALIENTES)
    if diferencia_sacos:
        motivos.append(DIFERENCIA_DE_SACOS)
    if personal_anomalo:
        motivos.append(PERSONAL_ANOMALO)

    if not motivos:
        return Decision(
            invocar=False, motivos=(NADA_QUE_EXPLICAR,),
            explicacion=("El conteo de sacos cuadra y la presencia de personal "
                         "fue la habitual. La RN-03 no invoca al modelo en este "
                         "caso, para controlar el costo."))

    return Decision(
        invocar=True, motivos=tuple(motivos),
        explicacion=_explicar(motivos, diferencia_sacos, sacos_salientes))


def _explicar(motivos: list[str], diferencia_sacos: int | None,
              sacos_salientes: int) -> str:
    partes = []
    if SACOS_SALIENTES in motivos:
        partes.append(f"{sacos_salientes} saco(s) salieron de la zona de carga")
    if DIFERENCIA_DE_SACOS in motivos:
        partes.append(f"la diferencia de sacos es {diferencia_sacos:+d}")
    if PERSONAL_ANOMALO in motivos:
        partes.append("la presencia de personal no fue la habitual")
    return "YOLO confirmo que " + " y ".join(partes) + "."
