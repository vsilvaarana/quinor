"""Interpretacion del evento y severidad. HU-09, desde el lado del grabador.

Contra un servicio de vision-lenguaje por HTTP de verdad, MySQL de verdad y un
servidor S3 de verdad. Lo que describe el servicio es preparado: describir es su
trabajo y alli tiene sus pruebas. Lo que se comprueba aqui es lo otro, que es lo
que puede fallar en planta: que los fotogramas suben al almacen y llegan al
modelo, que la severidad acaba en el evento, y que un proveedor caido deja el
caso en Pendiente de analisis y no en silencio.
"""
from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy import select

from app import almacen, clips, interpretacion, tablas
from app.conteo import Conteo, FotogramaClave
from tests.conftest import sembrar_evento

PENDIENTE_ANALISIS = "pendiente_analisis"


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


def conteo_con_fotogramas(cuantos: int = 2) -> Conteo:
    """Lo que el servicio YOLO acaba de devolver, con sus fotogramas clave."""
    return Conteo(
        sacos_contados=398, sacos_entrantes=400, sacos_salientes=2,
        personas_detectadas=3, sacos_esperados=400, diferencia_sacos=-2,
        modelo="sacos.pt", segundos_de_proceso=95.4,
        maximo_simultaneo=2, permanencia_maxima_s=320.5,
        personal_anomalo=True, motivos_de_anomalia=("demasiadas_personas_a_la_vez",),
        fotogramas=tuple(
            FotogramaClave(jpeg=b"\xff\xd8\xff" + bytes([i]) * 40,
                           motivo="saco_saliente" if i == 0 else "pico_de_personas",
                           detalle="x", segundo=12.0 * (i + 1),
                           fotograma=120 * (i + 1))
            for i in range(cuantos)))


def fila_de(sembrado, **extra) -> dict:
    return {"id": sembrado["evento_id"], "clip_url": "s3://clips/evento.mkv",
            "numero_orden": sembrado["numero_orden"],
            "producto": "Quinua blanca organica",
            "peso_esperado_kg": 20000.0, "peso_real_kg": 19850.0,
            "diferencia_kg": -150.0, "diferencia_pct": -0.75,
            "sacos_esperados": 400, "sacos_contados": 398,
            "diferencia_sacos": -2, "personas_detectadas": 3,
            "personal_anomalo": True, "estado": "pendiente", **extra}


# --------------------------------------------- criterio 2: se guarda el analisis
def test_la_severidad_y_la_descripcion_quedan_en_el_evento(ajustes_con_vlm, motor,
                                                           servicio_vlm, cliente_s3):
    sembrado = sembrar_evento(motor)

    resultado = interpretacion.interpretar(
        motor, ajustes_con_vlm, fila_de(sembrado),
        conteo=conteo_con_fotogramas(), cliente=cliente_s3)

    assert resultado.severidad == "alta"
    fila = leer_evento(motor, sembrado["evento_id"])
    assert fila["severidad"] == "alta"
    assert fila["descripcion_ia"]["descripcion"]
    assert fila["descripcion_ia"]["evidencia"]


def test_se_guarda_la_severidad_del_modelo_aparte_de_la_del_evento(
        ajustes_con_vlm, motor, servicio_vlm, cliente_s3):
    """De comparar las dos sale la concordancia semanal del apartado 9.2. Si solo
    se guardara una, esa medicion no se podria hacer."""
    servicio_vlm.respuesta["analisis"]["severidad_ia"] = "media"
    servicio_vlm.respuesta["concuerdan"] = False
    sembrado = sembrar_evento(motor)

    interpretacion.interpretar(motor, ajustes_con_vlm, fila_de(sembrado),
                               conteo=conteo_con_fotogramas(), cliente=cliente_s3)

    fila = leer_evento(motor, sembrado["evento_id"])
    assert fila["severidad"] == "alta"                       # la de la RN-04
    assert fila["descripcion_ia"]["severidad_ia"] == "media"  # la del modelo


