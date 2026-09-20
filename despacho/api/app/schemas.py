"""Contratos de entrada y salida de la API."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Rol = Literal["administrador", "supervisor", "consulta"]


# ------------------------------------------------------------ HU-01 pesadas
class CapturarPesada(BaseModel):
    """Cierre de una carga. HU-01.

    Sin peso_real_kg el orquestador lo lee de la bascula y el origen queda en
    'bascula'. Con peso_real_kg el supervisor lo esta introduciendo a mano y el
    origen queda en 'manual', de modo que la diferencia entre una lectura
    automatica y una anotacion humana no se pierde en el historial.
    """

    numero_orden: str = Field(min_length=1, max_length=40, examples=["ORD-2026-0001"])
    bascula_id: str | None = Field(default=None, max_length=20)
    peso_real_kg: Decimal | None = Field(
        default=None, ge=0, max_digits=12,
        description="Solo para registro manual. Se redondea a dos decimales con HALF_UP.")
    motivo_manual: str | None = Field(default=None, max_length=200)


class PesadaLeida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    numero_orden: str
    cliente: str
    producto: str
    bascula_id: str
    peso_real_kg: Decimal
    peso_esperado_kg: Decimal
    fecha_hora: dt.datetime
    origen: str


# ------------------------------------------------------------ HU-02 ordenes
class OrdenLeida(BaseModel):
    """Orden de despacho tal como queda en la copia local. HU-02."""

    model_config = ConfigDict(from_attributes=True)

    numero_orden: str
    cliente: str
    producto: str
    peso_esperado_kg: Decimal
    sacos_esperados: int
    fecha: dt.date
    sincronizado_en: dt.datetime


# ------------------------------------------------- HU-15 usuarios y tokens
class Credenciales(BaseModel):
    correo: str = Field(min_length=3, max_length=180, examples=["admin@quinor.local"])
    clave: str = Field(min_length=1, max_length=200)


class CrearUsuario(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    correo: str = Field(min_length=3, max_length=180)
    rol: Rol
    clave: str = Field(min_length=8, max_length=200,
                       description="Minimo 8 caracteres. bcrypt solo considera los 72 primeros bytes.")


class CambiarRol(BaseModel):
    rol: Rol


class CambiarActivacion(BaseModel):
    activo: bool


class CambiarClave(BaseModel):
    clave: str = Field(min_length=8, max_length=200)


class UsuarioLeido(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    correo: str
    rol: str
    activo: bool


class SolicitarToken(BaseModel):
    nombre: str = Field(default="token", min_length=1, max_length=120,
                        examples=["Laptop de rampa 1"])
    ttl_horas: float | None = Field(default=None, gt=0, le=8760,
                                    description="Por defecto, el configurado en TOKEN_TTL_HOURS.")


class TokenLeido(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    creado_en: dt.datetime
    expira_en: dt.datetime
    ultimo_uso_en: dt.datetime | None = None
    revocado_en: dt.datetime | None = None


class TokenEmitido(BaseModel):
    """El valor en claro viaja una sola vez: aqui. Despues solo existe su hash."""

    token: str
    aviso: str = "Guardalo ahora: este valor no se vuelve a mostrar."
    detalle: TokenLeido
    usuario: UsuarioLeido


# ------------------------------------------------- HU-06 marca de carga
class AbrirCarga(BaseModel):
    """Marca el inicio de la carga de una orden. Apoyo del criterio 1 de HU-06."""

    bascula_id: str | None = Field(default=None, max_length=20)


class CargaLeida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    numero_orden: str
    bascula_id: str
    inicio: dt.datetime
    consumida_en: dt.datetime | None = None
    pesada_id: int | None = None
    duracion_s: float | None = None


# ------------------------------------------------- HU-03 eventos
EstadoEvento = Literal["pendiente", "pendiente_analisis", "en_revision",
                       "confirmado", "falso_positivo", "sin_clip"]


class EventoLeido(BaseModel):
    """Evento de discrepancia. HU-03, criterio 2.

    Lleva la orden, los dos pesos y la diferencia en kg y en porcentaje: con eso
    el supervisor decide si baja a la rampa sin abrir otra pantalla.
    """

    id: int
    estado: str
    creado_en: dt.datetime

    numero_orden: str
    cliente: str
    producto: str

    peso_esperado_kg: Decimal
    peso_real_kg: Decimal
    diferencia_kg: Decimal
    diferencia_pct: Decimal
    tolerancia_aplicada_kg: Decimal | None = None

    pesada_id: int
    bascula_id: str
    pesada_fecha_hora: dt.datetime
    # HU-06: ventana del clip. inicio_carga en None significa que nadie marco el
    # inicio y el clip cubre solo los 5 minutos previos al cierre.
    inicio_carga: dt.datetime | None = None
    clip_desde: dt.datetime | None = None
    clip_hasta: dt.datetime | None = None
    # HU-07: el conteo del video y su diferencia con la orden. En None mientras
    # el clip no se ha analizado, que no es lo mismo que un conteo de cero.
    sacos_contados: int | None = None
    sacos_esperados: int | None = None
    diferencia_sacos: int | None = None
    # HU-08: cuantas personas estuvieron en la zona de carga y si su presencia
    # llamo la atencion. El detalle por persona esta en /eventos/{id}/personas.
    personas_detectadas: int | None = None
    personal_anomalo: bool | None = None
    # HU-09. `severidad` sale de la RN-04, que es una regla escrita con umbrales
    # exactos; la del modelo vive dentro de `descripcion_ia` como severidad_ia.
    severidad: str | None = None
    descripcion_ia: dict | None = None
    fotogramas_clave: list[dict] = []
    clip_url: str | None = None


class PersonaEnZonaLeida(BaseModel):
    """Una persona vista en la zona de carga durante el clip. HU-08.

    Esto es todo lo que el sistema sabe de ella. El identificador lo puso el
    rastreador, vale solo dentro de ese clip y no se puede cruzar con otro video
    ni con ninguna lista de personal: la RN-08 prohibe la identificacion facial y
    los datos biometricos.
    """

    id_temporal: int
    segundos_en_zona: Decimal
    primer_fotograma: int
    ultimo_fotograma: int


class PresenciaLeida(BaseModel):
    """Lo que HU-08 pide poder consultar de un evento. Criterio 2."""

    evento_id: int
    cuantas: int
    segundos_totales: Decimal
    permanencia_maxima_s: Decimal
    personal_anomalo: bool | None = None
    personas: list[PersonaEnZonaLeida] = []
    # El aviso que acompana al dato en cualquier pantalla donde se muestre.
    nota: str = ("Identificadores temporales del rastreador, validos solo dentro "
                 "de este clip. No hay identificacion facial ni datos biometricos "
                 "(RN-08).")


class NotificacionLeida(BaseModel):
    """Un aviso enviado por un evento. HU-10."""

    id: int
    canal: str
    severidad: str
    destinatarios: list[str] = []
    asunto: str
    estado: str
    intentos: int
    error: str | None = None
    # Criterio 3. NULL cuando no se pudo medir, que no es cero.
    segundos_desde_analisis: Decimal | None = None
    dentro_del_criterio: bool | None = None
    enviada_en: dt.datetime | None = None
    creado_en: dt.datetime


class AvisoDelEvento(BaseModel):
    """Lo que HU-10 deja consultar de un evento.

    `avisado` es lo primero que se mira: responde a "se aviso de esto", que es
    la pregunta que se hace cuando el cliente reclama meses despues. Un aviso
    fallido cuenta como no avisado, porque nadie lo recibio.
    """

    evento_id: int
    avisado: bool
    severidad: str | None = None
    notificaciones: list[NotificacionLeida] = []


class PesadaRegistrada(PesadaLeida):
    """Respuesta de POST /pesadas desde HU-03.

    Incluye el evento si la carga se salio de la tolerancia. Devolverlo en la
    misma respuesta es lo que hace que el aviso llegue en el momento y no cuando
    alguien decida mirar el dashboard.

    `evaluada` distingue las dos razones por las que puede no haber evento: la
    carga entro dentro de la tolerancia, o no se pudo comparar. Sin esa
    diferencia, un fallo de configuracion se leeria como una carga limpia.
    """

    evento: EventoLeido | None = None
    evaluada: bool = True
    motivo_sin_evaluar: str | None = None


# ------------------------------------------------- HU-04 tolerancias
class ToleranciaLeida(BaseModel):
    """Tolerancia configurada de un producto. HU-04."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    producto: str
    tolerancia_kg: Decimal
    tolerancia_pct: Decimal
    # Mapa de la RN-04. Se muestra, pero lo edita HU-10 en el Sprint 4.
    canales_por_severidad: dict
    actualizado_por: int | None = None
    actualizado_por_nombre: str | None = None
    fecha: dt.datetime


