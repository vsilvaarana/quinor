"""El aviso al supervisor desde el grabador. HU-10, criterio 3.

  3. La notificacion se envia en menos de 60 s tras el analisis.

Contra MySQL de verdad y contra un servicio de notificaciones de mentira pero
por HTTP de verdad. Lo que se comprueba aqui no es que el correo salga bien, que
es trabajo del servicio de notificaciones y alli se prueba contra un servidor
SMTP real, sino lo de este lado: que el aviso se pide en cuanto la severidad
queda escrita, que la medida del criterio 3 viaja, y que un servicio caido no
tumba el analisis ni deja al grabador llamando en bucle.
"""
from __future__ import annotations

import dataclasses
import time

import pytest
from sqlalchemy import select, text

from app import aviso, tablas
from tests.conftest import sembrar_evento


def clasificar(motor, evento_id: int, severidad: str = "alta") -> None:
    """Deja el evento como lo deja HU-09: con severidad escrita."""
    with motor.begin() as conexion:
        conexion.execute(tablas.evento.update()
                         .where(tablas.evento.c.id == evento_id)
                         .values(severidad=severidad, sacos_contados=398,
                                 diferencia_sacos=-2))


def auditoria_de(motor, evento_id: int, accion: str) -> list[dict]:
    with motor.connect() as conexion:
        return [dict(f) for f in conexion.execute(
            select(tablas.auditoria)
            .where(tablas.auditoria.c.entidad_id == evento_id,
                   tablas.auditoria.c.accion == accion)).mappings().all()]


# ------------------------------------------------------------------ criterio 3
def test_se_pide_el_aviso_con_lo_que_tardo_desde_el_analisis(
        motor, ajustes_con_avisos, servicio_notificaciones):
    """El servicio de notificaciones no sabe cuando termino el analisis; sabe
    cuando le pidieron el correo. El unico sitio donde consta ese instante es
    este, que es quien escribio la severidad."""
    sembrado = sembrar_evento(motor)
    clasificar(motor, sembrado["evento_id"])
    marca = time.monotonic()

    resultado = aviso.avisar(motor, ajustes_con_avisos, sembrado["evento_id"],
                             analizado_en=marca)

    assert resultado.enviado is True
    pedido = servicio_notificaciones.peticiones[0]["cuerpo"]
    assert pedido["evento_id"] == sembrado["evento_id"]
    assert 0.0 <= pedido["segundos_desde_analisis"] < 5.0
    assert resultado.dentro_del_criterio is True


def test_el_camino_normal_avisa_en_la_misma_pasada_del_analisis(
        motor, ajustes_con_avisos, servicio_notificaciones):
    """Con un sondeo cada 30 segundos, esperar a la vuelta siguiente gastaria
    media ventana del criterio sin hacer nada."""
    from app.grabador import Grabador

    sembrado = sembrar_evento(motor)
    clasificar(motor, sembrado["evento_id"])
    grabador = Grabador(ajustes_con_avisos, motor)

    comienzo = time.monotonic()
    grabador._avisar(sembrado["evento_id"], comienzo)

    assert len(servicio_notificaciones.peticiones) == 1
    assert grabador.eventos_avisados == 1
    assert time.monotonic() - comienzo < 5.0


def test_el_reintento_no_finge_que_el_analisis_acaba_de_pasar(
        motor, ajustes_con_avisos, servicio_notificaciones):
    """En la pasada de reintento el analisis puede haber sido hace horas. Decir
    "cero segundos" daria por cumplido el criterio 3 sin haberlo comprobado."""
    sembrado = sembrar_evento(motor)
    clasificar(motor, sembrado["evento_id"])

    resultado = aviso.avisar(motor, ajustes_con_avisos, sembrado["evento_id"])

    pedido = servicio_notificaciones.peticiones[0]["cuerpo"]
    assert "segundos_desde_analisis" not in pedido
    assert resultado.dentro_del_criterio is None


def test_un_aviso_tardio_se_registra_como_tal(motor, ajustes_con_avisos,
                                              servicio_notificaciones):
    """Un aviso que llega tarde hay que verlo antes de que sea costumbre."""
    sembrado = sembrar_evento(motor)
    clasificar(motor, sembrado["evento_id"])

    resultado = aviso.avisar(motor, ajustes_con_avisos, sembrado["evento_id"],
                             analizado_en=time.monotonic() - 300.0)

    assert resultado.enviado is True
    assert resultado.dentro_del_criterio is False
    detalle = auditoria_de(motor, sembrado["evento_id"], aviso.ACCION_OK)[0]
    assert detalle["detalle"]["dentro_del_criterio"] is False


# ------------------------------------------------------------ queda constancia
def test_el_aviso_enviado_queda_en_auditoria(motor, ajustes_con_avisos):
    sembrado = sembrar_evento(motor)
    clasificar(motor, sembrado["evento_id"])

    aviso.avisar(motor, ajustes_con_avisos, sembrado["evento_id"],
                 analizado_en=time.monotonic())

    registros = auditoria_de(motor, sembrado["evento_id"], aviso.ACCION_OK)
    assert len(registros) == 1
    assert registros[0]["detalle"]["severidad"] == "alta"
    assert len(registros[0]["detalle"]["destinatarios"]) == 2


