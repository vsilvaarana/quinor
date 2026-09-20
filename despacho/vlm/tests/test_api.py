"""El endpoint POST /analisis/vlm. HU-09, criterios 1, 2 y 3."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import (EVENTO, EVENTO_QUE_CUADRA, JPEG, fotogramas,
                            stub_que)


def servicio(estado, **cambios):
    return create_app(proveedor=cambios.pop("proveedor", "stub"),
                      base_url=estado.url, modelo="modelo-de-prueba",
                      espera_inicial_s=0.0, api_key="",
                      dormir=lambda _s: None, **cambios)


def analizar(cliente, evento=None, **extra):
    cuerpo = {**(evento or EVENTO), "fotogramas": fotogramas(2), **extra}
    return cliente.post("/analisis/vlm", json=cuerpo)


# ------------------------------------------------------------------ servicio
def test_la_raiz_es_publica_y_no_analiza_nada(cliente):
    cuerpo = cliente.get("/").json()
    assert "HU-09" in cuerpo["historia"]


def test_la_salud_avisa_de_que_se_esta_hablando_con_el_stub(cliente):
    """Nadie debe confundir una respuesta de mentira con un analisis."""
    cuerpo = cliente.get("/salud").json()

    assert cuerpo["es_stub"] is True
    assert cuerpo["estado"] == "degradado"
    assert "no analisis reales" in cuerpo["mensaje"]


def test_sin_clave_del_proveedor_la_salud_lo_dice(stub):
    app = create_app(proveedor="anthropic", api_key_proveedor="",
                     base_url=stub.url, api_key="")
    with TestClient(app) as cliente:
        cuerpo = cliente.get("/salud").json()

    assert cuerpo["estado"] == "error"
    assert cuerpo["configurado"] is False
    assert "VLM_API_KEY" in cuerpo["mensaje"]


def test_sin_clave_del_proveedor_el_analisis_responde_503(stub):
    """503 y no 500: el servicio esta bien, lo que falta es la clave."""
    app = create_app(proveedor="anthropic", api_key_proveedor="",
                     base_url=stub.url, api_key="")
    with TestClient(app) as cliente:
        resp = analizar(cliente)

    assert resp.status_code == 503
    assert "VLM_API_KEY" in resp.json()["detail"]


def test_la_salud_dice_cuantos_intentos_hara(cliente):
    assert cliente.get("/salud").json()["intentos"] == 3


# ------------------------------------------ criterio 1: solo cuando toca
def test_una_carga_que_cuadra_no_llama_al_modelo(cliente, stub):
    """RN-03: para controlar el costo, y para que el analisis se lea cuando
    aparece. Un aviso en todas las filas deja de leerse."""
    cuerpo = analizar(cliente, EVENTO_QUE_CUADRA).json()

    assert cuerpo["invocado"] is False
    assert cuerpo["motivo_de_invocacion"] == "nada_que_explicar"
    assert cuerpo["analisis"] is None
    assert stub.peticiones == []


def test_aunque_no_se_invoque_la_severidad_se_calcula(cliente):
    """La RN-04 no necesita al modelo. Dejarla en blanco obligaria a HU-11 a
    ordenar sin criterio la mitad de la cola."""
    cuerpo = analizar(cliente, EVENTO_QUE_CUADRA).json()

    assert cuerpo["severidad"] == "baja"
    assert "sustituido" in cuerpo["motivo_de_severidad"]


def test_una_diferencia_de_sacos_si_lo_llama(cliente, stub):
    cuerpo = analizar(cliente).json()

    assert cuerpo["invocado"] is True
    assert len(stub.peticiones) == 1


def test_el_personal_anomalo_por_si_solo_lo_llama(cliente, stub):
    cuerpo = analizar(cliente, {**EVENTO_QUE_CUADRA, "personal_anomalo": True}).json()

    assert cuerpo["invocado"] is True
    assert cuerpo["motivo_de_invocacion"] == "personal_anomalo"


def test_sin_analisis_de_video_se_espera(cliente, stub):
    sin_yolo = {**EVENTO, "sacos_contados": None, "diferencia_sacos": None,
                "sacos_salientes": 0, "personal_anomalo": None}
    cuerpo = analizar(cliente, sin_yolo).json()

    assert cuerpo["invocado"] is False
    assert cuerpo["motivo_de_invocacion"] == "sin_analisis_de_video"
    assert stub.peticiones == []


def test_un_supervisor_puede_forzar_el_reanalisis(cliente, stub):
    """Es una decision de una persona sobre un caso concreto, no del sistema."""
    cuerpo = analizar(cliente, EVENTO_QUE_CUADRA, forzar=True).json()

    assert cuerpo["invocado"] is True
    assert len(stub.peticiones) == 1


# ------------------------------------------ criterio 2: el JSON del analisis
def test_la_respuesta_trae_descripcion_severidad_y_evidencia(cliente):
    cuerpo = analizar(cliente).json()

    analisis = cuerpo["analisis"]
    assert analisis["descripcion"]
    assert analisis["severidad_ia"] in ("baja", "media", "alta")
    assert analisis["evidencia"]
    assert 0 <= analisis["confianza"] <= 1


def test_la_severidad_del_evento_sale_de_la_regla_y_no_del_modelo(cliente):
    """Una alerta de madrugada no puede depender de la temperatura de un
    modelo. El evento de prueba tiene un saco saliente: Alta por la RN-04."""
    cuerpo = analizar(cliente).json()

    assert cuerpo["severidad"] == "alta"
    assert "salieron de la zona de carga" in cuerpo["motivo_de_severidad"]


def test_se_informa_si_el_modelo_concuerda_con_la_regla(cliente):
    """De esta comparacion sale la concordancia semanal del apartado 9.2."""
    cuerpo = analizar(cliente).json()

    assert cuerpo["concuerdan"] is (
        cuerpo["analisis"]["severidad_ia"] == cuerpo["severidad"])


def test_la_severidad_del_modelo_no_pisa_la_del_evento():
    """Aunque el modelo diga baja, un saco que sale sigue siendo Alta."""
    estado = stub_que()
    try:
        app = servicio(estado)
        with TestClient(app) as cliente:
            cuerpo = analizar(cliente, {**EVENTO, "diferencia_sacos": 0,
                                        "sacos_salientes": 3}).json()

        assert cuerpo["severidad"] == "alta"
    finally:
        estado.servidor.shutdown()


def test_se_informa_con_que_modelo_se_analizo(cliente):
    analisis = analizar(cliente).json()["analisis"]

    assert analisis["modelo"] == "modelo-de-prueba"
    assert analisis["proveedor"] == "stub"
    assert analisis["intentos"] == 1


def test_los_fotogramas_llegan_al_proveedor(cliente, stub):
    contenido = stub.peticiones[0] if stub.peticiones else None
    analizar(cliente)
    contenido = stub.peticiones[0]["cuerpo"]["messages"][0]["content"]

    imagenes = [b for b in contenido if b["type"] == "image"]
    assert len(imagenes) == 2
    assert imagenes[0]["source"]["data"] == JPEG


def test_un_evento_sin_fotogramas_se_analiza_igual(cliente, stub):
    """Puede pasar con un clip muy corto o si el video quedo ilegible. Es peor
    no describir nada que describir solo con los datos."""
    resp = cliente.post("/analisis/vlm", json={**EVENTO, "fotogramas": []})

    assert resp.status_code == 200
    assert resp.json()["analisis"]["descripcion"]


# --------------------------- criterio 3: tres intentos y Pendiente de analisis
def test_tras_los_tres_intentos_se_informa_el_fallo():
    """El servicio no toca la base: dice que fallo y el grabador marca el evento
    en Pendiente de analisis, que es el estado del apartado 5.3."""
    estado = stub_que(fallar=503)
    try:
        with TestClient(servicio(estado)) as cliente:
            cuerpo = analizar(cliente).json()

        assert cuerpo["fallo"] is True
        assert cuerpo["intentos"] == 3
        assert "503" in cuerpo["motivo_del_fallo"]
        assert cuerpo["analisis"] is None
        assert len(estado.peticiones) == 3
    finally:
        estado.servidor.shutdown()


def test_un_fallo_del_proveedor_no_es_un_error_del_servicio():
    """200 y no 500: el servicio funciono, lo que fallo fue el proveedor. Un 500
    haria que quien llama lo tratara como un fallo propio y lo reintentara."""
    estado = stub_que(fallar=503)
    try:
        with TestClient(servicio(estado)) as cliente:
            resp = analizar(cliente)

        assert resp.status_code == 200
    finally:
        estado.servidor.shutdown()


def test_aunque_el_modelo_falle_la_severidad_sigue_saliendo():
    """Es lo que permite que HU-10 notifique igual: la alerta base no depende de
    una API externa, que es justo el riesgo del apartado 12."""
    estado = stub_que(fallar=503)
    try:
        with TestClient(servicio(estado)) as cliente:
            cuerpo = analizar(cliente).json()

        assert cuerpo["severidad"] == "alta"
        assert cuerpo["fallo"] is True
    finally:
        estado.servidor.shutdown()


def test_un_error_pasajero_se_resuelve_solo():
    estado = stub_que(fallar=429, veces=2)
    try:
        with TestClient(servicio(estado)) as cliente:
            cuerpo = analizar(cliente).json()

        assert cuerpo["fallo"] is False
        assert cuerpo["analisis"]["intentos"] == 3
    finally:
        estado.servidor.shutdown()


# ------------------------------------------------------------------ la clave
def test_con_clave_configurada_no_se_entra_sin_ella(stub):
    """El servicio vive en la red interna del apartado 8 y solo lo llama el
    grabador. Aqui ademas cada llamada que entre cuesta dinero."""
    app = create_app(proveedor="stub", base_url=stub.url,
                     api_key="clave-de-servicio", dormir=lambda _s: None)
    with TestClient(app) as cliente:
        assert analizar(cliente).status_code == 401
        assert cliente.get("/salud").status_code == 401
        assert cliente.get("/").status_code == 200

        con_clave = cliente.post(
            "/analisis/vlm", json={**EVENTO, "fotogramas": fotogramas(1)},
            headers={"X-API-Key": "clave-de-servicio"})
        assert con_clave.status_code == 200


def test_una_clave_equivocada_no_pasa(stub):
    app = create_app(proveedor="stub", base_url=stub.url, api_key="la-buena",
                     dormir=lambda _s: None)
    with TestClient(app) as cliente:
        resp = cliente.post("/analisis/vlm", json=EVENTO,
                            headers={"X-API-Key": "la-mala"})
    assert resp.status_code == 401


def test_la_clave_del_servicio_sale_del_entorno(stub, monkeypatch):
    """Apartado 8: el secreto vive en el entorno, nunca en el codigo."""
    monkeypatch.setenv("VLM_SERVICE_API_KEY", "clave-del-entorno")
    app = create_app(proveedor="stub", base_url=stub.url, dormir=lambda _s: None)

    with TestClient(app) as cliente:
        assert cliente.get("/salud").status_code == 401
        con_clave = cliente.get("/salud",
                                headers={"X-API-Key": "clave-del-entorno"})
        assert con_clave.status_code == 200


def test_sin_la_variable_el_servicio_queda_abierto(monkeypatch):
    from app.main import _api_key_del_entorno

    monkeypatch.delenv("VLM_SERVICE_API_KEY", raising=False)
    assert _api_key_del_entorno() == ""


# ------------------------------------------------------------- el contrato
def test_el_cuerpo_minimo_se_acepta(cliente):
    """Un evento sin datos de video: se decide no invocar, no se revienta."""
    resp = cliente.post("/analisis/vlm", json={})

    assert resp.status_code == 200
    assert resp.json()["invocado"] is False


@pytest.mark.parametrize("confianza", [-0.5, 1.5])
def test_una_confianza_fuera_de_rango_no_sale_del_servicio(confianza):
    """El contrato la acota; si saliera, el dashboard ordenaria mal la cola."""
    from app.schemas import AnalisisLeido

    with pytest.raises(ValueError):
        AnalisisLeido(descripcion="x", severidad_ia="alta", confianza=confianza,
                      modelo="m", proveedor="p", intentos=1, segundos=1.0)


def test_con_un_proveedor_real_configurado_la_salud_esta_ok(stub):
    """Es el unico camino en el que el servicio se declara sano del todo: hay
    clave y no se esta hablando con el stub."""
    app = create_app(proveedor="anthropic", api_key_proveedor="sk-de-prueba",
                     base_url=stub.url, api_key="", dormir=lambda _s: None)
    with TestClient(app) as cliente:
        cuerpo = cliente.get("/salud").json()

    assert cuerpo["estado"] == "ok"
    assert cuerpo["es_stub"] is False
    assert cuerpo["mensaje"] is None
