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


class FilaDeBandeja(BaseModel):
    """Una fila de la bandeja de eventos. HU-11, criterio 1.

    Deliberadamente mas estrecha que `EventoLeido`: solo lo que la tabla pinta.
    Los campos que salen de la auditoria (la tolerancia que se aplico, la
    ventana que se recorto) no estan aqui porque cuestan una consulta por fila, y
    el criterio 2 da 2 segundos para toda la pantalla. Viven en el detalle,
    `GET /eventos/{id}`, donde se pagan una sola vez.
    """

    id: int
    creado_en: dt.datetime
    numero_orden: str
    cliente: str
    producto: str
    diferencia_kg: Decimal
    diferencia_pct: Decimal
    # En None mientras el clip no se analizo, que no es lo mismo que cero.
    sacos_esperados: int | None = None
    sacos_contados: int | None = None
    diferencia_sacos: int | None = None
    personas_detectadas: int | None = None
    personal_anomalo: bool | None = None
    severidad: str | None = None
    estado: str
    tiene_clip: bool = False


class FiltrosAplicados(BaseModel):
    """Con que se filtro de verdad. HU-11, criterio 3.

    `por_defecto` lista los filtros que puso el sistema y no el usuario. Sin eso,
    un supervisor que entra y ve tres eventos puede creer que son todos los que
    existen, cuando en realidad esta viendo los pendientes de la ultima semana.
    """

    estado: str | None = None
    severidad: str | None = None
    numero_orden: str | None = None
    desde: dt.date | None = None
    hasta: dt.date | None = None
    solo_con_faltante: bool = False
    por_defecto: list[str] = []


class BandejaDeEventos(BaseModel):
    """La pagina completa que pinta la pantalla de HU-11."""

    filas: list[FilaDeBandeja] = []
    total: int
    pagina: int
    tamano: int
    paginas: int
    desde_fila: int
    hasta_fila: int

    # Criterio 2, medido y no supuesto. Si `dentro_del_criterio` viene en False,
    # la pantalla lo dice en lugar de disimularlo.
    segundos: float
    dentro_del_criterio: bool

    filtros: FiltrosAplicados
    resumen: dict = {}


# ------------------------------------------------------------- HU-12 detalle
class EnlaceLeido(BaseModel):
    """Un objeto del almacen listo para el navegador, o el motivo de que no.

    `url` caduca a proposito: sirve para revisar un caso delante de la pantalla,
    no para repartir evidencia por correo. `explicacion` no es un adorno: una
    pantalla que se queda sin video y no dice por que deja al supervisor sin
    saber si el clip se perdio o si es su navegador.
    """

    direccion: str | None = None
    url: str | None = None
    motivo: str | None = None
    explicacion: str | None = None
    minutos: int | None = None
    reproducible: bool = False


class PesosLeidos(BaseModel):
    """HU-12, criterio 1. La parte que existe desde que nace el evento."""

    esperado_kg: Decimal
    real_kg: Decimal
    diferencia_kg: Decimal
    diferencia_pct: Decimal
    tolerancia_aplicada_kg: Decimal | None = None
    # Cuanto se paso de lo que se aceptaba. Convierte "faltan 150 kg" en "faltan
    # 150 donde se toleraban 100", que es lo que dice si el caso esta al borde.
    exceso_sobre_la_tolerancia_kg: Decimal | None = None
    falta_producto: bool


class SacosLeidos(BaseModel):
    """HU-12, criterio 1. El conteo del video de HU-07."""

    esperados: int
    contados: int | None = None
    diferencia: int | None = None
    analizado: bool = False
    # None mientras no hay conteo: un False diria que no cuadran, que es otra cosa.
    cuadran: bool | None = None


class PersonasLeidas(BaseModel):
    """HU-12, criterio 1. Las personas detectadas, con el aviso de la RN-08."""

    detectadas: int | None = None
    personal_anomalo: bool | None = None
    analizado: bool = False
    segundos_totales: Decimal = Decimal("0.00")
    permanencia_maxima_s: Decimal = Decimal("0.00")
    presencias: list[PersonaEnZonaLeida] = []
    nota: str = ("Identificadores temporales del rastreador, validos solo dentro "
                 "de este clip. No hay identificacion facial ni datos biometricos "
                 "(RN-08).")


class AnalisisLeido(BaseModel):
    """HU-12, criterio 1. La descripcion y la severidad. HU-09.

    Las dos severidades juntas: la de la RN-04 manda, la del modelo esta al lado
    para que se vea cuando discrepan, que es de donde sale la revision semanal
    del apartado 9.2.
    """

    severidad: str | None = None
    severidad_ia: str | None = None
    descripcion: str | None = None
    evidencia: list[str] = []
    modelo: str | None = None
    proveedor: str | None = None
    confianza: float | None = None
    intentos: int | None = None
    hay_descripcion: bool = False
    discrepan: bool = False


class FotogramaLeido(BaseModel):
    """HU-12, criterio 3. Un fotograma guardado y por que se guardo.

    `segundo` es su posicion en el clip, que es lo que permite al reproductor
    abrir justo ahi en lugar de dejar al supervisor buscandolo a mano.
    """

    motivo: str
    detalle: str
    segundo: float
    fotograma: int
    es_anomalia: bool = False
    enlace: EnlaceLeido


class ClipLeido(BaseModel):
    """HU-12, criterio 2. El video y la ventana que cubre.

    `motivo_sin_clip` lleva lo que el grabador anoto cuando no pudo recortar: no
    es lo mismo que la camara estuviera caida que que el video ya se hubiera
    purgado del buffer.
    """

    enlace: EnlaceLeido
    desde: dt.datetime | None = None
    hasta: dt.datetime | None = None
    duracion_s: float | None = None
    camara: str | None = None
    cobertura_pct: float | None = None
    completo: bool | None = None
    motivo_sin_clip: str | None = None
    reproducible: bool = False
    # Contenedor del clip. El grabador escribe Matroska a proposito, y Matroska
    # lo reproducen Chrome y Edge pero no Firefox ni Safari: el criterio 2 habla
    # del navegador, asi que la pantalla tiene que poder advertirlo.
    formato: str | None = None


class DetalleDeEvento(BaseModel):
    """Todo lo que la pantalla de HU-12 necesita, en una sola respuesta.

    Mas ancha que `FilaDeBandeja` y a proposito: aqui hay un evento y el
    supervisor ya decidio que le interesa, asi que lo que cuesta una consulta se
    puede pagar porque se paga una vez.
    """

    id: int
    estado: str
    creado_en: dt.datetime

    numero_orden: str
    cliente: str
    producto: str

    pesada_id: int
    bascula_id: str
    pesada_fecha_hora: dt.datetime
    inicio_carga: dt.datetime | None = None

    pesos: PesosLeidos
    sacos: SacosLeidos
    personas: PersonasLeidas
    analisis: AnalisisLeido
    clip: ClipLeido
    fotogramas: list[FotogramaLeido] = []

    # Criterio 3: cual de los fotogramas es el de la anomalia y en que segundo
    # abrir el reproductor para verla sin buscarla.
    anomalia: FotogramaLeido | None = None
    segundo_de_entrada: float = 0.0

    analizado: bool = False
    # Falta peso y los bultos cuadran: la firma de la sustitucion de producto,
    # que es el problema por el que existe este sistema.
    peso_corto_con_sacos_completos: bool = False


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
