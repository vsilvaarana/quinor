"""Fixtures compartidas.

Las pruebas corren contra MySQL de verdad, no contra SQLite: el valor del
esquema esta en sus triggers, sus restricciones CHECK y el tipo DECIMAL, y
ninguno de los tres sobrevive a una base sustituta.

La bascula la sustituye un servidor Modbus en proceso con registros fijos. El
simulador de desarrollo alterna a "en movimiento" en cada ciclo, lo que hace
fallar una prueba de cada diez sin que nada este roto; aqui los registros no
cambian, de modo que un fallo siempre significa un fallo.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import pathlib
import socket
import struct
import subprocess
import threading
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.main import create_app

RAIZ = pathlib.Path(__file__).resolve().parent.parent
ESQUEMA = RAIZ / "db" / "01_esquema.sql"

ADMIN_CORREO = "admin@quinor.local"
ADMIN_CLAVE = "clave-admin-de-prueba"
ERP_URL = "http://erp-de-prueba:8001"
SIN_NADIE = 5099          # puerto sin servidor: la conexion se rechaza al instante

URL_PRUEBAS = os.environ["TEST_DATABASE_URL"]
BASE_PRUEBAS = URL_PRUEBAS.rsplit("/", 1)[1].split("?")[0]

ORDEN = {
    "numero_orden": "ORD-2026-0001",
    "cliente": "Andean Foods GmbH",
    "producto": "Quinua blanca organica",
    "peso_esperado_kg": Decimal("20000.00"),
    "sacos_esperados": 400,
    "fecha": dt.date(2026, 9, 14),
}
PESO_FIJO = Decimal("19850.00")     # el que publica la bascula de prueba
CONTADOR_FIJO = 42

# Tolerancias que siembra db/01_esquema.sql (HU-04). Las pruebas las editan, asi
# que se restauran antes de cada una.
PRODUCTO = ORDEN["producto"]                    # Quinua blanca organica
PRODUCTO_ROJA = "Quinua roja organica"
PRODUCTO_NEGRA = "Quinua negra convencional"
TOLERANCIA_KG = Decimal("50.00")
TOLERANCIA_PCT = Decimal("0.50")
TOLERANCIA_PCT_NEGRA = Decimal("0.75")
# El mapa de la RN-04 que siembra el esquema. Lo edita HU-10, en el Sprint 4.
CANALES_SEMBRADOS = json.dumps({"alta": ["sms", "slack"],
                                "media": ["slack", "correo"],
                                "baja": ["correo"]})
TOLERANCIAS_SEMBRADAS = (
    (PRODUCTO, TOLERANCIA_PCT),
    (PRODUCTO_ROJA, TOLERANCIA_PCT),
    (PRODUCTO_NEGRA, TOLERANCIA_PCT_NEGRA),
)

# La misma orden, tal como la publica el ERP (HU-02). Los tipos son los del
# JSON, no los de la base: es justo lo que el cliente tiene que convertir.
ORDEN_ERP = {
    "numero_orden": "ORD-2026-0001",
    "cliente": "Andean Foods GmbH",
    "producto": "Quinua blanca organica",
    "peso_esperado_kg": 20000.0,
    "sacos_esperados": 400,
    "fecha": "2026-09-14",
}


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


@pytest.fixture(scope="session", autouse=True)
def esquema() -> None:
    """Crea la base de pruebas desde el DDL de referencia, no desde los modelos."""
    # Sin COLLATE explicito: se deja la del servidor. MySQL 8 pone
    # utf8mb4_0900_ai_ci y MariaDB utf8mb4_general_ci, y las dos ignoran
    # mayusculas y tildes, que es lo unico que el esquema necesita. Fijar la
    # de MySQL 8 dejaba la suite sin poder correr contra MariaDB, que es el
    # motor del hosting.
    _mysql("-e", f"DROP DATABASE IF EXISTS {BASE_PRUEBAS}; "
                 f"CREATE DATABASE {BASE_PRUEBAS} CHARACTER SET utf8mb4;")
    _mysql(BASE_PRUEBAS, entrada=ESQUEMA.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def motor(esquema):
    # READ COMMITTED y no el REPEATABLE READ por defecto de MySQL: con el
    # snapshot por transaccion, la sesion de prueba no veria lo que la API
    # acaba de confirmar desde su propia conexion.
    m = create_engine(URL_PRUEBAS, pool_pre_ping=True, future=True,
                      isolation_level="READ COMMITTED")
    yield m
    m.dispose()


@pytest.fixture()
def sesion(motor):
    """Sesion limpia por prueba.

    La limpieza usa TRUNCATE y no DELETE porque los triggers de auditoria
    rechazan el borrado. Es el mismo mecanismo que protege la evidencia en
    produccion, asi que la prueba no puede saltarselo con un DELETE.
    """
    Sesion = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)
    with motor.begin() as conexion:
        conexion.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for tabla in ("auditoria", "salud_componente", "veredicto",
                      "notificacion", "persona_en_evento", "evento",
                      "carga", "pesada", "orden_despacho", "api_token", "usuario"):
            conexion.execute(text(f"TRUNCATE TABLE {tabla}"))
        # configuracion se devuelve a los valores sembrados. No basta un UPDATE:
        # alguna prueba borra una fila para simular un producto sin tolerancia,
        # asi que se reinserta. Tambien hay que soltar actualizado_por, que
        # apunta a un usuario que el TRUNCATE de arriba acaba de borrar.
        for producto, pct in TOLERANCIAS_SEMBRADAS:
            conexion.execute(text(
                "INSERT INTO configuracion (producto, tolerancia_kg, tolerancia_pct, "
                "canales_por_severidad) VALUES (:p, :kg, :pct, :canales) "
                "ON DUPLICATE KEY UPDATE tolerancia_kg = :kg, tolerancia_pct = :pct, "
                "actualizado_por = NULL"),
                {"p": producto, "kg": TOLERANCIA_KG, "pct": pct,
                 "canales": CANALES_SEMBRADOS})
        conexion.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    s = Sesion()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def orden(sesion):
    """Orden de despacho local. HU-02 sera la que la traiga del ERP."""
    from app.models import OrdenDespacho

    o = OrdenDespacho(**ORDEN, sincronizado_en=dt.datetime.now())
    sesion.add(o)
    sesion.commit()
    sesion.refresh(o)
    return o


# --------------------------------------------------------------------- bascula
def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _BucleEnHilo:
    """Bucle de eventos propio en un hilo aparte.

    Los servidores de prueba viven aqui y no en el bucle de pytest para que
    tanto las pruebas asincronas como TestClient, que levanta su propio bucle,
    puedan alcanzarlos.
    """

    def __init__(self):
        self.bucle = asyncio.new_event_loop()
        self.hilo = threading.Thread(target=self.bucle.run_forever, daemon=True)
        self.hilo.start()

    def ejecutar(self, corrutina, timeout=10):
        return asyncio.run_coroutine_threadsafe(corrutina, self.bucle).result(timeout)

    def lanzar(self, corrutina):
        return asyncio.run_coroutine_threadsafe(corrutina, self.bucle)

    def parar(self):
        self.bucle.call_soon_threadsafe(self.bucle.stop)
        self.hilo.join(timeout=5)


@pytest.fixture(scope="session")
def hilo_servidores():
    h = _BucleEnHilo()
    yield h
    h.parar()


def _levantar_bascula(hilo, peso: Decimal, contador: int, estable: bool) -> int:
    """Arranca un servidor Modbus con registros fijos y devuelve su puerto."""
    from pymodbus.datastore import (ModbusSequentialDataBlock, ModbusServerContext,
                                    ModbusSlaveContext)
    from pymodbus.server import ModbusTcpServer

    crudo = struct.pack(">f", float(peso))
    registros = [int.from_bytes(crudo[0:2], "big"), int.from_bytes(crudo[2:4], "big"),
                 contador, int(estable)]
    puerto = _puerto_libre()

    async def _arrancar():
        bloque = ModbusSequentialDataBlock(0, registros + [0] * 12)
        contexto = ModbusServerContext(
            slaves={1: ModbusSlaveContext(hr=bloque, zero_mode=True)}, single=False)
        return ModbusTcpServer(contexto, address=("127.0.0.1", puerto))

    servidor = hilo.ejecutar(_arrancar())
    hilo.lanzar(servidor.serve_forever())
    _esperar_puerto(puerto)
    return puerto


@pytest.fixture(scope="session")
def bascula_estable(hilo_servidores):
    """Bascula con peso fijo y estable: 19850.00 kg, contador 42."""
    return _levantar_bascula(hilo_servidores, PESO_FIJO, CONTADOR_FIJO, estable=True)


@pytest.fixture(scope="session")
def bascula_inestable(hilo_servidores):
    """Bascula todavia oscilando: el registro de estado vale 0."""
    return _levantar_bascula(hilo_servidores, Decimal("19000.00"), 7, estable=False)


@pytest.fixture(scope="session")
def bascula_muda(hilo_servidores):
    """Servidor TCP que acepta la conexion y nunca contesta.

    Es el fallo mas incomodo de una bascula: el PLC sigue en pie y acepta el
    socket, pero deja de responder al protocolo. Una conexion rechazada falla al
    instante; esta se queda colgada, y es la que obliga al presupuesto de tiempo
    a existir.
    """
    puerto = _puerto_libre()

    async def _mudo(lector, escritor):
        await asyncio.sleep(600)

    async def _arrancar():
        return await asyncio.start_server(_mudo, "127.0.0.1", puerto)

    servidor = hilo_servidores.ejecutar(_arrancar())
    _esperar_puerto(puerto)
    yield puerto
    servidor.close()


def _esperar_puerto(puerto: int, intentos: int = 50) -> None:
    for _ in range(intentos):
        with socket.socket() as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", puerto)) == 0:
                return
        threading.Event().wait(0.05)
    raise RuntimeError(f"el servidor de prueba no llego a escuchar en {puerto}")


# ----------------------------------------------------------------- aplicacion
@pytest.fixture()
def app(sesion, bascula_estable):
    """Aplicacion configurada por parametro: sin tocar el entorno del proceso."""
    aplicacion = create_app(
        database_url=URL_PRUEBAS,
        admin_email=ADMIN_CORREO,
        admin_password=ADMIN_CLAVE,
        scale_host="127.0.0.1",
        scale_port=bascula_estable,
        erp_base_url=ERP_URL,
    )
    yield aplicacion
    aplicacion.state.cerrar()


def iniciar_sesion(cliente: TestClient, correo: str, clave: str) -> str:
    """Devuelve el token opaco que emite POST /auth/login. HU-15, criterio 4."""
    resp = cliente.post("/auth/login", json={"correo": correo, "clave": clave})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


@pytest.fixture()
def client(app):
    """Cliente autenticado como administrador.

    Entrar en el contexto de TestClient dispara el ciclo de vida, que crea el
    administrador inicial. Desde ahi todo pasa por el flujo real: login, token
    opaco y cabecera. No queda ninguna clave estatica.
    """
    with TestClient(app) as test_client:
        token = iniciar_sesion(test_client, ADMIN_CORREO, ADMIN_CLAVE)
        test_client.headers.update({"X-API-Key": token})
        yield test_client


def _cliente_con_rol(app, client, rol: str, correo: str, clave: str) -> TestClient:
    """Crea un usuario con ese rol usando al administrador, y devuelve su cliente."""
    resp = client.post("/usuarios", json={
        "nombre": f"Usuario {rol}", "correo": correo, "rol": rol, "clave": clave})
    assert resp.status_code == 201, resp.text
    otro = TestClient(app)
    otro.headers.update({"X-API-Key": iniciar_sesion(otro, correo, clave)})
    return otro


@pytest.fixture()
def client_consulta(app, client):
    """Cliente con rol Consulta. Criterio 2: no debe poder escribir nada."""
    return _cliente_con_rol(app, client, "consulta",
                            "consulta@quinor.local", "clave-consulta-123")


@pytest.fixture()
def client_supervisor(app, client):
    return _cliente_con_rol(app, client, "supervisor",
                            "supervisor@quinor.local", "clave-supervisor-123")


@pytest.fixture()
def crear_cliente(sesion):
    """Fabrica de clientes con la bascula que cada prueba necesite.

    Las rutas de fallo (bascula caida, peso inestable) exigen una aplicacion
    apuntando a otro servidor, y la configuracion se inyecta en create_app en
    lugar de manipular variables de entorno.
    """
    creadas, cerrar = [], []

    def _crear(**configuracion) -> TestClient:
        aplicacion = create_app(
            database_url=URL_PRUEBAS, admin_email=ADMIN_CORREO,
            admin_password=ADMIN_CLAVE, erp_base_url=ERP_URL,
            scale_host="127.0.0.1", **configuracion,
        )
        creadas.append(aplicacion)
        c = TestClient(aplicacion)
        c.__enter__()                       # dispara el ciclo de vida
        cerrar.append(c)
        c.headers.update({"X-API-Key": iniciar_sesion(c, ADMIN_CORREO, ADMIN_CLAVE)})
        return c

    yield _crear
    for c in cerrar:
        c.__exit__(None, None, None)
    for aplicacion in creadas:
        aplicacion.state.cerrar()


# -------------------------------------------------------------------- ERP (HU-02)
# El ERP se sustituye con respx y no levantando el stub: las pruebas necesitan
# provocar un 404, una caida de red y una respuesta corrupta a voluntad, y eso
# no se consigue contra un servicio real.
@pytest.fixture()
def erp_sano():
    """El ERP responde y reconoce la orden de prueba."""
    import respx

    with respx.mock(assert_all_called=False) as router:
        router.get(f"{ERP_URL}/salud").respond(200, json={"estado": "OK"})
        router.get(f"{ERP_URL}/ordenes/ORD-2026-0001").respond(200, json=ORDEN_ERP)
        yield router


@pytest.fixture()
def erp_sin_orden():
    """El ERP contesta, pero no reconoce ninguna orden. RN-02: no se registra."""
    import respx

    with respx.mock(assert_all_called=False) as router:
        router.get(f"{ERP_URL}/salud").respond(200, json={"estado": "OK"})
        router.get(url__regex=rf"{ERP_URL}/ordenes/.*").respond(
            404, json={"detail": "Orden no existe en el ERP"})
        yield router


@pytest.fixture()
def erp_caido():
    """El ERP no contesta: incidencia de integracion, no rechazo de la orden."""
    import httpx
    import respx

    with respx.mock(assert_all_called=False) as router:
        router.get(url__regex=rf"{ERP_URL}/.*").mock(
            side_effect=httpx.ConnectError("sin ruta al ERP"))
        yield router