def test_un_servicio_caido_queda_escrito_y_no_revienta(motor, ajustes_con_avisos,
                                                       servicio_notificaciones):
    """El analisis ya esta guardado y el evento ya es visible en el dashboard.
    Quedarse sin correo es malo; perder el analisis por eso seria mucho peor."""
    servicio_notificaciones.codigo = 503
    sembrado = sembrar_evento(motor)
    clasificar(motor, sembrado["evento_id"])

    resultado = aviso.avisar(motor, ajustes_con_avisos, sembrado["evento_id"])

    assert resultado.enviado is False
    assert "503" in resultado.error
    assert len(auditoria_de(motor, sembrado["evento_id"], aviso.ACCION_FALLO)) == 1


def test_un_correo_que_no_salio_queda_escrito(motor, ajustes_con_avisos,
                                              servicio_notificaciones):
    """El servicio respondio 200: el fallo fue del relay, no del servicio. Se
    registra igual, porque es aqui donde se cuentan los intentos."""
    servicio_notificaciones.respuesta = {
        **servicio_notificaciones.respuesta, "enviado": False,
        "error": "El relay no responde"}
    sembrado = sembrar_evento(motor)
    clasificar(motor, sembrado["evento_id"])

    resultado = aviso.avisar(motor, ajustes_con_avisos, sembrado["evento_id"])

    assert resultado.enviado is False
    fallos = auditoria_de(motor, sembrado["evento_id"], aviso.ACCION_FALLO)
    assert fallos and "relay" in fallos[0]["detalle"]["motivo"]


def test_un_duplicado_no_ensucia_la_auditoria(motor, ajustes_con_avisos,
                                              servicio_notificaciones):
    """La auditoria es para lo que paso, no para lo que no hizo falta repetir."""
    servicio_notificaciones.respuesta = {
        **servicio_notificaciones.respuesta, "enviado": False, "duplicado": True}
    sembrado = sembrar_evento(motor)
    clasificar(motor, sembrado["evento_id"])

    resultado = aviso.avisar(motor, ajustes_con_avisos, sembrado["evento_id"])

    assert resultado.duplicado is True
    assert auditoria_de(motor, sembrado["evento_id"], aviso.ACCION_OK) == []
    assert auditoria_de(motor, sembrado["evento_id"], aviso.ACCION_FALLO) == []


def test_la_clave_del_servicio_viaja(motor, ajustes_con_avisos,
                                     servicio_notificaciones):
    """El servicio de notificaciones vive en la red interna del apartado 8: sin
    clave, cualquier cosa de esa red podria mandar correos a nombre de QUINOR."""
    servicio_notificaciones.clave = "clave-de-servicio"
    con_clave = dataclasses.replace(ajustes_con_avisos,
                                    notificaciones_api_key="clave-de-servicio")
    sembrado = sembrar_evento(motor)
    clasificar(motor, sembrado["evento_id"])

    resultado = aviso.avisar(motor, con_clave, sembrado["evento_id"])

    assert resultado.enviado is True
    assert servicio_notificaciones.peticiones[0]["clave"] == "clave-de-servicio"


def test_sin_la_clave_el_servicio_lo_rechaza(motor, ajustes_con_avisos,
                                             servicio_notificaciones):
    servicio_notificaciones.clave = "clave-de-servicio"
    sembrado = sembrar_evento(motor)
    clasificar(motor, sembrado["evento_id"])

    resultado = aviso.avisar(motor, ajustes_con_avisos, sembrado["evento_id"])

    assert resultado.enviado is False
    assert "401" in resultado.error


# -------------------------------------------------------------- los pendientes
def test_un_evento_clasificado_sin_correo_sale_en_los_pendientes(
        motor, ajustes_con_avisos):
    sembrado = sembrar_evento(motor)
    clasificar(motor, sembrado["evento_id"])

    assert aviso.pendientes_de_avisar(motor, ajustes_con_avisos) == [
        sembrado["evento_id"]]


def test_un_evento_sin_severidad_no_se_avisa(motor, ajustes_con_avisos):
    """Sin severidad no hay a quien avisar ni con que urgencia: el criterio 1
    reparte por nivel, y avisar antes de saberlo seria avisar a ciegas."""
    sembrar_evento(motor)

    assert aviso.pendientes_de_avisar(motor, ajustes_con_avisos) == []


def test_un_evento_ya_avisado_no_vuelve_a_salir(motor, ajustes_con_avisos):
    sembrado = sembrar_evento(motor)
    clasificar(motor, sembrado["evento_id"])
    with motor.begin() as conexion:
        conexion.execute(text(
            "INSERT INTO notificacion (evento_id, canal, severidad, "
            "destinatarios, asunto, estado, intentos, enviada_en) VALUES "
            "(:e, 'correo', 'alta', '[\"ana@quinor.com.pe\"]', 'asunto', "
            "'enviada', 1, NOW(6))"), {"e": sembrado["evento_id"]})

    assert aviso.pendientes_de_avisar(motor, ajustes_con_avisos) == []


