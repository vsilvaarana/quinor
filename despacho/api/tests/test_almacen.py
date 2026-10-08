"""Enlaces temporales al almacen. HU-12, criterios 2 y 3.

Sin MinIO y a proposito. Firmar es una cuenta local con HMAC, asi que estas
pruebas comprueban justo eso: que de aqui no sale ni un paquete a la red. El
endpoint configurado es `minio:9000`, un nombre que en este contenedor no
resuelve, de modo que si alguien quita la region del cliente y la firma vuelve a
preguntarle al servidor donde vive el bucket, la prueba se cae con un error de
resolucion de nombres en lugar de pasar por casualidad.

Lo que no se prueba aqui es que MinIO acepte la URL: eso ya lo cubre el grabador
contra un MinIO de verdad al subir el clip. Lo que se prueba es que la API
construya el enlace, y que cuando no pueda lo diga en lugar de reventar la
pantalla del supervisor.
"""
from __future__ import annotations

import datetime as dt

import pytest
import urllib3.exceptions
from minio.error import MinioException

from app import almacen
from app.almacen import (ALMACEN_NO_CONFIGURADO, DIRECCION_INVALIDA,
                         NO_SE_PUDO_FIRMAR, SIN_OBJETO, Enlace, Firmador,
                         partes_de)
from app.config import cargar_ajustes

CLIP = "s3://clips/ORD-2026-0001/evento-1-rampa.mkv"


def ajustes(**extra):
    base = {"database_url": "mysql+pymysql://sin/uso",
            "minio_access_key": "llave", "minio_secret_key": "secreto"}
    base.update(extra)
    return cargar_ajustes(**base)


class ClienteQueFalla:
    """Un cliente que levanta la excepcion que se le diga al firmar."""

    def __init__(self, excepcion):
        self.excepcion = excepcion

    def presigned_get_object(self, *_args, **_kwargs):
        raise self.excepcion


# ------------------------------------------------------------------- partes_de
@pytest.mark.parametrize("direccion, esperado", [
    (CLIP, ("clips", "ORD-2026-0001/evento-1-rampa.mkv")),
    ("s3://clips/a.mkv", ("clips", "a.mkv")),
    ("s3://clips/sub/carpeta/a.jpg", ("clips", "sub/carpeta/a.jpg")),
])
def test_separa_bucket_y_objeto(direccion, esperado):
    assert partes_de(direccion) == esperado


@pytest.mark.parametrize("direccion", [
    None, "", "clips/a.mkv", "http://minio:9000/clips/a.mkv",
    "s3://", "s3://clips", "s3://clips/", "s3:///a.mkv",
])
def test_lo_que_no_es_una_direccion_del_almacen(direccion):
    """Ninguna de estas se puede localizar, y ninguna puede hacer saltar nada."""
    assert partes_de(direccion) is None


# ---------------------------------------------------------------------- Enlace
def test_un_enlace_sin_url_no_es_reproducible():
    assert Enlace(direccion=CLIP, motivo=SIN_OBJETO).reproducible is False


def test_un_enlace_con_url_es_reproducible_y_no_explica_nada():
    enlace = Enlace(direccion=CLIP, url="http://minio:9000/firmada", minutos=15)
    assert enlace.reproducible is True
    assert enlace.explicacion is None


def test_cada_motivo_conocido_tiene_su_frase():
    """La pantalla escribe esta frase en el hueco del reproductor.

    Un motivo sin frase dejaria al supervisor con un hueco en blanco, que es
    justo lo que este modulo existe para evitar.
    """
    for motivo in (SIN_OBJETO, DIRECCION_INVALIDA, ALMACEN_NO_CONFIGURADO,
                   NO_SE_PUDO_FIRMAR):
        assert Enlace(motivo=motivo).explicacion


def test_un_motivo_que_nadie_previo_tambien_dice_algo():
    assert Enlace(motivo="invento").explicacion == "No se pudo preparar el enlace."


# -------------------------------------------------------------- criterio 2 y 3
def test_firma_un_enlace_sin_salir_a_la_red():
    """El nombre 'minio' no resuelve aqui: si saliera a la red, esto fallaria."""
    enlace = Firmador(ajustes()).firmar(CLIP)

    assert enlace.reproducible
    assert enlace.direccion == CLIP
    assert enlace.minutos == 15
    assert "X-Amz-Signature=" in enlace.url
    assert "evento-1-rampa.mkv" in enlace.url


