"""La llamada al modelo: reintentos y validacion. HU-09, criterios 2 y 3.

Contra el stub por HTTP de verdad. Lo que se comprueba aqui es lo que de verdad
falla en planta: un 429 del proveedor, una clave mala, un JSON envuelto en un
bloque de codigo, una severidad que no existe. Un mock del cliente escondería
todas esas cosas.
"""
from __future__ import annotations

import json

import pytest

from app import vlm
from app.proveedores import Imagen
from app.vlm import (AnalisisFallido, RespuestaInvalida, SinConfigurar,
                     analizar, validar)
from tests.conftest import EVENTO, JPEG, ajustes_de, stub_que


def imagenes(cuantas: int = 2) -> list[Imagen]:
    return [Imagen(base64=JPEG, pie=f"[segundo {12 * (i + 1)} - saco_saliente]")
            for i in range(cuantas)]


def sin_dormir(_segundos):
    """Las esperas de los reintentos no se esperan de verdad: una prueba que
    tarda seis segundos en verificar un backoff acaba desactivada."""


# ------------------------------------------------ criterio 2: el JSON esperado
def test_se_obtiene_descripcion_severidad_y_evidencia(ajustes):
    analisis = analizar(ajustes, EVENTO, imagenes(), dormir=sin_dormir)

    assert analisis.descripcion
    assert analisis.severidad_ia in ("baja", "media", "alta")
    assert analisis.evidencia
    assert 0.0 <= analisis.confianza <= 1.0


def test_la_respuesta_dice_con_que_modelo_se_analizo(ajustes):
    """Cuando alguien discuta un caso dentro de seis meses, hara falta saber que
    modelo lo describio."""
    analisis = analizar(ajustes, EVENTO, imagenes(), dormir=sin_dormir)

    assert analisis.modelo == "modelo-de-prueba"
    assert analisis.proveedor == "stub"
    assert analisis.intentos == 1
    assert analisis.segundos >= 0


def test_lo_que_se_guarda_es_serializable(ajustes):
    """Acaba en evento.descripcion_ia, que es una columna JSON."""
    analisis = analizar(ajustes, EVENTO, imagenes(), dormir=sin_dormir)

    como_json = analisis.a_json()

    assert json.loads(json.dumps(como_json))["severidad_ia"] == analisis.severidad_ia
    assert set(como_json) == {"descripcion", "severidad_ia", "evidencia",
                              "confianza", "modelo", "proveedor", "intentos",
                              "segundos"}


# ------------------------------------------ lo que se le manda al proveedor
def test_los_datos_estructurados_viajan_con_las_imagenes(ajustes, stub):
    """Apartado 9.2: ademas de las imagenes se envian peso esperado, peso real,
    sacos contados y personas detectadas. Sin eso el modelo describiria un camion
    y unos sacos, que es lo que el supervisor ya sabe."""
    analizar(ajustes, EVENTO, imagenes(), dormir=sin_dormir)

    contenido = stub.peticiones[0]["cuerpo"]["messages"][0]["content"]
    texto = " ".join(b.get("text", "") for b in contenido if b["type"] == "text")

    assert "20000.0" in texto and "19850.0" in texto
    assert "397" in texto and "400" in texto
    assert "Personas en la zona de carga: 4" in texto
    assert "ORD-2026-0101" in texto


def test_las_imagenes_llegan_enteras(ajustes, stub):
    analizar(ajustes, EVENTO, imagenes(3), dormir=sin_dormir)

    contenido = stub.peticiones[0]["cuerpo"]["messages"][0]["content"]
    adjuntas = [b for b in contenido if b["type"] == "image"]

    assert len(adjuntas) == 3
    assert adjuntas[0]["source"]["data"] == JPEG
    assert adjuntas[0]["source"]["media_type"] == "image/jpeg"


def test_cada_imagen_va_con_su_pie(ajustes, stub):
    """El modelo tiene que saber que mira: un fotograma suelto sin contexto no
    dice si ese saco iba o venia."""
    analizar(ajustes, EVENTO, imagenes(2), dormir=sin_dormir)

    contenido = stub.peticiones[0]["cuerpo"]["messages"][0]["content"]
    pies = [b["text"] for b in contenido
            if b["type"] == "text" and b["text"].startswith("[segundo")]

    assert len(pies) == 2


def test_el_prompt_lleva_el_contexto_de_planta(ajustes, stub):
    """Apartado 9.2. Un modelo que no sabe como es una carga normal no puede
    decir que algo no lo fue."""
    analizar(ajustes, EVENTO, imagenes(), dormir=sin_dormir)

    sistema = stub.peticiones[0]["cuerpo"]["system"]

    assert "QUINOR" in sistema
    assert "RN-04" in sistema
    assert "Ley 29733" in sistema          # la prohibicion de identificar
    assert "no busques algo" in sistema.lower()


