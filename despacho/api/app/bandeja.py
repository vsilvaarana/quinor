"""Bandeja de eventos del supervisor. HU-11.

Como supervisor de despacho, quiero ver la lista de eventos con filtros por
fecha, orden, severidad y estado, para encontrar rapidamente los casos que debo
atender.

Criterios de aceptacion:
  1. La tabla muestra ID, fecha, orden, diferencia, severidad y estado.
  2. Los filtros se combinan y la tabla se actualiza en menos de 2 s.
  3. Por defecto se muestran los eventos Pendientes de los ultimos 7 dias.

Por que este modulo existe aparte de app/eventos.py
---------------------------------------------------
`eventos.py` es el caso de uso de HU-03: evaluar una pesada y crear el evento.
Esto es lo contrario, leer muchos a la vez, y tiene una exigencia que el otro no
tiene: el criterio 2 pone un techo de 2 segundos.

El listado que existia hasta ahora armaba cada fila con cuatro consultas: la
pesada, la orden y dos lecturas de auditoria para recuperar la tolerancia que se
aplico y la ventana del clip. Con 50 eventos son mas de doscientas consultas, y
con 500 pasan de dos mil. Hoy no se nota porque hay pocos datos; con un ano de
operacion, esa pantalla deja de abrir.

Aqui se hace al reves: **una sola consulta** con sus JOIN, que devuelve
exactamente las columnas que la tabla pinta y ninguna mas. Los campos que salen
de la auditoria (la tolerancia aplicada, la ventana recortada) no estan, y es a
proposito: son del detalle, que es `GET /eventos/{id}`, y es ahi donde cuestan
una consulta y se pagan una sola vez.

Hay una prueba que cuenta las consultas que se ejecutan, de modo que si alguien
vuelve a meter un acceso por fila, la suite lo dice antes de que llegue a
produccion.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import time
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models import Evento, OrdenDespacho, Pesada

# Criterio 3: "por defecto se muestran los eventos Pendientes de los ultimos 7
# dias". Son dos defectos distintos y conviene no mezclarlos: el estado y la
# ventana de tiempo.
ESTADO_POR_DEFECTO = "pendiente"
DIAS_POR_DEFECTO = 7

# Criterio 2. El limite es del criterio, no una preferencia: por encima de esto
# la pantalla deja de cumplir y hay que decirlo en lugar de disimularlo.
SEGUNDOS_DEL_CRITERIO = 2.0

# Cuantas filas caben en una pagina. Cincuenta es lo que entra en una pantalla
# sin desplazarse mucho, y lo que una consulta devuelve sin despeinarse.
TAMANO_DE_PAGINA = 50
TAMANO_MAXIMO = 200

ESTADOS = ("pendiente", "pendiente_analisis", "en_revision", "confirmado",
           "falso_positivo", "sin_clip")
SEVERIDADES = ("baja", "media", "alta")

# Estados que el supervisor todavia tiene que atender. Sirve para el contador de
# la cabecera: cuantos de los que salen siguen esperando a alguien.
ABIERTOS = ("pendiente", "pendiente_analisis", "en_revision")


class FiltroInvalido(ValueError):
    """Un filtro que la base rechazaria o que no significa nada.

    Se valida antes de consultar para devolver un mensaje que diga que corregir,
    en lugar de un error de motor que no ayuda a nadie.
    """


@dataclasses.dataclass(frozen=True)
class Filtros:
    """Lo que el supervisor pidio ver.

    `aplicados_por_defecto` recuerda si el estado y la ventana los eligio el
    usuario o los puso el criterio 3. La pantalla lo necesita para poder decir
    "estas viendo lo de siempre" en lugar de dejar al supervisor creyendo que
    esos son todos los eventos que existen.
    """

    estado: str | None = None
    severidad: str | None = None
    numero_orden: str | None = None
    desde: dt.date | None = None
    hasta: dt.date | None = None
    # Solo los que tienen diferencia de sacos distinta de cero. Es el filtro que
    # separa "falta producto" de "la bascula se movio 60 kg".
    solo_con_faltante: bool = False
    pagina: int = 1
    tamano: int = TAMANO_DE_PAGINA
    aplicados_por_defecto: tuple[str, ...] = ()

    @property
    def desplazamiento(self) -> int:
        return (self.pagina - 1) * self.tamano


@dataclasses.dataclass(frozen=True)
class FilaDeEvento:
    """Una fila de la tabla. Criterio 1.

    Las columnas que el criterio nombra (ID, fecha, orden, diferencia, severidad
    y estado) mas las que el supervisor necesita para decidir sin abrir el
    detalle: el cliente, los sacos y si la presencia de personal llamo la
    atencion.
    """

    id: int
    creado_en: dt.datetime
    numero_orden: str
    cliente: str
    producto: str
    diferencia_kg: Decimal
    diferencia_pct: Decimal
    # En None mientras el clip no se ha analizado, que no es lo mismo que cero.
    sacos_esperados: int | None
    sacos_contados: int | None
    diferencia_sacos: int | None
    personas_detectadas: int | None
    personal_anomalo: bool | None
    severidad: str | None
    estado: str
    tiene_clip: bool

    @property
    def falta_producto(self) -> bool:
        """Diferencia negativa en el peso. Lo contrario, un sobrepeso, tambien
        es una senal, pero no la que motiva el proyecto."""
        return self.diferencia_kg < 0


@dataclasses.dataclass(frozen=True)
class Pagina:
    """Lo que la pantalla necesita para pintarse entera."""

    filas: tuple[FilaDeEvento, ...]
    total: int
    pagina: int
    tamano: int
    # Criterio 2: cuanto tardo de verdad la consulta, medido aqui y no supuesto.
    segundos: float
    filtros: Filtros

    @property
    def paginas(self) -> int:
        if self.total == 0:
            return 1
        return (self.total + self.tamano - 1) // self.tamano

    @property
    def desde_fila(self) -> int:
        return 0 if self.total == 0 else self.filtros.desplazamiento + 1

    @property
    def hasta_fila(self) -> int:
        return min(self.filtros.desplazamiento + len(self.filas), self.total)

    @property
    def dentro_del_criterio(self) -> bool:
        return self.segundos <= SEGUNDOS_DEL_CRITERIO

    @property
    def abiertos(self) -> int:
        """De los que se ven, cuantos siguen esperando a alguien."""
        return sum(1 for f in self.filas if f.estado in ABIERTOS)


def resolver_filtros(
    estado: str | None = None,
    severidad: str | None = None,
    numero_orden: str | None = None,
    desde: dt.date | None = None,
    hasta: dt.date | None = None,
    solo_con_faltante: bool = False,
    pagina: int = 1,
    tamano: int = TAMANO_DE_PAGINA,
    sin_defectos: bool = False,
    hoy: dt.date | None = None,
) -> Filtros:
    """Normaliza lo que llego y aplica el criterio 3 cuando falta.

    `sin_defectos` existe para los clientes que quieren ver todo el historico y
    saben lo que piden, como el reporte de HU-14. Es explicito a proposito: que
    una pantalla muestre menos de lo que hay tiene que ser una decision visible,
    no un efecto secundario.
    """
    hoy = hoy or dt.date.today()

    if estado is not None and estado not in ESTADOS:
        raise FiltroInvalido(
            f"Estado '{estado}' no existe. Los que hay: {', '.join(ESTADOS)}.")
    if severidad is not None and severidad not in SEVERIDADES:
        raise FiltroInvalido(
            f"Severidad '{severidad}' no existe. Las que hay: "
            f"{', '.join(SEVERIDADES)}.")
    if desde and hasta and desde > hasta:
        raise FiltroInvalido(
            "La fecha inicial es posterior a la final. Si se invirtieran en "
            "silencio, la tabla mostraria un rango que nadie pidio.")
    if pagina < 1:
        raise FiltroInvalido("La pagina empieza en 1.")
    if not 1 <= tamano <= TAMANO_MAXIMO:
        raise FiltroInvalido(
            f"El tamano de pagina va entre 1 y {TAMANO_MAXIMO}.")

    puestos = []
    if not sin_defectos:
        # Criterio 3. Cada defecto se aplica solo si quien llama no dijo nada de
        # ese campo: pedir "todos los confirmados" no debe arrastrar la ventana
        # de 7 dias sin avisar.
        if estado is None and severidad is None:
            estado = ESTADO_POR_DEFECTO
            puestos.append("estado")
        if desde is None and hasta is None:
            desde = hoy - dt.timedelta(days=DIAS_POR_DEFECTO)
            puestos.append("desde")

    return Filtros(
        estado=estado,
        severidad=severidad,
        numero_orden=(numero_orden or "").strip() or None,
        desde=desde,
        hasta=hasta,
        solo_con_faltante=solo_con_faltante,
        pagina=pagina,
        tamano=tamano,
        aplicados_por_defecto=tuple(puestos),
    )


def _consulta_base(filtros: Filtros) -> Select:
    """El FROM y el WHERE, compartidos por el conteo y por la pagina.

    Los dos tienen que filtrar igual: si el total contara una cosa y las filas
    otra, el paginador mandaria al supervisor a paginas vacias.
    """
    consulta = (
        select(Evento)
        .join(Pesada, Evento.pesada_id == Pesada.id)
        .join(OrdenDespacho, Pesada.orden_id == OrdenDespacho.id))

    if filtros.estado:
        consulta = consulta.where(Evento.estado == filtros.estado)
    if filtros.severidad:
        consulta = consulta.where(Evento.severidad == filtros.severidad)
    if filtros.numero_orden:
        # Coincidencia parcial: el supervisor recuerda "0148", no la orden
        # entera. El indice unico de numero_orden no sirve para un LIKE con
        # comodin delante, pero este filtro siempre viaja junto a la ventana de
        # fechas, que es la que acota de verdad.
        consulta = consulta.where(
            OrdenDespacho.numero_orden.like(f"%{filtros.numero_orden}%"))
    if filtros.desde:
        consulta = consulta.where(
            Evento.creado_en >= dt.datetime.combine(filtros.desde, dt.time.min))
    if filtros.hasta:
        # Hasta el final de ese dia: un supervisor que pone "hasta el 3" espera
        # ver lo del 3, no lo anterior a su medianoche.
        consulta = consulta.where(
            Evento.creado_en <= dt.datetime.combine(filtros.hasta, dt.time.max))
    if filtros.solo_con_faltante:
        consulta = consulta.where(Evento.diferencia_sacos.is_not(None),
                                  Evento.diferencia_sacos != 0)
    return consulta


def listar(sesion: Session, filtros: Filtros) -> Pagina:
    """Una pagina de la bandeja. Dos consultas en total: el conteo y las filas.

    El orden es el mas reciente primero, desempatado por id. Sin el desempate,
    dos eventos creados en el mismo microsegundo podrian salir en distinto orden
    entre una pagina y la siguiente, y alguno se veria dos veces o ninguna.
    """
    comienzo = time.monotonic()

    total = sesion.scalar(
        select(func.count()).select_from(_consulta_base(filtros).subquery()))

    columnas = (
        _consulta_base(filtros)
        .with_only_columns(
            Evento.id, Evento.creado_en, Evento.diferencia_kg,
            Evento.diferencia_pct, Evento.sacos_contados,
            Evento.diferencia_sacos, Evento.personas_detectadas,
            Evento.personal_anomalo, Evento.severidad, Evento.estado,
            Evento.clip_url,
            OrdenDespacho.numero_orden, OrdenDespacho.cliente,
            OrdenDespacho.producto, OrdenDespacho.sacos_esperados)
        .order_by(Evento.creado_en.desc(), Evento.id.desc())
        .limit(filtros.tamano)
        .offset(filtros.desplazamiento))

    filas = tuple(
        FilaDeEvento(
            id=f.id,
            creado_en=f.creado_en,
            numero_orden=f.numero_orden,
            cliente=f.cliente,
            producto=f.producto,
            diferencia_kg=f.diferencia_kg,
            diferencia_pct=f.diferencia_pct,
            sacos_esperados=f.sacos_esperados,
            sacos_contados=f.sacos_contados,
            diferencia_sacos=f.diferencia_sacos,
            personas_detectadas=f.personas_detectadas,
            personal_anomalo=(None if f.personal_anomalo is None
                              else bool(f.personal_anomalo)),
            severidad=f.severidad,
            estado=f.estado,
            tiene_clip=bool(f.clip_url),
        )
        for f in sesion.execute(columnas).all())

    return Pagina(filas=filas, total=int(total or 0), pagina=filtros.pagina,
                  tamano=filtros.tamano,
                  segundos=time.monotonic() - comienzo, filtros=filtros)


def resumen(pagina: Pagina) -> dict:
    """Las cifras de la cabecera, calculadas sobre lo que se esta viendo.

    Son de la pagina y no del total a proposito: contar sobre todo el filtro
    exigiria otras consultas de agregacion, y el criterio 2 manda. Quien quiera
    el total de cada cosa tiene los filtros para pedirlo.
    """
    return {
        "en_pantalla": len(pagina.filas),
        "total": pagina.total,
        "abiertos": pagina.abiertos,
        "con_faltante_de_sacos": sum(
            1 for f in pagina.filas
            if f.diferencia_sacos is not None and f.diferencia_sacos < 0),
        # Peso corto con los sacos cuadrados es la firma de la sustitucion de
        # producto, que es el problema que motiva el proyecto. Contarlos aparte
        # evita que se pierdan entre los faltantes de bultos.
        "con_peso_corto_y_sacos_completos": sum(
            1 for f in pagina.filas
            if f.falta_producto and f.diferencia_sacos == 0),
        "con_personal_anomalo": sum(1 for f in pagina.filas
                                    if f.personal_anomalo),
        "sin_analizar": sum(1 for f in pagina.filas
                            if f.sacos_contados is None),
        "altas": sum(1 for f in pagina.filas if f.severidad == "alta"),
    }