def test_la_discrepancia_de_severidad_queda_en_auditoria(ajustes_con_vlm, motor,
                                                         servicio_vlm, cliente_s3):
    servicio_vlm.respuesta["concuerdan"] = False
    sembrado = sembrar_evento(motor)

    interpretacion.interpretar(motor, ajustes_con_vlm, fila_de(sembrado),
                               conteo=conteo_con_fotogramas(), cliente=cliente_s3)

    detalle = auditoria_de(motor, sembrado["evento_id"],
                           interpretacion.ACCION_OK)[0]["detalle"]
    assert detalle["concuerdan"] is False
    assert detalle["severidad"] == "alta"
    assert detalle["severidad_ia"] == "alta"


def test_queda_el_rastro_de_con_que_modelo_se_describio(ajustes_con_vlm, motor,
                                                        servicio_vlm, cliente_s3):
    sembrado = sembrar_evento(motor)

    interpretacion.interpretar(motor, ajustes_con_vlm, fila_de(sembrado),
                               conteo=conteo_con_fotogramas(), cliente=cliente_s3)

    guardado = leer_evento(motor, sembrado["evento_id"])["descripcion_ia"]
    assert guardado["modelo"] == "modelo-de-prueba"
    assert guardado["proveedor"] == "stub"


# ----------------------------------------------------------- los fotogramas
def test_los_fotogramas_se_guardan_junto_al_clip(ajustes_con_vlm, motor,
                                                 servicio_vlm, cliente_s3):
    """Cuando alguien investigue un caso, la evidencia de ese evento esta en una
    sola carpeta del almacen."""
    sembrado = sembrar_evento(motor)

    interpretacion.interpretar(
        motor, ajustes_con_vlm,
        fila_de(sembrado, clip_url="s3://clips/2026/09/17/ORD/evento-1.mkv"),
        conteo=conteo_con_fotogramas(), cliente=cliente_s3)

    guardados = leer_evento(motor, sembrado["evento_id"])["fotogramas_clave"]
    assert len(guardados) == 2
    assert guardados[0]["url"].startswith(
        "s3://clips/2026/09/17/ORD/evento-1/fotogramas/")
    assert almacen.existe(cliente_s3, "clips",
                          guardados[0]["url"].split("clips/", 1)[1])


def test_el_fotograma_guardado_es_el_que_devolvio_yolo(ajustes_con_vlm, motor,
                                                       servicio_vlm, cliente_s3):
    sembrado = sembrar_evento(motor)
    conteo = conteo_con_fotogramas(1)

    interpretacion.interpretar(motor, ajustes_con_vlm, fila_de(sembrado),
                               conteo=conteo, cliente=cliente_s3)

    guardado = leer_evento(motor, sembrado["evento_id"])["fotogramas_clave"][0]
    objeto = guardado["url"].split("clips/", 1)[1]
    respuesta = cliente_s3.get_object("clips", objeto)
    try:
        assert respuesta.read() == conteo.fotogramas[0].jpeg
    finally:
        respuesta.close()
        respuesta.release_conn()


def test_los_fotogramas_llegan_al_modelo(ajustes_con_vlm, motor, servicio_vlm,
                                         cliente_s3):
    sembrado = sembrar_evento(motor)

    interpretacion.interpretar(motor, ajustes_con_vlm, fila_de(sembrado),
                               conteo=conteo_con_fotogramas(2), cliente=cliente_s3)

    enviados = servicio_vlm.peticiones[0]["cuerpo"]["fotogramas"]
    assert len(enviados) == 2
    assert enviados[0]["motivo"] == "saco_saliente"
    assert enviados[0]["jpeg_base64"]


def test_se_guarda_el_motivo_y_el_segundo_de_cada_fotograma(ajustes_con_vlm, motor,
                                                            servicio_vlm, cliente_s3):
    """HU-12 pedira mostrar el fotograma de la anomalia y saltar a ese punto del
    clip: sin el segundo, habria que buscarlo a ojo."""
    sembrado = sembrar_evento(motor)

    interpretacion.interpretar(motor, ajustes_con_vlm, fila_de(sembrado),
                               conteo=conteo_con_fotogramas(), cliente=cliente_s3)

    guardado = leer_evento(motor, sembrado["evento_id"])["fotogramas_clave"][0]
    assert guardado["motivo"] == "saco_saliente"
    assert guardado["segundo"] == 12.0
    assert guardado["fotograma"] == 120


