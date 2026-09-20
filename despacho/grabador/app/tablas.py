"""Tablas del orquestador que este servicio necesita leer o escribir.

El grabador no define esquema: la fuente de verdad sigue siendo
quinor/despacho/api/db/01_esquema.sql. Aqui solo se declaran las columnas que
HU-06 usa, con SQLAlchemy Core y no con modelos ORM, para dejar claro que este
servicio es un invitado en esas tablas y no su dueno.

De `evento` se tocan `clip_url` y `estado`, que son justo lo que el criterio 2
de HU-06 pide vincular y lo que su criterio 3 pide cambiar, y las tres columnas
del conteo, que son lo que pide el criterio 3 de HU-07.
"""
from __future__ import annotations

from sqlalchemy import (BigInteger, Boolean, Column, Date, Enum, Integer,
                        MetaData, Numeric, String, Table)
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy.dialects.mysql import JSON

metadatos = MetaData()

Marca = MySQLDateTime(fsp=6)

ESTADOS_DE_EVENTO = ("pendiente", "pendiente_analisis", "en_revision",
                     "confirmado", "falso_positivo", "sin_clip")

evento = Table(
    "evento", metadatos,
    Column("id", BigInteger, primary_key=True),
    Column("pesada_id", BigInteger, nullable=False),
    Column("estado", Enum(*ESTADOS_DE_EVENTO), nullable=False),
    Column("clip_url", String(500)),
    # HU-09: el contexto que el apartado 9.2 manda enviar al modelo.
    Column("diferencia_kg", Numeric(10, 2)),
    Column("diferencia_pct", Numeric(6, 2)),
    # HU-07, criterio 3: el conteo y la diferencia con la orden se guardan aqui.
    Column("sacos_contados", Integer),
    Column("diferencia_sacos", Integer),
    # HU-08, criterio 2: cuantas personas estuvieron en la zona de carga.
    Column("personas_detectadas", Integer),
    # HU-08 y RN-03: la senal que decide si HU-09 llama al modelo de
    # vision-lenguaje. NULL mientras no se ha analizado, que no es 0.
    Column("personal_anomalo", Boolean),
    # HU-09. `severidad` sale de la RN-04 y no del modelo; la del modelo va
    # dentro de descripcion_ia como severidad_ia.
    Column("severidad", Enum("baja", "media", "alta")),
    Column("descripcion_ia", JSON),
    Column("fotogramas_clave", JSON),
    Column("creado_en", Marca, nullable=False),
)

# HU-08, criterios 1 y 2. Una fila por persona vista en la zona de carga.
#
# De cada una se guardan un numero de seguimiento que solo vale en este clip, dos
# fotogramas y unos segundos. Nada mas: la RN-08 prohibe la identificacion facial
# y los datos biometricos, y la forma de cumplirla es no tener nada que
# identificar.
persona_en_evento = Table(
    "persona_en_evento", metadatos,
    Column("id", BigInteger, primary_key=True),
    Column("evento_id", BigInteger, nullable=False),
    Column("id_temporal", Integer, nullable=False),
    Column("segundos_en_zona", Numeric(8, 2), nullable=False),
    Column("primer_fotograma", Integer, nullable=False),
    Column("ultimo_fotograma", Integer, nullable=False),
    Column("creado_en", Marca),
)

pesada = Table(
    "pesada", metadatos,
    Column("id", BigInteger, primary_key=True),
    Column("orden_id", Integer, nullable=False),
    Column("bascula_id", String(20), nullable=False),
    Column("peso_real_kg", Numeric(10, 2), nullable=False),
    Column("fecha_hora", Marca, nullable=False),
    # HU-06: origen de la ventana del clip. NULL cuando nadie marco el inicio.
    Column("inicio_carga", Marca),
)

orden_despacho = Table(
    "orden_despacho", metadatos,
    Column("id", Integer, primary_key=True),
    Column("numero_orden", String(40), nullable=False),
    Column("cliente", String(180), nullable=False),
    Column("producto", String(120), nullable=False),
    Column("peso_esperado_kg", Numeric(10, 2), nullable=False),
    # HU-07: contra esto se compara el conteo del video.
    Column("sacos_esperados", Integer, nullable=False),
    Column("fecha", Date, nullable=False),
)

auditoria = Table(
    "auditoria", metadatos,
    Column("id", BigInteger, primary_key=True),
    Column("entidad", String(60), nullable=False),
    Column("entidad_id", BigInteger),
    Column("accion", String(60), nullable=False),
    Column("usuario_id", Integer),
    Column("detalle", JSON),
    Column("fecha", Marca, nullable=False),
)

# HU-10. El grabador no escribe aqui: lo hace el servicio de notificaciones.
# Solo la lee, para saber de que eventos ya salio el correo y no volver a
# pedirlo en cada vuelta del sondeo.
notificacion = Table(
    "notificacion", metadatos,
    Column("id", BigInteger, primary_key=True),
    Column("evento_id", BigInteger, nullable=False),
    Column("canal", Enum("correo"), nullable=False),
    Column("severidad", Enum("baja", "media", "alta"), nullable=False),
    Column("estado", Enum("enviada", "fallida"), nullable=False),
    Column("enviada_en", Marca),
    Column("creado_en", Marca),
)
