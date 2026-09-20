"""El envio del correo, contra un servidor SMTP de verdad.

El buzon de estas pruebas es aiosmtpd escuchando en 127.0.0.1. Todo lo que se
comprueba aqui se comprueba del lado del servidor: que el correo llego, a que
direcciones, con que cabeceras y con que cuerpo. Un mock de aiosmtplib habria
demostrado que se llama a una funcion, que es lo que no falla nunca.

Los reintentos se prueban en los dos sentidos: con un servidor que contesta 451
las dos primeras veces, que es un relay saturado y se arregla esperando, y con
uno que rechaza la direccion con 550, que no se arregla insistiendo.
"""
from __future__ import annotations

import dataclasses
import email.header

import aiosmtplib
import pytest

from app.correo import Resultado, SinConfigurar, armar, enviar
from app.destinatarios import Reparto
from app.plantilla import Contexto, componer

ENLACE = "http://dashboard.quinor.local:8050/eventos/41"


def contexto(**cambios) -> Contexto:
    base = dict(evento_id=41, severidad="alta", numero_orden="OD-2026-0148",
                cliente="Andean Grains LLC", diferencia_sacos=-8,
                diferencia_kg=-400.0)
    base.update(cambios)
    return Contexto(**base)


def reparto(severidad="alta", *correos, urgente=True) -> Reparto:
    correos = correos or ("ana@quinor.com.pe", "rosa@quinor.com.pe")
    return Reparto(severidad=severidad, destinatarios=tuple(correos),
                   roles=("supervisor",), urgente=urgente)


def mensaje(**cambios):
    return componer(contexto(**cambios), ENLACE)


# ------------------------------------------------------------- el envio de verdad
async def test_el_correo_llega_al_servidor(ajustes, buzon):
    resultado = await enviar(ajustes, mensaje(), reparto(), evento_id=41)

    assert resultado.enviado is True
    assert resultado.intentos == 1
    assert len(buzon.mensajes) == 1


async def test_llega_a_todos_los_destinatarios(ajustes, buzon):
    await enviar(ajustes, mensaje(), reparto(), evento_id=41)

    _, a_quien = buzon.envueltos[0]
    assert set(a_quien) == {"ana@quinor.com.pe", "rosa@quinor.com.pe"}


async def test_el_asunto_sobrevive_a_las_tildes(ajustes, buzon):
    """El cliente se llama "Comercializadora Andina S.A.C." y el asunto lleva
    acentos. Si la cabecera se codifica mal, el supervisor recibe un asunto
    ilegible y no lo abre."""
    await enviar(ajustes, mensaje(cliente="Distribución Ñuñoa S.A.C."),
                 reparto(), evento_id=41)

    assert "Distribución Ñuñoa S.A.C." in buzon.asunto()


async def test_el_correo_llega_en_texto_y_en_html(ajustes, buzon):
    await enviar(ajustes, mensaje(), reparto(), evento_id=41)

    partes = buzon.partes()
    assert set(partes) == {"plain", "html"}
    assert ENLACE in partes["plain"]
    assert ENLACE in partes["html"]


async def test_la_alta_llega_marcada_como_urgente(ajustes, buzon):
    """Criterio 1. Las tres cabeceras porque ningun cliente las entiende todas:
    Outlook mira X-Priority, Thunderbird Importance, y Priority es la del
    estandar."""
    await enviar(ajustes, mensaje(), reparto(urgente=True), evento_id=41)

    assert buzon.ultimo["X-Priority"] == "1"
    assert buzon.ultimo["Importance"] == "high"
    assert buzon.ultimo["Priority"] == "urgent"


async def test_la_baja_llega_con_prioridad_normal(ajustes, buzon):
    """Si todas fueran urgentes, ninguna lo seria."""
    await enviar(ajustes, mensaje(severidad="baja"),
                 reparto("baja", urgente=False), evento_id=41)

    assert buzon.ultimo["X-Priority"] == "3"
    assert buzon.ultimo["Importance"] == "normal"


async def test_el_correo_dice_de_que_evento_es_en_una_cabecera(ajustes, buzon):
    """Para que el supervisor pueda filtrar por severidad en su cliente sin
    depender de como escribamos el asunto."""
    await enviar(ajustes, mensaje(), reparto("media"), evento_id=41)

    assert buzon.ultimo["X-QUINOR-Evento"] == "41"
    assert buzon.ultimo["X-QUINOR-Severidad"] == "media"


