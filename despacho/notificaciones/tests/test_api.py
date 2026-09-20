"""El servicio completo. HU-10, criterios 1, 2 y 3.

Contra la base de verdad y contra un servidor SMTP de verdad: se pide el aviso
por HTTP y se comprueba que el correo llego al buzon, que dice lo que tiene que
decir y que quedo escrito en la tabla `notificacion`.
"""
from __future__ import annotations

import dataclasses
import json

import sqlalchemy as sa
from fastapi.testclient import TestClient

from app import tablas
from app.main import create_app

import pytest


@pytest.fixture()
def cliente(ajustes, motor, equipo):
    app = create_app(ajustes=ajustes, motor=motor)
    with TestClient(app) as c:
        yield c


def notificaciones(motor):
    with motor.connect() as conexion:
        return conexion.execute(
            sa.select(tablas.notificacion)).mappings().all()


# ------------------------------------------------------------------ criterio 1
def test_la_alta_llega_a_supervisores_y_administradores(cliente, buzon,
                                                        evento_id):
    respuesta = cliente.post("/notificaciones", json={"evento_id": evento_id})

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["enviado"] is True
    assert set(cuerpo["destinatarios"]) == {"ana@quinor.com.pe",
                                            "luis@quinor.com.pe",
                                            "rosa@quinor.com.pe"}
    _, a_quien = buzon.envueltos[0]
    assert len(a_quien) == 3


def test_la_alta_sale_marcada_y_urgente(cliente, buzon, evento_id):
    cliente.post("/notificaciones", json={"evento_id": evento_id})

    assert buzon.asunto().startswith("[ALERTA ALTA]")
    assert buzon.ultimo["X-Priority"] == "1"


def test_la_media_solo_va_a_supervisores(cliente, buzon, crear_evento):
    evento_id = crear_evento(severidad="media")

    cuerpo = cliente.post("/notificaciones",
                          json={"evento_id": evento_id}).json()

    assert set(cuerpo["destinatarios"]) == {"ana@quinor.com.pe",
                                            "luis@quinor.com.pe"}
    assert cuerpo["urgente"] is False


def test_la_baja_va_a_supervisores_con_prioridad_normal(cliente, buzon,
                                                        crear_evento):
    evento_id = crear_evento(severidad="baja")

    cuerpo = cliente.post("/notificaciones",
                          json={"evento_id": evento_id}).json()

    assert cuerpo["enviado"] is True
    assert set(cuerpo["destinatarios"]) == {"ana@quinor.com.pe",
                                            "luis@quinor.com.pe"}
    assert buzon.ultimo["X-Priority"] == "3"


@pytest.mark.parametrize("nivel", ["alta", "media", "baja"])
def test_los_tres_niveles_salen_por_correo(cliente, buzon, crear_evento, nivel):
    """"La notificacion se envia por correo en los tres niveles". Antes del
    cambio de alcance, la Alta iba por SMS y Slack y la Media por Slack."""
    evento_id = crear_evento(severidad=nivel,
                             numero_orden=f"OD-2026-{nivel[:3]}")

    respuesta = cliente.post("/notificaciones", json={"evento_id": evento_id})

    assert respuesta.json()["enviado"] is True
    assert len(buzon.mensajes) == 1


def test_un_evento_sin_severidad_se_avisa_como_alta(cliente, buzon,
                                                    crear_evento):
    """Un evento sin clasificar es justo el que conviene mirar."""
    evento_id = crear_evento(severidad=None)

    cuerpo = cliente.post("/notificaciones",
                          json={"evento_id": evento_id}).json()

    assert cuerpo["severidad"] == "alta"
    assert cuerpo["urgente"] is True
    assert buzon.asunto().startswith("[ALERTA ALTA]")


# ------------------------------------------------------------------ criterio 2
def test_el_correo_lleva_orden_diferencia_y_enlace(cliente, buzon, evento_id):
    respuesta = cliente.post("/notificaciones",
                             json={"evento_id": evento_id}).json()
    partes = buzon.partes()
    enlace = f"http://dashboard.quinor.local:8050/eventos/{evento_id}"

    assert respuesta["enlace"] == enlace
    for cuerpo in partes.values():
        assert "OD-2026-0148" in cuerpo
        assert "8 sacos" in cuerpo
        assert enlace in cuerpo


