"""El endpoint POST /analisis/yolo. HU-07, criterios 1 y 3."""
from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import ModeloFalso, sacos_cruzando


# ------------------------------------------------------------------ servicio
def test_la_raiz_es_publica_y_no_analiza_nada(cliente):
    cuerpo = cliente.get("/").json()
    assert cuerpo["servicio"] == "Servicio YOLO de QUINOR"
    assert "HU-07" in cuerpo["historia"]


def test_salud_dice_si_el_modelo_esta_cargado(cliente):
    cuerpo = cliente.get("/salud").json()
    assert cuerpo["estado"] == "ok"
    assert cuerpo["modelo_cargado"] is True
    assert cuerpo["linea"] == [0.5, 0.0, 0.5, 1.0]


def test_sin_modelo_la_salud_lo_dice_antes_del_primer_camion(tmp_path):
    app = create_app(ruta_pesos=tmp_path / "no-existe.pt", api_key="")
    with TestClient(app) as cliente:
        cuerpo = cliente.get("/salud").json()
    assert cuerpo["estado"] == "error"
    assert cuerpo["modelo_cargado"] is False
    assert "respondera 503" in cuerpo["mensaje"]


def test_sin_modelo_el_analisis_responde_503(tmp_path, clip):
    """503 y no 500: el servicio esta bien, lo que falta es el modelo."""
    app = create_app(ruta_pesos=tmp_path / "no-existe.pt", api_key="")
    with TestClient(app) as cliente:
        resp = cliente.post("/analisis/yolo", json={"clip": str(clip)})
    assert resp.status_code == 503
    assert "no esta cargado" in resp.json()["detail"]


# ------------------------------------------------------- criterio 1: el conteo
def test_cuenta_los_sacos_que_cruzan(cliente, clip):
    resp = cliente.post("/analisis/yolo", json={"clip": str(clip)})
    assert resp.status_code == 200
    cuerpo = resp.json()
    assert cuerpo["sacos_contados"] == 2
    assert cuerpo["sacos_entrantes"] == 2
    assert cuerpo["sacos_salientes"] == 0


def test_la_respuesta_trae_lo_que_tardo(cliente, clip):
    """RNF-01: un clip de 7 min se analiza en menos de 3 en planta. Sin la cifra
    en la respuesta, nadie sabria si se esta cumpliendo."""
    cuerpo = cliente.post("/analisis/yolo", json={"clip": str(clip)}).json()
    assert cuerpo["segundos_de_proceso"] >= 0
    assert cuerpo["duracion_del_clip_s"] > 0
    assert cuerpo["fotogramas_procesados"] == 3


def test_un_clip_que_no_existe_devuelve_404(cliente):
    resp = cliente.post("/analisis/yolo", json={"clip": "/video/no-existe.mkv"})
    assert resp.status_code == 404


def test_un_archivo_que_no_es_video_devuelve_404(cliente, tmp_path):
    falso = tmp_path / "no-es-video.mkv"
    falso.write_text("esto no es un video")
    assert cliente.post("/analisis/yolo", json={"clip": str(falso)}).status_code == 404


def test_las_personas_salen_del_mismo_recorrido(clip, tmp_path):
    """HU-08 en la misma pasada que HU-07: el video ya esta abierto y las
    personas vienen en la misma inferencia. Dos recorridos doblarian el coste."""
    pesos = tmp_path / "sacos.pt"
    pesos.write_bytes(b"x")
    app = create_app(ruta_pesos=pesos, api_key="", permanencia_minima_s=0.0,
                     modelo=ModeloFalso(sacos_cruzando(3, personas=2)))
    with TestClient(app) as cliente:
        cuerpo = cliente.post("/analisis/yolo", json={"clip": str(clip)}).json()
    assert cuerpo["sacos_contados"] == 3
    assert cuerpo["personas_detectadas"] == 2


# --------------------------------------------- criterio 3: diferencia con la orden
def test_con_los_sacos_esperados_viene_la_diferencia(cliente, clip):
    cuerpo = cliente.post("/analisis/yolo", json={
        "clip": str(clip), "sacos_esperados": 5}).json()

    assert cuerpo["sacos_esperados"] == 5
    # Negativa es faltante, el mismo criterio de signo que la diferencia de peso.
    assert cuerpo["diferencia_sacos"] == -3