def test_sin_almacen_se_interpreta_igual_pero_sin_guardar_imagenes(
        ajustes_con_vlm, motor, servicio_vlm):
    """Una descripcion sin fotogramas sigue siendo util; no tenerla porque MinIO
    no responde, no."""
    sembrado = sembrar_evento(motor)

    resultado = interpretacion.interpretar(
        motor, ajustes_con_vlm, fila_de(sembrado),
        conteo=conteo_con_fotogramas(), cliente=None)

    assert resultado.severidad == "alta"
    assert leer_evento(motor, sembrado["evento_id"])["fotogramas_clave"] is None


def test_un_clip_con_direccion_rara_no_rompe_la_subida(ajustes_con_vlm, motor,
                                                       servicio_vlm, cliente_s3):
    sembrado = sembrar_evento(motor)

    resultado = interpretacion.interpretar(
        motor, ajustes_con_vlm, fila_de(sembrado, clip_url="/video/local.mkv"),
        conteo=conteo_con_fotogramas(), cliente=cliente_s3)

    assert resultado.severidad == "alta"


# ------------------------------------------- criterio 1: no siempre se invoca
def test_cuando_el_servicio_no_invoca_se_guarda_la_severidad_igual(
        ajustes_con_vlm, motor, servicio_vlm, cliente_s3):
    """La RN-04 no necesita al modelo, y HU-11 necesita la severidad para
    ordenar la cola."""
    servicio_vlm.respuesta.update({
        "invocado": False, "motivo_de_invocacion": "nada_que_explicar",
        "severidad": "baja", "analisis": None})
    sembrado = sembrar_evento(motor)

    resultado = interpretacion.interpretar(
        motor, ajustes_con_vlm, fila_de(sembrado),
        conteo=conteo_con_fotogramas(), cliente=cliente_s3)

    assert resultado.invocado is False
    fila = leer_evento(motor, sembrado["evento_id"])
    assert fila["severidad"] == "baja"
    assert fila["descripcion_ia"] is None


def test_no_haber_invocado_tambien_se_registra(ajustes_con_vlm, motor,
                                               servicio_vlm, cliente_s3):
    """Un evento sin descripcion y sin explicacion parece un fallo del sistema, y
    alguien acabara reintentandolo a mano."""
    servicio_vlm.respuesta.update({
        "invocado": False, "motivo_de_invocacion": "nada_que_explicar",
        "explicacion": "El conteo cuadra.", "severidad": "baja", "analisis": None})
    sembrado = sembrar_evento(motor)

    interpretacion.interpretar(motor, ajustes_con_vlm, fila_de(sembrado),
                               conteo=conteo_con_fotogramas(), cliente=cliente_s3)

    filas = auditoria_de(motor, sembrado["evento_id"],
                         interpretacion.ACCION_NO_INVOCADO)
    assert len(filas) == 1
    assert filas[0]["detalle"]["motivo"] == "nada_que_explicar"


def test_sin_servicio_configurado_no_se_intenta(ajustes_con_yolo, motor):
    """El apartado 12 da la conectividad como riesgo: el sistema tiene que
    seguir detectando y guardando evidencia sin ella."""
    sembrado = sembrar_evento(motor)

    assert ajustes_con_yolo.interpreta_eventos is False
    assert interpretacion.interpretar(
        motor, ajustes_con_yolo, fila_de(sembrado),
        conteo=conteo_con_fotogramas()) is None
    assert leer_evento(motor, sembrado["evento_id"])["severidad"] is None


# ------------------------ criterio 3: tres intentos y Pendiente de analisis
def test_cuando_el_modelo_agota_sus_intentos_el_evento_queda_marcado(
        ajustes_con_vlm, motor, servicio_vlm, cliente_s3):
    """Es el estado del apartado 5.3: "el analisis de IA fallo tras los
    reintentos", y vuelve a Pendiente al reintentar."""
    servicio_vlm.respuesta.update({
        "fallo": True, "motivo_del_fallo": "El proveedor respondio 503 tres veces.",
        "intentos": 3, "analisis": None})
    sembrado = sembrar_evento(motor)

    resultado = interpretacion.interpretar(
        motor, ajustes_con_vlm, fila_de(sembrado),
        conteo=conteo_con_fotogramas(), cliente=cliente_s3)

    assert resultado.fallo is True
    assert leer_evento(motor, sembrado["evento_id"])["estado"] == PENDIENTE_ANALISIS