def test_el_contenido_sale_de_la_base_y_no_de_la_peticion(cliente, buzon,
                                                          crear_evento):
    """La peticion solo trae el identificador del evento. El correo y el
    dashboard tienen que contar lo mismo."""
    evento_id = crear_evento(numero_orden="OD-2026-0999", diferencia_sacos=-25,
                             sacos_contados=375)

    cliente.post("/notificaciones", json={"evento_id": evento_id,
                                          "numero_orden": "inventada"})

    assert "OD-2026-0999" in buzon.asunto()
    assert "25 sacos" in buzon.asunto()


def test_la_descripcion_del_modelo_entra_en_el_correo(cliente, buzon,
                                                      crear_evento):
    evento_id = crear_evento(descripcion_ia={
        "descripcion": "Dos personas retiran sacos junto a la rampa.",
        "severidad_ia": "alta", "evidencia": ["Saco saliente en el minuto 4"]})

    cliente.post("/notificaciones", json={"evento_id": evento_id})

    assert "retiran sacos" in buzon.partes()["plain"]
    assert "minuto 4" in buzon.partes()["plain"]


# ------------------------------------------------------------------ criterio 3
def test_se_mide_cuanto_paso_desde_el_analisis(cliente, motor, evento_id):
    """"La notificacion se envia en menos de 60 s tras el analisis". Quien llama
    sabe cuando termino el analisis; el servicio, no. Con esa marca se mide."""
    cuerpo = cliente.post("/notificaciones",
                          json={"evento_id": evento_id,
                                "segundos_desde_analisis": 3.5}).json()

    assert cuerpo["dentro_del_criterio"] is True
    assert cuerpo["segundos_desde_analisis"] >= 3.5
    fila = notificaciones(motor)[0]
    assert float(fila["segundos_desde_analisis"]) >= 3.5


def test_un_aviso_tardio_se_dice_en_lugar_de_ocultarse(cliente, evento_id):
    """El criterio 3 se mide con lo que pasa de verdad. Un aviso tardio hay que
    verlo antes de que sea costumbre."""
    cuerpo = cliente.post("/notificaciones",
                          json={"evento_id": evento_id,
                                "segundos_desde_analisis": 180.0}).json()

    assert cuerpo["enviado"] is True
    assert cuerpo["dentro_del_criterio"] is False


def test_sin_marca_de_tiempo_no_se_finge_que_se_cumplio(cliente, evento_id):
    """NULL no es cero: un cero fingido daria por cumplido el criterio sin
    haberlo comprobado."""
    cuerpo = cliente.post("/notificaciones",
                          json={"evento_id": evento_id}).json()

    assert cuerpo["dentro_del_criterio"] is None
    assert cuerpo["segundos_desde_analisis"] is None


def test_el_envio_completo_tarda_bastante_menos_del_limite(cliente, evento_id):
    cuerpo = cliente.post("/notificaciones",
                          json={"evento_id": evento_id}).json()

    assert cuerpo["segundos_de_envio"] < 5.0


# ------------------------------------------------------------ no avisar dos veces
def test_el_segundo_intento_no_manda_otro_correo(cliente, buzon, evento_id):
    """El grabador sondea. Sin esto, el supervisor recibiria un correo por
    vuelta hasta que alguien clasificara el evento."""
    cliente.post("/notificaciones", json={"evento_id": evento_id})
    segunda = cliente.post("/notificaciones",
                           json={"evento_id": evento_id}).json()

    assert segunda["duplicado"] is True
    assert segunda["enviado"] is False
    assert len(buzon.mensajes) == 1


def test_forzar_vuelve_a_mandarlo(cliente, buzon, motor, evento_id):
    """Reavisar es una decision de una persona, no del sistema."""
    cliente.post("/notificaciones", json={"evento_id": evento_id})

    segunda = cliente.post("/notificaciones",
                           json={"evento_id": evento_id,
                                 "forzar": True}).json()

    assert segunda["enviado"] is True
    assert len(buzon.mensajes) == 2
    # La constancia sigue siendo una por evento y canal.
    assert len(notificaciones(motor)) == 1