def test_sin_sacos_esperados_no_se_inventa_una_diferencia(cliente, clip):
    cuerpo = cliente.post("/analisis/yolo", json={"clip": str(clip)}).json()
    assert cuerpo["sacos_esperados"] is None
    assert cuerpo["diferencia_sacos"] is None


def test_contar_de_mas_da_diferencia_positiva(cliente, clip):
    cuerpo = cliente.post("/analisis/yolo", json={
        "clip": str(clip), "sacos_esperados": 1}).json()
    assert cuerpo["diferencia_sacos"] == 1


# ------------------------------------------------------------- la linea de carga
def test_quien_llama_puede_pasar_su_propia_linea(cliente, clip):
    """Con dos camaras enfocando rampas distintas la linea no es la misma. Con
    la linea en el otro extremo, esos sacos ya no la cruzan."""
    cuerpo = cliente.post("/analisis/yolo", json={
        "clip": str(clip), "linea": [0.95, 0.0, 0.95, 1.0]}).json()
    assert cuerpo["sacos_contados"] == 0


def test_se_puede_invertir_el_sentido_por_peticion(cliente, clip):
    cuerpo = cliente.post("/analisis/yolo", json={
        "clip": str(clip), "invertir_sentido": True}).json()
    assert cuerpo["sacos_entrantes"] == 0
    assert cuerpo["sacos_salientes"] == 2


@pytest.mark.parametrize("linea", [[0.5, 0.0, 0.5], [0.5, 0.0, 0.5, 1.0, 0.2]])
def test_una_linea_mal_formada_se_rechaza(cliente, clip, linea):
    assert cliente.post("/analisis/yolo", json={
        "clip": str(clip), "linea": linea}).status_code == 422


def test_el_clip_es_obligatorio(cliente):
    assert cliente.post("/analisis/yolo", json={}).status_code == 422


# ------------------------------------------------------------------ la clave
def test_con_clave_configurada_no_se_entra_sin_ella(tmp_path, clip, modelo_con_dos_sacos):
    """El servicio vive en la red interna del apartado 8 y solo lo llama el
    grabador; la clave evita que cualquier cosa de esa red le mande clips."""
    pesos = tmp_path / "sacos.pt"
    pesos.write_bytes(b"x")
    app = create_app(ruta_pesos=pesos, api_key="clave-de-servicio",
                     modelo=modelo_con_dos_sacos)
    with TestClient(app) as cliente:
        assert cliente.post("/analisis/yolo", json={"clip": str(clip)}).status_code == 401
        assert cliente.get("/salud").status_code == 401
        # La raiz sigue siendo publica: es el healthcheck del compose.
        assert cliente.get("/").status_code == 200
        con_clave = cliente.post("/analisis/yolo", json={"clip": str(clip)},
                                 headers={"X-API-Key": "clave-de-servicio"})
        assert con_clave.status_code == 200


def test_una_clave_equivocada_no_pasa(tmp_path, clip, modelo_con_dos_sacos):
    pesos = tmp_path / "sacos.pt"
    pesos.write_bytes(b"x")
    app = create_app(ruta_pesos=pesos, api_key="la-buena", modelo=modelo_con_dos_sacos)
    with TestClient(app) as cliente:
        resp = cliente.post("/analisis/yolo", json={"clip": str(clip)},
                            headers={"X-API-Key": "la-mala"})
    assert resp.status_code == 401


# ------------------------------------------------------ como se llama al modelo
def test_al_modelo_se_le_pide_seguimiento_y_no_solo_deteccion(cliente, clip,
                                                              modelo_con_dos_sacos):
    """Contar sin seguir es contar fotogramas, no sacos."""
    cliente.post("/analisis/yolo", json={"clip": str(clip)})
    llamada = modelo_con_dos_sacos.llamadas[0]

    assert llamada["persist"] is True
    assert llamada["tracker"] == "bytetrack.yaml"      # el del apartado 6.4
    # stream=True: un clip de 7 min a 1080p no cabe en memoria de otro modo.
    assert llamada["stream"] is True