async def test_el_remitente_es_el_buzon_del_sistema(ajustes, buzon):
    """Conviene un buzon del sistema y no el de una persona: los avisos siguen
    saliendo cuando esa persona se va de la empresa."""
    await enviar(ajustes, mensaje(), reparto(), evento_id=41)

    de_quien, _ = buzon.envueltos[0]
    assert de_quien == "alertas@quinor.com.pe"
    assert "QUINOR" in str(email.header.make_header(
        email.header.decode_header(buzon.ultimo["From"])))


async def test_el_reply_to_se_pone_cuando_esta_configurado(ajustes, buzon):
    con_respuesta = dataclasses.replace(ajustes,
                                        responder_a="soporte@quinor.com.pe")
    await enviar(con_respuesta, mensaje(), reparto(), evento_id=41)

    assert buzon.ultimo["Reply-To"] == "soporte@quinor.com.pe"


# ------------------------------------------------------------------- reintentos
async def test_un_relay_saturado_se_reintenta_y_acaba_llegando(
        ajustes, buzon, dormir_sin_esperar):
    """451 es "ahora no puedo, vuelve luego". Eso se arregla esperando."""
    buzon.fallos_temporales = 2

    resultado = await enviar(ajustes, mensaje(), reparto(), evento_id=41,
                             dormir=dormir_sin_esperar)

    assert resultado.enviado is True
    assert resultado.intentos == 3
    assert len(buzon.mensajes) == 1


async def test_la_espera_entre_intentos_se_duplica(ajustes, buzon,
                                                   dormir_sin_esperar):
    """Insistir de inmediato contra un relay saturado solo lo empeora."""
    buzon.fallos_temporales = 2
    await enviar(ajustes, mensaje(), reparto(), evento_id=41,
                 dormir=dormir_sin_esperar)

    assert dormir_sin_esperar.esperas == [0.01, 0.02]


async def test_si_el_relay_nunca_responde_bien_se_registra_el_fallo(
        ajustes, buzon, dormir_sin_esperar):
    buzon.fallos_temporales = 10

    resultado = await enviar(ajustes, mensaje(), reparto(), evento_id=41,
                             dormir=dormir_sin_esperar)

    assert resultado.enviado is False
    assert resultado.intentos == ajustes.intentos
    assert resultado.error
    assert buzon.mensajes == []


async def test_una_direccion_que_no_existe_no_se_reintenta(
        ajustes, buzon, dormir_sin_esperar):
    """550 es "esa direccion no existe". Repetirlo tres veces solo retrasa el
    registro del fallo, y el criterio 3 da 60 segundos."""
    buzon.rechazar = {"ana@quinor.com.pe", "rosa@quinor.com.pe"}

    resultado = await enviar(ajustes, mensaje(), reparto(), evento_id=41,
                             dormir=dormir_sin_esperar)

    assert resultado.enviado is False
    assert resultado.intentos == 1
    assert dormir_sin_esperar.esperas == []


async def test_si_solo_rechaza_a_uno_el_correo_sale_y_se_dice_a_quien_no(
        ajustes, buzon):
    """Un correo con dos de tres destinatarios es un envio con matiz, no un
    exito: el administrador que no lo recibio tiene que aparecer en algun sitio."""
    buzon.rechazar = {"rosa@quinor.com.pe"}

    resultado = await enviar(ajustes, mensaje(), reparto(), evento_id=41)

    assert resultado.enviado is True
    assert resultado.parcial is True
    assert resultado.rechazados == ("rosa@quinor.com.pe",)
    assert len(buzon.mensajes) == 1


async def test_un_servidor_apagado_se_reintenta(ajustes, dormir_sin_esperar):
    """Una conexion rechazada no trae codigo SMTP, y es justo lo que hay que
    reintentar: el relay puede estar reiniciandose."""
    apagado = dataclasses.replace(ajustes, smtp_port=1)

    resultado = await enviar(apagado, mensaje(), reparto(), evento_id=41,
                             dormir=dormir_sin_esperar)

    assert resultado.enviado is False
    assert resultado.intentos == 3


async def test_un_error_que_no_tiene_arreglo_corta_los_intentos(
        ajustes, dormir_sin_esperar):
    async def rechaza(_ajustes, _correo):
        raise aiosmtplib.SMTPRecipientsRefused([])

    resultado = await enviar(ajustes, mensaje(), reparto(), evento_id=41,
                             enviador=rechaza, dormir=dormir_sin_esperar)

    assert resultado.enviado is False
    assert resultado.intentos == 1
    assert "SMTPRecipientsRefused" in resultado.error