def test_un_aviso_que_fallo_se_puede_reintentar(cliente, buzon, motor,
                                                evento_id, ajustes):
    """Un relay caido durante un minuto no puede dejar un evento Alto sin aviso
    para siempre."""
    buzon.rechazar = {"ana@quinor.com.pe", "luis@quinor.com.pe",
                      "rosa@quinor.com.pe"}
    primera = cliente.post("/notificaciones",
                           json={"evento_id": evento_id}).json()
    assert primera["enviado"] is False

    buzon.rechazar = set()
    segunda = cliente.post("/notificaciones",
                           json={"evento_id": evento_id}).json()

    assert segunda["duplicado"] is False
    assert segunda["enviado"] is True
    assert len(notificaciones(motor)) == 1


# ------------------------------------------------------ cuando las cosas van mal
def test_un_evento_que_no_existe_responde_404(cliente):
    assert cliente.post("/notificaciones",
                        json={"evento_id": 999999}).status_code == 404


def test_sin_nadie_a_quien_avisar_queda_registrado(ajustes, motor, buzon,
                                                   evento_id):
    """Un evento Alto sin destinatarios es un problema de configuracion que
    tiene que verse en el dashboard, no desaparecer en un log."""
    app = create_app(ajustes=ajustes, motor=motor)   # sin la fixture `equipo`
    with TestClient(app) as sin_equipo:
        cuerpo = sin_equipo.post("/notificaciones",
                                 json={"evento_id": evento_id}).json()

    assert cuerpo["enviado"] is False
    assert "destinatarios" in cuerpo["error"]
    assert notificaciones(motor)[0]["estado"] == "fallida"
    assert buzon.mensajes == []


def test_un_relay_caido_deja_constancia_del_fallo(motor, buzon, ajustes,
                                                  equipo, evento_id,
                                                  dormir_sin_esperar):
    apagado = dataclasses.replace(ajustes, smtp_port=1)
    app = create_app(ajustes=apagado, motor=motor, dormir=dormir_sin_esperar)

    with TestClient(app) as c:
        cuerpo = c.post("/notificaciones", json={"evento_id": evento_id}).json()

    # No es un 500: el servicio funciono, lo que fallo fue el relay.
    assert cuerpo["enviado"] is False
    assert cuerpo["intentos"] == 3
    fila = notificaciones(motor)[0]
    assert fila["estado"] == "fallida"
    assert fila["error"]


def test_si_rechazan_a_uno_se_dice_a_quien(cliente, buzon, evento_id):
    buzon.rechazar = {"rosa@quinor.com.pe"}

    cuerpo = cliente.post("/notificaciones",
                          json={"evento_id": evento_id}).json()

    assert cuerpo["enviado"] is True
    assert cuerpo["rechazados"] == ["rosa@quinor.com.pe"]


def test_sin_servidor_de_correo_responde_503(motor, equipo, ajustes, evento_id):
    sin_correo = dataclasses.replace(ajustes, smtp_host="")
    app = create_app(ajustes=sin_correo, motor=motor)

    with TestClient(app) as c:
        assert c.post("/notificaciones",
                      json={"evento_id": evento_id}).status_code == 503


def test_sin_base_de_datos_responde_503(ajustes):
    sin_base = dataclasses.replace(ajustes, database_url="")
    app = create_app(ajustes=sin_base, motor=None)

    with TestClient(app) as c:
        assert c.post("/notificaciones", json={"evento_id": 1}).status_code == 503


def test_un_evento_id_invalido_lo_rechaza_el_contrato(cliente):
    assert cliente.post("/notificaciones", json={"evento_id": 0}).status_code == 422


# ------------------------------------------------------------------ el servicio
def test_la_raiz_no_pide_clave_y_sirve_de_healthcheck(cliente):
    cuerpo = cliente.get("/").json()

    assert cuerpo["historia"].startswith("HU-10")


def test_la_salud_dice_a_cuantos_se_avisaria(cliente):
    cuerpo = cliente.get("/salud").json()

    assert cuerpo["estado"] == "ok"
    assert cuerpo["destinatarios_alta"] == 3
    assert cuerpo["configurado"] is True
    assert cuerpo["base_de_datos"] is True