def test_aunque_el_modelo_falle_la_severidad_se_guarda(ajustes_con_vlm, motor,
                                                       servicio_vlm, cliente_s3):
    """La alerta base no depende de una API externa, que es justo el riesgo que
    senala el apartado 12."""
    servicio_vlm.respuesta.update({
        "fallo": True, "motivo_del_fallo": "503", "intentos": 3, "analisis": None})
    sembrado = sembrar_evento(motor)

    interpretacion.interpretar(motor, ajustes_con_vlm, fila_de(sembrado),
                               conteo=conteo_con_fotogramas(), cliente=cliente_s3)

    fila = leer_evento(motor, sembrado["evento_id"])
    assert fila["severidad"] == "alta"
    assert fila["estado"] == PENDIENTE_ANALISIS


def test_el_servicio_caido_tambien_deja_el_evento_marcado(ajustes_con_vlm, motor,
                                                          servicio_vlm, cliente_s3):
    """No es lo mismo que el proveedor falle a que el servicio no este; para el
    evento, las dos acaban igual."""
    servicio_vlm.parar()
    sembrado = sembrar_evento(motor)

    resultado = interpretacion.interpretar(
        motor, ajustes_con_vlm, fila_de(sembrado),
        conteo=conteo_con_fotogramas(), cliente=cliente_s3)

    assert resultado.fallo is True
    assert leer_evento(motor, sembrado["evento_id"])["estado"] == PENDIENTE_ANALISIS
    assert auditoria_de(motor, sembrado["evento_id"], interpretacion.ACCION_FALLO)


def test_un_reintento_con_exito_devuelve_el_evento_a_pendiente(
        ajustes_con_vlm, motor, servicio_vlm, cliente_s3):
    """La transicion de vuelta del apartado 5.3."""
    sembrado = sembrar_evento(motor, estado=PENDIENTE_ANALISIS)

    interpretacion.interpretar(motor, ajustes_con_vlm,
                               fila_de(sembrado, estado=PENDIENTE_ANALISIS),
                               conteo=conteo_con_fotogramas(), cliente=cliente_s3)

    assert leer_evento(motor, sembrado["evento_id"])["estado"] == "pendiente"


def test_un_caso_ya_abierto_por_un_supervisor_no_se_toca(ajustes_con_vlm, motor,
                                                         servicio_vlm, cliente_s3):
    """Un analisis que falla tarde no puede devolver a la cola un caso que
    alguien esta revisando."""
    servicio_vlm.respuesta.update({"fallo": True, "motivo_del_fallo": "503",
                                   "intentos": 3, "analisis": None})
    sembrado = sembrar_evento(motor, estado="en_revision")

    interpretacion.interpretar(motor, ajustes_con_vlm,
                               fila_de(sembrado, estado="en_revision"),
                               conteo=conteo_con_fotogramas(), cliente=cliente_s3)

    assert leer_evento(motor, sembrado["evento_id"])["estado"] == "en_revision"


def test_un_confirmado_no_retrocede(ajustes_con_vlm, motor, servicio_vlm,
                                    cliente_s3):
    """RN-06: un evento Confirmado no puede regresar al estado Pendiente."""
    servicio_vlm.respuesta.update({"fallo": True, "motivo_del_fallo": "503",
                                   "intentos": 3, "analisis": None})
    sembrado = sembrar_evento(motor, estado="confirmado")

    interpretacion.interpretar(motor, ajustes_con_vlm,
                               fila_de(sembrado, estado="confirmado"),
                               conteo=conteo_con_fotogramas(), cliente=cliente_s3)

    assert leer_evento(motor, sembrado["evento_id"])["estado"] == "confirmado"