def test_el_dispositivo_y_el_umbral_llegan_al_modelo(clip, tmp_path,
                                                     modelo_con_dos_sacos):
    pesos = tmp_path / "sacos.pt"
    pesos.write_bytes(b"x")
    app = create_app(ruta_pesos=pesos, api_key="", dispositivo="cpu",
                     confianza_minima=0.55, modelo=modelo_con_dos_sacos)
    with TestClient(app) as cliente:
        cliente.post("/analisis/yolo", json={"clip": str(clip)})

    llamada = modelo_con_dos_sacos.llamadas[0]
    assert llamada["device"] == "cpu"
    assert llamada["conf"] == 0.55


def test_el_nombre_del_modelo_viaja_en_la_respuesta(cliente, clip):
    """Para saber con que version se conto esa carga cuando HU-19 cambie el modelo."""
    assert cliente.post("/analisis/yolo",
                        json={"clip": str(clip)}).json()["modelo"] == "sacos.pt"


def test_un_clip_sin_detecciones_cuenta_cero(clip, tmp_path):
    pesos = tmp_path / "sacos.pt"
    pesos.write_bytes(b"x")
    app = create_app(ruta_pesos=pesos, api_key="",
                     modelo=ModeloFalso([[], [], []]))
    with TestClient(app) as cliente:
        cuerpo = cliente.post("/analisis/yolo", json={"clip": str(clip)}).json()
    assert cuerpo["sacos_contados"] == 0
    assert cuerpo["personas_detectadas"] == 0


def test_un_cero_sospechoso_viaja_con_su_aviso(clip, tmp_path):
    """Cero sacos es una respuesta grave: manda a alguien a la rampa. Si sale de
    un rastreador que no siguio nada, quien llama tiene que saberlo."""
    pesos = tmp_path / "sacos.pt"
    pesos.write_bytes(b"x")
    app = create_app(ruta_pesos=pesos, api_key="",
                     modelo=ModeloFalso(sacos_cruzando(2), con_id=False))
    with TestClient(app) as cliente:
        cuerpo = cliente.post("/analisis/yolo", json={"clip": str(clip)}).json()

    assert cuerpo["sacos_contados"] == 0
    assert "YOLO_FRAME_STRIDE" in cuerpo["aviso"]


def test_un_conteo_normal_no_lleva_aviso(cliente, clip):
    assert cliente.post("/analisis/yolo",
                        json={"clip": str(clip)}).json()["aviso"] is None


# ------------------------------------------------------- el arranque del modelo
def test_el_modelo_se_carga_al_arrancar_y_no_con_el_camion_esperando(tmp_path,
                                                                     monkeypatch):
    """Cargar PyTorch son segundos; pagarlos en el primer clip del dia es pagarlos
    con el camion en la rampa."""
    pesos = tmp_path / "sacos.pt"
    pesos.write_bytes(b"x")
    from app import analisis

    cargados = []

    def falso(ajustes):
        cargados.append(ajustes.ruta_pesos)
        return ModeloFalso(sacos_cruzando(1))

    monkeypatch.setattr(analisis, "_cargar_modelo", falso)
    app = create_app(ruta_pesos=pesos, api_key="")

    assert cargados == []                 # todavia no: se carga en el arranque
    with TestClient(app) as cliente:
        assert cliente.get("/salud").json()["modelo_cargado"] is True
    assert cargados == [pesos]


def test_unos_pesos_corruptos_no_impiden_arrancar(tmp_path, monkeypatch):
    """El servicio arranca igual y lo dice en /salud. Si no arrancara, el compose
    lo reiniciaria en bucle y nadie veria el motivo."""
    pesos = tmp_path / "sacos.pt"
    pesos.write_bytes(b"esto no son pesos")
    from app import analisis

    def revienta(ajustes):
        raise RuntimeError("archivo de pesos ilegible")

    monkeypatch.setattr(analisis, "_cargar_modelo", revienta)
    with TestClient(create_app(ruta_pesos=pesos, api_key="")) as cliente:
        cuerpo = cliente.get("/salud").json()

    assert cuerpo["estado"] == "error"
    assert cuerpo["modelo_cargado"] is False


