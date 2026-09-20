"""Lo que el servicio lee y escribe en MySQL. HU-10.

Contra la base de verdad, porque de eso van los criterios 1 y 2: los
destinatarios salen de la tabla `usuario` y el contenido del correo de `evento`,
`pesada` y `orden_despacho`. Un diccionario en memoria no tiene la clave unica
que impide el segundo correo ni el ENUM que rechaza una severidad inventada.
"""
from __future__ import annotations

import json

import sqlalchemy as sa

from app import tablas
from app.destinatarios import ALTA, BAJA, MEDIA, Reparto
from app.registro import (EventoDesconocido, contexto_del_evento,
                          personas_activas, registrar, reparto_de, ya_avisado)

import pytest


def reparto(severidad=ALTA, *correos) -> Reparto:
    correos = correos or ("ana@quinor.com.pe",)
    return Reparto(severidad=severidad, destinatarios=tuple(correos),
                   roles=("supervisor",), urgente=(severidad == ALTA))


def filas_de_notificacion(motor):
    with motor.connect() as conexion:
        return conexion.execute(
            sa.select(tablas.notificacion)).mappings().all()


# ------------------------------------------------------------------ criterio 1
def test_los_destinatarios_salen_de_la_tabla_de_usuarios(motor, equipo):
    """Dar de alta a alguien en el dashboard basta para que reciba alertas. Una
    lista en una variable de entorno habria que acordarse de tocarla el dia que
    alguien entra, y nadie se acuerda."""
    correos = {p.correo for p in personas_activas(motor)}

    assert "ana@quinor.com.pe" in correos
    assert "jorge@quinor.com.pe" not in correos     # dado de baja


def test_la_alta_llega_a_supervisores_y_administradores(motor, equipo):
    destinatarios = set(reparto_de(motor, ALTA).destinatarios)

    assert destinatarios == {"ana@quinor.com.pe", "luis@quinor.com.pe",
                             "rosa@quinor.com.pe"}


def test_la_media_y_la_baja_solo_a_supervisores(motor, equipo):
    for nivel in (MEDIA, BAJA):
        assert set(reparto_de(motor, nivel).destinatarios) == {
            "ana@quinor.com.pe", "luis@quinor.com.pe"}


def test_sin_usuarios_activos_no_hay_a_quien_avisar(motor):
    """El fallo silencioso que mas duele: todo responde 200 y nadie recibe nada
    porque no hay un supervisor dado de alta."""
    assert reparto_de(motor, ALTA).hay_a_quien_avisar is False


# ------------------------------------------------------------------ criterio 2
def test_el_contexto_trae_la_orden_y_la_diferencia(motor, evento_id):
    contexto = contexto_del_evento(motor, evento_id)

    assert contexto.numero_orden == "OD-2026-0148"
    assert contexto.cliente == "Andean Grains LLC"
    assert contexto.diferencia_sacos == -8
    assert contexto.diferencia_kg == -400.0


def test_el_contexto_se_lee_de_la_base_y_no_de_quien_llama(motor, crear_evento):
    """El correo dice lo que dice el sistema. Si el dashboard y el correo
    contaran cosas distintas, el supervisor dejaria de fiarse de los dos."""
    evento_id = crear_evento(numero_orden="OD-2026-0777", severidad="media",
                             sacos_contados=400, diferencia_sacos=0)

    contexto = contexto_del_evento(motor, evento_id)

    assert contexto.numero_orden == "OD-2026-0777"
    assert contexto.severidad == "media"
    assert contexto.diferencia_sacos == 0


def test_el_contexto_trae_la_descripcion_del_modelo(motor, crear_evento):
    analisis = {"descripcion": "Dos personas retiran sacos junto a la rampa.",
                "severidad_ia": "alta",
                "evidencia": ["Saco saliente en el minuto 4"]}
    evento_id = crear_evento(descripcion_ia=analisis)

    contexto = contexto_del_evento(motor, evento_id)

    assert "retiran sacos" in contexto.descripcion_ia
    assert contexto.evidencia == ("Saco saliente en el minuto 4",)