def test_la_clave_del_servicio_viaja_en_la_cabecera(ajustes_con_vlm, motor,
                                                    servicio_vlm, cliente_s3):
    servicio_vlm.clave = "clave-de-servicio"
    ajustes = dataclasses.replace(ajustes_con_vlm, vlm_api_key="clave-de-servicio")
    sembrado = sembrar_evento(motor)

    interpretacion.interpretar(motor, ajustes, fila_de(sembrado),
                               conteo=conteo_con_fotogramas(), cliente=cliente_s3)

    assert servicio_vlm.peticiones[0]["clave"] == "clave-de-servicio"


def test_sin_la_clave_el_servicio_cierra_la_puerta(ajustes_con_vlm, motor,
                                                   servicio_vlm, cliente_s3):
    servicio_vlm.clave = "la-buena"
    sembrado = sembrar_evento(motor)

    resultado = interpretacion.interpretar(
        motor, ajustes_con_vlm, fila_de(sembrado),
        conteo=conteo_con_fotogramas(), cliente=cliente_s3)

    assert resultado.fallo is True
    assert "401" in resultado.motivo_del_fallo


def test_un_servicio_que_tarda_demasiado_se_corta(ajustes_con_vlm, motor,
                                                  servicio_vlm, cliente_s3):
    servicio_vlm.demora_s = 2.0
    ajustes = dataclasses.replace(ajustes_con_vlm, vlm_timeout_s=0.3)
    sembrado = sembrar_evento(motor)

    resultado = interpretacion.interpretar(
        motor, ajustes, fila_de(sembrado),
        conteo=conteo_con_fotogramas(), cliente=cliente_s3)

    assert resultado.fallo is True


# --------------------------------------------------------------- los reintentos
def test_un_evento_analizado_y_sin_severidad_queda_pendiente(ajustes_con_vlm, motor):
    sembrado = sembrar_evento(motor)
    with motor.begin() as conexion:
        conexion.execute(tablas.evento.update()
                         .where(tablas.evento.c.id == sembrado["evento_id"])
                         .values(sacos_contados=398, diferencia_sacos=-2))

    pendientes = interpretacion.pendientes_de_interpretar(motor, ajustes_con_vlm)

    assert [f["id"] for f in pendientes] == [sembrado["evento_id"]]
    assert pendientes[0]["numero_orden"] == sembrado["numero_orden"]


def test_un_evento_sin_analizar_todavia_no_se_interpreta(ajustes_con_vlm, motor):
    """La RN-03 pide que YOLO confirme antes. Sin conteo no hay confirmacion."""
    sembrar_evento(motor)
    assert interpretacion.pendientes_de_interpretar(motor, ajustes_con_vlm) == []


def test_un_evento_ya_interpretado_no_vuelve(ajustes_con_vlm, motor, servicio_vlm,
                                             cliente_s3):
    sembrado = sembrar_evento(motor)
    with motor.begin() as conexion:
        conexion.execute(tablas.evento.update()
                         .where(tablas.evento.c.id == sembrado["evento_id"])
                         .values(sacos_contados=398, diferencia_sacos=-2))
    interpretacion.interpretar(motor, ajustes_con_vlm, fila_de(sembrado),
                               conteo=conteo_con_fotogramas(), cliente=cliente_s3)

    assert interpretacion.pendientes_de_interpretar(motor, ajustes_con_vlm) == []


def test_un_caso_cerrado_no_entra_en_la_cola(ajustes_con_vlm, motor):
    sembrado = sembrar_evento(motor, estado="confirmado")
    with motor.begin() as conexion:
        conexion.execute(tablas.evento.update()
                         .where(tablas.evento.c.id == sembrado["evento_id"])
                         .values(sacos_contados=398, diferencia_sacos=-2))

    assert interpretacion.pendientes_de_interpretar(motor, ajustes_con_vlm) == []


def test_los_intentos_se_acaban(ajustes_con_vlm, motor, servicio_vlm, cliente_s3):
    """Un proveedor caido un dia entero tendria al grabador bajando los mismos
    fotogramas y pagando llamadas cada treinta segundos."""
    servicio_vlm.parar()
    sembrado = sembrar_evento(motor)
    with motor.begin() as conexion:
        conexion.execute(tablas.evento.update()
                         .where(tablas.evento.c.id == sembrado["evento_id"])
                         .values(sacos_contados=398, diferencia_sacos=-2))

    for intento in range(ajustes_con_vlm.intentos_de_interpretacion):
        assert len(interpretacion.pendientes_de_interpretar(
            motor, ajustes_con_vlm)) == 1, intento
        interpretacion.interpretar(motor, ajustes_con_vlm, fila_de(sembrado),
                                   cliente=cliente_s3)

    assert interpretacion.pendientes_de_interpretar(motor, ajustes_con_vlm) == []


