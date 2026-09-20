"""Fixtures del grabador.

Las pruebas de salud corren contra MySQL de verdad, como las del orquestador: la
tabla salud_componente vive en su esquema y es lo que GET /salud lee.

Las pruebas de grabacion usan ffmpeg de verdad contra un servidor RTSP de
verdad. Una camara simulada con un mock probaria que el codigo llama a
subprocess, no que el video acaba en disco partido en segmentos, que es lo que
pide el criterio 1. Cuando no hay servidor RTSP disponible, esas pruebas se
saltan y lo dicen: es preferible a fingir que pasaron.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import socket
import subprocess
import time

import pytest
from sqlalchemy import create_engine, text

from app.config import Ajustes, Camara

RAIZ = pathlib.Path(__file__).resolve().parent.parent
ESQUEMA = RAIZ.parent / "api" / "db" / "01_esquema.sql"

URL_PRUEBAS = os.environ.get("TEST_DATABASE_URL", "")
BASE_PRUEBAS = URL_PRUEBAS.rsplit("/", 1)[1].split("?")[0] if URL_PRUEBAS else ""

# Binario del servidor RTSP para el simulador de camaras. En el compose es el
# servicio rtsp-server (mediamtx); en local, lo que diga MEDIAMTX_BIN o el PATH.
MEDIAMTX = os.environ.get("MEDIAMTX_BIN") or shutil.which("mediamtx")

CAMARA_PRUEBA = "camara-01"


# ---------------------------------------------------------------- base de datos
def _mysql(*argumentos: str, entrada: str | None = None) -> None:
    base = ["mysql"]
    if sock := os.environ.get("TEST_MYSQL_SOCKET"):
        base.append(f"--socket={sock}")
    base += ["--default-character-set=utf8mb4", "-u", os.environ.get("TEST_MYSQL_USER", "root")]
    if clave := os.environ.get("TEST_MYSQL_PASSWORD"):
        base.append(f"-p{clave}")
    subprocess.run(base + list(argumentos), input=entrada, text=True, check=True,
                   capture_output=True)


@pytest.fixture(scope="session")
def esquema() -> None:
    """Crea la base de pruebas desde el DDL del orquestador.

    El grabador no define esquema: escribe en la tabla que define
    quinor/despacho/api/db/01_esquema.sql, y esa es la que se carga aqui.
    """
    if not URL_PRUEBAS:
        pytest.skip("Sin TEST_DATABASE_URL: no se prueban las escrituras de salud")
    # Sin COLLATE explicito: se deja la del servidor. MySQL 8 pone
    # utf8mb4_0900_ai_ci y MariaDB utf8mb4_general_ci, y las dos ignoran
    # mayusculas y tildes, que es lo unico que el esquema necesita. Fijar la
    # de MySQL 8 dejaba la suite sin poder correr contra MariaDB, que es el
    # motor del hosting.
    _mysql("-e", f"DROP DATABASE IF EXISTS {BASE_PRUEBAS}; "
                 f"CREATE DATABASE {BASE_PRUEBAS} CHARACTER SET utf8mb4;")
    _mysql(BASE_PRUEBAS, entrada=ESQUEMA.read_text(encoding="utf-8"))


@pytest.fixture()
def motor(esquema):
    m = create_engine(URL_PRUEBAS, pool_pre_ping=True, future=True,
                      isolation_level="READ COMMITTED")
    # TRUNCATE y no DELETE porque los triggers de auditoria rechazan el borrado.
    # Es el mismo mecanismo que protege la evidencia en produccion.
    with m.begin() as conexion:
        conexion.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for tabla in ("auditoria", "salud_componente", "veredicto",
                      "notificacion", "persona_en_evento", "evento",
                      "carga", "pesada", "orden_despacho"):
            conexion.execute(text(f"TRUNCATE TABLE {tabla}"))
        conexion.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    yield m
    m.dispose()


# --------------------------------------------------------------------- buffer
@pytest.fixture()
def buffer(tmp_path) -> pathlib.Path:
    carpeta = tmp_path / "video"
    carpeta.mkdir()
    return carpeta


@pytest.fixture()
def ajustes(buffer) -> Ajustes:
    return Ajustes(
        database_url=URL_PRUEBAS or "mysql+pymysql://sin/base",
        camaras=(Camara(id=CAMARA_PRUEBA, url="rtsp://camara/rampa"),),
        directorio_buffer=buffer,
        segundos_por_segmento=2,      # un minuto por prueba seria inaceptable
        horas_de_retencion=72.0,
        segundos_entre_purgas=0.0,
        segundos_entre_reintentos=0.1,
        segundos_entre_clips=0.0,
        camara_de_clips=CAMARA_PRUEBA,
    )


def segmento(carpeta: pathlib.Path, camara: str, marca: str,
             tamano: int = 1024) -> pathlib.Path:
    """Crea un segmento falso con el nombre que pone ffmpeg con -strftime."""
    destino = carpeta / camara
    destino.mkdir(parents=True, exist_ok=True)
    ruta = destino / f"{camara}_{marca}.mkv"
    ruta.write_bytes(b"\0" * tamano)
    return ruta


# ----------------------------------------------------------------- camara RTSP
def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _CamaraSimulada:
    """Servidor RTSP mas una camara publicando, como en el compose."""

    def __init__(self, puerto: int, camara_id: str):
        self.puerto = puerto
        self.camara_id = camara_id
        self.url = f"rtsp://127.0.0.1:{puerto}/{camara_id}"
        self.servidor: subprocess.Popen | None = None
        self.emisor: subprocess.Popen | None = None

    def arrancar(self, tmp_path: pathlib.Path) -> None:
        from sim.camara_sim import construir_comando

        configuracion = tmp_path / "mediamtx.yml"
        # Solo TCP: asi el servidor no reserva los puertos UDP de RTP, que en
        # una maquina compartida suelen estar ocupados. El grabador tambien
        # habla TCP, de modo que la prueba usa el mismo transporte que planta.
        configuracion.write_text(
            f"logLevel: error\nrtspAddress: :{self.puerto}\n"
            "rtspTransports: [tcp]\n"
            "rtmp: no\nhls: no\nwebrtc: no\nsrt: no\napi: no\n"
            "paths:\n  all_others:\n", encoding="utf-8")
        self.servidor = subprocess.Popen(
            [MEDIAMTX, str(configuracion)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _esperar_puerto(self.puerto)
        self.emisor = subprocess.Popen(
            construir_comando(destino=self.url, camara_id=self.camara_id,
                              fps=10, gop=10, resolucion="320x180"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)          # que la camara este emitiendo antes de grabar

    def apagar_camara(self) -> None:
        """Deja el servidor en pie y corta la emision: es lo que ve el grabador
        cuando a una camara se le va la red."""
        if self.emisor is not None:
            self.emisor.terminate()
            self.emisor.wait(timeout=10)
            self.emisor = None

    def parar(self) -> None:
        self.apagar_camara()
        if self.servidor is not None:
            self.servidor.terminate()
            self.servidor.wait(timeout=10)
            self.servidor = None


def _esperar_puerto(puerto: int, espera_s: float = 10.0) -> None:
    limite = time.monotonic() + espera_s
    while time.monotonic() < limite:
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", puerto)) == 0:
                return
        time.sleep(0.2)
    raise RuntimeError(f"El servidor RTSP no levanto en el puerto {puerto}")


@pytest.fixture()
def camara_rtsp(tmp_path):
    """Camara simulada de verdad: servidor RTSP mas emisor."""
    if not MEDIAMTX:
        pytest.skip("Sin servidor RTSP (MEDIAMTX_BIN): no se prueba la grabacion real")
    simulada = _CamaraSimulada(_puerto_libre(), CAMARA_PRUEBA)
    simulada.arrancar(tmp_path)
    yield simulada
    simulada.parar()


# ------------------------------------------------------- HU-06 clips y MinIO
@pytest.fixture()
def s3():
    """Servidor S3 de pruebas.

    MinIO habla S3, asi que el cliente oficial de MinIO funciona igual contra
    este servidor. Lo que se comprueba es que el clip acaba subido y legible, no
    que se llamo a una funcion: un mock del cliente no diria si el objeto quedo
    donde el evento apunta.
    """
    from moto.server import ThreadedMotoServer

    servidor = ThreadedMotoServer(port=0, verbose=False)
    servidor.start()
    puerto = servidor.get_host_and_port()[1]
    yield f"127.0.0.1:{puerto}"
    servidor.stop()


@pytest.fixture()
def ajustes_con_s3(ajustes, s3) -> Ajustes:
    import dataclasses

    return dataclasses.replace(
        ajustes, minio_endpoint=s3, minio_access_key="prueba",
        minio_secret_key="prueba-secreta", minio_bucket="clips", minio_seguro=False)


@pytest.fixture()
def cliente_s3(ajustes_con_s3):
    from app import almacen

    return almacen.crear_cliente(ajustes_con_s3)


def sembrar_evento(motor, *, inicio_carga=None, fecha_hora=None,
                   numero_orden="ORD-2026-0001", estado="pendiente",
                   clip_url=None, sacos_esperados=400) -> dict:
    """Crea orden, pesada y evento como los deja el orquestador.

    El grabador es un invitado en esas tablas: no las crea, las encuentra. Aqui
    se reproduce lo que HU-02, HU-01 y HU-03 habrian dejado.
    """
    import datetime as _dt

    from sqlalchemy import text as _text

    fecha_hora = fecha_hora or _dt.datetime.now().replace(tzinfo=None)
    with motor.begin() as conexion:
        orden_id = conexion.execute(_text(
            "INSERT INTO orden_despacho (numero_orden, cliente, producto, "
            "peso_esperado_kg, sacos_esperados, fecha) VALUES "
            "(:n, 'Andean Foods GmbH', 'Quinua blanca organica', 20000.00, :s, :f)"),
            {"n": numero_orden, "s": sacos_esperados,
             "f": fecha_hora.date()}).lastrowid
        pesada_id = conexion.execute(_text(
            "INSERT INTO pesada (orden_id, bascula_id, peso_real_kg, fecha_hora, "
            "inicio_carga, origen) VALUES (:o, 'BASCULA-01', 19850.00, :f, :i, 'bascula')"),
            {"o": orden_id, "f": fecha_hora, "i": inicio_carga}).lastrowid
        evento_id = conexion.execute(_text(
            "INSERT INTO evento (pesada_id, diferencia_kg, diferencia_pct, estado, "
            "clip_url, creado_en) VALUES (:p, -150.00, -0.75, :e, :c, :f)"),
            {"p": pesada_id, "e": estado, "c": clip_url, "f": fecha_hora}).lastrowid
    return {"evento_id": evento_id, "pesada_id": pesada_id, "orden_id": orden_id,
            "numero_orden": numero_orden, "fecha_hora": fecha_hora,
            "inicio_carga": inicio_carga, "sacos_esperados": sacos_esperados}


# Un JPEG minimo de verdad: cabecera, cuerpo y fin de imagen.
JPEG_DE_PRUEBA = __import__("base64").b64encode(
    bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9")).decode()


# --------------------------------------------------- HU-07 servicio YOLO falso
class _ServicioYolo:
    """Un servicio YOLO de mentira, pero por HTTP de verdad.

    Se prueba contra HTTP y no contra un mock del cliente porque lo que puede
    fallar en planta es justo lo que un mock esconde: el servicio devolviendo
    503 mientras carga el modelo, la clave que no viaja, el timeout. El conteo
    que devuelve si es de mentira: contar es trabajo del servicio YOLO y alli
    tiene sus propias pruebas.
    """

    def __init__(self):
        self.peticiones: list[dict] = []
        self.respuesta: dict = {
            "sacos_contados": 398, "sacos_entrantes": 400, "sacos_salientes": 2,
            "sacos_esperados": None, "diferencia_sacos": None,
            "personas_detectadas": 3, "fotogramas_procesados": 1200,
            "duracion_del_clip_s": 420.0, "segundos_de_proceso": 95.4,
            "modelo": "sacos.pt",
            # HU-08. Tres operarios en la rampa, uno de ellos casi toda la carga.
            "presencia": {
                "cuantas": 3, "maximo_simultaneo": 2, "segundos_totales": 540.0,
                "permanencia_maxima_s": 320.5, "permanencia_media_s": 180.0,
                "zona_completa": False,
                "personas": [
                    {"id_temporal": 1, "segundos_en_zona": 320.5,
                     "primer_fotograma": 10, "ultimo_fotograma": 3200},
                    {"id_temporal": 2, "segundos_en_zona": 150.0,
                     "primer_fotograma": 400, "ultimo_fotograma": 1900},
                    {"id_temporal": 3, "segundos_en_zona": 69.5,
                     "primer_fotograma": 2100, "ultimo_fotograma": 2800},
                ],
            },
            "anomalia_de_personal": False,
            "motivos_de_anomalia": [],
            # HU-09: los fotogramas que explican la carga, en base64.
            "fotogramas_clave": [
                {"fotograma": 120, "segundo": 12.0, "motivo": "saco_saliente",
                 "detalle": "Un saco cruza hacia fuera.",
                 "jpeg_base64": JPEG_DE_PRUEBA},
                {"fotograma": 900, "segundo": 90.0, "motivo": "pico_de_personas",
                 "detalle": "Dos personas a la vez.",
                 "jpeg_base64": JPEG_DE_PRUEBA},
            ],
        }
        self.codigo = 200
        self.clave = ""
        self.demora_s = 0.0
        self._servidor = None
        self._hilo = None
        self.url = ""

    def arrancar(self) -> None:
        import http.server
        import json
        import threading

        servicio = self

        class Manejador(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):          # noqa: N802
                largo = int(self.headers.get("Content-Length", 0))
                cuerpo = json.loads(self.rfile.read(largo) or b"{}")
                servicio.peticiones.append({
                    "ruta": self.path, "cuerpo": cuerpo,
                    "clave": self.headers.get("X-API-Key"),
                })
                if servicio.demora_s:
                    time.sleep(servicio.demora_s)
                if servicio.clave and self.headers.get("X-API-Key") != servicio.clave:
                    self._responder(401, {"detail": "Clave de servicio invalida"})
                    return
                if servicio.codigo != 200:
                    self._responder(servicio.codigo, {"detail": "el modelo no esta cargado"})
                    return
                datos = dict(servicio.respuesta)
                esperados = cuerpo.get("sacos_esperados")
                if esperados is not None:
                    datos["sacos_esperados"] = esperados
                    datos["diferencia_sacos"] = datos["sacos_contados"] - esperados
                self._responder(200, datos)

            def _responder(self, codigo: int, datos: dict):
                cuerpo = json.dumps(datos).encode()
                self.send_response(codigo)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

        self._servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        self.url = f"http://127.0.0.1:{self._servidor.server_address[1]}"
        self._hilo = threading.Thread(target=self._servidor.serve_forever, daemon=True)
        self._hilo.start()

    def parar(self) -> None:
        if self._servidor is not None:
            self._servidor.shutdown()
            self._servidor.server_close()
            self._servidor = None


@pytest.fixture()
def servicio_yolo():
    servicio = _ServicioYolo()
    servicio.arrancar()
    yield servicio
    servicio.parar()


@pytest.fixture()
def ajustes_con_yolo(ajustes_con_s3, servicio_yolo) -> Ajustes:
    import dataclasses

    return dataclasses.replace(ajustes_con_s3, yolo_url=servicio_yolo.url,
                               segundos_entre_conteos=0.0)


# ------------------------------------------ HU-09 servicio de vision-lenguaje
class _ServicioVlm:
    """El servicio de vision-lenguaje, de mentira pero por HTTP de verdad.

    Lo que se comprueba con el no es que describa bien, que es trabajo suyo y
    alli tiene sus pruebas, sino lo de este lado: que los fotogramas suben a
    MinIO y llegan al servicio, que la severidad se guarda, y que un fallo deja
    el evento en Pendiente de analisis.
    """

    def __init__(self):
        self.peticiones: list[dict] = []
        self.respuesta: dict = {
            "invocado": True,
            "motivo_de_invocacion": "diferencia_de_sacos",
            "explicacion": "YOLO confirmo que la diferencia de sacos es -2.",
            "severidad": "alta",
            "motivo_de_severidad": "La diferencia de sacos es -2.",
            "concuerdan": True,
            "analisis": {
                "descripcion": "Un operario retira un saco de la zona de carga.",
                "severidad_ia": "alta",
                "evidencia": ["Se observa un saco saliendo hacia fuera."],
                "confianza": 0.8,
                "modelo": "modelo-de-prueba",
                "proveedor": "stub",
                "intentos": 1,
                "segundos": 3.2,
            },
            "fallo": False,
            "motivo_del_fallo": "",
            "intentos": 1,
        }
        self.codigo = 200
        self.clave = ""
        self.demora_s = 0.0
        self._servidor = None
        self.url = ""

    def arrancar(self) -> None:
        import http.server
        import json
        import threading

        servicio = self

        class Manejador(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):          # noqa: N802
                largo = int(self.headers.get("Content-Length", 0))
                cuerpo = json.loads(self.rfile.read(largo) or b"{}")
                servicio.peticiones.append({
                    "ruta": self.path, "cuerpo": cuerpo,
                    "clave": self.headers.get("X-API-Key"),
                })
                if servicio.demora_s:
                    time.sleep(servicio.demora_s)
                if servicio.clave and self.headers.get("X-API-Key") != servicio.clave:
                    self._responder(401, {"detail": "Clave de servicio invalida"})
                    return
                if servicio.codigo != 200:
                    self._responder(servicio.codigo, {"detail": "provocado"})
                    return
                self._responder(200, servicio.respuesta)

            def _responder(self, codigo: int, datos: dict):
                cuerpo = json.dumps(datos, ensure_ascii=False).encode()
                self.send_response(codigo)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

        self._servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        self.url = f"http://127.0.0.1:{self._servidor.server_address[1]}"
        threading.Thread(target=self._servidor.serve_forever, daemon=True).start()

    def parar(self) -> None:
        if self._servidor is not None:
            self._servidor.shutdown()
            self._servidor.server_close()
            self._servidor = None


@pytest.fixture()
def servicio_vlm():
    servicio = _ServicioVlm()
    servicio.arrancar()
    yield servicio
    servicio.parar()


@pytest.fixture()
def ajustes_con_vlm(ajustes_con_yolo, servicio_vlm) -> Ajustes:
    import dataclasses

    return dataclasses.replace(ajustes_con_yolo, vlm_url=servicio_vlm.url,
                               segundos_entre_interpretaciones=0.0)


# ------------------------------------------- HU-10 servicio de notificaciones
class _ServicioNotificaciones:
    """El servicio de notificaciones, de mentira pero por HTTP de verdad.

    Lo que se comprueba con el no es que el correo salga bien, que es trabajo
    suyo y alli tiene sus pruebas contra un servidor SMTP real, sino lo de este
    lado: que el aviso se pide en cuanto la severidad queda escrita, que viaja
    la medida del criterio 3, y que un servicio caido no tumba el analisis ni
    deja al grabador llamando en bucle.
    """

    def __init__(self):
        self.peticiones: list[dict] = []
        self.respuesta: dict = {
            "evento_id": 0,
            "enviado": True,
            "duplicado": False,
            "severidad": "alta",
            "destinatarios": ["ana@quinor.com.pe", "rosa@quinor.com.pe"],
            "roles": ["supervisor", "administrador"],
            "urgente": True,
            "asunto": "[ALERTA ALTA] Orden ORD-A: faltan 2 sacos",
            "enlace": "http://dashboard:8050/eventos/1",
            "intentos": 1,
            "segundos_de_envio": 0.4,
            "segundos_desde_analisis": None,
            "dentro_del_criterio": None,
            "error": "",
            "rechazados": [],
        }
        self.codigo = 200
        self.clave = ""
        self.demora_s = 0.0
        self._servidor = None
        self.url = ""

    def arrancar(self) -> None:
        import http.server
        import json
        import threading

        servicio = self

        class Manejador(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):          # noqa: N802
                largo = int(self.headers.get("Content-Length", 0))
                cuerpo = json.loads(self.rfile.read(largo) or b"{}")
                servicio.peticiones.append({
                    "ruta": self.path, "cuerpo": cuerpo,
                    "clave": self.headers.get("X-API-Key"),
                })
                if servicio.demora_s:
                    time.sleep(servicio.demora_s)
                if servicio.clave and self.headers.get("X-API-Key") != servicio.clave:
                    self._responder(401, {"detail": "Clave de servicio invalida"})
                    return
                if servicio.codigo != 200:
                    self._responder(servicio.codigo, {"detail": "provocado"})
                    return
                datos = dict(servicio.respuesta)
                datos["evento_id"] = cuerpo.get("evento_id", 0)
                # El servicio devuelve lo que midio quien llamo, que es de donde
                # sale la verificacion del criterio 3.
                desde = cuerpo.get("segundos_desde_analisis")
                if desde is not None:
                    datos["segundos_desde_analisis"] = desde
                    datos["dentro_del_criterio"] = desde <= 60.0
                self._responder(200, datos)

            def _responder(self, codigo: int, datos: dict):
                cuerpo = json.dumps(datos, ensure_ascii=False).encode()
                self.send_response(codigo)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

        self._servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        self.url = f"http://127.0.0.1:{self._servidor.server_address[1]}"
        threading.Thread(target=self._servidor.serve_forever, daemon=True).start()

    def parar(self) -> None:
        if self._servidor is not None:
            self._servidor.shutdown()
            self._servidor.server_close()
            self._servidor = None


@pytest.fixture()
def servicio_notificaciones():
    servicio = _ServicioNotificaciones()
    servicio.arrancar()
    yield servicio
    servicio.parar()


@pytest.fixture()
def ajustes_con_avisos(ajustes_con_vlm, servicio_notificaciones) -> Ajustes:
    import dataclasses

    return dataclasses.replace(ajustes_con_vlm,
                               notificaciones_url=servicio_notificaciones.url,
                               segundos_entre_avisos=0.0)
