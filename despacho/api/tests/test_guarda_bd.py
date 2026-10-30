"""La guarda que impide que las suites destructivas apunten al servidor real.

Ninguna prueba de este archivo se conecta a nada: la guarda solo lee la cadena.
La fixture `sin_red` lo hace cumplir, de modo que si alguien la cambia para
resolver el nombre o abrir un socket, la prueba falla en lugar de tocar
vallesol.pe. La guarda es una sola, en `despacho/pruebas_comunes`, y se prueba
aqui una vez; los conftest de grabador y notificaciones importan la misma.
"""
import socket
import subprocess

import pytest

from guarda_bd_pruebas import validar_url_de_pruebas, verificar_comando_mysql

# La URL de produccion tal como la documenta CONTEXTO_DEL_PROYECTO.md, con una
# clave inventada.
URL_REAL = ("mysql+pymysql://vallesol_user_yolo:no-es-la-clave@vallesol.pe:3306/"
            "vallesol_yolo?charset=utf8mb4")


@pytest.fixture()
def sin_red(monkeypatch):
    """Cualquier intento de resolver un nombre, abrir un socket o lanzar un
    proceso hace fallar la prueba."""
    def prohibido(*_a, **_k):
        raise AssertionError("la guarda no debe tocar la red ni lanzar procesos")

    monkeypatch.setattr(socket, "getaddrinfo", prohibido)
    monkeypatch.setattr(socket, "create_connection", prohibido)
    monkeypatch.setattr(socket.socket, "connect", prohibido)
    monkeypatch.setattr(socket.socket, "connect_ex", prohibido)
    monkeypatch.setattr(subprocess, "run", prohibido)
    monkeypatch.setattr(subprocess, "Popen", prohibido)


def test_rechaza_la_url_del_servidor_real_sin_conectarse(sin_red):
    with pytest.raises(RuntimeError, match="vallesol.pe"):
        validar_url_de_pruebas(URL_REAL)


def test_el_error_no_filtra_la_clave(sin_red):
    with pytest.raises(RuntimeError) as error:
        validar_url_de_pruebas(URL_REAL)
    assert "no-es-la-clave" not in str(error.value)


def test_rechaza_vallesol_aunque_la_base_se_llame_test(sin_red):
    url = "mysql+pymysql://u:p@vallesol.pe:3306/quinor_test"
    with pytest.raises(RuntimeError, match="vallesol.pe"):
        validar_url_de_pruebas(url)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "LOCALHOST", "[::1]"])
def test_acepta_los_hosts_locales(sin_red, host):
    url = f"mysql+pymysql://root:@{host}:3307/quinor_test?charset=utf8mb4"
    assert validar_url_de_pruebas(url) == "quinor_test"


@pytest.mark.parametrize("host", [
    "localhost.vallesol.pe",     # empieza como uno local, pero es otro nombre
    "127.0.0.1.vallesol.pe",
    "127.0.0.2",                 # loopback, pero no de la lista
    "192.168.1.20",
    "",                          # sin host: el cliente elegiria por su cuenta
])
def test_rechaza_hosts_que_no_son_locales(sin_red, host):
    with pytest.raises(RuntimeError):
        validar_url_de_pruebas(f"mysql+pymysql://root:@{host}/quinor_test")


@pytest.mark.parametrize("base", ["vallesol_yolo", "quinor", "", "Produccion"])
def test_rechaza_bases_sin_test_en_el_nombre(sin_red, base):
    with pytest.raises(RuntimeError, match="test"):
        validar_url_de_pruebas(f"mysql+pymysql://root:@127.0.0.1:3307/{base}")


def test_test_se_busca_sin_distinguir_mayusculas(sin_red):
    assert validar_url_de_pruebas(
        "mysql+pymysql://root:@127.0.0.1/QUINOR_TEST") == "QUINOR_TEST"


def test_rechaza_nombres_que_no_caben_en_un_drop_database(sin_red):
    with pytest.raises(RuntimeError, match="DROP DATABASE"):
        validar_url_de_pruebas("mysql+pymysql://root:@127.0.0.1/test-a;drop")


@pytest.mark.parametrize("parametro", ["host=vallesol.pe", "unix_socket=/x&host=vallesol.pe",
                                        "read_default_file=/etc/mi.cnf"])
def test_rechaza_parametros_que_sustituyen_al_host(sin_red, parametro):
    with pytest.raises(RuntimeError, match="sustituir al host"):
        validar_url_de_pruebas(
            f"mysql+pymysql://root:@127.0.0.1/quinor_test?{parametro}")


def test_una_cadena_ilegible_falla_sin_mostrarla(sin_red):
    with pytest.raises(RuntimeError, match="no se puede interpretar") as error:
        validar_url_de_pruebas("clave-en-medio-sin-forma")
    assert "clave-en-medio" not in str(error.value)


# ------------------------------------------------------ el cliente mysql
BASE = ["mysql", "--default-character-set=utf8mb4", "-u", "root"]


def test_el_comando_habitual_pasa(sin_red):
    verificar_comando_mysql(BASE + ["-e", "SELECT 1"], entorno={})
    verificar_comando_mysql(BASE + ["--socket=/tmp/mysql.sock", "-pclave", "quinor_test"],
                            entorno={})


@pytest.mark.parametrize("intruso", [["--host=vallesol.pe"], ["--host", "vallesol.pe"],
                                     ["-h", "vallesol.pe"], ["-hvallesol.pe"]])
def test_el_cliente_nunca_recibe_host(sin_red, intruso):
    with pytest.raises(RuntimeError, match="--host ni -h"):
        verificar_comando_mysql(BASE + intruso, entorno={})


def test_mysql_host_del_entorno_tambien_desvia_al_cliente(sin_red):
    with pytest.raises(RuntimeError, match="MYSQL_HOST"):
        verificar_comando_mysql(BASE, entorno={"MYSQL_HOST": "vallesol.pe"})
    verificar_comando_mysql(BASE, entorno={"MYSQL_HOST": "127.0.0.1"})
