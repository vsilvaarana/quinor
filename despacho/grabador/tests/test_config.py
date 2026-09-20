"""Ajustes del grabador: catalogo de camaras y limites del criterio 2."""
from __future__ import annotations

import pathlib

import pytest

from app.config import (HORAS_DE_RETENCION, MAXIMO_DE_CAMARAS, Ajustes,
                        cargar_ajustes, parsear_camaras)


# ------------------------------------------------------------ catalogo de camaras
def test_una_camara():
    camaras = parsear_camaras("camara-01=rtsp://10.0.0.11:554/stream")
    assert len(camaras) == 1
    assert camaras[0].id == "camara-01"
    assert camaras[0].url == "rtsp://10.0.0.11:554/stream"


def test_varias_camaras():
    camaras = parsear_camaras(
        "camara-01=rtsp://a/s, camara-02=rtsp://b/s ,camara-03=rtsp://c/s")
    assert [c.id for c in camaras] == ["camara-01", "camara-02", "camara-03"]


def test_una_url_con_credenciales_no_se_parte_por_el_igual():
    """Las camaras IP llevan usuario y clave en la URL, y a veces un = en la ruta."""
    camaras = parsear_camaras("camara-01=rtsp://admin:c=l@10.0.0.11:554/h264?ch=1")
    assert camaras[0].url == "rtsp://admin:c=l@10.0.0.11:554/h264?ch=1"


def test_sin_camaras_configuradas():
    assert parsear_camaras("") == ()
    assert parsear_camaras("  ,  ") == ()


def test_sin_el_igual_el_mensaje_ensena_el_formato():
    with pytest.raises(ValueError, match="id=url"):
        parsear_camaras("camara-01")


@pytest.mark.parametrize("crudo", ["=rtsp://a/s", "camara-01="])
def test_una_camara_a_medias_se_rechaza(crudo):
    with pytest.raises(ValueError, match="Falta el id o la url"):
        parsear_camaras(crudo)


def test_no_se_admiten_camaras_repetidas():
    """Dos filas con el mismo id escribirian en la misma carpeta y en el mismo
    componente de salud, tapandose la una a la otra."""
    with pytest.raises(ValueError, match="repetida"):
        parsear_camaras("camara-01=rtsp://a/s,CAMARA-01=rtsp://b/s")


def test_mas_camaras_de_las_dimensionadas():
    """El RNF-04 dimensiona cuatro. La quinta no es un detalle: cambia el calculo
    de disco del criterio 2 y el de CPU de la planta."""
    muchas = ",".join(f"camara-{i:02d}=rtsp://a/s" for i in range(MAXIMO_DE_CAMARAS + 1))
    with pytest.raises(ValueError, match=str(MAXIMO_DE_CAMARAS)):
        parsear_camaras(muchas)


def test_el_componente_de_salud_sale_del_id():
    camara = parsear_camaras("CAMARA-01=rtsp://a/s")[0]
    assert camara.componente == "camara-01"


# ---------------------------------------------------------------- cargar_ajustes
def test_sin_base_de_datos_no_arranca():
    with pytest.raises(ValueError, match="DATABASE_URL"):
        cargar_ajustes(database_url="")


def test_los_parametros_ganan_al_entorno(monkeypatch):
    monkeypatch.setenv("VIDEO_DIR", "/del-entorno")
    ajustes = cargar_ajustes(database_url="mysql+pymysql://x/y",
                             directorio_buffer=pathlib.Path("/del-parametro"))
    assert ajustes.directorio_buffer == pathlib.Path("/del-parametro")