def test_la_clave_sale_del_entorno_cuando_no_se_pasa(tmp_path, monkeypatch, clip,
                                                     modelo_con_dos_sacos):
    """Apartado 8: el secreto vive en el entorno, nunca en el codigo."""
    monkeypatch.setenv("YOLO_API_KEY", "clave-del-entorno")
    pesos = tmp_path / "sacos.pt"
    pesos.write_bytes(b"x")
    app = create_app(ruta_pesos=pesos, modelo=modelo_con_dos_sacos)

    with TestClient(app) as cliente:
        assert cliente.get("/salud").status_code == 401
        con_clave = cliente.get("/salud", headers={"X-API-Key": "clave-del-entorno"})
        assert con_clave.status_code == 200


def test_sin_la_variable_el_servicio_queda_abierto(monkeypatch):
    """En desarrollo no hay clave; en planta el compose la exige."""
    from app.main import ajustes_api_key

    monkeypatch.delenv("YOLO_API_KEY", raising=False)
    assert ajustes_api_key() == ""


def test_pathlib_no_se_cuela_en_la_respuesta(cliente, clip):
    """El contrato es JSON: una ruta de Python ahi romperia a quien llame."""
    cuerpo = cliente.post("/analisis/yolo", json={"clip": str(clip)}).json()
    assert isinstance(cuerpo["modelo"], str)
    assert not isinstance(cuerpo["modelo"], pathlib.Path)


# ------------------------------------------- HU-08: las personas en el contrato
def app_con_gente(tmp_path, personas=2, sacos=3, **ajustes):
    """Servicio con un modelo que pone gente en la rampa durante el clip."""
    pesos = tmp_path / "sacos.pt"
    pesos.write_bytes(b"x")
    ajustes.setdefault("permanencia_minima_s", 0.0)
    return create_app(ruta_pesos=pesos, api_key="",
                      modelo=ModeloFalso(sacos_cruzando(sacos, personas=personas)),
                      **ajustes)


def test_la_respuesta_trae_quien_estuvo_en_zona_y_cuanto(clip, tmp_path):
    """Criterio 2 visto desde fuera: cuantas personas y su permanencia."""
    with TestClient(app_con_gente(tmp_path, personas=2)) as cliente:
        cuerpo = cliente.post("/analisis/yolo", json={"clip": str(clip)}).json()

    presencia = cuerpo["presencia"]
    assert presencia["cuantas"] == 2
    assert presencia["maximo_simultaneo"] == 2
    assert len(presencia["personas"]) == 2
    assert all(p["segundos_en_zona"] >= 0 for p in presencia["personas"])


def test_de_cada_persona_solo_viaja_un_numero_y_unos_segundos(clip, tmp_path):
    """RN-08: si alguien anadiera un recorte de imagen o un descriptor al
    contrato, esta prueba lo diria antes de que saliera de la red interna."""
    with TestClient(app_con_gente(tmp_path, personas=1)) as cliente:
        cuerpo = cliente.post("/analisis/yolo", json={"clip": str(clip)}).json()

    persona = cuerpo["presencia"]["personas"][0]
    assert set(persona) == {"id_temporal", "segundos_en_zona",
                            "primer_fotograma", "ultimo_fotograma"}


def test_una_rampa_vacia_devuelve_presencia_en_cero(clip, tmp_path):
    with TestClient(app_con_gente(tmp_path, personas=0)) as cliente:
        cuerpo = cliente.post("/analisis/yolo", json={"clip": str(clip)}).json()

    assert cuerpo["presencia"]["cuantas"] == 0
    assert cuerpo["presencia"]["personas"] == []
    assert cuerpo["anomalia_de_personal"] is False


def test_quien_llama_puede_pasar_su_propia_zona(clip, tmp_path):
    """Con dos camaras enfocando rampas distintas, la zona no es la misma. En el
    clip de prueba la gente esta en x=0.3, asi que una zona a la derecha la deja
    fuera."""
    app = app_con_gente(tmp_path, personas=2)
    with TestClient(app) as cliente:
        fuera = cliente.post("/analisis/yolo", json={
            "clip": str(clip), "zona": [0.6, 0.0, 1.0, 1.0]}).json()

    assert fuera["presencia"]["cuantas"] == 0
    assert fuera["presencia"]["zona_completa"] is False


