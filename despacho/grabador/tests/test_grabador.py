"""El supervisor de grabacion. HU-05, los tres criterios juntos.

Las pruebas marcadas con `camara_rtsp` graban de verdad: servidor RTSP, camara
emitiendo y ffmpeg escribiendo en disco. Comprobar con un mock que se llama a
subprocess no diria nada sobre si el video acaba partido en segmentos, que es lo
que pide el criterio 1.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import subprocess
import time

import pytest

from app import aviso, ffmpeg, retencion, salud, tablas
from app.config import Camara
from app.grabador import Grabador
from tests.conftest import CAMARA_PRUEBA, segmento


class ProcesoFalso:
    """Un ffmpeg que no existe, para probar la logica del supervisor."""

    def __init__(self, vivo: bool = True, error: str = ""):
        self._vivo = vivo
        self.stderr = _Texto(error)
        self.terminado = False

    def poll(self):
        return None if self._vivo else 1

    def terminate(self):
        self.terminado = True
        self._vivo = False

    def wait(self, timeout=None):
        self._vivo = False
        return 0

    def kill(self):
        self._vivo = False

    def morir(self):
        self._vivo = False


class _Texto:
    def __init__(self, contenido: str):
        self.contenido = contenido

    def read(self):
        return self.contenido


@pytest.fixture()
def grabador(ajustes, motor) -> Grabador:
    return Grabador(ajustes, motor)


def poner_grabacion(grabador, proceso, indice: int = 0):
    estado = grabador.camaras[indice]
    estado.grabacion = ffmpeg.Grabacion(camara=estado.camara, proceso=proceso,
                                        comando=("ffmpeg",))
    return estado


# --------------------------------------------------------- vigilancia y salud
def test_una_camara_viva_se_registra_como_conectada(grabador, motor):
    poner_grabacion(grabador, ProcesoFalso(vivo=True))
    grabador.revisar_camaras()

    assert grabador.camaras[0].conectada is True
    assert salud.ultimo(motor, CAMARA_PRUEBA)["estado"] == "ok"


def test_una_camara_caida_se_registra_en_salud(grabador, motor):
    """Criterio 3, que es la razon de ser de todo este vigilante."""
    poner_grabacion(grabador, ProcesoFalso(vivo=False, error="Connection timed out"))
    grabador.revisar_camaras()

    fila = salud.ultimo(motor, CAMARA_PRUEBA)
    assert fila["estado"] == "error"
    assert "Connection timed out" in fila["mensaje"]
    assert grabador.camaras[0].caidas == 1


def test_una_camara_caida_se_vuelve_a_intentar(grabador, monkeypatch):
    """Una camara vuelve cuando vuelve la red: rendirse dejaria la rampa ciega
    hasta que alguien se acordara de reiniciar el servicio."""
    intentos = []
    monkeypatch.setattr(ffmpeg, "iniciar",
                        lambda a, c: intentos.append(c) or ffmpeg.Grabacion(
                            camara=c, proceso=ProcesoFalso(), comando=("ffmpeg",)))

    poner_grabacion(grabador, ProcesoFalso(vivo=False, error="caida"))
    grabador.revisar_camaras()          # detecta la caida
    assert grabador.camaras[0].grabacion is None

    time.sleep(grabador.ajustes.segundos_entre_reintentos + 0.05)
    grabador.revisar_camaras()          # reintenta
    assert len(intentos) == 1
    assert grabador.camaras[0].grabacion is not None


def test_no_se_reintenta_antes_de_tiempo(grabador, monkeypatch):
    """Reintentar en bucle cerrado contra una camara apagada solo llenaria el log."""
    intentos = []
    monkeypatch.setattr(ffmpeg, "iniciar", lambda a, c: intentos.append(c))

    poner_grabacion(grabador, ProcesoFalso(vivo=False, error="caida"))
    grabador.revisar_camaras()
    grabador.revisar_camaras()
    grabador.revisar_camaras()
    assert intentos == []


def test_cuando_ffmpeg_calla_el_mensaje_nombra_la_camara(grabador, motor):
    """Una camara que corta limpiamente no deja nada en stderr. Decir solo
    "termino" no le sirve a quien mira el panel a las once de la noche."""
    poner_grabacion(grabador, ProcesoFalso(vivo=False, error=""))
    grabador.revisar_camaras()

    mensaje = salud.ultimo(motor, CAMARA_PRUEBA)["mensaje"]
    assert CAMARA_PRUEBA in mensaje
    assert "dejo de emitir" in mensaje


def test_la_vuelta_de_una_camara_queda_registrada(grabador, motor):
    poner_grabacion(grabador, ProcesoFalso(vivo=False, error="caida"))
    grabador.revisar_camaras()
    poner_grabacion(grabador, ProcesoFalso(vivo=True))
    grabador.revisar_camaras()

    assert salud.ultimo(motor, CAMARA_PRUEBA)["estado"] == "ok"


def test_una_camara_estable_no_reescribe_su_estado(grabador, motor):
    from sqlalchemy import func, select

    poner_grabacion(grabador, ProcesoFalso(vivo=True))
    for _ in range(10):
        grabador.revisar_camaras()

    with motor.connect() as conexion:
        filas = conexion.execute(
            select(func.count()).select_from(salud.salud_componente)).scalar_one()
    assert filas == 1


def test_una_camara_caida_no_afecta_a_las_demas(ajustes, motor, monkeypatch):
    dos = dataclasses.replace(ajustes, camaras=(
        Camara(id="camara-01", url="rtsp://una/stream"),
        Camara(id="camara-02", url="rtsp://otra/stream")))
    grabador = Grabador(dos, motor)

    poner_grabacion(grabador, ProcesoFalso(vivo=False, error="caida"), indice=0)
    poner_grabacion(grabador, ProcesoFalso(vivo=True), indice=1)
    monkeypatch.setattr(ffmpeg, "iniciar", lambda a, c: None)
    grabador.revisar_camaras()

    assert salud.ultimo(motor, "camara-01")["estado"] == "error"
    assert salud.ultimo(motor, "camara-02")["estado"] == "ok"


def test_si_ffmpeg_no_arranca_tambien_se_avisa(grabador, motor, monkeypatch):
    """Sin esto el buffer estaria vacio y nadie lo sabria hasta pedir un clip."""
    def revienta(_a, _c):
        raise OSError("No such file or directory: 'ffmpeg'")

    monkeypatch.setattr(ffmpeg, "iniciar", revienta)
    grabador.revisar_camaras()

    fila = salud.ultimo(motor, CAMARA_PRUEBA)
    assert fila["estado"] == "error"
    assert "ffmpeg" in fila["mensaje"]


def test_un_fallo_de_mysql_no_para_la_grabacion(grabador, monkeypatch):
    """Grabar es lo primero. Al reves seria absurdo: se perderia el video por no
    poder anotar que se estaba grabando."""
    from sqlalchemy.exc import OperationalError

    def revienta(*_a, **_k):
        raise OperationalError("select 1", {}, Exception("MySQL caido"))

    monkeypatch.setattr(salud, "camara_conectada", revienta)
    poner_grabacion(grabador, ProcesoFalso(vivo=True))
    grabador.revisar_camaras()          # no debe propagar


# --------------------------------------------------------------- retencion
def test_la_purga_deja_el_estado_del_disco(grabador, motor, buffer):
    segmento(buffer, CAMARA_PRUEBA, "20260101-000000")
    grabador.revisar_retencion(forzar=True)

    fila = salud.ultimo(motor, salud.COMPONENTE_DISCO)
    assert fila["estado"] == "ok"
    assert "de disco libre" in fila["mensaje"]


def test_el_disco_al_limite_queda_en_error(grabador, motor, buffer, monkeypatch):
    # Segmentos recientes de verdad, no una fecha escrita a mano: lo que se mide
    # es la purga por espacio, y con una fecha fija los segmentos envejecen solos
    # y acaban borrandose por antiguedad, que es otra cosa.
    ahora = dt.datetime.now()
    for minuto in range(3):
        marca = (ahora - dt.timedelta(minutes=minuto)).strftime("%Y%m%d-%H%M%S")
        segmento(buffer, CAMARA_PRUEBA, marca)
    monkeypatch.setattr(retencion, "_libre_pct", lambda _d: 1.0)

    grabador.revisar_retencion(forzar=True)

    fila = salud.ultimo(motor, salud.COMPONENTE_DISCO)
    assert fila["estado"] == "error"
    assert "72 h" in fila["mensaje"]


def test_la_purga_no_se_repite_en_cada_vuelta(ajustes, motor, monkeypatch):
    lento = dataclasses.replace(ajustes, segundos_entre_purgas=3600.0)
    grabador = Grabador(lento, motor)
    pasadas = []
    monkeypatch.setattr(retencion, "purgar",
                        lambda a, ahora=None: pasadas.append(1) or retencion.ResultadoDePurga())

    grabador.revisar_retencion(forzar=True)
    grabador.revisar_retencion()
    grabador.revisar_retencion()
    assert len(pasadas) == 1


# ------------------------------------------------------------------- ciclo
def test_el_bucle_da_las_vueltas_que_se_le_piden(grabador, monkeypatch):
    monkeypatch.setattr(ffmpeg, "iniciar",
                        lambda a, c: ffmpeg.Grabacion(camara=c, proceso=ProcesoFalso(),
                                                      comando=("ffmpeg",)))
    assert grabador.ejecutar(segundos_entre_vueltas=0.01, vueltas_maximas=3) == 3


def test_al_detenerlo_se_cierran_los_ffmpeg(grabador, monkeypatch):
    """SIGTERM y no SIGKILL: ffmpeg cierra el segmento en curso en lugar de
    dejarlo a medias."""
    procesos = []

    def falso(_a, c):
        p = ProcesoFalso()
        procesos.append(p)
        return ffmpeg.Grabacion(camara=c, proceso=p, comando=("ffmpeg",))

    monkeypatch.setattr(ffmpeg, "iniciar", falso)
    grabador.ejecutar(segundos_entre_vueltas=0.01, vueltas_maximas=1)
    assert procesos and all(p.terminado for p in procesos)


def test_una_senal_de_parada_corta_el_bucle(grabador, monkeypatch):
    monkeypatch.setattr(ffmpeg, "iniciar",
                        lambda a, c: ffmpeg.Grabacion(camara=c, proceso=ProcesoFalso(),
                                                      comando=("ffmpeg",)))
    grabador.detener()
    assert grabador.ejecutar(segundos_entre_vueltas=0.01, vueltas_maximas=10) == 0


def test_el_resumen_dice_que_camara_graba(grabador, buffer):
    poner_grabacion(grabador, ProcesoFalso(vivo=True))
    grabador.revisar_camaras()
    segmento(buffer, CAMARA_PRUEBA, "20260914-110000")

    resumen = grabador.resumen()
    assert resumen["camaras"][CAMARA_PRUEBA] == "grabando"
    assert resumen["horas_en_buffer"] >= 0


def test_detener_una_grabacion_ya_muerta_no_revienta():
    proceso = ProcesoFalso(vivo=False)
    grabacion = ffmpeg.Grabacion(camara=Camara(id="x", url="rtsp://x"),
                                 proceso=proceso, comando=("ffmpeg",))
    grabacion.detener()
    assert proceso.terminado is False


def test_un_ffmpeg_que_ignora_el_sigterm_se_mata():
    class Tozudo(ProcesoFalso):
        def __init__(self):
            super().__init__(vivo=True)
            self.matado = False
            self.intentos = 0

        def wait(self, timeout=None):
            self.intentos += 1
            if self.intentos == 1:
                raise subprocess.TimeoutExpired("ffmpeg", timeout or 0)
            self._vivo = False
            return 0

        def kill(self):
            self.matado = True

    proceso = Tozudo()
    ffmpeg.Grabacion(camara=Camara(id="x", url="rtsp://x"), proceso=proceso,
                     comando=("ffmpeg",)).detener(espera_s=0.01)
    assert proceso.matado is True


def test_sin_stderr_el_motivo_queda_vacio():
    class SinSalida(ProcesoFalso):
        def __init__(self):
            super().__init__(vivo=False)
            self.stderr = None

    grabacion = ffmpeg.Grabacion(camara=Camara(id="x", url="rtsp://x"),
                                 proceso=SinSalida(), comando=("ffmpeg",))
    assert ffmpeg.ultimo_error(grabacion) == ""


# ------------------------------------------------- grabacion real contra RTSP
def test_graba_de_verdad_partiendo_en_segmentos(ajustes, motor, camara_rtsp):
    """Criterio 1 de punta a punta: RTSP real, ffmpeg real, archivos reales."""
    reales = dataclasses.replace(
        ajustes, segundos_por_segmento=2,
        camaras=(Camara(id=CAMARA_PRUEBA, url=camara_rtsp.url),))
    grabador = Grabador(reales, motor)
    grabador.arrancar_camara(grabador.camaras[0])
    time.sleep(7)
    grabador.cerrar()

    segmentos = retencion.segmentos(reales.directorio_buffer)
    assert len(segmentos) >= 2, "deberia haber partido el video en varios archivos"
    assert all(s.stat().st_size > 0 for s in segmentos)
    # El nombre lleva la marca que puso -strftime, no un contador.
    assert all(ffmpeg.marca_de_segmento(s) for s in segmentos)


def test_los_segmentos_duran_lo_configurado(ajustes, motor, camara_rtsp):
    reales = dataclasses.replace(
        ajustes, segundos_por_segmento=2,
        camaras=(Camara(id=CAMARA_PRUEBA, url=camara_rtsp.url),))
    grabador = Grabador(reales, motor)
    grabador.arrancar_camara(grabador.camaras[0])
    time.sleep(8)
    grabador.cerrar()

    segmentos = retencion.segmentos(reales.directorio_buffer)
    duracion = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(segmentos[0])],
        capture_output=True, text=True, check=True).stdout.strip()
    assert 1.0 <= float(duracion) <= 3.5


def test_el_video_grabado_no_esta_reencodificado(ajustes, motor, camara_rtsp):
    """`-c copy`: el codec que sale tiene que ser el que entro."""
    reales = dataclasses.replace(
        ajustes, camaras=(Camara(id=CAMARA_PRUEBA, url=camara_rtsp.url),))
    grabador = Grabador(reales, motor)
    grabador.arrancar_camara(grabador.camaras[0])
    time.sleep(5)
    grabador.cerrar()

    segmentos = retencion.segmentos(reales.directorio_buffer)
    codec = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(segmentos[0])],
        capture_output=True, text=True, check=True).stdout.strip()
    assert codec == "h264"


def test_si_la_camara_se_apaga_se_detecta_y_se_registra(ajustes, motor, camara_rtsp):
    """Criterio 3 de punta a punta: se corta la emision y el grabador lo anota."""
    reales = dataclasses.replace(
        ajustes, segundos_de_espera_rtsp=3.0, segundos_entre_reintentos=60.0,
        camaras=(Camara(id=CAMARA_PRUEBA, url=camara_rtsp.url),))
    grabador = Grabador(reales, motor)
    grabador.arrancar_camara(grabador.camaras[0])
    time.sleep(3)
    grabador.revisar_camaras()
    assert salud.ultimo(motor, CAMARA_PRUEBA)["estado"] == "ok"

    camara_rtsp.apagar_camara()
    limite = time.monotonic() + 25
    while time.monotonic() < limite:
        grabador.revisar_camaras()
        if salud.ultimo(motor, CAMARA_PRUEBA)["estado"] == "error":
            break
        time.sleep(0.5)
    grabador.cerrar()

    fila = salud.ultimo(motor, CAMARA_PRUEBA)
    assert fila["estado"] == "error"
    assert fila["mensaje"]


# ------------------------------------------------------------------ fabrica
def test_la_fabrica_construye_el_servicio_con_su_motor(monkeypatch, tmp_path):
    """Equivale a create_app del orquestador: un objeto listo, sin estado global."""
    from app import grabador as modulo

    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://x/y")
    monkeypatch.setenv("CAMERAS", "camara-01=rtsp://a/s,camara-02=rtsp://b/s")
    monkeypatch.setenv("VIDEO_DIR", str(tmp_path))

    construido = modulo.crear_grabador()

    assert [e.componente for e in construido.camaras] == ["camara-01", "camara-02"]
    assert construido.ajustes.directorio_buffer == tmp_path
    assert construido.motor is not None          # motor creado, sin conectar


def test_la_fabrica_admite_ajustes_ya_hechos(ajustes):
    from app import grabador as modulo

    construido = modulo.crear_grabador(ajustes)
    assert construido.ajustes is ajustes


# ----------------------------------------------------------- HU-10 los avisos
def test_la_vuelta_del_bucle_incluye_los_avisos(ajustes_con_avisos, motor,
                                                monkeypatch):
    """El reintento del correo es parte del bucle, como el del conteo y el de la
    interpretacion. El camino normal avisa antes, dentro del analisis."""
    pasadas = []
    monkeypatch.setattr(aviso, "procesar_pendientes",
                        lambda m, a, **_k: pasadas.append(1) or [])
    grabador = Grabador(ajustes_con_avisos, motor)

    grabador.revisar_avisos(forzar=True)

    assert pasadas == [1]


def test_el_sondeo_de_avisos_no_se_repite_en_cada_vuelta(ajustes_con_avisos,
                                                         motor, monkeypatch):
    lento = dataclasses.replace(ajustes_con_avisos, segundos_entre_avisos=3600.0)
    pasadas = []
    monkeypatch.setattr(aviso, "procesar_pendientes",
                        lambda m, a, **_k: pasadas.append(1) or [])
    grabador = Grabador(lento, motor)

    grabador.revisar_avisos(forzar=True)
    grabador.revisar_avisos()
    grabador.revisar_avisos()

    assert len(pasadas) == 1


def test_sin_servicio_de_notificaciones_no_se_intenta_avisar(ajustes_con_vlm,
                                                             motor):
    """Una instalacion sin servidor de correo sigue detectando y clasificando."""
    grabador = Grabador(ajustes_con_vlm, motor)

    assert grabador.revisar_avisos(forzar=True) == []
    assert grabador.resumen()["avisa_eventos"] is False


def test_un_fallo_de_mysql_no_para_los_avisos(ajustes_con_avisos, motor,
                                              monkeypatch):
    from sqlalchemy.exc import OperationalError

    def revienta(*_a, **_k):
        raise OperationalError("select 1", {}, Exception("MySQL caido"))

    monkeypatch.setattr(aviso, "procesar_pendientes", revienta)
    grabador = Grabador(ajustes_con_avisos, motor)

    assert grabador.revisar_avisos(forzar=True) == []


def test_el_resumen_cuenta_los_eventos_avisados(ajustes_con_avisos, motor,
                                                servicio_notificaciones):
    from tests.conftest import sembrar_evento

    sembrado = sembrar_evento(motor)
    with motor.begin() as conexion:
        conexion.execute(tablas.evento.update()
                         .where(tablas.evento.c.id == sembrado["evento_id"])
                         .values(severidad="alta"))
    grabador = Grabador(ajustes_con_avisos, motor)

    grabador.revisar_avisos(forzar=True)

    assert grabador.resumen()["eventos_avisados"] == 1
    assert grabador.resumen()["avisa_eventos"] is True
