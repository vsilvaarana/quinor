"""Tablas del orquestador que este servicio necesita leer o escribir.

El servicio de notificaciones no define esquema: la fuente de verdad sigue
siendo quinor/despacho/api/db/01_esquema.sql. Aqui solo se declaran las columnas
que HU-10 usa, con SQLAlchemy Core y no con modelos ORM, para dejar claro que
este servicio es un invitado en esas tablas y no su dueno.

Lee `usuario` (a quien avisar, criterio 1), `evento`, `pesada` y
`orden_despacho` (orden y diferencia, criterio 2), y escribe `notificacion`, que
es lo que permite responder a "se aviso de esto" meses despues sin depender del
buzon de nadie.
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

SEVERIDADES = ("baja", "media", "alta")

ENVIADA = "enviada"
FALLIDA = "fallida"
ESTADOS_DE_NOTIFICACION = (ENVIADA, FALLIDA)

CORREO = "correo"

# HU-15. De aqui salen los destinatarios del criterio 1.
usuario = Table(
    "usuario", metadatos,
    Column("id", Integer, primary_key=True),
    Column("nombre", String(120), nullable=False),
    Column("correo", String(180), nullable=False),
    Column("rol", Enum("administrador", "supervisor", "consulta"),
           nullable=False),
    Column("activo", Boolean, nullable=False),
)

evento = Table(
    "evento", metadatos,
    Column("id", BigInteger, primary_key=True),
    Column("pesada_id", BigInteger, nullable=False),
    Column("estado", Enum(*ESTADOS_DE_EVENTO), nullable=False),
    Column("diferencia_kg", Numeric(10, 2)),
    Column("diferencia_pct", Numeric(6, 2)),
    Column("sacos_contados", Integer),
    Column("diferencia_sacos", Integer),
    Column("personas_detectadas", Integer),
    Column("personal_anomalo", Boolean),
    # La del evento sale de la RN-04 y es la que decide destinatarios y urgencia.
    Column("severidad", Enum(*SEVERIDADES)),
    Column("descripcion_ia", JSON),
    Column("creado_en", Marca, nullable=False),
)

pesada = Table(
    "pesada", metadatos,
    Column("id", BigInteger, primary_key=True),
    Column("orden_id", Integer, nullable=False),
    Column("peso_real_kg", Numeric(10, 2), nullable=False),
    Column("fecha_hora", Marca, nullable=False),
)

orden_despacho = Table(
    "orden_despacho", metadatos,
    Column("id", Integer, primary_key=True),
    Column("numero_orden", String(40), nullable=False),
    Column("cliente", String(180), nullable=False),
    Column("producto", String(120), nullable=False),
    Column("peso_esperado_kg", Numeric(10, 2), nullable=False),
    Column("sacos_esperados", Integer, nullable=False),
    Column("fecha", Date, nullable=False),
)

# HU-10. Una fila por aviso, con a quien se mando y cuanto tardo.
#
# La clave unica (evento_id, canal) es la que impide que el sondeo del grabador
# mande el mismo correo en cada vuelta: el segundo intento choca con ella y el
# servicio responde "ya estaba avisado" en lugar de volver a escribir al
# supervisor. Es preferible a un `SELECT` previo, que entre dos procesos deja
# una ventana por la que se cuelan dos correos.
notificacion = Table(
    "notificacion", metadatos,
    Column("id", BigInteger, primary_key=True),
    Column("evento_id", BigInteger, nullable=False),
    Column("canal", Enum(CORREO), nullable=False),
    Column("severidad", Enum(*SEVERIDADES), nullable=False),
    Column("destinatarios", JSON, nullable=False),
    Column("asunto", String(300), nullable=False),
    Column("estado", Enum(*ESTADOS_DE_NOTIFICACION), nullable=False),
    Column("intentos", Integer, nullable=False),
    Column("error", String(500)),
    Column("segundos_desde_analisis", Numeric(8, 2)),
    Column("enviada_en", Marca),
    Column("creado_en", Marca),
)