def test_el_reintento_baja_los_fotogramas_del_almacen(ajustes_con_vlm, motor,
                                                      servicio_vlm, cliente_s3,
                                                      tmp_path):
    """Asi un fallo del modelo no obliga a reanalizar el video, que es lo caro."""
    imagen = tmp_path / "f.jpg"
    imagen.write_bytes(b"\xff\xd8\xffevidencia")
    direccion = almacen.subir(cliente_s3, "clips", "evento-1/fotogramas/f.jpg",
                              imagen, tipo="image/jpeg")
    sembrado = sembrar_evento(motor)
    fila = fila_de(sembrado, fotogramas_clave=[
        {"url": direccion, "motivo": "saco_saliente", "detalle": "x",
         "segundo": 12.0, "fotograma": 120}])

    interpretacion.interpretar(motor, ajustes_con_vlm, fila, cliente=cliente_s3)

    enviados = servicio_vlm.peticiones[0]["cuerpo"]["fotogramas"]
    assert len(enviados) == 1
    assert enviados[0]["motivo"] == "saco_saliente"


def test_un_fotograma_que_ya_no_esta_no_impide_interpretar(ajustes_con_vlm, motor,
                                                           servicio_vlm, cliente_s3):
    """Es mejor una descripcion basada solo en los datos que ninguna."""
    sembrado = sembrar_evento(motor)
    fila = fila_de(sembrado, fotogramas_clave=[
        {"url": "s3://clips/no-existe.jpg", "motivo": "x", "detalle": "x",
         "segundo": 0.0, "fotograma": 0}])

    resultado = interpretacion.interpretar(motor, ajustes_con_vlm, fila,
                                           cliente=cliente_s3)

    assert resultado.severidad == "alta"
    assert servicio_vlm.peticiones[0]["cuerpo"]["fotogramas"] == []


def test_una_pasada_completa_interpreta_lo_pendiente(ajustes_con_vlm, motor,
                                                     servicio_vlm, cliente_s3):
    sembrado = sembrar_evento(motor)
    with motor.begin() as conexion:
        conexion.execute(tablas.evento.update()
                         .where(tablas.evento.c.id == sembrado["evento_id"])
                         .values(sacos_contados=398, diferencia_sacos=-2))

    hechos = interpretacion.procesar_pendientes(motor, ajustes_con_vlm,
                                                cliente=cliente_s3)

    assert len(hechos) == 1
    assert leer_evento(motor, sembrado["evento_id"])["severidad"] == "alta"


def test_un_evento_roto_no_detiene_a_los_demas(ajustes_con_vlm, motor,
                                               servicio_vlm, cliente_s3,
                                               monkeypatch):
    sembrar_evento(motor, numero_orden="ORD-2026-0001")
    segundo = sembrar_evento(motor, numero_orden="ORD-2026-0002")
    with motor.begin() as conexion:
        conexion.execute(tablas.evento.update()
                         .values(sacos_contados=398, diferencia_sacos=-2))

    original = interpretacion.interpretar
    llamadas = {"n": 0}

    def a_veces_revienta(*args, **kwargs):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise RuntimeError("se cayo la red del almacen")
        return original(*args, **kwargs)

    monkeypatch.setattr(interpretacion, "interpretar", a_veces_revienta)
    hechos = interpretacion.procesar_pendientes(motor, ajustes_con_vlm,
                                                cliente=cliente_s3)

    assert len(hechos) == 1
    assert leer_evento(motor, segundo["evento_id"])["severidad"] == "alta"


def test_con_la_interpretacion_apagada_la_pasada_no_hace_nada(ajustes_con_yolo,
                                                              motor):
    assert interpretacion.procesar_pendientes(motor, ajustes_con_yolo) == []