def test_la_temperatura_es_baja(ajustes, stub):
    """Aqui no se busca variedad: se busca que el mismo clip describa lo mismo
    dos veces."""
    analizar(ajustes, EVENTO, imagenes(), dormir=sin_dormir)

    assert stub.peticiones[0]["cuerpo"]["temperature"] <= 0.3


def test_la_clave_viaja_en_la_cabecera_del_proveedor():
    """Y no en el cuerpo ni en la URL, donde acabaria en un log."""
    estado = stub_que(clave="clave-del-proveedor")
    try:
        ajustes = ajustes_de(estado, proveedor="anthropic",
                             api_key="clave-del-proveedor")
        analizar(ajustes, EVENTO, imagenes(), dormir=sin_dormir)

        assert estado.peticiones[0]["clave"] == "clave-del-proveedor"
        assert estado.peticiones[0]["version"]      # anthropic-version
        assert "clave" not in json.dumps(estado.peticiones[0]["cuerpo"])
    finally:
        estado.servidor.shutdown()


# --------------------------------------------- criterio 3: los tres reintentos
def test_un_error_pasajero_se_reintenta_y_acaba_saliendo():
    """Un 429 se arregla esperando; por eso hay reintentos."""
    estado = stub_que(fallar=429, veces=2)
    try:
        analisis = analizar(ajustes_de(estado), EVENTO, imagenes(),
                            dormir=sin_dormir)

        assert analisis.intentos == 3
        assert len(estado.peticiones) == 3
    finally:
        estado.servidor.shutdown()


def test_tras_los_tres_intentos_se_rinde():
    """Criterio 3. El evento pasara a Pendiente de analisis, que lo hace quien
    llama porque este servicio no toca la base."""
    estado = stub_que(fallar=503)
    try:
        with pytest.raises(AnalisisFallido) as fallo:
            analizar(ajustes_de(estado), EVENTO, imagenes(), dormir=sin_dormir)

        assert fallo.value.intentos == 3
        assert len(estado.peticiones) == 3
        assert "503" in fallo.value.ultimo_motivo
    finally:
        estado.servidor.shutdown()


def test_son_tres_porque_lo_dice_la_historia():
    from app.config import INTENTOS

    assert INTENTOS == 3


def test_el_numero_de_intentos_es_configurable():
    estado = stub_que(fallar=500)
    try:
        with pytest.raises(AnalisisFallido):
            analizar(ajustes_de(estado, intentos=5), EVENTO, imagenes(),
                     dormir=sin_dormir)

        assert len(estado.peticiones) == 5
    finally:
        estado.servidor.shutdown()


def test_una_clave_mala_no_se_reintenta():
    """Insistir con una clave mala tres veces solo retrasa el momento de leer el
    error, y en un proveedor de pago cada intento se paga."""
    estado = stub_que(clave="la-buena")
    try:
        with pytest.raises(AnalisisFallido, match="401"):
            analizar(ajustes_de(estado, api_key="la-mala", proveedor="anthropic"),
                     EVENTO, imagenes(), dormir=sin_dormir)

        assert len(estado.peticiones) == 1
    finally:
        estado.servidor.shutdown()


@pytest.mark.parametrize("codigo", [400, 401, 403, 404, 422])
def test_los_errores_del_que_llama_no_se_reintentan(codigo):
    estado = stub_que(fallar=codigo)
    try:
        with pytest.raises(AnalisisFallido):
            analizar(ajustes_de(estado), EVENTO, imagenes(), dormir=sin_dormir)

        assert len(estado.peticiones) == 1
    finally:
        estado.servidor.shutdown()


@pytest.mark.parametrize("codigo", [429, 500, 502, 503, 504])
def test_los_errores_pasajeros_si_se_reintentan(codigo):
    estado = stub_que(fallar=codigo)
    try:
        with pytest.raises(AnalisisFallido):
            analizar(ajustes_de(estado), EVENTO, imagenes(), dormir=sin_dormir)

        assert len(estado.peticiones) == 3
    finally:
        estado.servidor.shutdown()


def test_la_espera_entre_intentos_crece():
    """Un 429 no se arregla insistiendo mas rapido."""
    estado = stub_que(fallar=429)
    esperas = []
    try:
        with pytest.raises(AnalisisFallido):
            analizar(ajustes_de(estado, espera_inicial_s=1.0), EVENTO,
                     imagenes(), dormir=esperas.append)

        assert esperas == [1.0, 2.0]      # dos esperas entre tres intentos
    finally:
        estado.servidor.shutdown()


def test_un_proveedor_apagado_se_reintenta_y_se_avisa():
    estado = stub_que()
    estado.servidor.shutdown()
    estado.servidor.server_close()

    with pytest.raises(AnalisisFallido) as fallo:
        analizar(ajustes_de(estado), EVENTO, imagenes(), dormir=sin_dormir)

    assert fallo.value.intentos == 3


def test_una_respuesta_ilegible_se_reintenta():
    """No es un fallo de red: es un modelo que devolvio algo que no sirve. Puede
    devolver algo legible al repetir, asi que se repite."""
    estado = stub_que(basura=True)
    try:
        with pytest.raises(AnalisisFallido):
            analizar(ajustes_de(estado), EVENTO, imagenes(), dormir=sin_dormir)

        assert len(estado.peticiones) == 3
    finally:
        estado.servidor.shutdown()