def test_el_entorno_se_lee_cuando_no_hay_parametro(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://x/y")
    monkeypatch.setenv("CAMERAS", "camara-01=rtsp://a/s")
    monkeypatch.setenv("VIDEO_DIR", "/video-planta")
    monkeypatch.setenv("RETENTION_HOURS", "96")

    ajustes = cargar_ajustes()

    assert ajustes.directorio_buffer == pathlib.Path("/video-planta")
    assert ajustes.horas_de_retencion == 96.0
    assert len(ajustes.camaras) == 1


def test_no_se_puede_configurar_menos_de_72_horas(monkeypatch):
    """El criterio 2 no es un valor por defecto: es el minimo."""
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://x/y")
    with pytest.raises(ValueError, match="72"):
        cargar_ajustes(horas_de_retencion=48)


def test_por_defecto_se_guardan_72_horas(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://x/y")
    assert cargar_ajustes().horas_de_retencion == HORAS_DE_RETENCION


def test_un_segmento_de_cero_segundos_no_tiene_sentido(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://x/y")
    with pytest.raises(ValueError, match="SEGMENT_SECONDS"):
        cargar_ajustes(segundos_por_segmento=0)


def test_por_defecto_los_segmentos_son_de_un_minuto(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://x/y")
    assert cargar_ajustes().segundos_por_segmento == 60


def test_los_segundos_de_retencion_son_las_horas_por_3600():
    ajustes = Ajustes(database_url="mysql+pymysql://x/y", horas_de_retencion=72.0)
    assert ajustes.segundos_de_retencion == 259200.0


def test_los_ajustes_son_inmutables():
    """Igual que en el orquestador: nadie cambia la configuracion en caliente."""
    import dataclasses

    ajustes = Ajustes(database_url="mysql+pymysql://x/y")
    with pytest.raises(dataclasses.FrozenInstanceError):
        ajustes.horas_de_retencion = 1


# --------------------------------------------------------- HU-06 ventana y MinIO
def test_la_duracion_por_defecto_del_clip_son_7_minutos(monkeypatch):
    """5 min antes mas 2 despues: la misma cifra que el RNF de rendimiento usa
    al hablar del "clip de 7 min"."""
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://x/y")
    assert cargar_ajustes().duracion_del_clip_s == 420


def test_los_margenes_del_clip_no_pueden_ser_negativos(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://x/y")
    with pytest.raises(ValueError, match="margenes"):
        cargar_ajustes(segundos_antes=-1)


def test_sin_credenciales_de_minio_no_se_recortan_clips(monkeypatch):
    """Y se dice en el arranque, en lugar de fallar en el primer evento."""
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://x/y")
    assert cargar_ajustes().recorta_clips is False


def test_con_credenciales_si(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://x/y")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "quinor")
    monkeypatch.setenv("MINIO_SECRET_KEY", "secreta")
    ajustes = cargar_ajustes()
    assert ajustes.recorta_clips is True
    assert ajustes.minio_bucket == "clips"


@pytest.mark.parametrize("valor,esperado", [
    ("true", True), ("1", True), ("si", True), ("yes", True),
    ("false", False), ("no", False), ("", False),
])
def test_minio_secure_se_lee_como_booleano(monkeypatch, valor, esperado):
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://x/y")
    monkeypatch.setenv("MINIO_SECURE", valor)
    assert cargar_ajustes().minio_seguro is esperado


# ------------------------------------------------- HU-07 conteo de sacos
def test_sin_url_de_yolo_el_conteo_esta_apagado(monkeypatch):
    """En una instalacion sin GPU, HU-05 y HU-06 tienen que seguir funcionando."""
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://u:c@mysql/quinor")
    monkeypatch.delenv("YOLO_URL", raising=False)
    assert cargar_ajustes().cuenta_sacos is False


def test_con_url_de_yolo_el_conteo_se_enciende(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://u:c@mysql/quinor")
    monkeypatch.setenv("YOLO_URL", "http://yolo:8002")
    monkeypatch.setenv("YOLO_API_KEY", "clave")

    ajustes = cargar_ajustes()

    assert ajustes.cuenta_sacos is True
    assert ajustes.yolo_api_key == "clave"


@pytest.mark.parametrize("valor", ["0", "-2"])
def test_sin_intentos_el_conteo_nunca_se_haria(monkeypatch, valor):
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://u:c@mysql/quinor")
    monkeypatch.setenv("COUNT_MAX_ATTEMPTS", valor)
    with pytest.raises(ValueError, match="1 o mas"):
        cargar_ajustes()


def test_sin_intentos_la_interpretacion_nunca_se_haria(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://u:c@mysql/quinor")
    monkeypatch.setenv("VLM_MAX_ATTEMPTS", "0")
    with pytest.raises(ValueError, match="VLM_MAX_ATTEMPTS"):
        cargar_ajustes()


def test_sin_url_de_vlm_la_interpretacion_esta_apagada(monkeypatch):
    """El apartado 12 da la conectividad a internet como riesgo: el sistema
    tiene que seguir detectando y guardando evidencia sin ella."""
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://u:c@mysql/quinor")
    monkeypatch.delenv("VLM_URL", raising=False)
    assert cargar_ajustes().interpreta_eventos is False


def test_con_url_de_vlm_la_interpretacion_se_enciende(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://u:c@mysql/quinor")
    monkeypatch.setenv("VLM_URL", "http://vlm:8003")
    monkeypatch.setenv("VLM_SERVICE_API_KEY", "clave")

    ajustes = cargar_ajustes()

    assert ajustes.interpreta_eventos is True
    assert ajustes.vlm_api_key == "clave"


# --------------------------------------------------------- HU-10 los avisos
def test_sin_servicio_de_notificaciones_hu10_queda_apagada():
    """Es una instalacion valida: el evento se detecta, se graba y se clasifica,
    y el supervisor lo ve en el dashboard. Lo que no hay es el correo."""
    apagado = cargar_ajustes(database_url="mysql+pymysql://x/y",
                             notificaciones_url="")

    assert apagado.avisa_eventos is False


def test_el_servicio_de_notificaciones_sale_del_entorno(monkeypatch):
    monkeypatch.setenv("NOTIFY_URL", "http://notificaciones:8004")
    monkeypatch.setenv("NOTIFY_SERVICE_API_KEY", "clave-de-servicio")
    monkeypatch.setenv("NOTIFY_POLL_SECONDS", "5")

    ajustes = cargar_ajustes(database_url="mysql+pymysql://x/y")

    assert ajustes.avisa_eventos is True
    assert ajustes.notificaciones_api_key == "clave-de-servicio"
    assert ajustes.segundos_entre_avisos == 5.0


def test_el_sondeo_de_avisos_es_mas_corto_que_el_de_interpretaciones():
    """Lo que espera aqui es un correo con una ventana de 60 segundos, no una
    llamada a un modelo que puede tardar minutos."""
    ajustes = cargar_ajustes(database_url="mysql+pymysql://x/y")

    assert ajustes.segundos_entre_avisos < ajustes.segundos_entre_interpretaciones


def test_un_timeout_de_aviso_mayor_que_el_criterio_no_tiene_sentido():
    """El criterio 3 da 60 segundos para todo. Esperar mas a que el servicio
    conteste seria gastar la ventana esperando a algo que ya no llega a tiempo."""
    ajustes = cargar_ajustes(database_url="mysql+pymysql://x/y")

    assert ajustes.aviso_timeout_s <= 60.0


@pytest.mark.parametrize("variable,valor", [
    ("NOTIFY_MAX_ATTEMPTS", "0"),
    ("NOTIFY_TIMEOUT_SECONDS", "0"),
])
def test_un_aviso_mal_configurado_se_descubre_al_arrancar(monkeypatch, variable,
                                                          valor):
    monkeypatch.setenv(variable, valor)

    with pytest.raises(ValueError):
        cargar_ajustes(database_url="mysql+pymysql://x/y")
