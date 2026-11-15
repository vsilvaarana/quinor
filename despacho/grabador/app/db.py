"""Motor de SQLAlchemy del grabador.

Sin estado de modulo: crear_grabador construye el motor y lo pasa. Importar este
modulo no abre ninguna conexion, de modo que las pruebas pueden importar el
grabador sin que exista una base de datos.

El grabador no define esquema: la fuente de verdad sigue siendo
quinor/despacho/api/db/01_esquema.sql. Aqui solo se escribe en salud_componente.
"""
from __future__ import annotations

from sqlalchemy import Engine, create_engine


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
    """pool_pre_ping y pool_recycle: este proceso vive semanas y MySQL cierra
    las conexiones ociosas mucho antes de eso."""
    return create_engine(database_url, pool_pre_ping=True, pool_recycle=RECICLAR_SEGUNDOS,
                         connect_args=LIMITES_DE_CONEXION,
                         pool_size=2, max_overflow=2, future=True)
