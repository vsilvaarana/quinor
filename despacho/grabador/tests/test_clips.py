"""Subida del clip y vinculo con el evento. HU-06, criterios 2 y 3.

Contra un servidor S3 de verdad y contra MySQL de verdad. Lo que importa
comprobar no es que se llamo al cliente, sino que el objeto quedo donde el
evento apunta y que el estado del evento dice la verdad.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import time

import pytest
from sqlalchemy import select

from app import almacen, clips, recorte, tablas
from app.config import Camara
from app.grabador import Grabador
from tests.conftest import CAMARA_PRUEBA, sembrar_evento


def grabar_unos_segundos(ajustes, camara_rtsp, segundos: float = 9.0):
    """Deja video real en el buffer, grabado por el grabador de HU-05."""
    reales = dataclasses.replace(
        ajustes, segundos_por_segmento=2,
        camaras=(Camara(id=CAMARA_PRUEBA, url=camara_rtsp.url),))
    grabador = Grabador(reales, None)
    grabador.arrancar_camara(grabador.camaras[0])
    time.sleep(segundos)
    grabador.cerrar()
    return reales


def leer_evento(motor, evento_id: int) -> dict:
    with motor.connect() as conexion:
        return dict(conexion.execute(
            select(tablas.evento).where(tablas.evento.c.id == evento_id)
        ).mappings().one())


# ---------------------------------------------------- criterio 2: a MinIO
def test_el_bucket_se_crea_si_no_existe(ajustes_con_s3, cliente_s3):
    """Una instalacion nueva no tiene buckets, y pedirselo al operador antes del
    primer evento es garantizar que el primer clip se pierda."""
    assert almacen.asegurar_bucket(cliente_s3, ajustes_con_s3.minio_bucket) is True
    assert almacen.asegurar_bucket(cliente_s3, ajustes_con_s3.minio_bucket) is False


def test_el_clip_se_sube_y_se_puede_recuperar(ajustes_con_s3, cliente_s3, tmp_path):
    archivo = tmp_path / "clip.mkv"
    archivo.write_bytes(b"video de prueba" * 100)

    direccion = almacen.subir(cliente_s3, ajustes_con_s3.minio_bucket,
                              "2026/09/14/ORD-A/evento-1.mkv", archivo)

    assert direccion == "s3://clips/2026/09/14/ORD-A/evento-1.mkv"
    assert almacen.existe(cliente_s3, "clips", "2026/09/14/ORD-A/evento-1.mkv")


def test_lo_que_se_baja_es_lo_que_se_subio(ajustes_con_s3, cliente_s3, tmp_path):
    original = tmp_path / "clip.mkv"
    original.write_bytes(b"\x1a\x45\xdf\xa3contenido exacto")
    almacen.subir(cliente_s3, "clips", "prueba.mkv", original)

    respuesta = cliente_s3.get_object("clips", "prueba.mkv")
    try:
        assert respuesta.read() == original.read_bytes()
    finally:
        respuesta.close()
        respuesta.release_conn()


def test_subir_un_archivo_que_no_existe_se_avisa(cliente_s3, tmp_path):
    with pytest.raises(almacen.ErrorDeAlmacen):
        almacen.subir(cliente_s3, "clips", "x.mkv", tmp_path / "no-existe.mkv")


def test_la_url_firmada_apunta_al_objeto(ajustes_con_s3, cliente_s3, tmp_path):
    archivo = tmp_path / "clip.mkv"
    archivo.write_bytes(b"video")
    direccion = almacen.subir(cliente_s3, "clips", "carpeta/clip.mkv", archivo)

    url = almacen.url_temporal(cliente_s3, direccion, minutos=5)
    assert url and "carpeta/clip.mkv" in url


@pytest.mark.parametrize("direccion", ["", None, "no-es-s3", "s3://solo-bucket"])
def test_una_direccion_invalida_no_da_url(cliente_s3, direccion):
    assert almacen.url_temporal(cliente_s3, direccion) is None


def test_lo_que_se_guarda_en_el_evento_no_caduca(ajustes_con_s3, cliente_s3, tmp_path):
    """El evento se conserva 12 meses; una URL firmada caduca en una hora.
    Guardar algo que dentro de una semana ya no abre seria peor que nada."""
    archivo = tmp_path / "clip.mkv"
    archivo.write_bytes(b"video")
    direccion = almacen.subir(cliente_s3, "clips", "clip.mkv", archivo)

    assert direccion.startswith("s3://")
    assert "X-Amz-Signature" not in direccion
    assert "Expires" not in direccion


# ------------------------------------------- criterios 1, 2 y 3 de punta a punta
def test_un_evento_recibe_su_clip(ajustes_con_s3, motor, camara_rtsp, cliente_s3):
    reales = grabar_unos_segundos(ajustes_con_s3, camara_rtsp)
    reales = dataclasses.replace(reales, segundos_antes=4, segundos_despues=1,
                                 minio_endpoint=ajustes_con_s3.minio_endpoint,
                                 minio_access_key=ajustes_con_s3.minio_access_key,
                                 minio_secret_key=ajustes_con_s3.minio_secret_key)
    sembrado = sembrar_evento(
        motor, fecha_hora=dt.datetime.now().replace(tzinfo=None) - dt.timedelta(seconds=3))

    resultados = clips.procesar_pendientes(motor, reales)

    assert len(resultados) == 1
    resultado = resultados[0]
    assert resultado.tiene_clip

    # Criterio 2: vinculado al evento y presente en el almacen.
    fila = leer_evento(motor, sembrado["evento_id"])
    assert fila["clip_url"] == resultado.clip_url
    assert fila["estado"] == "pendiente"
    bucket, _, objeto = resultado.clip_url[len("s3://"):].partition("/")
    assert almacen.existe(cliente_s3, bucket, objeto)


def test_la_ventana_recortada_queda_en_auditoria(ajustes_con_s3, motor, camara_rtsp):
    reales = grabar_unos_segundos(ajustes_con_s3, camara_rtsp, segundos=12)
    reales = dataclasses.replace(reales, segundos_antes=2, segundos_despues=1,
                                 minio_endpoint=ajustes_con_s3.minio_endpoint,
                                 minio_access_key=ajustes_con_s3.minio_access_key,
                                 minio_secret_key=ajustes_con_s3.minio_secret_key)
    # Ventana holgadamente dentro de lo grabado: lo que se comprueba aqui es que
    # la ventana queda escrita, no el limite de cobertura.
    ahora = dt.datetime.now().replace(tzinfo=None)
    inicio = ahora - dt.timedelta(seconds=8)
    sembrado = sembrar_evento(
        motor, inicio_carga=inicio, fecha_hora=ahora - dt.timedelta(seconds=4))

    clips.procesar_pendientes(motor, reales)

    with motor.connect() as conexion:
        registro = dict(conexion.execute(
            select(tablas.auditoria)
            .where(tablas.auditoria.c.accion == "recortar_clip")).mappings().one())
    detalle = registro["detalle"]
    assert detalle["numero_orden"] == sembrado["numero_orden"]
    assert detalle["inicio_carga_marcado"] is True
    assert detalle["desde"] and detalle["hasta"]
    assert detalle["segmentos_usados"] >= 1


def test_sin_video_el_evento_pasa_a_sin_clip(ajustes_con_s3, motor):
    """Criterio 3, con el estado del apartado 5.3."""
    sembrado = sembrar_evento(
        motor, fecha_hora=dt.datetime.now().replace(tzinfo=None) - dt.timedelta(days=30))

    resultados = clips.procesar_pendientes(motor, ajustes_con_s3)

    assert resultados[0].estado == "sin_clip"
    fila = leer_evento(motor, sembrado["evento_id"])
    assert fila["estado"] == "sin_clip"
    assert fila["clip_url"] is None


def test_el_motivo_de_quedarse_sin_clip_queda_escrito(ajustes_con_s3, motor):
    """No es lo mismo que la camara estuviera caida que que el video se purgara."""
    sembrar_evento(motor,
                   fecha_hora=dt.datetime.now().replace(tzinfo=None) - dt.timedelta(days=30))
    clips.procesar_pendientes(motor, ajustes_con_s3)

    with motor.connect() as conexion:
        registro = dict(conexion.execute(
            select(tablas.auditoria)
            .where(tablas.auditoria.c.accion == "evento_sin_clip")).mappings().one())
    assert "No hay video" in registro["detalle"]["motivo"]


def test_con_muy_poco_video_tambien_es_sin_clip(ajustes_con_s3, motor, camara_rtsp):
    """Un trozo suelto de una ventana larga no sirve para revisar nada, y guardarlo
    haria creer al supervisor que tiene la carga entera."""
    reales = grabar_unos_segundos(ajustes_con_s3, camara_rtsp, segundos=5)
    reales = dataclasses.replace(
        reales, segundos_antes=600, segundos_despues=2, cobertura_minima_pct=50.0,
        minio_endpoint=ajustes_con_s3.minio_endpoint,
        minio_access_key=ajustes_con_s3.minio_access_key,
        minio_secret_key=ajustes_con_s3.minio_secret_key)
    sembrado = sembrar_evento(
        motor, fecha_hora=dt.datetime.now().replace(tzinfo=None) - dt.timedelta(seconds=3))

    resultados = clips.procesar_pendientes(motor, reales)

    assert resultados[0].estado == "sin_clip"
    assert leer_evento(motor, sembrado["evento_id"])["estado"] == "sin_clip"


# ------------------------------------------------------------ el sondeo
def test_solo_se_miran_los_eventos_sin_clip(ajustes_con_s3, motor):
    viejo = dt.datetime.now().replace(tzinfo=None) - dt.timedelta(minutes=10)
    sembrar_evento(motor, clip_url="s3://clips/ya-tiene.mkv", fecha_hora=viejo)
    assert clips.pendientes_de_clip(motor, ajustes_con_s3) == []


def test_un_evento_ya_marcado_sin_clip_no_se_reintenta(ajustes_con_s3, motor):
    """Sin clip es una conclusion, no un reintento pendiente. Volver a intentarlo
    en bucle solo gastaria disco."""
    viejo = dt.datetime.now().replace(tzinfo=None) - dt.timedelta(minutes=10)
    sembrar_evento(motor, estado="sin_clip", fecha_hora=viejo)
    assert clips.pendientes_de_clip(motor, ajustes_con_s3) == []


def test_los_pendientes_salen_del_mas_antiguo(ajustes_con_s3, motor):
    # Los dos con la ventana ya cerrada: lo que se ordena es la antiguedad, no
    # quien tiene el margen posterior completo.
    ahora = dt.datetime.now().replace(tzinfo=None) - dt.timedelta(minutes=10)
    sembrar_evento(motor, numero_orden="ORD-NUEVA", fecha_hora=ahora)
    sembrar_evento(motor, numero_orden="ORD-VIEJA",
                   fecha_hora=ahora - dt.timedelta(hours=2))

    pendientes = clips.pendientes_de_clip(motor, ajustes_con_s3)
    assert [p["numero_orden"] for p in pendientes] == ["ORD-VIEJA", "ORD-NUEVA"]


def test_el_limite_del_sondeo_se_respeta(ajustes_con_s3, motor):
    viejo = dt.datetime.now().replace(tzinfo=None) - dt.timedelta(minutes=10)
    for i in range(4):
        sembrar_evento(motor, numero_orden=f"ORD-{i}", fecha_hora=viejo)
    assert len(clips.pendientes_de_clip(motor, ajustes_con_s3, limite=2)) == 2


def test_un_evento_que_revienta_no_frena_a_los_demas(ajustes_con_s3, motor, monkeypatch):
    viejo = dt.datetime.now().replace(tzinfo=None) - dt.timedelta(minutes=10)
    sembrar_evento(motor, numero_orden="ORD-A", fecha_hora=viejo)
    sembrar_evento(motor, numero_orden="ORD-B", fecha_hora=viejo)

    llamadas = []

    def revienta(motor_, ajustes_, fila, cliente=None, **_extra):
        llamadas.append(fila["numero_orden"])
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(clips, "procesar_evento", revienta)
    assert clips.procesar_pendientes(motor, ajustes_con_s3) == []
    assert len(llamadas) == 2


def test_procesar_dos_veces_no_duplica_el_clip(ajustes_con_s3, motor, camara_rtsp):
    reales = grabar_unos_segundos(ajustes_con_s3, camara_rtsp)
    reales = dataclasses.replace(reales, segundos_antes=4, segundos_despues=1,
                                 minio_endpoint=ajustes_con_s3.minio_endpoint,
                                 minio_access_key=ajustes_con_s3.minio_access_key,
                                 minio_secret_key=ajustes_con_s3.minio_secret_key)
    sembrar_evento(motor,
                   fecha_hora=dt.datetime.now().replace(tzinfo=None) - dt.timedelta(seconds=3))

    primero = clips.procesar_pendientes(motor, reales)
    segundo = clips.procesar_pendientes(motor, reales)

    assert len(primero) == 1
    assert segundo == []          # ya tiene clip_url, no vuelve a salir


# ------------------------------------------------- el grabador que lo dispara
def test_sin_credenciales_de_minio_no_se_marca_nada_sin_clip(ajustes, motor):
    """Marcar todos los eventos Sin clip por un fallo de configuracion seria
    destruir informacion que todavia esta en el buffer."""
    sembrado = sembrar_evento(
        motor, fecha_hora=dt.datetime.now().replace(tzinfo=None) - dt.timedelta(minutes=10))
    grabador = Grabador(ajustes, motor)

    assert grabador.revisar_clips(forzar=True) == []
    assert leer_evento(motor, sembrado["evento_id"])["estado"] == "pendiente"


def test_el_grabador_recorta_en_su_vuelta(ajustes_con_s3, motor, camara_rtsp):
    reales = grabar_unos_segundos(ajustes_con_s3, camara_rtsp)
    reales = dataclasses.replace(reales, segundos_antes=4, segundos_despues=1,
                                 segundos_entre_clips=0.0,
                                 minio_endpoint=ajustes_con_s3.minio_endpoint,
                                 minio_access_key=ajustes_con_s3.minio_access_key,
                                 minio_secret_key=ajustes_con_s3.minio_secret_key)
    sembrado = sembrar_evento(
        motor, fecha_hora=dt.datetime.now().replace(tzinfo=None) - dt.timedelta(seconds=3))

    grabador = Grabador(reales, motor)
    resultados = grabador.revisar_clips(forzar=True)

    assert resultados and resultados[0].tiene_clip
    assert grabador.clips_recortados == 1
    assert leer_evento(motor, sembrado["evento_id"])["clip_url"]


def test_el_sondeo_no_se_repite_en_cada_vuelta(ajustes_con_s3, motor, monkeypatch):
    lento = dataclasses.replace(ajustes_con_s3, segundos_entre_clips=3600.0)
    grabador = Grabador(lento, motor)
    pasadas = []
    monkeypatch.setattr(clips, "procesar_pendientes",
                        lambda m, a, limite=20, **_extra: pasadas.append(1) or [])

    grabador.revisar_clips(forzar=True)
    grabador.revisar_clips()
    grabador.revisar_clips()
    assert len(pasadas) == 1


def test_un_fallo_de_mysql_no_para_el_grabador(ajustes_con_s3, motor, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def revienta(*_a, **_k):
        raise OperationalError("select 1", {}, Exception("MySQL caido"))

    monkeypatch.setattr(clips, "procesar_pendientes", revienta)
    grabador = Grabador(ajustes_con_s3, motor)
    assert grabador.revisar_clips(forzar=True) == []


def test_el_resumen_cuenta_los_clips(ajustes_con_s3, motor):
    grabador = Grabador(ajustes_con_s3, motor)
    resumen = grabador.resumen()
    assert resumen["clips_recortados"] == 0
    assert resumen["recorta_clips"] is True


def test_la_ventana_del_clip_sale_del_inicio_de_carga(ajustes_con_s3, motor, camara_rtsp):
    """Lo que se gana con la marca de inicio: el clip cubre la carga entera."""
    reales = grabar_unos_segundos(ajustes_con_s3, camara_rtsp, segundos=12)
    reales = dataclasses.replace(reales, segundos_antes=2, segundos_despues=1,
                                 minio_endpoint=ajustes_con_s3.minio_endpoint,
                                 minio_access_key=ajustes_con_s3.minio_access_key,
                                 minio_secret_key=ajustes_con_s3.minio_secret_key)
    ahora = dt.datetime.now().replace(tzinfo=None)
    sembrar_evento(motor, inicio_carga=ahora - dt.timedelta(seconds=10),
                   fecha_hora=ahora - dt.timedelta(seconds=2))

    clips.procesar_pendientes(motor, reales)

    with motor.connect() as conexion:
        detalle = conexion.execute(
            select(tablas.auditoria.c.detalle)
            .where(tablas.auditoria.c.accion == "recortar_clip")).scalar_one()
    desde = dt.datetime.fromisoformat(detalle["desde"])
    hasta = dt.datetime.fromisoformat(detalle["hasta"])
    assert (hasta - desde).total_seconds() == pytest.approx(11, abs=0.5)


def test_la_ventana_se_calcula_igual_en_el_servicio_y_en_el_recorte(ajustes_con_s3):
    """Una sola formula: si se duplicara, las dos copias acabarian discrepando."""
    cierre = dt.datetime(2026, 9, 14, 10, 0, 0)
    inicio = cierre - dt.timedelta(minutes=3)
    ventana = recorte.ventana_de(inicio, cierre, ajustes_con_s3)
    assert ventana.desde == inicio - dt.timedelta(seconds=ajustes_con_s3.segundos_antes)
    assert ventana.hasta == cierre + dt.timedelta(seconds=ajustes_con_s3.segundos_despues)


# ---------------------------------------------------- caminos de error raros
def test_un_bucket_con_nombre_invalido_se_avisa(cliente_s3):
    """S3 no admite mayusculas en el nombre del bucket. Mejor un mensaje que un
    rastro de excepcion del cliente."""
    with pytest.raises(almacen.ErrorDeAlmacen):
        almacen.asegurar_bucket(cliente_s3, "Bucket Invalido")


def test_preguntar_por_un_objeto_que_no_esta_no_revienta(cliente_s3):
    almacen.asegurar_bucket(cliente_s3, "clips")
    assert almacen.existe(cliente_s3, "clips", "no-existe.mkv") is False


def test_una_ventana_de_duracion_cero_no_divide_por_cero():
    momento = dt.datetime(2026, 9, 14, 10, 0, 0)
    clip = recorte.Clip(ruta=None, ventana=recorte.Ventana(momento, momento),
                        camara="camara-01", segmentos_usados=0, segundos_cubiertos=0.0)
    assert clip.cobertura_pct == 0.0


# ------------------------------- el margen posterior tiene que existir primero
def test_no_se_recorta_hasta_que_el_margen_posterior_esta_grabado(ajustes_con_s3, motor):
    """El criterio 1 pide 2 minutos despues del cierre, y esos dos minutos tardan
    dos minutos en existir. Recortar en cuanto nace el evento daria un clip
    cortado justo donde hay que mirar."""
    recien = dataclasses.replace(ajustes_con_s3, segundos_despues=120)
    sembrar_evento(motor, fecha_hora=dt.datetime.now().replace(tzinfo=None))

    assert clips.pendientes_de_clip(motor, recien) == []


def test_pasado_el_margen_el_evento_ya_se_recoge(ajustes_con_s3, motor):
    recien = dataclasses.replace(ajustes_con_s3, segundos_despues=120)
    sembrar_evento(motor,
                   fecha_hora=dt.datetime.now().replace(tzinfo=None) - dt.timedelta(minutes=3))

    assert len(clips.pendientes_de_clip(motor, recien)) == 1


def test_el_margen_se_mide_contra_el_cierre_y_no_contra_la_creacion(ajustes_con_s3, motor):
    """Lo que tiene que haberse grabado es el video posterior a la pesada."""
    recien = dataclasses.replace(ajustes_con_s3, segundos_despues=60)
    ahora = dt.datetime.now().replace(tzinfo=None)
    sembrar_evento(motor, fecha_hora=ahora - dt.timedelta(seconds=30))

    assert clips.pendientes_de_clip(motor, recien) == []
    # Media hora despues, el mismo evento ya tiene su ventana completa.
    assert len(clips.pendientes_de_clip(
        motor, recien, ahora=ahora + dt.timedelta(minutes=30))) == 1
