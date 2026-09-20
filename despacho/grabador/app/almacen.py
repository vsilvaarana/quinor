"""Almacen de clips en MinIO. HU-06, criterio 2.

"El clip se guarda en MinIO y se vincula al evento."

MinIO habla S3, asi que este modulo es una capa fina sobre el cliente oficial.
Lo unico que anade es lo que hace falta para no repetirlo en cada llamada: crear
el bucket si no existe y devolver una URL que sirva para algo.

La URL que se guarda en el evento es `s3://bucket/objeto`, no una URL firmada.
Una firmada caduca, y el evento se conserva 12 meses segun el RNF-06: guardar
algo que dentro de una semana ya no abre seria peor que no guardar nada. El
dashboard pide la firmada en el momento de reproducir.
"""
from __future__ import annotations

import pathlib

import structlog
from minio import Minio
from minio.error import S3Error

from app.config import Ajustes

log = structlog.get_logger("quinor.almacen")

TIPO_DE_CONTENIDO = "video/x-matroska"


class ErrorDeAlmacen(RuntimeError):
    """MinIO no acepto el clip. El evento se queda sin vincular y se reintenta."""


def crear_cliente(ajustes: Ajustes) -> Minio:
    """Cliente apuntando al MinIO configurado."""
    return Minio(
        ajustes.minio_endpoint,
        access_key=ajustes.minio_access_key,
        secret_key=ajustes.minio_secret_key,
        secure=ajustes.minio_seguro,
    )


def asegurar_bucket(cliente: Minio, bucket: str) -> bool:
    """Crea el bucket si falta. Devuelve True si lo tuvo que crear.

    Una instalacion nueva no tiene buckets, y pedirle al operador que lo cree a
    mano antes del primer evento es garantizar que el primer clip se pierda.
    """
    try:
        if cliente.bucket_exists(bucket):
            return False
        cliente.make_bucket(bucket)
    except (S3Error, ValueError) as exc:
        # ValueError: el propio cliente rechaza un nombre que S3 no admite, como
        # uno con mayusculas. Sale como error de almacen para que quien lo lea
        # vea que bucket fallo y no un rastro del cliente.
        raise ErrorDeAlmacen(f"No se pudo preparar el bucket '{bucket}': {exc}") from exc
    log.info("bucket_creado", bucket=bucket)
    return True


def subir(cliente: Minio, bucket: str, objeto: str, ruta: pathlib.Path,
          tipo: str = TIPO_DE_CONTENIDO) -> str:
    """Sube un objeto y devuelve su direccion s3://.

    `tipo` se puede cambiar porque desde HU-09 tambien viajan los fotogramas
    clave, que son JPEG: subirlos como video haria que el navegador de HU-12 se
    los descargara en lugar de mostrarlos.
    """
    asegurar_bucket(cliente, bucket)
    try:
        cliente.fput_object(bucket, objeto, str(ruta), content_type=tipo)
    except (S3Error, OSError) as exc:
        raise ErrorDeAlmacen(f"No se pudo subir el clip '{objeto}': {exc}") from exc

    direccion = f"s3://{bucket}/{objeto}"
    log.info("clip_subido", objeto=objeto,
             mb=round(ruta.stat().st_size / 1_048_576, 2))
    return direccion


def partes_de(direccion: str) -> tuple[str, str] | None:
    """Separa una direccion s3://bucket/objeto. None si no lo es."""
    if not direccion or not direccion.startswith("s3://"):
        return None
    bucket, _, objeto = direccion[len("s3://"):].partition("/")
    return (bucket, objeto) if bucket and objeto else None


def descargar(cliente: Minio, direccion: str, destino: pathlib.Path) -> pathlib.Path:
    """Trae de vuelta un clip ya subido, a partir de su direccion s3://.

    Lo usa el reintento de conteo de HU-07: el buffer local solo guarda 72 h,
    y el clip de MinIO es exactamente el que se vinculo al evento.
    """
    partes = partes_de(direccion)
    if partes is None:
        raise ErrorDeAlmacen(f"'{direccion}' no es una direccion s3://bucket/objeto.")
    bucket, objeto = partes
    try:
        cliente.fget_object(bucket, objeto, str(destino))
    except (S3Error, OSError) as exc:
        raise ErrorDeAlmacen(f"No se pudo bajar el clip '{objeto}': {exc}") from exc
    return destino


def existe(cliente: Minio, bucket: str, objeto: str) -> bool:
    try:
        cliente.stat_object(bucket, objeto)
        return True
    except S3Error:
        return False


def url_temporal(cliente: Minio, direccion: str, minutos: int = 60) -> str | None:
    """URL firmada para reproducir el clip, a partir de su direccion s3://.

    La caducidad es deliberada: el enlace sirve para la revision de HU-12 y no
    para repartir evidencia por correo.
    """
    import datetime as dt

    partes = partes_de(direccion)
    if partes is None:
        return None
    bucket, objeto = partes
    try:
        return cliente.presigned_get_object(
            bucket, objeto, expires=dt.timedelta(minutes=minutos))
    except S3Error as exc:      # pragma: no cover - depende del servidor
        log.warning("url_no_firmada", objeto=objeto, error=str(exc))
        return None