async def test_un_error_temporal_con_codigo_si_se_reintenta(
        ajustes, dormir_sin_esperar):
    intentos = []

    async def saturado(_ajustes, _correo):
        intentos.append(1)
        raise aiosmtplib.SMTPResponseException(451, "Try again later")

    resultado = await enviar(ajustes, mensaje(), reparto(), evento_id=41,
                             enviador=saturado, dormir=dormir_sin_esperar)

    assert len(intentos) == 3
    assert resultado.enviado is False


async def test_el_mensaje_de_error_cabe_en_la_columna(ajustes,
                                                      dormir_sin_esperar):
    async def revienta(_ajustes, _correo):
        raise ValueError("x" * 2000)

    resultado = await enviar(ajustes, mensaje(), reparto(), evento_id=41,
                             enviador=revienta, dormir=dormir_sin_esperar)

    assert len(resultado.error) <= 500


# ------------------------------------------------------------- casos de borde
async def test_sin_destinatarios_no_se_intenta_enviar(ajustes, buzon):
    """No es un fallo del correo y no tiene sentido reintentarlo. Queda
    registrado igual: un evento Alto sin nadie a quien avisar es un problema de
    configuracion que hay que ver en el dashboard."""
    vacio = Reparto(severidad="alta", destinatarios=(), roles=("supervisor",),
                    urgente=True)

    resultado = await enviar(ajustes, mensaje(), vacio, evento_id=41)

    assert resultado.enviado is False
    assert resultado.intentos == 0
    assert "destinatarios" in resultado.error
    assert buzon.mensajes == []


async def test_sin_servidor_configurado_se_avisa_en_lugar_de_fallar_callando(
        ajustes):
    sin_host = dataclasses.replace(ajustes, smtp_host="")

    with pytest.raises(SinConfigurar):
        await enviar(sin_host, mensaje(), reparto(), evento_id=41)


async def test_la_espera_por_defecto_es_real(ajustes, buzon):
    """Sin inyectar `dormir`, la espera la pone asyncio de verdad. Con un solo
    intento no llega a usarse, pero la rama tiene que existir."""
    resultado = await enviar(dataclasses.replace(ajustes, intentos=1),
                             mensaje(), reparto(), evento_id=41)

    assert resultado.enviado is True


def test_el_mensaje_armado_no_lleva_las_direcciones_en_copia_oculta(ajustes):
    """Todos los destinatarios van en To y no en Bcc: el supervisor tiene que
    ver que el administrador tambien lo recibio, para no llamarle a contarselo."""
    correo = armar(ajustes, mensaje(), reparto(), evento_id=41)

    assert correo["Bcc"] is None
    assert "ana@quinor.com.pe" in correo["To"]
    assert "rosa@quinor.com.pe" in correo["To"]


def test_el_resultado_parcial_solo_lo_es_si_llego_a_alguien():
    assert Resultado(enviado=False, intentos=1, segundos=0.0,
                     rechazados=("a@b.c",)).parcial is False


async def test_si_el_servidor_rechaza_a_todos_sin_lanzar_es_un_fallo(
        ajustes, dormir_sin_esperar):
    """Algunos relays aceptan la conexion y devuelven el rechazo por direccion
    en lugar de lanzar. Un correo que no recibio nadie es un fallo, aunque
    ninguna excepcion lo diga."""
    async def rechaza_a_todos(_ajustes, _correo):
        return {"ana@quinor.com.pe": (550, "no such user"),
                "rosa@quinor.com.pe": (550, "no such user")}

    resultado = await enviar(ajustes, mensaje(), reparto(), evento_id=41,
                             enviador=rechaza_a_todos, dormir=dormir_sin_esperar)

    assert resultado.enviado is False
    assert resultado.parcial is False
    assert "rechazo todas las direcciones" in resultado.error


async def test_la_espera_entre_intentos_la_pone_asyncio_si_no_se_inyecta(
        ajustes, buzon):
    """Sin `dormir` inyectado, la espera es real. Con la espera a cero se
    recorre el mismo camino que en produccion sin gastar el reloj de la suite."""
    buzon.fallos_temporales = 1
    sin_espera = dataclasses.replace(ajustes, espera_inicial_s=0.0)

    resultado = await enviar(sin_espera, mensaje(), reparto(), evento_id=41)

    assert resultado.enviado is True
    assert resultado.intentos == 2