def test_un_analisis_guardado_como_texto_tambien_se_lee(motor, crear_evento):
    evento_id = crear_evento(descripcion_ia=json.dumps(
        {"descripcion": "Carga normal.", "evidencia": "sin novedad"}))

    contexto = contexto_del_evento(motor, evento_id)

    assert contexto.descripcion_ia == "Carga normal."
    assert contexto.evidencia == ("sin novedad",)


def test_un_evento_sin_analisis_no_deja_el_correo_sin_enviar(motor,
                                                             crear_evento):
    """Un aviso con un hueco llega a tiempo; un aviso que no sale por falta de
    un campo no sirve de nada."""
    evento_id = crear_evento(descripcion_ia=None, sacos_contados=None,
                             diferencia_sacos=None, severidad=None)

    contexto = contexto_del_evento(motor, evento_id)

    assert contexto.descripcion_ia == ""
    assert contexto.diferencia_sacos is None
    assert contexto.diferencia_kg == -400.0


def test_un_evento_que_no_existe_se_dice_claramente(motor):
    with pytest.raises(EventoDesconocido):
        contexto_del_evento(motor, 999999)


def test_la_fecha_del_evento_viene_formateada(motor, evento_id):
    contexto = contexto_del_evento(motor, evento_id)

    assert "/" in contexto.fecha_del_evento and ":" in contexto.fecha_del_evento


# --------------------------------------------------------- constancia del aviso
def test_el_aviso_queda_escrito_en_la_base(motor, evento_id):
    """La pregunta que se hace despues de un hurto es "se aviso o no se aviso".
    La respuesta no puede depender de que un supervisor conserve el correo."""
    identificador = registrar(motor, evento_id, reparto(),
                              "[ALERTA ALTA] Orden OD-2026-0148: faltan 8 sacos",
                              enviado=True, intentos=1,
                              segundos_desde_analisis=12.5)

    filas = filas_de_notificacion(motor)
    assert identificador is not None
    assert len(filas) == 1
    assert filas[0]["estado"] == "enviada"
    assert filas[0]["enviada_en"] is not None
    assert float(filas[0]["segundos_desde_analisis"]) == 12.5


def test_se_guarda_a_quien_se_le_mando(motor, evento_id):
    """Tal como estaban en ese momento: si manana se da de baja a alguien, el
    registro tiene que seguir diciendo que aquel dia lo recibio."""
    registrar(motor, evento_id, reparto(ALTA, "ana@quinor.com.pe",
                                        "rosa@quinor.com.pe"),
              "asunto", enviado=True, intentos=1)

    guardados = filas_de_notificacion(motor)[0]["destinatarios"]
    if isinstance(guardados, str):
        guardados = json.loads(guardados)
    assert set(guardados) == {"ana@quinor.com.pe", "rosa@quinor.com.pe"}


def test_un_correo_que_no_salio_tambien_queda_escrito(motor, evento_id):
    registrar(motor, evento_id, reparto(), "asunto", enviado=False, intentos=3,
              error="El relay no responde")

    fila = filas_de_notificacion(motor)[0]
    assert fila["estado"] == "fallida"
    assert fila["enviada_en"] is None
    assert "relay" in fila["error"]
    assert fila["intentos"] == 3


def test_no_se_avisa_dos_veces_del_mismo_evento(motor, evento_id):
    """El grabador sondea, y sondear significa que el mismo evento pasa por aqui
    en cada vuelta. Sin esto, el supervisor recibiria un correo por vuelta."""
    registrar(motor, evento_id, reparto(), "asunto", enviado=True, intentos=1)

    assert ya_avisado(motor, evento_id) is True
    assert registrar(motor, evento_id, reparto(), "otro asunto",
                     enviado=True, intentos=1) is None
    assert len(filas_de_notificacion(motor)) == 1