def test_la_salud_avisa_cuando_no_hay_nadie_que_reciba_alertas(ajustes, motor):
    """Es el fallo silencioso que mas duele: todo responde 200 y nadie recibe
    nada porque no hay un supervisor activo dado de alta."""
    app = create_app(ajustes=ajustes, motor=motor)

    with TestClient(app) as c:
        cuerpo = c.get("/salud").json()

    assert cuerpo["estado"] == "degradado"
    assert cuerpo["destinatarios_alta"] == 0
    assert "usuario activo" in cuerpo["mensaje"]


def test_la_salud_lo_dice_cuando_no_puede_enviar(motor, equipo, ajustes):
    sin_correo = dataclasses.replace(ajustes, smtp_host="")
    app = create_app(ajustes=sin_correo, motor=motor)

    with TestClient(app) as c:
        cuerpo = c.get("/salud").json()

    assert cuerpo["estado"] == "error"
    assert "SMTP_HOST" in cuerpo["mensaje"]


def test_la_salud_lo_dice_cuando_la_base_no_responde(ajustes):
    rota = sa.create_engine("mysql+pymysql://nadie@127.0.0.1:1/no_existe")
    app = create_app(ajustes=ajustes, motor=rota)

    with TestClient(app) as c:
        cuerpo = c.get("/salud").json()

    assert cuerpo["base_de_datos"] is False
    assert cuerpo["estado"] == "error"


def test_la_salud_avisa_del_correo_sin_cifrar_en_produccion(motor, equipo,
                                                            ajustes):
    produccion = dataclasses.replace(ajustes, app_env="production")
    app = create_app(ajustes=produccion, motor=motor)

    with TestClient(app) as c:
        cuerpo = c.get("/salud").json()

    assert "sin cifrar" in cuerpo["mensaje"]


# ------------------------------------------------------------------ la clave
def test_con_clave_puesta_nadie_manda_correos_sin_ella(ajustes, motor, equipo,
                                                       evento_id):
    """El servicio vive en la red interna del apartado 8 y solo lo llama el
    grabador. Sin clave, cualquier cosa de esa red podria mandar correos a
    nombre de la empresa."""
    app = create_app(ajustes=ajustes, motor=motor, api_key="clave-secreta")

    with TestClient(app) as c:
        assert c.post("/notificaciones",
                      json={"evento_id": evento_id}).status_code == 401
        assert c.post("/notificaciones", json={"evento_id": evento_id},
                      headers={"X-API-Key": "otra"}).status_code == 401
        assert c.post("/notificaciones", json={"evento_id": evento_id},
                      headers={"X-API-Key": "clave-secreta"}).status_code == 200


def test_la_clave_sale_del_entorno_si_no_se_pasa(monkeypatch, ajustes, motor,
                                                 equipo, evento_id):
    monkeypatch.setenv("NOTIFY_SERVICE_API_KEY", "del-entorno")
    app = create_app(ajustes=ajustes, motor=motor)

    with TestClient(app) as c:
        assert c.post("/notificaciones",
                      json={"evento_id": evento_id}).status_code == 401
        assert c.post("/notificaciones", json={"evento_id": evento_id},
                      headers={"X-API-Key": "del-entorno"}).status_code == 200


def test_el_servicio_se_puede_construir_desde_el_entorno(monkeypatch, buzon):
    """La fabrica es la que usa uvicorn en el contenedor, sin ningun parametro."""
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_PORT", str(buzon.puerto))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    app = create_app()

    assert app.state.ajustes.smtp_host == "127.0.0.1"
    assert app.state.motor is None


def test_los_destinatarios_guardados_son_los_que_recibieron(cliente, motor,
                                                            buzon, evento_id):
    cliente.post("/notificaciones", json={"evento_id": evento_id})

    guardados = notificaciones(motor)[0]["destinatarios"]
    if isinstance(guardados, str):
        guardados = json.loads(guardados)
    _, recibieron = buzon.envueltos[0]
    assert set(guardados) == set(recibieron)


def test_la_fabrica_del_motor_devuelve_una_conexion_utilizable(ajustes):
    """Es lo que construye create_app cuando nadie le inyecta un motor, que es
    el caso de produccion."""
    from app.main import crear_motor

    fabricado = crear_motor(ajustes.database_url)
    try:
        with fabricado.connect() as conexion:
            assert conexion.execute(sa.text("SELECT 1")).scalar() == 1
    finally:
        fabricado.dispose()
