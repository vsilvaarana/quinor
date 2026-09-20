"""Conteo de sacos del clip y escritura en el evento. HU-07, criterio 3.

Contra un servicio YOLO por HTTP de verdad, MySQL de verdad y un servidor S3 de
verdad. El conteo que devuelve el servicio si es preparado: contar es su trabajo
y alli tiene sus propias pruebas. Lo que se comprueba aqui es lo otro, que es lo
que puede fallar en planta: que la cifra llega al evento, que la diferencia se
calcula contra la orden correcta, y que un servicio caido no se lleva por delante
el clip que HU-06 acaba de guardar.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

import pytest
from sqlalchemy import select

from app import almacen, clips, conteo, tablas
from app.config import Ajustes
from tests.conftest import sembrar_evento


def leer_evento(motor, evento_id: int) -> dict:
    with motor.connect() as conexion:
        return dict(conexion.execute(
            select(tablas.evento).where(tablas.evento.c.id == evento_id)
        ).mappings().one())


def auditoria_de(motor, evento_id: int, accion: str) -> list[dict]:
    with motor.connect() as conexion:
        return [dict(f) for f in conexion.execute(
            select(tablas.auditoria)
            .where(tablas.auditoria.c.entidad == "evento",
                   tablas.auditoria.c.entidad_id == evento_id,
                   tablas.auditoria.c.accion == accion)
        ).mappings().all()]


def clip_falso(tmp_path, nombre="evento.mkv"):
    ruta = tmp_path / nombre
    ruta.write_bytes(b"\x1a\x45\xdf\xa3video de prueba")
    return ruta


# ------------------------------------------------------- hablar con el servicio
def test_se_le_pide_el_conteo_al_servicio(ajustes_con_yolo, servicio_yolo, tmp_path):
    resultado = conteo.analizar(ajustes_con_yolo, clip_falso(tmp_path), 400)

    assert resultado.sacos_contados == 398
    assert resultado.sacos_esperados == 400
    assert resultado.diferencia_sacos == -2
    assert resultado.personas_detectadas == 3
    assert servicio_yolo.peticiones[0]["ruta"] == "/analisis/yolo"


def test_el_clip_viaja_por_ruta_y_no_por_el_cuerpo(ajustes_con_yolo, servicio_yolo,
                                                   tmp_path):
    """Son cientos de megas y los dos contenedores comparten el volumen del
    buffer: subirlo por HTTP seria copiar gigas al dia sin motivo."""
    clip = clip_falso(tmp_path)
    conteo.analizar(ajustes_con_yolo, clip, 400)

    cuerpo = servicio_yolo.peticiones[0]["cuerpo"]
    assert cuerpo["clip"] == str(clip)
    assert "video" not in cuerpo and "contenido" not in cuerpo


def test_la_clave_del_servicio_viaja_en_la_cabecera(ajustes_con_yolo, servicio_yolo,
                                                    tmp_path):
    servicio_yolo.clave = "clave-de-servicio"
    ajustes = dataclasses.replace(ajustes_con_yolo, yolo_api_key="clave-de-servicio")

    conteo.analizar(ajustes, clip_falso(tmp_path), 400)

    assert servicio_yolo.peticiones[0]["clave"] == "clave-de-servicio"


def test_sin_la_clave_el_servicio_cierra_la_puerta(ajustes_con_yolo, servicio_yolo,
                                                   tmp_path):
    servicio_yolo.clave = "la-buena"
    with pytest.raises(conteo.ServicioNoDisponible, match="401"):
        conteo.analizar(ajustes_con_yolo, clip_falso(tmp_path), 400)


def test_un_servicio_sin_modelo_cargado_se_avisa(ajustes_con_yolo, servicio_yolo,
                                                 tmp_path):
    """El 503 del servicio mientras carga PyTorch: pasa en cada despliegue."""
    servicio_yolo.codigo = 503
    with pytest.raises(conteo.ServicioNoDisponible, match="503"):
        conteo.analizar(ajustes_con_yolo, clip_falso(tmp_path), 400)


def test_un_servicio_apagado_se_avisa(ajustes_con_yolo, servicio_yolo, tmp_path):
    servicio_yolo.parar()
    with pytest.raises(conteo.ServicioNoDisponible, match="No se pudo hablar"):
        conteo.analizar(ajustes_con_yolo, clip_falso(tmp_path), 400)


def test_un_servicio_que_tarda_demasiado_se_corta(ajustes_con_yolo, servicio_yolo,
                                                  tmp_path):
    """Sin timeout, un YOLO colgado dejaria la vuelta del grabador parada y con
    ella la vigilancia de las camaras."""
    servicio_yolo.demora_s = 2.0
    ajustes = dataclasses.replace(ajustes_con_yolo, yolo_timeout_s=0.3)

    with pytest.raises(conteo.ServicioNoDisponible):
        conteo.analizar(ajustes, clip_falso(tmp_path), 400)


def test_sin_url_configurada_el_conteo_esta_apagado(ajustes, tmp_path):
    """En una instalacion sin GPU, HU-05 y HU-06 siguen funcionando."""
    assert ajustes.cuenta_sacos is False
    with pytest.raises(conteo.ServicioNoDisponible, match="apagado"):
        conteo.analizar(ajustes, clip_falso(tmp_path), 400)


def test_la_barra_final_de_la_url_no_duplica_la_ruta(ajustes_con_yolo, servicio_yolo,
                                                     tmp_path):
    ajustes = dataclasses.replace(ajustes_con_yolo,
                                  yolo_url=ajustes_con_yolo.yolo_url + "/")
    conteo.analizar(ajustes, clip_falso(tmp_path), 400)
    assert servicio_yolo.peticiones[0]["ruta"] == "/analisis/yolo"


# ------------------------------------------- criterio 3: se guarda en el evento
def test_el_conteo_y_la_diferencia_quedan_en_el_evento(ajustes_con_yolo, motor,
                                                       servicio_yolo, tmp_path):
    sembrado = sembrar_evento(motor, sacos_esperados=400)

    resultado = conteo.contar(motor, ajustes_con_yolo, sembrado["evento_id"],
                              clip_falso(tmp_path), 400)

    assert resultado is not None
    fila = leer_evento(motor, sembrado["evento_id"])
    assert fila["sacos_contados"] == 398
    assert fila["diferencia_sacos"] == -2
    assert fila["personas_detectadas"] == 3


def test_la_diferencia_negativa_es_faltante(ajustes_con_yolo, motor, servicio_yolo,
                                            tmp_path):
    """El mismo criterio de signo que la diferencia de peso de HU-03: quien lea
    el evento no tiene que aprender dos convenciones."""
    sembrado = sembrar_evento(motor, sacos_esperados=420)
    resultado = conteo.contar(motor, ajustes_con_yolo, sembrado["evento_id"],
                              clip_falso(tmp_path), 420)

    assert resultado.diferencia_sacos == -22
    assert resultado.faltan_sacos is True
    assert resultado.cuadra is False


def test_una_carga_que_cuadra_se_nota(ajustes_con_yolo, motor, servicio_yolo, tmp_path):
    sembrado = sembrar_evento(motor, sacos_esperados=398)
    resultado = conteo.contar(motor, ajustes_con_yolo, sembrado["evento_id"],
                              clip_falso(tmp_path), 398)

    assert resultado.cuadra is True
    assert resultado.faltan_sacos is False
    assert leer_evento(motor, sembrado["evento_id"])["diferencia_sacos"] == 0


def test_contar_de_mas_da_diferencia_positiva(ajustes_con_yolo, motor, servicio_yolo,
                                              tmp_path):
    sembrado = sembrar_evento(motor, sacos_esperados=390)
    conteo.contar(motor, ajustes_con_yolo, sembrado["evento_id"],
                  clip_falso(tmp_path), 390)
    assert leer_evento(motor, sembrado["evento_id"])["diferencia_sacos"] == 8


def test_queda_el_rastro_de_con_que_modelo_se_conto(ajustes_con_yolo, motor,
                                                    servicio_yolo, tmp_path):
    """HU-19 va a cambiar el modelo; sin esto, nadie sabria con cual se conto una
    carga que se discute seis meses despues."""
    sembrado = sembrar_evento(motor)
    conteo.contar(motor, ajustes_con_yolo, sembrado["evento_id"],
                  clip_falso(tmp_path), 400)

    filas = auditoria_de(motor, sembrado["evento_id"], conteo.ACCION_OK)
    assert len(filas) == 1
    detalle = filas[0]["detalle"]
    assert detalle["modelo"] == "sacos.pt"
    assert detalle["sacos_contados"] == 398
    assert detalle["diferencia_sacos"] == -2
    assert detalle["segundos_de_proceso"] == 95.4


def test_con_el_conteo_apagado_no_se_toca_el_evento(ajustes_con_s3, motor, tmp_path):
    sembrado = sembrar_evento(motor)

    assert conteo.contar(motor, ajustes_con_s3, sembrado["evento_id"],
                         clip_falso(tmp_path), 400) is None
    assert leer_evento(motor, sembrado["evento_id"])["sacos_contados"] is None


def test_un_servicio_caido_no_rompe_el_evento(ajustes_con_yolo, motor, servicio_yolo,
                                              tmp_path):
    """El clip ya esta guardado y vinculado, que es lo que no se puede perder."""
    servicio_yolo.codigo = 503
    sembrado = sembrar_evento(motor, clip_url="s3://clips/evento.mkv")

    assert conteo.contar(motor, ajustes_con_yolo, sembrado["evento_id"],
                         clip_falso(tmp_path), 400) is None

    fila = leer_evento(motor, sembrado["evento_id"])
    assert fila["sacos_contados"] is None
    assert fila["clip_url"] == "s3://clips/evento.mkv"
    fallos = auditoria_de(motor, sembrado["evento_id"], conteo.ACCION_FALLO)
    assert len(fallos) == 1 and "503" in fallos[0]["detalle"]["motivo"]


# --------------------------------------------------------------- los reintentos
def test_un_evento_con_clip_y_sin_conteo_queda_pendiente(ajustes_con_yolo, motor):
    sembrado = sembrar_evento(motor, clip_url="s3://clips/evento.mkv")

    pendientes = conteo.pendientes_de_conteo(motor, ajustes_con_yolo)

    assert [f["id"] for f in pendientes] == [sembrado["evento_id"]]
    assert pendientes[0]["sacos_esperados"] == 400


def test_un_evento_sin_clip_todavia_no_se_puede_contar(ajustes_con_yolo, motor):
    sembrar_evento(motor, clip_url=None)
    assert conteo.pendientes_de_conteo(motor, ajustes_con_yolo) == []


def test_un_evento_ya_contado_no_vuelve(ajustes_con_yolo, motor, servicio_yolo,
                                        tmp_path):
    sembrado = sembrar_evento(motor, clip_url="s3://clips/evento.mkv")
    conteo.contar(motor, ajustes_con_yolo, sembrado["evento_id"],
                  clip_falso(tmp_path), 400)

    assert conteo.pendientes_de_conteo(motor, ajustes_con_yolo) == []


def test_un_evento_sin_clip_disponible_no_se_reintenta(ajustes_con_yolo, motor):
    """Sin clip no hay nada que analizar: ese estado es una conclusion de HU-06,
    no un pendiente."""
    sembrar_evento(motor, estado="sin_clip", clip_url=None)
    assert conteo.pendientes_de_conteo(motor, ajustes_con_yolo) == []


def test_los_intentos_se_acaban(ajustes_con_yolo, motor, servicio_yolo, tmp_path):
    """Un YOLO caido un dia entero tendria al grabador bajando los mismos clips
    cada quince segundos hasta que alguien mirase el log."""
    servicio_yolo.codigo = 503
    sembrado = sembrar_evento(motor, clip_url="s3://clips/evento.mkv")

    for intento in range(ajustes_con_yolo.intentos_de_conteo):
        assert len(conteo.pendientes_de_conteo(motor, ajustes_con_yolo)) == 1, intento
        conteo.contar(motor, ajustes_con_yolo, sembrado["evento_id"],
                      clip_falso(tmp_path), 400)

    assert conteo.pendientes_de_conteo(motor, ajustes_con_yolo) == []


def test_el_reintento_baja_el_clip_del_almacen(ajustes_con_yolo, motor, cliente_s3,
                                               servicio_yolo, tmp_path):
    """Se baja de MinIO y no se vuelve a recortar del buffer: el buffer solo
    guarda 72 h y el clip del almacen es exactamente el que se vinculo."""
    original = clip_falso(tmp_path, "original.mkv")
    direccion = almacen.subir(cliente_s3, "clips", "2026/09/16/ORD/evento.mkv", original)
    sembrado = sembrar_evento(motor, clip_url=direccion)

    hechos = conteo.procesar_pendientes(motor, ajustes_con_yolo, cliente=cliente_s3)

    assert len(hechos) == 1
    assert leer_evento(motor, sembrado["evento_id"])["sacos_contados"] == 398
    # El servicio recibio la ruta del archivo bajado, no la direccion s3://.
    assert servicio_yolo.peticiones[0]["cuerpo"]["clip"].endswith(
        f"evento-{sembrado['evento_id']}.mkv")


def test_un_clip_que_ya_no_esta_en_el_almacen_se_anota(ajustes_con_yolo, motor,
                                                       cliente_s3, servicio_yolo):
    sembrado = sembrar_evento(motor, clip_url="s3://clips/no-existe.mkv")

    assert conteo.procesar_pendientes(motor, ajustes_con_yolo,
                                      cliente=cliente_s3) == []
    assert auditoria_de(motor, sembrado["evento_id"], conteo.ACCION_FALLO)


def test_una_direccion_que_no_es_del_almacen_se_avisa(cliente_s3, tmp_path):
    with pytest.raises(almacen.ErrorDeAlmacen, match="no es una direccion"):
        almacen.descargar(cliente_s3, "/video/clip.mkv", tmp_path / "x.mkv")


def test_un_evento_roto_no_detiene_a_los_demas(ajustes_con_yolo, motor, cliente_s3,
                                               servicio_yolo, tmp_path, monkeypatch):
    """La misma regla que en HU-06: el que reviente se queda, los otros siguen."""
    bueno = clip_falso(tmp_path, "bueno.mkv")
    direccion = almacen.subir(cliente_s3, "clips", "bueno.mkv", bueno)
    sembrar_evento(motor, numero_orden="ORD-2026-0001", clip_url=direccion)
    segundo = sembrar_evento(motor, numero_orden="ORD-2026-0002", clip_url=direccion)

    original = conteo.procesar_evento
    llamadas = {"n": 0}

    def a_veces_revienta(*args, **kwargs):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise RuntimeError("disco lleno al bajar el clip")
        return original(*args, **kwargs)

    monkeypatch.setattr(conteo, "procesar_evento", a_veces_revienta)
    hechos = conteo.procesar_pendientes(motor, ajustes_con_yolo, cliente=cliente_s3)

    assert len(hechos) == 1
    assert leer_evento(motor, segundo["evento_id"])["sacos_contados"] == 398


# ----------------------------------------- el camino normal: junto con el clip
def test_el_clip_recien_recortado_se_cuenta_sin_bajarlo(ajustes_con_yolo, motor,
                                                        camara_rtsp, cliente_s3,
                                                        servicio_yolo):
    """De punta a punta: video real, recorte real, subida real y conteo.

    El clip se analiza mientras todavia esta en disco local, que es el momento
    mas barato para hacerlo.
    """
    from tests.test_clips import grabar_unos_segundos

    reales = grabar_unos_segundos(ajustes_con_yolo, camara_rtsp)
    reales = dataclasses.replace(
        reales, segundos_antes=4, segundos_despues=1,
        minio_endpoint=ajustes_con_yolo.minio_endpoint,
        minio_access_key=ajustes_con_yolo.minio_access_key,
        minio_secret_key=ajustes_con_yolo.minio_secret_key,
        yolo_url=ajustes_con_yolo.yolo_url)
    sembrado = sembrar_evento(
        motor, sacos_esperados=400,
        fecha_hora=dt.datetime.now().replace(tzinfo=None) - dt.timedelta(seconds=3))

    resultados = clips.procesar_pendientes(motor, reales)

    assert len(resultados) == 1
    assert resultados[0].tiene_clip and resultados[0].tiene_conteo
    assert resultados[0].sacos_contados == 398
    assert resultados[0].diferencia_sacos == -2

    fila = leer_evento(motor, sembrado["evento_id"])
    assert fila["clip_url"].startswith("s3://")
    assert fila["sacos_contados"] == 398
    assert fila["diferencia_sacos"] == -2

    # Y ya no queda pendiente de conteo: se hizo en la misma pasada.
    assert conteo.pendientes_de_conteo(motor, reales) == []


# ------------------------------- HU-08: las personas de la zona de carga
def personas_de(motor, evento_id: int) -> list[dict]:
    with motor.connect() as conexion:
        return [dict(f) for f in conexion.execute(
            select(tablas.persona_en_evento)
            .where(tablas.persona_en_evento.c.evento_id == evento_id)
            .order_by(tablas.persona_en_evento.c.id_temporal)
        ).mappings().all()]


def test_quien_estuvo_en_zona_y_cuanto_queda_guardado(ajustes_con_yolo, motor,
                                                      servicio_yolo, tmp_path):
    """Criterio 2 de HU-08: cuantas personas y el tiempo de permanencia."""
    sembrado = sembrar_evento(motor)

    conteo.contar(motor, ajustes_con_yolo, sembrado["evento_id"],
                  clip_falso(tmp_path), 400)

    filas = personas_de(motor, sembrado["evento_id"])
    assert len(filas) == 3
    assert [f["id_temporal"] for f in filas] == [1, 2, 3]
    assert float(filas[0]["segundos_en_zona"]) == pytest.approx(320.5)
    assert leer_evento(motor, sembrado["evento_id"])["personas_detectadas"] == 3


def test_de_cada_persona_solo_se_guardan_un_numero_y_unos_segundos(
        ajustes_con_yolo, motor, servicio_yolo, tmp_path):
    """RN-08: si alguien anadiera una foto, un recorte o un descriptor a la
    tabla, esta prueba lo diria. El criterio 3 no se cumple por omision."""
    sembrado = sembrar_evento(motor)
    conteo.contar(motor, ajustes_con_yolo, sembrado["evento_id"],
                  clip_falso(tmp_path), 400)

    columnas = set(personas_de(motor, sembrado["evento_id"])[0])

    assert columnas == {"id", "evento_id", "id_temporal", "segundos_en_zona",
                        "primer_fotograma", "ultimo_fotograma", "creado_en"}


def test_reanalizar_el_clip_reemplaza_y_no_duplica(ajustes_con_yolo, motor,
                                                   servicio_yolo, tmp_path):
    """HU-19 va a cambiar el modelo y reanalizar clips. El registro tiene que
    quedar como ese analisis, no como la suma de todos los que se hicieron."""
    sembrado = sembrar_evento(motor)
    conteo.contar(motor, ajustes_con_yolo, sembrado["evento_id"],
                  clip_falso(tmp_path), 400)

    servicio_yolo.respuesta["presencia"]["personas"] = [
        {"id_temporal": 1, "segundos_en_zona": 300.0,
         "primer_fotograma": 10, "ultimo_fotograma": 3000}]
    servicio_yolo.respuesta["presencia"]["cuantas"] = 1
    servicio_yolo.respuesta["personas_detectadas"] = 1
    conteo.contar(motor, ajustes_con_yolo, sembrado["evento_id"],
                  clip_falso(tmp_path), 400)

    filas = personas_de(motor, sembrado["evento_id"])
    assert len(filas) == 1
    assert float(filas[0]["segundos_en_zona"]) == pytest.approx(300.0)


def test_una_rampa_vacia_no_deja_filas(ajustes_con_yolo, motor, servicio_yolo,
                                       tmp_path):
    servicio_yolo.respuesta["presencia"]["personas"] = []
    servicio_yolo.respuesta["presencia"]["cuantas"] = 0
    servicio_yolo.respuesta["personas_detectadas"] = 0
    sembrado = sembrar_evento(motor)

    conteo.contar(motor, ajustes_con_yolo, sembrado["evento_id"],
                  clip_falso(tmp_path), 400)

    assert personas_de(motor, sembrado["evento_id"]) == []
    assert leer_evento(motor, sembrado["evento_id"])["personas_detectadas"] == 0


def test_la_senal_de_personal_anomalo_queda_en_el_evento(ajustes_con_yolo, motor,
                                                         servicio_yolo, tmp_path):
    """Es lo que HU-09 consultara para decidir si invoca al modelo de
    vision-lenguaje, segun la RN-03."""
    servicio_yolo.respuesta["anomalia_de_personal"] = True
    servicio_yolo.respuesta["motivos_de_anomalia"] = [
        {"codigo": "demasiadas_personas_a_la_vez",
         "detalle": "Hubo 6 personas a la vez y lo habitual son 3.",
         "medido": 6.0, "umbral": 3.0}]
    sembrado = sembrar_evento(motor)

    resultado = conteo.contar(motor, ajustes_con_yolo, sembrado["evento_id"],
                              clip_falso(tmp_path), 400)

    assert resultado.personal_anomalo is True
    assert resultado.motivos_de_anomalia == ("demasiadas_personas_a_la_vez",)
    assert leer_evento(motor, sembrado["evento_id"])["personal_anomalo"] == 1


def test_una_carga_normal_deja_la_senal_en_falso(ajustes_con_yolo, motor,
                                                 servicio_yolo, tmp_path):
    """Falso y no nulo: nulo significa que el clip no se ha analizado, y HU-09
    no puede confundir "no se miro" con "se miro y estaba bien"."""
    sembrado = sembrar_evento(motor)
    conteo.contar(motor, ajustes_con_yolo, sembrado["evento_id"],
                  clip_falso(tmp_path), 400)

    assert leer_evento(motor, sembrado["evento_id"])["personal_anomalo"] == 0


def test_antes_de_analizar_la_senal_es_nula(motor):
    sembrado = sembrar_evento(motor)
    assert leer_evento(motor, sembrado["evento_id"])["personal_anomalo"] is None


def test_la_auditoria_guarda_los_numeros_y_no_a_las_personas(ajustes_con_yolo,
                                                             motor, servicio_yolo,
                                                             tmp_path):
    servicio_yolo.respuesta["anomalia_de_personal"] = True
    servicio_yolo.respuesta["motivos_de_anomalia"] = [
        {"codigo": "permanencia_excesiva", "detalle": "x", "medido": 900.0,
         "umbral": 600.0}]
    sembrado = sembrar_evento(motor)

    conteo.contar(motor, ajustes_con_yolo, sembrado["evento_id"],
                  clip_falso(tmp_path), 400)

    detalle = auditoria_de(motor, sembrado["evento_id"], conteo.ACCION_OK)[0]["detalle"]
    assert detalle["maximo_simultaneo"] == 2
    assert detalle["permanencia_maxima_s"] == 320.5
    assert detalle["motivos_de_anomalia"] == ["permanencia_excesiva"]
    # Ni un identificador de persona: en auditoria van los numeros que sostienen
    # el aviso, no quien estuvo.
    assert "personas" not in detalle
    assert "id_temporal" not in str(detalle)


def test_un_servicio_antiguo_sin_presencia_no_rompe_el_conteo(ajustes_con_yolo,
                                                              motor, servicio_yolo,
                                                              tmp_path):
    """Durante un despliegue puede haber un YOLO de la version anterior en pie.
    Que no traiga personas no puede tumbar el conteo de sacos, que si trae."""
    servicio_yolo.respuesta.pop("presencia")
    servicio_yolo.respuesta.pop("anomalia_de_personal")
    servicio_yolo.respuesta.pop("motivos_de_anomalia")
    sembrado = sembrar_evento(motor)

    resultado = conteo.contar(motor, ajustes_con_yolo, sembrado["evento_id"],
                              clip_falso(tmp_path), 400)

    assert resultado.sacos_contados == 398
    assert resultado.personas == ()
    assert resultado.personal_anomalo is False
    assert personas_de(motor, sembrado["evento_id"]) == []


# ------------------------------------------- el grabador que lo dispara
def test_el_grabador_reintenta_en_su_vuelta(ajustes_con_yolo, motor, cliente_s3,
                                            servicio_yolo, tmp_path, monkeypatch):
    from app.grabador import Grabador

    monkeypatch.setattr(conteo, "almacen", _AlmacenFalso(clip_falso(tmp_path)))
    sembrado = sembrar_evento(motor, clip_url="s3://clips/evento.mkv")
    grabador = Grabador(ajustes_con_yolo, motor)

    hechos = grabador.revisar_conteos(forzar=True)

    assert len(hechos) == 1
    assert grabador.sacos_contados == 1
    assert leer_evento(motor, sembrado["evento_id"])["sacos_contados"] == 398


def test_sin_servicio_configurado_no_se_intenta_contar(ajustes_con_s3, motor):
    """En una instalacion sin GPU, HU-05 y HU-06 siguen funcionando solas."""
    from app.grabador import Grabador

    sembrar_evento(motor, clip_url="s3://clips/evento.mkv")
    grabador = Grabador(ajustes_con_s3, motor)

    assert grabador.revisar_conteos(forzar=True) == []


def test_sin_minio_tampoco_hay_de_donde_bajar_el_clip(ajustes, motor, servicio_yolo):
    """El reintento baja el clip del almacen; sin credenciales no hay almacen."""
    from app.grabador import Grabador

    sin_almacen = dataclasses.replace(ajustes, yolo_url=servicio_yolo.url)
    assert sin_almacen.cuenta_sacos is True and sin_almacen.recorta_clips is False
    assert Grabador(sin_almacen, motor).revisar_conteos(forzar=True) == []


def test_el_sondeo_de_conteos_no_se_repite_en_cada_vuelta(ajustes_con_yolo, motor,
                                                          monkeypatch):
    from app.grabador import Grabador

    lento = dataclasses.replace(ajustes_con_yolo, segundos_entre_conteos=3600.0)
    pasadas = []
    monkeypatch.setattr(conteo, "procesar_pendientes",
                        lambda *a, **k: pasadas.append(1) or [])
    grabador = Grabador(lento, motor)

    grabador.revisar_conteos(forzar=True)
    grabador.revisar_conteos()
    grabador.revisar_conteos()

    assert len(pasadas) == 1


def test_un_fallo_de_mysql_no_para_el_grabador(ajustes_con_yolo, motor, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from app.grabador import Grabador

    def revienta(*_a, **_k):
        raise OperationalError("select 1", {}, Exception("MySQL caido"))

    monkeypatch.setattr(conteo, "procesar_pendientes", revienta)
    assert Grabador(ajustes_con_yolo, motor).revisar_conteos(forzar=True) == []


def test_la_vuelta_completa_incluye_el_conteo(ajustes_con_yolo, motor, monkeypatch):
    """Si `una_vuelta` no lo llamara, el reintento no existiria en produccion
    aunque todas las pruebas de este archivo pasaran."""
    from app.grabador import Grabador

    llamadas = []
    monkeypatch.setattr(conteo, "procesar_pendientes",
                        lambda *a, **k: llamadas.append(1) or [])
    grabador = Grabador(dataclasses.replace(ajustes_con_yolo, camaras=()), motor)

    grabador.una_vuelta()

    assert llamadas == [1]


def test_el_resumen_dice_si_el_conteo_esta_encendido(ajustes_con_yolo, motor):
    from app.grabador import Grabador

    resumen = Grabador(ajustes_con_yolo, motor).resumen()
    assert resumen["cuenta_sacos"] is True
    assert resumen["eventos_contados"] == 0


class _AlmacenFalso:
    """Un almacen que entrega siempre el mismo clip local.

    Para las pruebas del bucle, donde lo que se mira es que el grabador llame al
    conteo cuando toca. Que la descarga de MinIO funciona lo prueba
    `test_el_reintento_baja_el_clip_del_almacen` con un servidor S3 de verdad.
    """

    ErrorDeAlmacen = almacen.ErrorDeAlmacen

    def __init__(self, clip):
        self.clip = clip

    def crear_cliente(self, _ajustes):
        return object()

    def descargar(self, _cliente, _direccion, destino):
        destino.write_bytes(self.clip.read_bytes())
        return destino