def test_la_region_viaja_en_la_firma():
    """Es la que evita el viaje al servidor. Si se va, vuelve la llamada de red."""
    assert "us-east-1" in Firmador(ajustes()).firmar(CLIP).url


def test_la_caducidad_se_puede_acortar_por_llamada():
    enlace = Firmador(ajustes()).firmar(CLIP, minutos=2)

    assert enlace.minutos == 2
    assert "X-Amz-Expires=120" in enlace.url


def test_la_caducidad_por_defecto_sale_de_los_ajustes():
    enlace = Firmador(ajustes(clip_url_minutos=45)).firmar(CLIP)

    assert enlace.minutos == 45
    assert "X-Amz-Expires=2700" in enlace.url


def test_sin_direccion_no_hay_nada_guardado():
    enlace = Firmador(ajustes()).firmar(None)

    assert enlace.motivo == SIN_OBJETO
    assert enlace.direccion is None


def test_una_direccion_con_otra_forma_se_conserva_y_se_explica():
    """La direccion se devuelve igual: es la pista para ir a buscarla a mano."""
    enlace = Firmador(ajustes()).firmar("/var/clips/a.mkv")

    assert enlace.motivo == DIRECCION_INVALIDA
    assert enlace.direccion == "/var/clips/a.mkv"
    assert enlace.url is None


def test_sin_credenciales_el_objeto_sigue_ahi_pero_no_se_puede_enlazar():
    """Una instalacion sin MinIO tiene que poder atender pesadas igual."""
    firmador = Firmador(ajustes(minio_access_key="", minio_secret_key=""))

    assert firmador.disponible is False
    enlace = firmador.firmar(CLIP)
    assert enlace.motivo == ALMACEN_NO_CONFIGURADO
    assert enlace.direccion == CLIP


def test_un_endpoint_imposible_se_anota_una_vez_y_no_se_reintenta():
    """Un endpoint mal escrito no mejora por reintentarlo en cada peticion."""
    intentos = []

    def fabrica(_ajustes):
        intentos.append(1)
        raise ValueError("endpoint sin forma de host:puerto")

    firmador = Firmador(ajustes(), fabrica=fabrica)

    assert firmador.firmar(CLIP).motivo == ALMACEN_NO_CONFIGURADO
    assert firmador.firmar(CLIP).motivo == ALMACEN_NO_CONFIGURADO
    assert len(intentos) == 1
    assert firmador.disponible is False


def test_el_cliente_se_construye_una_sola_vez():
    construidos = []

    def fabrica(ajustes_recibidos):
        construidos.append(ajustes_recibidos)
        return almacen.crear_cliente(ajustes_recibidos)

    firmador = Firmador(ajustes(), fabrica=fabrica)
    firmador.firmar(CLIP)
    firmador.firmar(CLIP)

    assert len(construidos) == 1


@pytest.mark.parametrize("excepcion", [
    MinioException("el almacen dijo que no"),
    urllib3.exceptions.ProtocolError("conexion cortada"),
    OSError("socket cerrado"),
    ValueError("nombre de objeto inaceptable"),
])
def test_si_la_firma_falla_la_pantalla_se_entera_pero_no_se_cae(excepcion):
    """Ninguna de estas puede llegar al endpoint: el detalle vale sin el video."""
    firmador = Firmador(ajustes(), fabrica=lambda _a: ClienteQueFalla(excepcion))

    enlace = firmador.firmar(CLIP)

    assert enlace.motivo == NO_SE_PUDO_FIRMAR
    assert enlace.direccion == CLIP
    assert enlace.explicacion


def test_un_fallo_de_firma_no_inhabilita_el_almacen():
    """Distinto de un endpoint imposible: aqui el almacen existe y puede volver."""
    firmador = Firmador(ajustes(),
                        fabrica=lambda _a: ClienteQueFalla(MinioException("tropiezo")))

    firmador.firmar(CLIP)

    assert firmador.disponible is True


# ------------------------------------------------------------------- el cliente
def test_el_cliente_lleva_lo_que_dicen_los_ajustes():
    cliente = almacen.crear_cliente(ajustes(minio_endpoint="almacen.local:9100"))

    url = cliente.presigned_get_object("clips", "a.mkv",
                                       expires=dt.timedelta(minutes=1))
    assert url.startswith("http://almacen.local:9100/clips/a.mkv")


def test_con_tls_el_enlace_sale_por_https():
    cliente = almacen.crear_cliente(ajustes(minio_seguro=True))

    assert cliente.presigned_get_object("clips", "a.mkv").startswith("https://")
