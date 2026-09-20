"""Modelos mapeados al esquema del apartado 6.5 del documento funcional.

Solo se declaran las tablas que el Sprint 1 necesita hoy. api_token y
configuracion llegan con HU-15 y HU-04; evento, veredicto y modelo_version con
los sprints siguientes. Las tablas existen en la base desde db/01_esquema.sql,
de modo que anadirlas aqui mas adelante no exige tocar el esquema.
"""
from __future__ import annotations

import datetime as dt
import decimal

from sqlalchemy import (BigInteger, Boolean, Date, Enum, ForeignKey, Integer,
                        Numeric, String)
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# DATETIME(6): los milisegundos son los que permiten cruzar la pesada con el
# fotograma del video. Se guarda hora local de planta, la misma que veran las
# camaras, y por eso el requisito de sincronizacion NTP del apartado 6.7.
Marca = MySQLDateTime(fsp=6)


ADMINISTRADOR = "administrador"
SUPERVISOR = "supervisor"
CONSULTA = "consulta"
ROLES = (ADMINISTRADOR, SUPERVISOR, CONSULTA)

# Quien puede escribir. El criterio 2 de HU-15 dice que el rol Consulta no
# cambia estados ni configuraciones, asi que no aparece aqui.
ROLES_QUE_ESCRIBEN = (ADMINISTRADOR, SUPERVISOR)


class Usuario(Base):
    __tablename__ = "usuario"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120))
    correo: Mapped[str] = mapped_column(String(180), unique=True)
    rol: Mapped[str] = mapped_column(Enum("administrador", "supervisor", "consulta"))
    hash_password: Mapped[str] = mapped_column(String(255))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)

    tokens: Mapped[list["ApiToken"]] = relationship(
        back_populates="usuario", foreign_keys="ApiToken.usuario_id")

    def puede_escribir(self) -> bool:
        return self.activo and self.rol in ROLES_QUE_ESCRIBEN

    def es_administrador(self) -> bool:
        return self.activo and self.rol == ADMINISTRADOR


class ApiToken(Base):
    """Token de acceso a la API. HU-15, criterio 4.

    Solo se guarda el hash: quien lea esta tabla no puede usar ningun token.
    La revocacion es inmediata porque cada peticion consulta esta fila.
    """

    __tablename__ = "api_token"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    nombre: Mapped[str] = mapped_column(String(120))
    creado_en: Mapped[dt.datetime] = mapped_column(Marca)
    expira_en: Mapped[dt.datetime] = mapped_column(Marca)
    ultimo_uso_en: Mapped[dt.datetime | None] = mapped_column(Marca, nullable=True)
    revocado_en: Mapped[dt.datetime | None] = mapped_column(Marca, nullable=True)
    revocado_por: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"), nullable=True)

    usuario: Mapped[Usuario] = relationship(back_populates="tokens",
                                            foreign_keys=[usuario_id])

    def vigente(self, ahora: dt.datetime) -> bool:
        return self.revocado_en is None and self.expira_en > ahora


class OrdenDespacho(Base):
    __tablename__ = "orden_despacho"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    numero_orden: Mapped[str] = mapped_column(String(40), unique=True)
    cliente: Mapped[str] = mapped_column(String(180))
    producto: Mapped[str] = mapped_column(String(120))
    peso_esperado_kg: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 2))
    sacos_esperados: Mapped[int] = mapped_column(Integer)
    fecha: Mapped[dt.date] = mapped_column(Date)
    sincronizado_en: Mapped[dt.datetime] = mapped_column(Marca)

    pesadas: Mapped[list["Pesada"]] = relationship(back_populates="orden")


class Pesada(Base):
    """Registro de cada pesada capturada de la bascula. HU-01."""

    __tablename__ = "pesada"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    orden_id: Mapped[int] = mapped_column(ForeignKey("orden_despacho.id"))
    bascula_id: Mapped[str] = mapped_column(String(20))
    # DECIMAL y no coma flotante: la comparacion contra la tolerancia de HU-03
    # tiene que ser exacta, y el criterio 3 de HU-01 exige dos decimales.
    peso_real_kg: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 2))
    fecha_hora: Mapped[dt.datetime] = mapped_column(Marca)
    # HU-06: origen de la ventana del clip. NULL cuando nadie marco el inicio.
    inicio_carga: Mapped[dt.datetime | None] = mapped_column(Marca, nullable=True)
    origen: Mapped[str] = mapped_column(Enum("bascula", "manual"), default="bascula")

    orden: Mapped[OrdenDespacho] = relationship(back_populates="pesadas")
    evento: Mapped["Evento | None"] = relationship(
        back_populates="pesada", uselist=False)