# --------------------------------------------------- el grabador que lo dispara
def test_el_grabador_interpreta_en_su_vuelta(ajustes_con_vlm, motor, servicio_vlm,
                                             cliente_s3, monkeypatch):
    from app.grabador import Grabador

    sembrado = sembrar_evento(motor)
    with motor.begin() as conexion:
        conexion.execute(tablas.evento.update()
                         .where(tablas.evento.c.id == sembrado["evento_id"])
                         .values(sacos_contados=398, diferencia_sacos=-2))
    monkeypatch.setattr(interpretacion, "crear_cliente_de_almacen", None,
                        raising=False)
    monkeypatch.setattr(interpretacion.almacen, "crear_cliente",
                        lambda _a: cliente_s3)
    grabador = Grabador(ajustes_con_vlm, motor)

    hechos = grabador.revisar_interpretaciones(forzar=True)

    assert len(hechos) == 1
    assert grabador.eventos_interpretados == 1


def test_sin_servicio_configurado_el_grabador_no_lo_intenta(ajustes_con_yolo, motor):
    from app.grabador import Grabador

    assert Grabador(ajustes_con_yolo, motor).revisar_interpretaciones(
        forzar=True) == []


def test_el_sondeo_no_se_repite_en_cada_vuelta(ajustes_con_vlm, motor, monkeypatch):
    from app.grabador import Grabador

    lento = dataclasses.replace(ajustes_con_vlm,
                                segundos_entre_interpretaciones=3600.0)
    pasadas = []
    monkeypatch.setattr(interpretacion, "procesar_pendientes",
                        lambda *a, **k: pasadas.append(1) or [])
    grabador = Grabador(lento, motor)

    grabador.revisar_interpretaciones(forzar=True)
    grabador.revisar_interpretaciones()
    grabador.revisar_interpretaciones()

    assert len(pasadas) == 1


