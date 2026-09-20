"""Contratos de entrada y salida del servicio de vision-lenguaje."""
from __future__ import annotations

from pydantic import BaseModel, Field


class FotogramaDeEntrada(BaseModel):
    """Un fotograma clave, tal como lo devolvio el servicio YOLO."""

    jpeg_base64: str = Field(min_length=1)
    motivo: str = ""
    detalle: str = ""
    segundo: float = 0.0
    fotograma: int = 0


class PeticionDeAnalisis(BaseModel):
    """Un evento a interpretar. HU-09.

    Lleva los datos estructurados que el apartado 9.2 manda enviar junto a las
    imagenes: sin ellos el modelo describiria un camion y unos sacos, que es lo
    que el supervisor ya sabe. Lo util es el contraste con lo esperado.
    """

    evento_id: int | None = Field(default=None, ge=1,
                                  description="Solo para el log; el servicio no toca la base.")
    numero_orden: str = ""
    producto: str = ""

    peso_esperado_kg: float | None = None
    peso_real_kg: float | None = None
    diferencia_kg: float | None = None
    diferencia_pct: float | None = None

    # HU-07. En None significa que el clip no se analizo, que no es cero.
    sacos_esperados: int | None = None
    sacos_contados: int | None = None
    diferencia_sacos: int | None = None
    sacos_salientes: int = 0

    # HU-08.
    personas_detectadas: int | None = None
    maximo_simultaneo: int | None = None
    permanencia_maxima_s: float | None = None
    personal_anomalo: bool | None = None
    motivos_de_anomalia: list[str] = []

    duracion_del_clip_s: float | None = None
    fotogramas: list[FotogramaDeEntrada] = []

    # La RN-03 se comprueba aqui dentro. Esto existe para el reanalisis manual
    # de un caso concreto, que es una decision de una persona y no del sistema,
    # y queda registrado como tal.
    forzar: bool = Field(
        default=False,
        description="Salta la RN-03. Para reanalizar un caso a peticion de un "
                    "supervisor; queda en el log.")


class AnalisisLeido(BaseModel):
    """El JSON del criterio 2, ya validado."""

    descripcion: str
    # La del modelo. La del evento sale de la RN-04 y viaja en `severidad`.
    severidad_ia: str
    evidencia: list[str] = []
    confianza: float = Field(ge=0, le=1)
    modelo: str
    proveedor: str
    intentos: int
    segundos: float


class RespuestaDeAnalisis(BaseModel):
    """Lo que el servicio devuelve. HU-09, criterios 1, 2 y 3."""

    # Criterio 1: si no se invoco, aqui se dice por que.
    invocado: bool
    motivo_de_invocacion: str = ""
    explicacion: str = ""

    # Criterio 2. `severidad` es la que manda y sale de la RN-04, que es una
    # regla escrita y reproducible; `analisis.severidad_ia` es la opinion del
    # modelo, y de comparar las dos sale la concordancia del apartado 9.2.
    severidad: str | None = None
    motivo_de_severidad: str = ""
    concuerdan: bool | None = None

    analisis: AnalisisLeido | None = None

    # Criterio 3: cuando fallaron los tres intentos, quien llama marca el evento
    # en Pendiente de analisis. El servicio no toca la base, asi que lo dice.
    fallo: bool = False
    motivo_del_fallo: str = ""
    intentos: int = 0


class RespuestaDeSalud(BaseModel):
    estado: str
    proveedor: str
    modelo: str
    configurado: bool
    # True cuando se esta hablando con el stub de desarrollo. Se expone para que
    # nadie confunda una respuesta de mentira con un analisis de verdad.
    es_stub: bool
    intentos: int
    mensaje: str | None = None