class Configuracion(Base):
    """Tolerancia de peso por tipo de producto. HU-04.

    La RN-01 la define en kg y en porcentaje y manda aplicar la mas restrictiva.
    Esa decision vive aqui, en `tolerancia_efectiva_kg`, y no repartida por los
    modulos que la consulten: HU-03 tendra que comparar contra un solo numero.

    `actualizado_por` y `fecha` guardan el ultimo cambio, que es lo que la
    pantalla muestra. El historial completo esta en la tabla auditoria.
    """

    __tablename__ = "configuracion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    producto: Mapped[str] = mapped_column(String(120), unique=True)
    tolerancia_kg: Mapped[decimal.Decimal] = mapped_column(Numeric(8, 2))
    tolerancia_pct: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2))
    # Mapa de la RN-04. Lo edita HU-10, en el Sprint 4; aqui solo se lee.
    canales_por_severidad: Mapped[dict] = mapped_column(JSON)
    actualizado_por: Mapped[int | None] = mapped_column(
        ForeignKey("usuario.id"), nullable=True)
    fecha: Mapped[dt.datetime] = mapped_column(Marca)

    autor: Mapped[Usuario | None] = relationship()

    def tolerancia_efectiva_kg(
        self, peso_esperado_kg: decimal.Decimal
    ) -> decimal.Decimal:
        """Kg que se pueden perder antes de que la carga sea una discrepancia.

        RN-01: se aplica la mas restrictiva de las dos, es decir la menor. El
        porcentaje solo gana en ordenes pequenas, que es donde 50 kg serian
        demasiado permisivos.
        """
        del_porcentaje = (peso_esperado_kg * self.tolerancia_pct / 100).quantize(
            decimal.Decimal("0.01"), rounding=decimal.ROUND_HALF_UP)
        return min(self.tolerancia_kg, del_porcentaje)


class Carga(Base):
    """Marca de inicio de carga. HU-06.

    El apartado 5.2 dice que el sistema marca el inicio de la ventana de carga, y
    hasta HU-06 nadie lo hacia. Se abre cuando el camion entra a la rampa y la
    consume la pesada que cierra esa carga, que se queda con el instante.
    """

    __tablename__ = "carga"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    orden_id: Mapped[int] = mapped_column(ForeignKey("orden_despacho.id"))
    bascula_id: Mapped[str] = mapped_column(String(20))
    inicio: Mapped[dt.datetime] = mapped_column(Marca)
    consumida_en: Mapped[dt.datetime | None] = mapped_column(Marca, nullable=True)
    pesada_id: Mapped[int | None] = mapped_column(ForeignKey("pesada.id"), nullable=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"), nullable=True)

    orden: Mapped[OrdenDespacho] = relationship()

    def abierta(self) -> bool:
        return self.consumida_en is None


PENDIENTE = "pendiente"
ESTADOS_DE_EVENTO = ("pendiente", "pendiente_analisis", "en_revision",
                     "confirmado", "falso_positivo", "sin_clip")


class Evento(Base):
    """Discrepancia entre el peso real y el esperado. HU-03.

    Una pesada genera como maximo un evento: la clave unica sobre `pesada_id`
    permite reprocesar una pesada sin duplicar nada.

    Las columnas de sprints posteriores nacen en NULL: `sacos_contados` y
    `diferencia_sacos` (HU-07), `personas_detectadas` y `personal_anomalo`
    (HU-08), `severidad` y `descripcion_ia` (HU-09) y `clip_url` (HU-06).
    """

    __tablename__ = "evento"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pesada_id: Mapped[int] = mapped_column(ForeignKey("pesada.id"), unique=True)
    # Con signo: negativa es faltante, que es el caso que motiva el proyecto.
    diferencia_kg: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 2))
    diferencia_pct: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 2))
    sacos_contados: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # HU-07, criterio 3. Con signo, igual que diferencia_kg: negativa es
    # faltante. Se guarda y no se recalcula contra la orden porque la orden se
    # resincroniza desde el ERP y un evento ya investigado no puede cambiar de
    # cifra a posteriori.
    diferencia_sacos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # HU-08, criterio 2: personas que estuvieron en la zona de carga. El detalle
    # por persona vive en persona_en_evento.
    personas_detectadas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # HU-08 y RN-03. NULL mientras el clip no se ha analizado, que no es lo mismo
    # que False: HU-09 no puede confundir "no se miro" con "se miro y estaba
    # bien". Es la condicion que decide si se invoca al modelo de vision-lenguaje.
    personal_anomalo: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    severidad: Mapped[str | None] = mapped_column(
        Enum("baja", "media", "alta"), nullable=True)
    # HU-09. La respuesta del modelo: descripcion, severidad_ia, evidencia y con
    # que modelo se obtuvo. La severidad del evento esta en `severidad` y sale de
    # la RN-04, no de aqui.
    descripcion_ia: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # HU-09 y criterio 3 de HU-12: los fotogramas que explican la carga, ya en
    # MinIO. Lista de {url, motivo, segundo, fotograma}.
    fotogramas_clave: Mapped[list | None] = mapped_column(JSON, nullable=True)
    estado: Mapped[str] = mapped_column(
        Enum(*ESTADOS_DE_EVENTO), default=PENDIENTE)
    clip_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    creado_en: Mapped[dt.datetime] = mapped_column(Marca)

    pesada: Mapped[Pesada] = relationship(back_populates="evento")
    personas: Mapped[list["PersonaEnEvento"]] = relationship(
        back_populates="evento", order_by="PersonaEnEvento.primer_fotograma")
    notificaciones: Mapped[list["Notificacion"]] = relationship(
        back_populates="evento", order_by="Notificacion.creado_en")

    def es_faltante(self) -> bool:
        """Falta producto. Lo contrario, un sobrepeso, tambien es una senal."""
        return self.diferencia_kg < 0