def test_un_aviso_fallido_no_cierra_el_asunto(motor, ajustes_con_avisos):
    """El evento sigue sin avisar. Un relay caido un minuto no puede dejar un
    evento Alto sin correo para siempre."""
    sembrado = sembrar_evento(motor)
    clasificar(motor, sembrado["evento_id"])
    with motor.begin() as conexion:
        conexion.execute(text(
            "INSERT INTO notificacion (evento_id, canal, severidad, "
            "destinatarios, asunto, estado, intentos, error) VALUES "
            "(:e, 'correo', 'alta', '[]', 'asunto', 'fallida', 3, 'sin relay')"),
            {"e": sembrado["evento_id"]})

    assert aviso.pendientes_de_avisar(motor, ajustes_con_avisos) == [
        sembrado["evento_id"]]


@pytest.mark.parametrize("estado", ["en_revision", "confirmado",
                                    "falso_positivo"])
def test_un_evento_que_ya_vio_un_supervisor_no_se_avisa(motor,
                                                        ajustes_con_avisos,
                                                        estado):
    """Un aviso tardio solo le haria volver sobre algo que ya resolvio."""
    sembrado = sembrar_evento(motor, estado=estado)
    clasificar(motor, sembrado["evento_id"])

    assert aviso.pendientes_de_avisar(motor, ajustes_con_avisos) == []


def test_tras_agotar_los_intentos_se_deja_de_llamar(motor, ajustes_con_avisos,
                                                    servicio_notificaciones):
    """Un servicio de correo caido un dia entero tendria al grabador llamando en
    bucle sin que el resultado cambiara."""
    servicio_notificaciones.codigo = 503
    sembrado = sembrar_evento(motor)
    clasificar(motor, sembrado["evento_id"])

    for _ in range(ajustes_con_avisos.intentos_de_aviso + 2):
        aviso.procesar_pendientes(motor, ajustes_con_avisos)

    assert len(servicio_notificaciones.peticiones) == (
        ajustes_con_avisos.intentos_de_aviso)
    assert aviso.pendientes_de_avisar(motor, ajustes_con_avisos) == []


def test_el_reintento_manda_el_correo_que_no_habia_salido(
        motor, ajustes_con_avisos, servicio_notificaciones):
    servicio_notificaciones.codigo = 503
    sembrado = sembrar_evento(motor)
    clasificar(motor, sembrado["evento_id"])
    aviso.procesar_pendientes(motor, ajustes_con_avisos)

    servicio_notificaciones.codigo = 200
    hechos = aviso.procesar_pendientes(motor, ajustes_con_avisos)

    assert len(hechos) == 1 and hechos[0].enviado is True


def test_un_evento_que_revienta_no_detiene_a_los_demas(
        motor, ajustes_con_avisos, monkeypatch):
    sembrado = sembrar_evento(motor)
    clasificar(motor, sembrado["evento_id"])

    def revienta(*_a, **_k):
        raise RuntimeError("algo muy raro")

    monkeypatch.setattr(aviso, "avisar", revienta)

    assert aviso.procesar_pendientes(motor, ajustes_con_avisos) == []


# ---------------------------------------------------------- apagado y encendido
def test_sin_servicio_configurado_no_se_avisa_y_no_es_un_error(motor,
                                                               ajustes_con_vlm):
    """Una instalacion sin servidor de correo sigue detectando, grabando y
    clasificando, y el supervisor lo ve en el dashboard."""
    sembrado = sembrar_evento(motor)
    clasificar(motor, sembrado["evento_id"])

    assert ajustes_con_vlm.avisa_eventos is False
    assert aviso.avisar(motor, ajustes_con_vlm, sembrado["evento_id"]) is None
    assert aviso.procesar_pendientes(motor, ajustes_con_vlm) == []


def test_pedir_con_el_aviso_apagado_lo_dice(ajustes_con_vlm):
    with pytest.raises(aviso.ServicioNoDisponible):
        aviso.pedir(ajustes_con_vlm, {"evento_id": 1})


def test_un_servicio_que_no_esta_se_dice_sin_reventar(motor, ajustes_con_avisos):
    caido = dataclasses.replace(ajustes_con_avisos,
                                notificaciones_url="http://127.0.0.1:1",
                                aviso_timeout_s=1.0)
    sembrado = sembrar_evento(motor)
    clasificar(motor, sembrado["evento_id"])

    resultado = aviso.avisar(motor, caido, sembrado["evento_id"])

    assert resultado.enviado is False
    assert "No se pudo hablar" in resultado.error


def test_el_aviso_dice_si_hubo_que_hacer_algo():
    enviado = aviso.Aviso(evento_id=1, enviado=True)
    repetido = aviso.Aviso(evento_id=1, enviado=False, duplicado=True)
    fallido = aviso.Aviso(evento_id=1, enviado=False, error="sin relay")

    assert enviado.hubo_que_hacer_algo is True
    assert repetido.hubo_que_hacer_algo is False
    assert fallido.hubo_que_hacer_algo is True
