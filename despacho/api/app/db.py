"""Motor y sesiones de SQLAlchemy.

Sin estado de modulo: create_app construye el motor y lo guarda en app.state.
Importar este modulo no abre ninguna conexion, de modo que las pruebas pueden
importar la aplicacion sin que exista una base de datos.

El esquema de referencia es db/01_esquema.sql. Los modelos se mapean contra ese
DDL, no lo generan: SQLAlchemy no sabe expresar los triggers que protegen la
auditoria ni las restricciones CHECK que sostienen las reglas de negocio.
"""
from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


# Por que 240 s y los limites de tiempo: la base esta en AWS Lightsail y el
# sistema puede correr en Azure, cuya salida a internet descarta en silencio las
# conexiones TCP ociosas a los 4 minutos. Una conexion del pool que paso ese
# tiempo sin uso queda muerta sin saberlo, y el pre_ping se quedaba colgado sobre
# ella hasta que el dashboard se rendia ("httpx.ReadTimeout" en Usuarios).
# Reciclarlas antes de los 4 minutos evita el caso, y los limites de PyMySQL
# hacen que, si aun asi pasa, falle en segundos y el pool abra otra.
RECICLAR_SEGUNDOS = 240
LIMITES_DE_CONEXION = {"connect_timeout": 10, "read_timeout": 60, "write_timeout": 60}


def crear_motor(database_url: str) -> Engine:
    """Motor con pool_pre_ping: descarta conexiones muertas tras un reinicio de
    MySQL en lugar de entregarlas al primer request del dia."""
    return create_engine(database_url, pool_pre_ping=True, pool_recycle=RECICLAR_SEGUNDOS,
                         connect_args=LIMITES_DE_CONEXION, future=True)


def crear_fabrica_de_sesiones(motor: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=motor, autoflush=False, expire_on_commit=False, class_=Session)
