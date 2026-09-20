"""Contratos de entrada y salida del servicio YOLO."""
from __future__ import annotations

from pydantic import BaseModel, Field


class PeticionDeAnalisis(BaseModel):
    """Un clip a analizar. HU-07, criterio 1.

    El clip llega por ruta compartida y no por el cuerpo: son cientos de megas
    que los dos contenedores ya ven en el mismo volumen.
    """

    clip: str = Field(min_length=1, max_length=500,
                      examples=["/video/clips/evento-1.mkv"])
    evento_id: int | None = Field(default=None, ge=1,
                                  description="Solo para el log. El servicio no toca la base.")
    sacos_esperados: int | None = Field(
        default=None, ge=0,
        description="Sacos de la orden. Con el, la respuesta trae la diferencia.")
    # Con dos camaras enfocando rampas distintas la linea no es la misma.
    linea: list[float] | None = Field(
        default=None, min_length=4, max_length=4,
        description="x1,y1,x2,y2 en coordenadas relativas de 0 a 1.")
    # HU-08: lo mismo para la zona de carga, que tampoco es la misma en dos
    # rampas distintas.
    zona: list[float] | None = Field(
        default=None, min_length=4, max_length=4,
        description="Zona de carga x1,y1,x2,y2 en coordenadas relativas, de la "
                    "esquina superior izquierda a la inferior derecha.")
    invertir_sentido: bool | None = Field(
        default=None,
        description="Si la camara mira la rampa desde el otro costado.")


class PersonaEnZona(BaseModel):
    """Una persona vista en la zona de carga. HU-08, criterios 1 y 2.

    Esto es todo lo que se informa de ella, y todo lo que se guarda. El
    identificador lo puso el rastreador, vale solo dentro de este clip y no se
    puede cruzar con otro video, con una nomina ni con un control de acceso: la
    RN-08 prohibe la identificacion facial y los datos biometricos, y la forma de
    cumplirla es no tener nada que identificar.
    """

    id_temporal: int = Field(
        description="Identificador del rastreador. Solo vale en este clip.")
    segundos_en_zona: float = Field(
        ge=0, description="Tiempo de permanencia en la zona de carga.")
    primer_fotograma: int
    ultimo_fotograma: int


class PresenciaDePersonal(BaseModel):
    """El resumen de quien estuvo en la rampa. HU-08, criterio 2."""

    cuantas: int = Field(ge=0, description="Personas que estuvieron en zona.")
    # Cuantas a la vez, que no es lo mismo: cuatro personas que se turnan no son
    # lo mismo que cuatro a la vez, y la segunda es la que llama la atencion.
    maximo_simultaneo: int = Field(ge=0)
    segundos_totales: float = Field(ge=0)
    permanencia_maxima_s: float = Field(ge=0)
    permanencia_media_s: float = Field(ge=0)
    personas: list[PersonaEnZona] = []
    # True cuando no se calibro zona y se tomo el cuadro entero: entonces
    # "en zona" incluye a quien solo pasaba por el fondo.
    zona_completa: bool = True


class MotivoDeAnomalia(BaseModel):
    """Por que la presencia de personal se marco anomala, con su numero.

    El codigo es estable y la frase es para leer. Ninguno de los dos dice quien
    es nadie: las reglas miran cuantos, cuanto tiempo y si hubo carga.
    """

    codigo: str
    detalle: str
    medido: float
    umbral: float


class FotogramaClaveLeido(BaseModel):
    """Un fotograma que explica la carga. HU-09, y el criterio 3 de HU-12.

    La imagen viaja en base64 dentro del JSON y no por ruta como el clip: son
    unas decenas de kilobytes, frente a los cientos de megas de un clip de 7
    minutos. Escribirla en el volumen compartido para que el otro contenedor la
    lea obligaria a coordinar limpieza de temporales por unas imagenes que caben
    en la propia respuesta.
    """

    fotograma: int = Field(description="Indice en el video, no en los mirados.")
    segundo: float = Field(ge=0, description="Momento del clip, para saltar ahi.")
    motivo: str = Field(description="Por que se guardo. Codigo estable.")
    detalle: str
    jpeg_base64: str


class RespuestaDeAnalisis(BaseModel):
    """Lo que el servicio devuelve. HU-07 criterios 1 y 3, HU-08 criterios 1 y 2."""

    sacos_contados: int
    sacos_entrantes: int
    # La RN-04 trata un saco que sale de la zona de carga como severidad Alta,
    # asi que se informa aparte del conteo neto.
    sacos_salientes: int
    sacos_esperados: int | None = None
    # Negativa es faltante, el mismo criterio de signo que la diferencia de peso.
    diferencia_sacos: int | None = None
    # HU-08. `personas_detectadas` es el conteo suelto que ya usaba HU-07;
    # `presencia` es el detalle que pide el criterio 2.
    personas_detectadas: int
    presencia: PresenciaDePersonal | None = None
    # RN-03: esta es la senal que decide si HU-09 llama al modelo de
    # vision-lenguaje. Lista vacia significa que nada llamo la atencion.
    anomalia_de_personal: bool = False
    motivos_de_anomalia: list[MotivoDeAnomalia] = []

    fotogramas_procesados: int
    duracion_del_clip_s: float
    # RNF-01: un clip de 7 min se analiza en menos de 3 en el hardware de planta.
    segundos_de_proceso: float
    modelo: str

    # HU-09: los pocos fotogramas que explican la carga, elegidos por lo que
    # ocurrio en ellos. Van al modelo de vision-lenguaje y, guardados, son el
    # fotograma que HU-12 mostrara.
    fotogramas_clave: list[FotogramaClaveLeido] = []

    # Un aviso, no un error: el detector vio objetos y el rastreador no siguio
    # ninguno, asi que este cero no significa que no pasaran sacos. Sin esto, un
    # salto de fotogramas mal puesto devuelve cero y parece una carga vacia.
    aviso: str | None = None


class RespuestaDeSalud(BaseModel):
    estado: str
    modelo: str
    modelo_cargado: bool
    dispositivo: str
    linea: list[float]
    # La zona de carga con la que se esta midiendo la permanencia. Se expone
    # porque una zona mal calibrada da cargas sin nadie en rampa, y eso desde
    # fuera se ve igual que una rampa vacia de verdad.
    zona: list[float] = [0.0, 0.0, 1.0, 1.0]
    mensaje: str | None = None