class PersonaEnEvento(Base):
    """Una persona vista en la zona de carga durante el clip. HU-08.

    Lo que esta tabla no tiene es tan importante como lo que tiene: ni foto, ni
    recorte, ni descriptor facial, ni nombre, ni codigo de empleado. La RN-08 y
    el apartado 8 prohiben la identificacion facial y los datos biometricos, y la
    forma de cumplirlo es no tener nada que identificar.

    `id_temporal` es el numero que asigno el rastreador dentro de ese video y
    solo dentro de ese video: el 1 de un evento no tiene ninguna relacion con el
    1 de otro. Por eso la clave unica es (evento_id, id_temporal): no es una
    persona, es una presencia en un clip.
    """

    __tablename__ = "persona_en_evento"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    evento_id: Mapped[int] = mapped_column(ForeignKey("evento.id"))
    id_temporal: Mapped[int] = mapped_column(Integer)
    # Criterio 2: el tiempo de permanencia.
    segundos_en_zona: Mapped[decimal.Decimal] = mapped_column(Numeric(8, 2))
    primer_fotograma: Mapped[int] = mapped_column(Integer)
    ultimo_fotograma: Mapped[int] = mapped_column(Integer)
    creado_en: Mapped[dt.datetime] = mapped_column(Marca)

    evento: Mapped[Evento] = relationship(back_populates="personas")


class Notificacion(Base):
    """Aviso enviado al supervisor por un evento. HU-10.

    Una fila por evento y canal, que es lo que impide que el sondeo del grabador
    mande el mismo correo en cada vuelta. Desde el cambio de alcance del
    18/09/2026 el unico canal es el correo; la columna se conserva porque Slack,
    Teams o SMS entraran con su propia historia y entonces cada uno tendra su
    fila.

    Existe para poder responder meses despues a "se aviso de esto", que es la
    pregunta que se hace cuando el cliente reclama. La respuesta no puede
    depender de que un supervisor conserve el correo.
    """

    __tablename__ = "notificacion"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    evento_id: Mapped[int] = mapped_column(ForeignKey("evento.id"))
    canal: Mapped[str] = mapped_column(Enum("correo"))
    severidad: Mapped[str] = mapped_column(Enum("baja", "media", "alta"))
    # Las direcciones tal como estaban en ese momento: si manana se da de baja a
    # alguien, el registro sigue diciendo que aquel dia lo recibio.
    destinatarios: Mapped[list] = mapped_column(JSON)
    asunto: Mapped[str] = mapped_column(String(300))
    estado: Mapped[str] = mapped_column(Enum("enviada", "fallida"))
    intentos: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Criterio 3: menos de 60 s desde el analisis. NULL cuando no se pudo medir,
    # que no es cero: un cero fingido daria el criterio por cumplido sin haberlo
    # comprobado.
    segundos_desde_analisis: Mapped[decimal.Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True)
    enviada_en: Mapped[dt.datetime | None] = mapped_column(Marca, nullable=True)
    creado_en: Mapped[dt.datetime] = mapped_column(Marca)

    evento: Mapped[Evento] = relationship(back_populates="notificaciones")


class SaludComponente(Base):
    """Historico de verificaciones. La vista v_salud_actual da el ultimo estado."""

    __tablename__ = "salud_componente"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    componente: Mapped[str] = mapped_column(String(60))
    estado: Mapped[str] = mapped_column(Enum("ok", "advertencia", "error"))
    mensaje: Mapped[str | None] = mapped_column(String(500), nullable=True)
    verificado_en: Mapped[dt.datetime] = mapped_column(Marca)


class Auditoria(Base):
    """Tabla de solo insercion. Los triggers del esquema bloquean UPDATE y DELETE."""

    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entidad: Mapped[str] = mapped_column(String(60))
    entidad_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    accion: Mapped[str] = mapped_column(String(60))
    # NULL cuando la accion la ejecuta el sistema y no una persona, que es el
    # caso de toda pesada capturada automaticamente.
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"), nullable=True)
    detalle: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fecha: Mapped[dt.datetime] = mapped_column(Marca)
