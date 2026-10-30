"""Guarda de las suites que usan base de datos.

Los conftest de api, grabador y notificaciones hacen DROP DATABASE y TRUNCATE en
cada prueba, por diseno. Lo unico que separa esa orden de la base de produccion
es una variable de entorno, y una variable mal copiada basta para apuntar al
sitio equivocado. Esta guarda hace que apuntar mal sea un error al importar el
conftest y no una base borrada.

Vive en un solo modulo porque tres copias acaban discrepando: la que se relaje
en una suite dejaria esa suite sin proteccion sin que nadie lo note.

No abre ninguna conexion ni resuelve ningun nombre: solo lee la cadena. Asi se
puede probar con la URL del servidor real sin que la prueba llegue a tocarlo.
"""
from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

HOSTS_LOCALES = frozenset({"127.0.0.1", "localhost", "::1"})

# El nombre acaba interpolado en un DROP DATABASE, sin comillas ni parametros:
# un guion, un punto o un espacio no deben poder colarse.
_NOMBRE_SEGURO = re.compile(r"[A-Za-z0-9_]+")

# Parametros de la URL con los que el driver puede cambiar de servidor por la
# puerta de atras aunque el host de la URL sea local.
_PARAMETROS_QUE_CAMBIAN_DE_HOST = ("host", "hostname", "read_default_file",
                                   "read_default_group")


def validar_url_de_pruebas(url: str) -> str:
    """Devuelve el nombre de la base de pruebas, o lanza RuntimeError.

    Exige host local explicito y que el nombre de la base contenga "test". Con
    host vacio no se adivina: el cliente caeria en su valor por defecto, y eso
    es justo lo que no se quiere depender de.

    El mensaje nunca incluye la URL entera: lleva la contrasena.
    """
    try:
        partes = make_url(url)
    except ArgumentError:
        raise RuntimeError(
            "TEST_DATABASE_URL no se puede interpretar como URL de base de "
            "datos. Si la clave lleva [ o ], codificalos como %5B y %5D."
        ) from None

    host = (partes.host or "").lower()
    if host not in HOSTS_LOCALES:
        raise RuntimeError(
            f"TEST_DATABASE_URL apunta al host {partes.host!r}. Las pruebas "
            f"hacen DROP DATABASE y solo corren contra {sorted(HOSTS_LOCALES)}.")

    desvios = [k for k in partes.query if k.lower() in _PARAMETROS_QUE_CAMBIAN_DE_HOST]
    if desvios:
        raise RuntimeError(
            f"TEST_DATABASE_URL trae {desvios}, que pueden sustituir al host "
            "de la URL. Quitalos.")

    base = partes.database or ""
    if "test" not in base.lower():
        raise RuntimeError(
            f"La base {base!r} no contiene 'test'. Las pruebas la borran y la "
            "recrean: el nombre tiene que decir que es desechable.")
    if not _NOMBRE_SEGURO.fullmatch(base):
        raise RuntimeError(
            f"La base {base!r} lleva caracteres fuera de [A-Za-z0-9_]; el nombre "
            "se usa sin comillas en DROP DATABASE.")
    return base


def verificar_comando_mysql(comando: Sequence[str],
                            entorno: Mapping[str, str] | None = None) -> None:
    """Falla si el cliente `mysql` puede acabar hablando con otro servidor.

    Las suites lo lanzan sin host a proposito: el cliente cae en localhost y el
    puerto lo pone MYSQL_TCP_PORT. Aqui se comprueba que nadie lo cambie, ni por
    argumento (--host, -h, y -hNOMBRE pegado) ni por MYSQL_HOST, que el cliente
    lee del entorno aunque el comando no lo diga.
    """
    entorno = os.environ if entorno is None else entorno
    for argumento in comando:
        if argumento.startswith("--host") or (
                argumento.startswith("-h") and not argumento.startswith("--")):
            raise RuntimeError(
                "El cliente mysql de las pruebas no debe recibir --host ni -h: "
                "se conecta al servidor local por defecto.")
    host_del_entorno = entorno.get("MYSQL_HOST", "")
    if host_del_entorno and host_del_entorno.lower() not in HOSTS_LOCALES:
        raise RuntimeError(
            f"MYSQL_HOST={host_del_entorno!r} desviaria al cliente mysql fuera "
            "de la maquina local. Quita la variable para correr las pruebas.")