def test_un_aviso_fallido_no_bloquea_el_siguiente_intento(motor, evento_id):
    """El evento sigue sin avisar. Si la clave unica lo bloqueara para siempre,
    un relay caido durante un minuto dejaria un evento Alto sin aviso para
    siempre, que es peor que el correo duplicado que se queria evitar."""
    registrar(motor, evento_id, reparto(), "asunto", enviado=False, intentos=3,
              error="El relay no responde")

    assert ya_avisado(motor, evento_id) is False

    identificador = registrar(motor, evento_id, reparto(), "asunto",
                              enviado=True, intentos=1)

    filas = filas_de_notificacion(motor)
    assert identificador is not None
    assert len(filas) == 1
    assert filas[0]["estado"] == "enviada"


def test_la_severidad_guardada_es_la_del_reparto(motor, crear_evento):
    evento_id = crear_evento(severidad="baja")

    registrar(motor, evento_id, reparto(BAJA), "asunto", enviado=True,
              intentos=1)

    assert filas_de_notificacion(motor)[0]["severidad"] == "baja"


def test_el_canal_es_correo_y_solo_correo(motor, evento_id):
    """Tras el cambio de alcance del 18/09/2026 es el unico canal. La columna se
    conserva porque Slack, Teams o SMS entraran con su propia historia, y
    entonces la clave unica por (evento, canal) permitira un aviso por cada uno."""
    registrar(motor, evento_id, reparto(), "asunto", enviado=True, intentos=1)

    assert filas_de_notificacion(motor)[0]["canal"] == "correo"


def test_un_asunto_larguisimo_no_revienta_la_insercion(motor, evento_id):
    registrar(motor, evento_id, reparto(), "A" * 900, enviado=True, intentos=1)

    assert len(filas_de_notificacion(motor)[0]["asunto"]) == 300


def test_sin_destinatarios_se_registra_como_un_intento(motor, evento_id):
    """La tabla exige 1 o mas intentos. Un evento Alto sin nadie a quien avisar
    tiene que verse en el dashboard, no desaparecer."""
    vacio = Reparto(severidad=ALTA, destinatarios=(), roles=("supervisor",),
                    urgente=True)

    registrar(motor, evento_id, vacio, "asunto", enviado=False, intentos=0,
              error="No hay destinatarios activos para esta severidad.")

    fila = filas_de_notificacion(motor)[0]
    assert fila["intentos"] == 1
    assert fila["estado"] == "fallida"


def test_sin_medida_del_retraso_la_columna_queda_nula(motor, evento_id):
    """NULL no es cero: significa que no se pudo medir, y un cero fingido daria
    por cumplido el criterio 3 sin haberlo comprobado."""
    registrar(motor, evento_id, reparto(), "asunto", enviado=True, intentos=1,
              segundos_desde_analisis=None)

    assert filas_de_notificacion(motor)[0]["segundos_desde_analisis"] is None


def test_un_analisis_ilegible_no_tumba_el_aviso(motor, crear_evento):
    """La columna es JSON y no deberia llegar rota, pero un aviso no puede
    quedarse sin salir porque el modelo devolviera algo raro."""
    evento_id = crear_evento(descripcion_ia='"no es un objeto"')

    contexto = contexto_del_evento(motor, evento_id)

    assert contexto.descripcion_ia == ""
    assert contexto.evidencia == ()


def test_un_analisis_que_es_una_lista_tampoco_lo_tumba(motor, crear_evento):
    evento_id = crear_evento(descripcion_ia=["a", "b"])

    assert contexto_del_evento(motor, evento_id).descripcion_ia == ""


def test_un_texto_que_no_es_json_se_ensena_tal_cual(motor):
    """La columna es JSON y MySQL no deja guardar ahi cualquier cosa, asi que
    este camino no deberia darse nunca. Se cubre igual porque el dia que alguien
    cambie el tipo de la columna, el correo tiene que seguir saliendo con lo que
    haya en lugar de reventar."""
    from app.registro import _descripcion

    assert _descripcion("hurto en la rampa") == ("hurto en la rampa", ())
    assert _descripcion(None) == ("", ())