def test_un_fallo_de_mysql_no_para_el_grabador(ajustes_con_vlm, motor, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from app.grabador import Grabador

    def revienta(*_a, **_k):
        raise OperationalError("select 1", {}, Exception("MySQL caido"))

    monkeypatch.setattr(interpretacion, "procesar_pendientes", revienta)
    assert Grabador(ajustes_con_vlm, motor).revisar_interpretaciones(
        forzar=True) == []


def test_la_vuelta_completa_incluye_la_interpretacion(ajustes_con_vlm, motor,
                                                      monkeypatch):
    """Si `una_vuelta` no lo llamara, el reintento no existiria en produccion
    aunque todas las pruebas de este archivo pasaran."""
    from app.grabador import Grabador

    llamadas = []
    monkeypatch.setattr(interpretacion, "procesar_pendientes",
                        lambda *a, **k: llamadas.append(1) or [])
    grabador = Grabador(dataclasses.replace(ajustes_con_vlm, camaras=()), motor)

    grabador.una_vuelta()

    assert llamadas == [1]


def test_el_resumen_dice_si_la_interpretacion_esta_encendida(ajustes_con_vlm, motor):
    from app.grabador import Grabador

    resumen = Grabador(ajustes_con_vlm, motor).resumen()
    assert resumen["interpreta_eventos"] is True
    assert resumen["eventos_interpretados"] == 0


def test_pedir_con_la_interpretacion_apagada_se_avisa(ajustes_con_yolo):
    """El caso de uso lo comprueba antes, pero la funcion de red tambien: un
    modulo que asume que alguien mas valido acaba llamando a una URL vacia."""
    with pytest.raises(interpretacion.ServicioNoDisponible, match="apagada"):
        interpretacion.pedir(ajustes_con_yolo, {})


# --------------------------------------------- enganche con HU-10 (criterio 3)
def test_al_quedar_clasificado_se_avisa_en_la_misma_pasada(
        motor, ajustes_con_vlm, servicio_vlm):
    """El criterio 3 de HU-10 cuenta desde que termina el analisis. Esperar a la
    vuelta siguiente del sondeo gastaria media ventana sin hacer nada."""
    avisados = []
    sembrado = sembrar_evento(motor)
    fila = {"id": sembrado["evento_id"], "numero_orden": sembrado["numero_orden"],
            "clip_url": "s3://clips/x.mkv", "estado": "pendiente",
            "diferencia_kg": -150.0, "diferencia_pct": -0.75,
            "peso_real_kg": 19850.0, "peso_esperado_kg": 20000.0,
            "sacos_esperados": 400, "sacos_contados": 398,
            "diferencia_sacos": -2, "personas_detectadas": 4,
            "personal_anomalo": True, "producto": "Quinua", "fotogramas_clave": []}

    interpretacion.interpretar(
        motor, ajustes_con_vlm, fila,
        al_clasificar=lambda evento_id, marca: avisados.append((evento_id, marca)))

    assert len(avisados) == 1
    assert avisados[0][0] == sembrado["evento_id"]


def test_tambien_se_avisa_cuando_no_hizo_falta_el_modelo(
        motor, ajustes_con_vlm, servicio_vlm):
    """La RN-04 da severidad con modelo o sin el, y el criterio 1 de HU-10 manda
    correo en los tres niveles."""
    servicio_vlm.respuesta = {**servicio_vlm.respuesta, "invocado": False,
                              "severidad": "baja", "analisis": None}
    avisados = []
    sembrado = sembrar_evento(motor)

    interpretacion.interpretar(
        motor, ajustes_con_vlm,
        {"id": sembrado["evento_id"], "numero_orden": sembrado["numero_orden"],
         "clip_url": "", "estado": "pendiente", "diferencia_kg": -10.0,
         "diferencia_pct": -0.05, "peso_real_kg": 19990.0,
         "peso_esperado_kg": 20000.0, "sacos_esperados": 400,
         "sacos_contados": 400, "diferencia_sacos": 0,
         "personas_detectadas": 3, "personal_anomalo": False,
         "producto": "Quinua", "fotogramas_clave": []},
        al_clasificar=lambda evento_id, marca: avisados.append(evento_id))

    assert avisados == [sembrado["evento_id"]]


def test_si_el_analisis_fallo_no_se_avisa_de_nada(motor, ajustes_con_vlm,
                                                  servicio_vlm):
    """Sin severidad no hay a quien avisar ni con que urgencia."""
    servicio_vlm.codigo = 503
    avisados = []
    sembrado = sembrar_evento(motor)

    interpretacion.interpretar(
        motor, ajustes_con_vlm,
        {"id": sembrado["evento_id"], "numero_orden": sembrado["numero_orden"],
         "clip_url": "", "estado": "pendiente", "diferencia_kg": -150.0,
         "diferencia_pct": -0.75, "peso_real_kg": 19850.0,
         "peso_esperado_kg": 20000.0, "sacos_esperados": 400,
         "sacos_contados": 398, "diferencia_sacos": -2,
         "personas_detectadas": 4, "personal_anomalo": True,
         "producto": "Quinua", "fotogramas_clave": []},
        al_clasificar=lambda evento_id, marca: avisados.append(evento_id))

    assert avisados == []


def test_un_fallo_avisando_no_tumba_la_interpretacion(motor, ajustes_con_vlm,
                                                      servicio_vlm):
    """El analisis ya esta guardado y el evento ya es visible en el dashboard.
    Quedarse sin correo es malo; perder el analisis por eso seria mucho peor."""
    sembrado = sembrar_evento(motor)

    def revienta(*_a):
        raise RuntimeError("el servicio de notificaciones exploto")

    resultado = interpretacion.interpretar(
        motor, ajustes_con_vlm,
        {"id": sembrado["evento_id"], "numero_orden": sembrado["numero_orden"],
         "clip_url": "", "estado": "pendiente", "diferencia_kg": -150.0,
         "diferencia_pct": -0.75, "peso_real_kg": 19850.0,
         "peso_esperado_kg": 20000.0, "sacos_esperados": 400,
         "sacos_contados": 398, "diferencia_sacos": -2,
         "personas_detectadas": 4, "personal_anomalo": True,
         "producto": "Quinua", "fotogramas_clave": []},
        al_clasificar=revienta)

    assert resultado.severidad == "alta"
    with motor.connect() as conexion:
        guardada = conexion.execute(
            select(tablas.evento.c.severidad)
            .where(tablas.evento.c.id == sembrado["evento_id"])).scalar_one()
    assert guardada == "alta"
