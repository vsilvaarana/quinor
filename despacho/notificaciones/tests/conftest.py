"""Fixtures del servicio de notificaciones.

Dos decisiones que sostienen toda la suite.

La primera: el correo se prueba contra un servidor SMTP de verdad, levantado
dentro de las pruebas con aiosmtpd. Un mock de aiosmtplib demostraria que se
llama a una funcion; lo que hay que demostrar es que sale un correo, con su
asunto codificado, sus dos partes y su cabecera de prioridad, y eso solo se ve
del lado del servidor. El buzon de estas pruebas es el mismo papel que hace
mailpit en desarrollo.

La segunda: los destinatarios y el contenido se leen de MySQL de verdad, porque
de eso van los criterios 1 y 2. Un diccionario en memoria no tiene la clave
unica que impide el segundo correo ni el ENUM que rechaza una severidad
inventada, que es justo lo que se quiere comprobar.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import email
import os
import pathlib
import socket
import subprocess

import pytest
from aiosmtpd.controller import Controller
from sqlalchemy import create_engine, insert, text

from app.config import SIN_CIFRAR, Ajustes
from app.tablas import evento, orden_despacho

RAIZ = pathlib.Path(__file__).resolve().parent.parent
ESQUEMA = RAIZ.parent / "api" / "db" / "01_esquema.sql"

URL_PRUEBAS = os.environ.get("TEST_DATABASE_URL", "")
BASE_PRUEBAS = URL_PRUEBAS.rsplit("/", 1)[1].split("?")[0] if URL_PRUEBAS else ""


# ---------------------------------------------------------------- base de datos
def _mysql(*argumentos: str, entrada: str | None = None) -> None:
    base = ["mysql"]
    if sock := os.environ.get("TEST_MYSQL_SOCKET"):
        base.append(f"--socket={sock}")
    base += ["--default-character-set=utf8mb4", "-u",
             os.environ.get("TEST_MYSQL_USER", "root")]
    if clave := os.environ.get("TEST_MYSQL_PASSWORD"):
        base.append(f"-p{clave}")
    subprocess.run(base + list(argumentos), input=entrada, text=True, check=True,
                   capture_output=True)


@pytest.fixture(scope="session")
def esquema() -> None:
    """Crea la base de pruebas desde el DDL del orquestador.

    Este servicio no define esquema: lee y escribe en las tablas que define
    quinor/despacho/api/db/01_esquema.sql, y esa es la que se carga aqui.
    """
    if not URL_PRUEBAS:
        pytest.skip("Sin TEST_DATABASE_URL: no se prueban las lecturas ni el "
                    "registro de notificaciones")
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
        for tabla in ("auditoria", "notificacion", "veredicto",
                      "persona_en_evento", "evento", "carga", "pesada",
                      "orden_despacho", "api_token", "usuario"):
            conexion.execute(text(f"TRUNCATE TABLE {tabla}"))
        conexion.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    yield m
    m.dispose()


# Las contrasenas de estas filas no existen: la columna pide un hash y se le da
# una cadena con la forma de uno. Aqui no se prueba el login, que es HU-14.
HASH = "$2b$12$" + "x" * 53


@pytest.fixture()
def equipo(motor):
    """Los usuarios de HU-15 de los que salen los destinatarios del criterio 1."""
    filas = [
        {"nombre": "Ana Quispe", "correo": "ana@quinor.com.pe",
         "rol": "supervisor", "activo": True},
        {"nombre": "Luis Mendoza", "correo": "luis@quinor.com.pe",
         "rol": "supervisor", "activo": True},
        {"nombre": "Rosa Ccahuana", "correo": "rosa@quinor.com.pe",
         "rol": "administrador", "activo": True},
        {"nombre": "Auditor externo", "correo": "auditor@quinor.com.pe",
         "rol": "consulta", "activo": True},
        {"nombre": "Jorge Ex", "correo": "jorge@quinor.com.pe",
         "rol": "supervisor", "activo": False},
    ]
    # Con SQL directo y no con la tabla de app/tablas.py: esa no declara
    # hash_password a proposito, porque el servicio de notificaciones no tiene
    # nada que hacer con las contrasenas de nadie.
    with motor.begin() as conexion:
        for fila in filas:
            conexion.execute(text(
                "INSERT INTO usuario (nombre, correo, rol, hash_password, "
                "activo) VALUES (:nombre, :correo, :rol, :hash, :activo)"),
                {**fila, "hash": HASH})
    return filas


def _crear_evento(motor, **sobrescrituras) -> int:
    """Una orden, su pesada y el evento de discrepancia, como en produccion."""
    datos = {
        "numero_orden": "OD-2026-0148",
        "cliente": "Andean Grains LLC",
        "producto": "Quinua organica blanca",
        "peso_esperado_kg": 20000.00,
        "sacos_esperados": 400,
        "peso_real_kg": 19600.00,
        "diferencia_kg": -400.00,
        "diferencia_pct": -2.00,
        "sacos_contados": 392,
        "diferencia_sacos": -8,
        "personas_detectadas": 5,
        "personal_anomalo": True,
        "severidad": "alta",
        "descripcion_ia": None,
        "estado": "pendiente",
    }
    datos.update(sobrescrituras)
    ahora = dt.datetime.now().replace(microsecond=0)

    with motor.begin() as conexion:
        orden_id = conexion.execute(insert(orden_despacho).values(
            numero_orden=datos["numero_orden"], cliente=datos["cliente"],
            producto=datos["producto"],
            peso_esperado_kg=datos["peso_esperado_kg"],
            sacos_esperados=datos["sacos_esperados"],
            fecha=ahora.date())).inserted_primary_key[0]
        pesada_id = conexion.execute(text(
            "INSERT INTO pesada (orden_id, bascula_id, peso_real_kg, "
            "fecha_hora) VALUES (:o, 'BAS-01', :p, :f)"),
            {"o": orden_id, "p": datos["peso_real_kg"], "f": ahora}).lastrowid
        evento_id = conexion.execute(insert(evento).values(
            pesada_id=pesada_id,
            diferencia_kg=datos["diferencia_kg"],
            diferencia_pct=datos["diferencia_pct"],
            sacos_contados=datos["sacos_contados"],
            diferencia_sacos=datos["diferencia_sacos"],
            personas_detectadas=datos["personas_detectadas"],
            personal_anomalo=datos["personal_anomalo"],
            severidad=datos["severidad"],
            descripcion_ia=datos["descripcion_ia"],
            estado=datos["estado"],
            creado_en=ahora)).inserted_primary_key[0]
    return int(evento_id)


@pytest.fixture()
def crear_evento(motor):
    def fabrica(**sobrescrituras) -> int:
        return _crear_evento(motor, **sobrescrituras)
    return fabrica


@pytest.fixture()
def evento_id(crear_evento) -> int:
    return crear_evento()


# ------------------------------------------------------------- servidor de correo
class Buzon:
    """Guarda lo que llega, y puede portarse mal a peticion.

    `fallos_temporales` hace que el servidor conteste 451 las primeras veces:
    es un relay saturado, que es exactamente lo que los reintentos tienen que
    sobrevivir. `rechazar` hace que rechace direcciones concretas con 550, que
    es lo que no tiene arreglo por mucho que se insista.
    """

    def __init__(self) -> None:
        self.mensajes: list[email.message.Message] = []
        self.envueltos: list[tuple[str, tuple[str, ...]]] = []
        self.fallos_temporales = 0
        self.rechazar: set[str] = set()
        self.intentos = 0

    async def handle_RCPT(self, server, session, envelope, address,
                          rcpt_options):
        if address in self.rechazar:
            return "550 No such user here"
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server, session, envelope):
        self.intentos += 1
        if self.fallos_temporales > 0:
            self.fallos_temporales -= 1
            return "451 Requested action aborted: local error in processing"
        mensaje = email.message_from_bytes(envelope.original_content)
        self.mensajes.append(mensaje)
        self.envueltos.append((envelope.mail_from, tuple(envelope.rcpt_tos)))
        return "250 Message accepted for delivery"

    # --- ayudas de lectura ---------------------------------------------------
    @property
    def ultimo(self):
        # Devuelve None y no revienta con el buzon vacio: aiosmtpd recorre los
        # miembros del manejador al arrancar, y una propiedad que lanza en ese
        # momento impide que el servidor llegue a levantarse.
        return self.mensajes[-1] if self.mensajes else None

    def asunto(self) -> str:
        cabecera = email.header.decode_header(self.ultimo["Subject"])
        return "".join(
            trozo.decode(codificacion or "utf-8") if isinstance(trozo, bytes)
            else trozo for trozo, codificacion in cabecera)

    def partes(self) -> dict[str, str]:
        salida = {}
        for parte in self.ultimo.walk():
            if parte.get_content_maintype() == "multipart":
                continue
            salida[parte.get_content_subtype()] = parte.get_payload(decode=True).decode(
                parte.get_content_charset() or "utf-8")
        return salida


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def buzon():
    """Un servidor SMTP de verdad, en 127.0.0.1, durante la prueba."""
    caja = Buzon()
    puerto = _puerto_libre()
    controlador = Controller(caja, hostname="127.0.0.1", port=puerto)
    controlador.start()
    caja.puerto = puerto
    try:
        yield caja
    finally:
        controlador.stop()


@pytest.fixture()
def ajustes(buzon) -> Ajustes:
    """Ajustes apuntando al buzon de la prueba.

    La espera entre reintentos baja a casi cero: lo que se comprueba es que se
    reintenta y cuantas veces, no que el reloj funciona.
    """
    return Ajustes(
        database_url=URL_PRUEBAS,
        smtp_host="127.0.0.1", smtp_port=buzon.puerto, cifrado=SIN_CIFRAR,
        timeout_s=10.0, remitente="alertas@quinor.com.pe",
        nombre_del_remitente="QUINOR - Control de despacho",
        dashboard_url="http://dashboard.quinor.local:8050",
        intentos=3, espera_inicial_s=0.01, app_env="test")


@pytest.fixture()
def dormir_sin_esperar():
    """Consume la espera entre reintentos sin gastarla."""
    esperas: list[float] = []

    async def falso(segundos: float) -> None:
        esperas.append(segundos)
        await asyncio.sleep(0)

    falso.esperas = esperas
    return falso
