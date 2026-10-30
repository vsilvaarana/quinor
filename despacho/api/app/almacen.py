"""Enlaces temporales a los objetos del almacen. HU-12, criterios 2 y 3.

  2. El clip se reproduce en el navegador con controles de pausa y avance.
  3. Se muestra el fotograma donde se detecto la anomalia.

El evento guarda `s3://bucket/objeto`, que es una direccion util para el sistema
y que ningun navegador sabe pedir. Este modulo la convierte en una URL firmada
con caducidad, que es lo que un reproductor y una etiqueta de imagen necesitan.

Por que la API firma y no sirve el video
----------------------------------------
Un clip de siete minutos pesa decenas de megas. Servirlo desde la API ocuparia
un trabajador de uvicorn durante toda la reproduccion, y el navegador no pide el
video entero: pide rangos, uno nuevo cada vez que el supervisor adelanta. MinIO
habla S3 y sabe responder por rangos; la API no tendria por que aprender a
hacerlo. Firmar, en cambio, es una cuenta local con HMAC.

Local **siempre que la region venga fijada**, y eso hay que decirlo porque no es
evidente. Si el cliente no sabe en que region esta el bucket, antes de firmar le
pregunta al servidor con un `GET ?location=`, y entonces la firma deja de ser
una cuenta y se convierte en una llamada de red: con MinIO caido, el detalle del
evento se queda esperando una respuesta que no llega. De ahi
`ajustes.minio_region`, que se pasa al construir el cliente.

La caducidad es deliberada. El enlace sirve para revisar un caso delante de la
pantalla, no para repartir evidencia por correo: a los quince minutos deja de
abrir y hay que volver a pedirlo con un token valido.

Cuando no se puede firmar
-------------------------
Aqui no se lanza ninguna excepcion. Un detalle que se cae por un video seria el
peor resultado posible: el supervisor tiene delante una discrepancia de peso que
existe de verdad y la pantalla se quedaria en blanco por la parte accesoria. Lo
que se devuelve es un `Enlace` que dice **por que** no hay URL, y la pantalla lo
escribe en el hueco del reproductor.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

import structlog
import urllib3.exceptions
from minio import Minio
from minio.error import MinioException

from app.config import Ajustes

log = structlog.get_logger("quinor.almacen")

PREFIJO = "s3://"

# Motivos por los que un enlace no se puede reproducir. Son codigos estables: la
# pantalla los traduce y el dia que haya un informe de clips perdidos, agrupar
# por ellos no puede depender de como estaba redactado el mensaje aquel mes.
SIN_OBJETO = "sin_objeto"
DIRECCION_INVALIDA = "direccion_invalida"
ALMACEN_NO_CONFIGURADO = "almacen_no_configurado"
NO_SE_PUDO_FIRMAR = "no_se_pudo_firmar"

EXPLICACIONES = {
    SIN_OBJETO: "No hay nada guardado para este evento.",
    DIRECCION_INVALIDA: ("La direccion guardada no tiene la forma "
                         "s3://bucket/objeto, asi que no se puede localizar."),
    ALMACEN_NO_CONFIGURADO: ("Esta instalacion no tiene credenciales del "
                             "almacen: el objeto existe, pero no se puede "
                             "firmar un enlace para verlo."),
    NO_SE_PUDO_FIRMAR: ("El almacen rechazo la firma del enlace. El objeto "
                        "sigue guardado; reintentarlo mas tarde."),
}


@dataclasses.dataclass(frozen=True)
class Enlace:
    """Un objeto del almacen listo para el navegador, o el motivo de que no.

    `direccion` es lo que guarda el evento y se conserva aunque no haya URL: es
    la que sirve para ir a buscar el objeto a mano cuando algo falla.
    """

    direccion: str | None = None
    url: str | None = None
    motivo: str | None = None
    minutos: int | None = None

    @property
    def reproducible(self) -> bool:
        return self.url is not None

    @property
    def explicacion(self) -> str | None:
        """La frase que la pantalla escribe en el hueco. None si todo esta bien."""
        if self.motivo is None:
            return None
        return EXPLICACIONES.get(self.motivo, "No se pudo preparar el enlace.")


def partes_de(direccion: str | None) -> tuple[str, str] | None:
    """Separa una direccion s3://bucket/objeto. None si no lo es.

    Misma funcion que en el grabador y a proposito: son dos servicios con su
    propio despliegue y su propio `requirements.txt`, y compartir diez lineas
    los ataria en un paquete comun que hoy no existe.
    """
    if not direccion or not direccion.startswith(PREFIJO):
        return None
    bucket, _, objeto = direccion[len(PREFIJO):].partition("/")
    return (bucket, objeto) if bucket and objeto else None


def crear_cliente(ajustes: Ajustes) -> Minio:
    """Cliente apuntando al MinIO configurado. No conecta: solo guarda datos.

    `region` no es opcional aqui, aunque el cliente la acepte vacia: sin ella la
    primera firma sale a preguntarle al servidor donde vive el bucket.
    """
    return Minio(
        ajustes.minio_endpoint,
        access_key=ajustes.minio_access_key,
        secret_key=ajustes.minio_secret_key,
        secure=ajustes.minio_seguro,
        region=ajustes.minio_region,
    )


class Firmador:
    """Firma direcciones del almacen para el detalle de un evento.

    Vive en `app.state` y se construye una vez con la aplicacion. El cliente se
    crea de forma perezosa en la primera firma, no al arrancar: una instalacion
    sin MinIO tiene que poder levantar la API y atender pesadas, que es la parte
    que no depende del video.

    Si el cliente no se puede construir, se recuerda y no se vuelve a intentar.
    Un endpoint mal escrito no mejora por reintentarlo en cada peticion, y lo
    unico que se consigue es repetir la misma excepcion en el log del detalle.
    """

    def __init__(self, ajustes: Ajustes, fabrica=crear_cliente):
        self._ajustes = ajustes
        self._fabrica = fabrica
        self._cliente: Minio | None = None
        self._sin_almacen = not ajustes.almacen_configurado

    @property
    def minutos(self) -> int:
        return int(self._ajustes.clip_url_minutos)

    @property
    def disponible(self) -> bool:
        """Si tiene sentido pedirle una firma. Lo consulta GET /salud."""
        return not self._sin_almacen

    def _cliente_o_nada(self) -> Minio | None:
        if self._sin_almacen:
            return None
        if self._cliente is None:
            try:
                self._cliente = self._fabrica(self._ajustes)
            except (ValueError, TypeError) as exc:
                # El propio cliente rechaza un endpoint que no tiene forma de
                # host:puerto. Es configuracion, no una caida: se anota una vez.
                self._sin_almacen = True
                log.warning("almacen_no_configurado",
                            endpoint=self._ajustes.minio_endpoint, error=str(exc))
                return None
        return self._cliente

    def firmar(self, direccion: str | None, minutos: int | None = None) -> Enlace:
        """URL firmada para `direccion`, o un Enlace que explica por que no.

        Nunca lanza: quien la llama esta armando una pantalla y el video es la
        parte accesoria de lo que esa pantalla tiene que contar.
        """
        if not direccion:
            return Enlace(motivo=SIN_OBJETO)

        partes = partes_de(direccion)
        if partes is None:
            return Enlace(direccion=direccion, motivo=DIRECCION_INVALIDA)

        cliente = self._cliente_o_nada()
        if cliente is None:
            return Enlace(direccion=direccion, motivo=ALMACEN_NO_CONFIGURADO)

        bucket, objeto = partes
        validez = int(minutos) if minutos else self.minutos
        try:
            url = cliente.presigned_get_object(
                bucket, objeto, expires=dt.timedelta(minutes=validez))
        except (MinioException, urllib3.exceptions.HTTPError,
                OSError, ValueError) as exc:
            # urllib3 esta en la lista por lo que explica la cabecera: si alguien
            # deja la region vacia, esto sale a la red, y lo que llega cuando
            # MinIO no responde no es un error de S3 sino un MaxRetryError.
            log.warning("url_no_firmada", objeto=objeto, error=str(exc))
            return Enlace(direccion=direccion, motivo=NO_SE_PUDO_FIRMAR)
        return Enlace(direccion=direccion, url=url, minutos=validez)