def test_sin_clave_no_se_llega_a_llamar():
    """Con un proveedor real y sin clave, el servicio esta en pie pero no puede
    pedir nada. Mejor decirlo que gastar tres intentos en un 401."""
    estado = stub_que()
    try:
        with pytest.raises(SinConfigurar, match="VLM_API_KEY"):
            analizar(ajustes_de(estado, proveedor="anthropic", api_key=""),
                     EVENTO, imagenes(), dormir=sin_dormir)

        assert estado.peticiones == []
    finally:
        estado.servidor.shutdown()


# ------------------------------------------------- la validacion de lo devuelto
def test_un_json_dentro_de_un_bloque_de_codigo_se_acepta():
    """Es lo mas comun que hay que perdonar, y perdonarlo no oculta nada."""
    datos = vlm._extraer_json(
        '```json\n{"descripcion": "x", "severidad": "alta"}\n```')
    assert datos["severidad"] == "alta"


def test_una_frase_antes_del_json_no_lo_estropea():
    datos = vlm._extraer_json(
        'Claro, aqui esta: {"descripcion": "x", "severidad": "baja"} espero ayude')
    assert datos["severidad"] == "baja"


@pytest.mark.parametrize("crudo", ["", "   ", "no soy json", "[1, 2, 3]"])
def test_lo_que_no_es_un_objeto_json_se_rechaza(crudo):
    with pytest.raises(RespuestaInvalida):
        vlm._extraer_json(crudo)


def test_un_json_roto_se_rechaza():
    with pytest.raises(RespuestaInvalida, match="no se puede leer"):
        vlm._extraer_json('{"descripcion": "x", ')


@pytest.mark.parametrize("entrada,esperada", [
    ("alta", "alta"), ("ALTA", "alta"), (" Media ", "media"),
    ("high", "alta"), ("medium", "media"), ("low", "baja"),
])
def test_las_severidades_equivalentes_se_traducen(entrada, esperada):
    assert validar({"descripcion": "x", "severidad": entrada})["severidad_ia"] == esperada


@pytest.mark.parametrize("nivel", ["critica", "urgente", "muy alta", "", None, 3])
def test_una_severidad_inventada_se_rechaza(nivel):
    """Adivinar cual quiso decir seria inventarse la severidad de un evento, y
    una severidad inventada en la tabla es peor que un evento sin analizar: el
    segundo se ve, el primero no."""
    with pytest.raises(RespuestaInvalida, match="RN-04"):
        validar({"descripcion": "x", "severidad": nivel})


def test_sin_descripcion_no_hay_analisis():
    with pytest.raises(RespuestaInvalida, match="descripcion"):
        validar({"descripcion": "   ", "severidad": "alta"})


def test_la_evidencia_puede_venir_vacia():
    """Se le pide explicitamente al modelo que no rellene la lista si no tiene
    nada. Una evidencia inventada es peor que ninguna."""
    assert validar({"descripcion": "x", "severidad": "baja"})["evidencia"] == ()


def test_una_evidencia_en_texto_suelto_se_acepta_como_una():
    campos = validar({"descripcion": "x", "severidad": "baja",
                      "evidencia": "solo una observacion"})
    assert campos["evidencia"] == ("solo una observacion",)


def test_una_evidencia_que_no_es_lista_ni_texto_se_rechaza():
    with pytest.raises(RespuestaInvalida, match="lista de frases"):
        validar({"descripcion": "x", "severidad": "baja", "evidencia": {"a": 1}})


def test_las_frases_vacias_de_la_evidencia_se_descartan():
    campos = validar({"descripcion": "x", "severidad": "baja",
                      "evidencia": ["una", "", "  ", "otra"]})
    assert campos["evidencia"] == ("una", "otra")


@pytest.mark.parametrize("valor,esperada", [
    (0.85, 0.85), (1.5, 1.0), (-0.2, 0.0), ("0.4", 0.4),
])
def test_la_confianza_se_acota_entre_cero_y_uno(valor, esperada):
    assert validar({"descripcion": "x", "severidad": "baja",
                    "confianza": valor})["confianza"] == esperada


@pytest.mark.parametrize("valor", [None, "mucha", {}])
def test_una_confianza_ilegible_se_asume_nula(valor):
    """Una cifra inventada al alza haria que el dashboard ordenara mal la cola."""
    assert validar({"descripcion": "x", "severidad": "baja",
                    "confianza": valor})["confianza"] == 0.0


def test_un_json_que_no_es_un_objeto_se_rechaza():
    """Un texto o una lista son JSON validos y no sirven para nada aqui: el
    criterio 2 pide un objeto con descripcion, severidad y evidencia."""
    with pytest.raises(RespuestaInvalida, match="no un objeto"):
        vlm._extraer_json('```json\n"solo un texto"\n```')