class EditarTolerancia(BaseModel):
    """Los dos campos son opcionales por separado.

    Ajustar solo el porcentaje no obliga a reescribir los kg, que es como se usa
    en la practica. Enviar el cuerpo vacio no es un cambio y se rechaza.

    Los limites de rango no se repiten aqui: viven en app.configuracion.validar,
    que es tambien por donde pasa cualquier otro llamador. Duplicarlos dejaria
    dos verdades que tarde o temprano dejan de coincidir.
    """

    tolerancia_kg: Decimal | None = Field(
        default=None,
        description="Kg de diferencia admitidos. Se redondea a dos decimales.")
    tolerancia_pct: Decimal | None = Field(
        default=None,
        description="Porcentaje del peso esperado. Se aplica el mas restrictivo de los dos.")


class ToleranciaAplicada(BaseModel):
    """Cual de las dos tolerancias manda para un peso concreto. RN-01."""

    producto: str
    peso_esperado_kg: Decimal
    tolerancia_kg: Decimal
    tolerancia_pct: Decimal
    equivalente_del_pct_kg: Decimal
    tolerancia_efectiva_kg: Decimal
    manda: Literal["kg", "porcentaje"]


class CambioDeTolerancia(BaseModel):
    """Una linea del historial de auditoria de configuracion. Criterio 3."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    fecha: dt.datetime
    usuario_id: int | None = None
    usuario_nombre: str | None = None
    detalle: dict | None = None


# ---------------------------------------------------------------- salud
class ComponenteSalud(BaseModel):
    componente: str
    estado: str
    mensaje: str | None = None
    verificado_en: dt.datetime | None = None


class RespuestaSalud(BaseModel):
    estado: str
    componentes: list[ComponenteSalud]
