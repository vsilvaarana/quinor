"""Caso de uso de HU-04: tolerancias de peso por tipo de producto.

Como administrador del sistema, quiero configurar la tolerancia de peso
permitida (kg y porcentaje) por tipo de producto, para ajustar la sensibilidad
sin cambiar el codigo.

Criterios de aceptacion:
  1. Existe una pantalla de configuracion con campos de tolerancia en kg y %.
  2. Solo el rol Administrador puede editarla.
  3. Cada cambio queda registrado con usuario y fecha.

El criterio 3 se cumple en dos sitios a la vez, y a proposito. La fila de
`configuracion` guarda quien hizo el ultimo cambio y cuando, que es lo que la
pantalla necesita mostrar de un vistazo; la tabla `auditoria` guarda el
historial completo con los valores anteriores y los nuevos. Solo lo primero
dejaria sin rastro el cambio penultimo, que es justo el que se busca cuando una
tolerancia aparece mas laxa de lo que deberia.
"""
from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auditoria
from app.models import Configuracion

log = structlog.get_logger("quinor.configuracion")

CENTESIMA = Decimal("0.01")
PCT_MAXIMO = Decimal("100")
# Limite de la columna DECIMAL(8,2). Un valor mayor lo rechazaria MySQL con un
# error de rango; se rechaza antes, con un mensaje que dice que pasa.
KG_MAXIMO = Decimal("999999.99")


class ProductoNoConfigurado(LookupError):
    """No hay tolerancia definida para ese producto.

    En el Sprint 1 las filas las siembra el esquema: la pantalla edita lo que
    existe y no da de alta productos nuevos, que llegan del catalogo del ERP.
    """


class ToleranciaInvalida(ValueError):
    """Fuera de los limites que el esquema admite."""


def _ahora() -> dt.datetime:
    return dt.datetime.now().replace(tzinfo=None)


def _redondear(valor: Decimal | float | str, nombre: str) -> Decimal:
    """Normaliza a dos decimales. Lo que llega de un formulario es texto."""
    try:
        return Decimal(str(valor)).quantize(CENTESIMA, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ToleranciaInvalida(f"{nombre} no es un numero valido: {valor!r}") from exc


def validar(tolerancia_kg: Decimal, tolerancia_pct: Decimal) -> None:
    """Las mismas reglas que los CHECK del esquema, pero con mensaje util.

    Dejar que falle MySQL tambien impediria el dato incorrecto, solo que el
    administrador veria un error de motor en lugar de saber que corregir.
    """
    if tolerancia_kg < 0:
        raise ToleranciaInvalida("La tolerancia en kg no puede ser negativa")
    if tolerancia_kg > KG_MAXIMO:
        raise ToleranciaInvalida(f"La tolerancia en kg no puede pasar de {KG_MAXIMO}")
    if not (0 <= tolerancia_pct <= PCT_MAXIMO):
        raise ToleranciaInvalida("La tolerancia en porcentaje va de 0 a 100")


def listar(sesion: Session) -> list[Configuracion]:
    return list(sesion.scalars(
        select(Configuracion).order_by(Configuracion.producto)).all())


def obtener(sesion: Session, producto: str) -> Configuracion:
    fila = sesion.scalars(
        select(Configuracion).where(Configuracion.producto == producto.strip())
    ).first()
    if fila is None:
        raise ProductoNoConfigurado(f"No hay tolerancia configurada para '{producto}'")
    return fila


# ----------------------------------------------------------------- criterio 3
def actualizar(
    sesion: Session,
    producto: str,
    tolerancia_kg: Decimal | float | str | None,
    tolerancia_pct: Decimal | float | str | None,
    actor_id: int,
) -> Configuracion:
    """Cambia las tolerancias de un producto y deja constancia de quien y cuando.

    Los dos campos son opcionales por separado: ajustar solo el porcentaje no
    obliga a reescribir los kg, que es como se usa en la practica.

    Un cambio que no cambia nada no se registra. La auditoria sirve para saber
    que se movio, y llenarla de filas identicas la vuelve inutil justo cuando
    hace falta leerla.
    """
    fila = obtener(sesion, producto)
    antes_kg, antes_pct = fila.tolerancia_kg, fila.tolerancia_pct

    nuevo_kg = antes_kg if tolerancia_kg is None else _redondear(tolerancia_kg, "kg")
    nuevo_pct = antes_pct if tolerancia_pct is None else _redondear(tolerancia_pct, "porcentaje")
    validar(nuevo_kg, nuevo_pct)

    if nuevo_kg == antes_kg and nuevo_pct == antes_pct:
        return fila

    fila.tolerancia_kg = nuevo_kg
    fila.tolerancia_pct = nuevo_pct
    fila.actualizado_por = actor_id
    # La columna tiene ON UPDATE CURRENT_TIMESTAMP(6), pero se fija aqui para
    # que la fecha sea la misma que la de la fila de auditoria de este cambio.
    fila.fecha = _ahora()

    auditoria.registrar(
        sesion, entidad="configuracion", entidad_id=fila.id,
        accion="editar_tolerancia", usuario_id=actor_id,
        detalle={
            "producto": fila.producto,
            "antes": {"kg": str(antes_kg), "pct": str(antes_pct)},
            "despues": {"kg": str(nuevo_kg), "pct": str(nuevo_pct)},
        },
    )
    sesion.commit()
    sesion.refresh(fila)
    log.info("tolerancia_editada", producto=fila.producto, por=actor_id,
             kg=str(nuevo_kg), pct=str(nuevo_pct))
    return fila


def historial(sesion: Session, producto: str | None = None, limite: int = 50) -> list:
    """Cambios de tolerancia registrados, del mas reciente al mas antiguo."""
    from app.models import Auditoria     # local: evita un ciclo de importacion

    consulta = (select(Auditoria)
                .where(Auditoria.entidad == "configuracion")
                .order_by(Auditoria.id.desc())
                .limit(limite))
    filas = list(sesion.scalars(consulta).all())
    if producto is None:
        return filas
    objetivo = producto.strip()
    return [f for f in filas if (f.detalle or {}).get("producto") == objetivo]


def nombres_de(sesion: Session, ids: set[int | None]) -> dict[int, str]:
    """Nombre de cada usuario, por id. Un numero en la pantalla no dice nada."""
    from app.models import Usuario     # local: evita un ciclo de importacion

    concretos = {i for i in ids if i is not None}
    if not concretos:
        return {}
    filas = sesion.scalars(select(Usuario).where(Usuario.id.in_(concretos))).all()
    return {u.id: u.nombre for u in filas}


# ------------------------------------------------------------------- RN-01
def tolerancia_de(sesion: Session, producto: str, peso_esperado_kg: Decimal) -> Decimal:
    """Kg admisibles para esa orden. Punto de entrada de HU-03, en el Sprint 2.

    Existe desde ahora para que la pantalla pueda mostrar, con el peso de una
    orden real, cual de las dos tolerancias acaba mandando. Una configuracion
    que no se puede leer en unidades comprensibles se ajusta a ciegas.
    """
    return obtener(sesion, producto).tolerancia_efectiva_kg(peso_esperado_kg)