def test_se_avisa_cuando_la_zona_no_esta_calibrada(clip, tmp_path):
    """Con el cuadro entero, en zona incluye a quien solo pasa por el fondo.
    Quien lea el dato tiene que poder saberlo."""
    with TestClient(app_con_gente(tmp_path, personas=1)) as cliente:
        cuerpo = cliente.post("/analisis/yolo", json={"clip": str(clip)}).json()
    assert cuerpo["presencia"]["zona_completa"] is True


@pytest.mark.parametrize("zona", [[0.4, 0.0, 1.0], [0.4, 0.0, 1.0, 1.0, 0.2]])
def test_una_zona_mal_formada_se_rechaza(clip, tmp_path, zona):
    with TestClient(app_con_gente(tmp_path)) as cliente:
        assert cliente.post("/analisis/yolo", json={
            "clip": str(clip), "zona": zona}).status_code == 422


def test_la_salud_dice_con_que_zona_se_esta_midiendo(tmp_path):
    """Una zona mal calibrada da cargas sin nadie en rampa, y desde fuera eso se
    ve igual que una rampa vacia de verdad."""
    app = app_con_gente(tmp_path, zona=(0.4, 0.0, 1.0, 1.0))
    with TestClient(app) as cliente:
        cuerpo = cliente.get("/salud").json()
    assert cuerpo["zona"] == [0.4, 0.0, 1.0, 1.0]


# ---------------------------------------- HU-08: la senal de personal anomalo
def test_demasiada_gente_a_la_vez_viaja_como_anomalia(clip, tmp_path):
    """Es el disparo que la RN-03 necesita para no llamar al modelo de
    vision-lenguaje en cada carga."""
    app = app_con_gente(tmp_path, personas=4, personas_habituales=2)
    with TestClient(app) as cliente:
        cuerpo = cliente.post("/analisis/yolo", json={"clip": str(clip)}).json()

    assert cuerpo["anomalia_de_personal"] is True
    motivos = cuerpo["motivos_de_anomalia"]
    assert motivos[0]["codigo"] == "demasiadas_personas_a_la_vez"
    assert motivos[0]["medido"] == 4.0 and motivos[0]["umbral"] == 2.0


def test_una_carga_normal_no_dispara_la_anomalia(clip, tmp_path):
    app = app_con_gente(tmp_path, personas=2, sacos=3, personas_habituales=3)
    with TestClient(app) as cliente:
        cuerpo = cliente.post("/analisis/yolo", json={"clip": str(clip)}).json()

    assert cuerpo["anomalia_de_personal"] is False
    assert cuerpo["motivos_de_anomalia"] == []


def test_gente_sin_sacos_cruzando_tambien_dispara(clip, tmp_path):
    """Puede ser una limpieza y puede ser lo otro; merece que alguien mire."""
    pesos = tmp_path / "sacos.pt"
    pesos.write_bytes(b"x")
    solo_gente = [[(900, 1, 0.8, 0.3, 0.6)] for _ in range(3)]
    app = create_app(ruta_pesos=pesos, api_key="", permanencia_minima_s=0.0,
                     modelo=ModeloFalso(solo_gente))
    with TestClient(app) as cliente:
        cuerpo = cliente.post("/analisis/yolo", json={"clip": str(clip)}).json()

    assert cuerpo["sacos_contados"] == 0
    assert cuerpo["anomalia_de_personal"] is True
    assert "personas_sin_movimiento_de_sacos" in [
        m["codigo"] for m in cuerpo["motivos_de_anomalia"]]


def test_un_resultado_sin_personas_no_rompe_la_respuesta():
    """`personas` en None es el estado de un Resultado construido a mano, por
    ejemplo en una prueba de otra capa. El contrato tiene que aguantarlo en lugar
    de reventar con un AttributeError delante del grabador."""
    from app.analisis import Resultado
    from app.main import _presencia

    suelto = Resultado(sacos_contados=0, sacos_entrantes=0, sacos_salientes=0,
                       personas_detectadas=0, fotogramas_procesados=1,
                       fotogramas_totales=1, duracion_del_clip_s=1.0,
                       segundos_de_proceso=0.1, modelo="x.pt",
                       detecciones_de_saco=0)

    assert _presencia(suelto) is None
