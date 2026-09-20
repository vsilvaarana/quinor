"""Motor de SQLAlchemy del grabador.

Sin estado de modulo: crear_grabador construye el motor y lo pasa. Importar este
modulo no abre ninguna conexion, de modo que las pruebas pueden importar el
grabador sin que exista una base de datos.

El grabador no define esquema: la fuente de verdad sigue siendo
quinor/despacho/api/db/01_esquema.sql. Aqui solo se escribe en salud_componente.
"""
from __future__ import annotations

from sqlalchemy import Engine, create_engine


def crear_motor(database_url: str) -> Engine:
    """pool_pre_ping y pool_recycle: este proceso vive semanas y MySQL cierra
    las conexiones ociosas mucho antes de eso."""
    return create_engine(database_url, pool_pre_ping=True, pool_recycle=3600,
                         pool_size=2, max_overflow=2, future=True)
