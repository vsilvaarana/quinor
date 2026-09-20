"""Caso de uso de HU-03: evento de discrepancia.

Como supervisor de despacho, quiero que el sistema genere un evento de
discrepancia cuando el peso real difiera del esperado mas alla de la tolerancia,
para enterarme en el momento y no cuando reclama el cliente.

Criterios de aceptacion:
  1. Si |peso real - peso esperado| > tolerancia configurada, se crea un evento
     con estado Pendiente.
  2. El evento incluye orden, pesos, diferencia en kg y porcentaje.
  3. La creacion del evento ocurre en menos de 10 s desde la pesada.

Esta es la historia que cierra el circulo del proyecto: hasta aqui el sistema
sabia pesar y sabia cuanto se esperaba, pero nadie comparaba las dos cifras. Sin
esto, el faltante sigue apareciendo cuando reclama el cliente.

La tolerancia sale de HU-04 y se aplica segun la RN-01, la mas restrictiva entre
los kg y el porcentaje. La evaluacion es sincrona porque es una resta: el
criterio 3 da 10 segundos y aqui se responde en milisegundos. Lo que HU-17
sacara a una cola es el analisis de video, que si tarda.
"""
from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auditoria, configuracion, salud
from app.models import Evento, OrdenDespacho, Pesada

log = structlog.get_logger("quinor.eventos")

CENTESIMA = Decimal("0.01")
PENDIENTE = "pendiente"

# Tope de diferencia_pct, que es DECIMAL(6,2). Una orden con peso esperado
# ridiculo frente al real podria pasarse; se recorta para que el evento se cree
# igualmente, porque perder el aviso seria mucho peor que perder la precision.
PCT_MAXIMO = Decimal("9999.99")


class PesadaNoEncontrada(LookupError):
    pass


class SinToleranciaConfigurada(RuntimeError):
    """No se pudo comparar: falta la tolerancia de ese producto.

    No es lo mismo que una carga limpia, y quien llame tiene que poder
    distinguirlo. Callarse dejaria creer que la carga se reviso y salio bien.
    """


def _ahora() -> dt.datetime:
    return dt.datetime.now().replace(tzinfo=None)


def diferencias(peso_real: Decimal, peso_esperado: Decimal) -> tuple[Decimal, Decimal]:
    """Diferencia en kg y en porcentaje del peso esperado. Criterio 2.

    Con signo: negativa es faltante. El sobrepeso tambien interesa, porque un
    contenedor mas pesado de lo planificado apunta a una sustitucion igual que
    uno mas ligero.
    """
    kg = (peso_real - peso_esperado).quantize(CENTESIMA, rounding=ROUND_HALF_UP)
    bruto = (kg / peso_esperado * 100).quantize(CENTESIMA, rounding=ROUND_HALF_UP)
    pct = max(-PCT_MAXIMO, min(PCT_MAXIMO, bruto))
    return kg, pct


def hay_discrepancia(diferencia_kg: Decimal, tolerancia_kg: Decimal) -> bool:
    """Criterio 1: estrictamente mayor que la tolerancia.

    Una diferencia igual a la tolerancia no es discrepancia. La tolerancia es lo
    que se acepta, no lo primero que se rechaza.
    """
    return abs(diferencia_kg) > tolerancia_kg


def buscar_por_pesada(sesion: Session, pesada_id: int) -> Evento | None:
    return sesion.scalars(
        select(Evento).where(Evento.pesada_id == pesada_id)).first()


def obtener(sesion: Session, evento_id: int) -> Evento | None:
    return sesion.get(Evento, evento_id)


def listar(
    sesion: Session,
    estado: str | None = None,
    numero_orden: str | None = None,
    limite: int = 50,
) -> list[Evento]:
    """Listado basico. La pantalla con filtros y sus 2 s es HU-11."""
    consulta = select(Evento).order_by(Evento.creado_en.desc(), Evento.id.desc())
    if estado:
        consulta = consulta.where(Evento.estado == estado)
    if numero_orden:
        consulta = (consulta.join(Pesada, Evento.pesada_id == Pesada.id)
                    .join(OrdenDespacho, Pesada.orden_id == OrdenDespacho.id)
                    .where(OrdenDespacho.numero_orden == numero_orden.strip()))
    return list(sesion.scalars(consulta.limit(limite)).all())


# ------------------------------------------------------------------ criterio 1
def evaluar(sesion: Session, pesada: Pesada, orden: OrdenDespacho) -> Evento | None:
    """Compara la pesada con lo esperado y crea el evento si procede.

    Devuelve el evento creado, el que ya existia si la pesada se reprocesa, o
    None cuando la carga entra dentro de la tolerancia. Si el producto no tiene
    tolerancia configurada lanza SinToleranciaConfigurada: no hay evento, pero
    tampoco es una carga limpia.

    Es idempotente a proposito: la clave unica sobre `pesada_id` existe para que
    reprocesar una pesada no duplique el aviso al supervisor.
    """
    existente = buscar_por_pesada(sesion, pesada.id)
    if existente is not None:
        return existente

    try:
        tolerancia = configuracion.tolerancia_de(
            sesion, orden.producto, orden.peso_esperado_kg)
    except configuracion.ProductoNoConfigurado:
        _avisar_sin_tolerancia(sesion, pesada, orden)
        raise SinToleranciaConfigurada(
            f"El producto '{orden.producto}' no tiene tolerancia configurada: "
            f"la carga no se pudo evaluar") from None

    kg, pct = diferencias(pesada.peso_real_kg, orden.peso_esperado_kg)
    if not hay_discrepancia(kg, tolerancia):
        log.info("pesada_dentro_de_tolerancia", pesada_id=pesada.id,
                 diferencia_kg=str(kg), tolerancia_kg=str(tolerancia))
        return None

    evento = Evento(
        pesada_id=pesada.id,
        diferencia_kg=kg,
        diferencia_pct=pct,
        estado=PENDIENTE,          # criterio 1
        creado_en=_ahora(),
    )
    sesion.add(evento)
    sesion.flush()
    auditoria.registrar(
        sesion, entidad="evento", entidad_id=evento.id, accion="crear_evento",
        detalle={
            "numero_orden": orden.numero_orden,
            "producto": orden.producto,
            "peso_esperado_kg": str(orden.peso_esperado_kg),
            "peso_real_kg": str(pesada.peso_real_kg),
            "diferencia_kg": str(kg),
            "diferencia_pct": str(pct),
            "tolerancia_aplicada_kg": str(tolerancia),
        },
    )
    sesion.commit()
    sesion.refresh(evento)
    log.info("evento_creado", evento_id=evento.id, orden=orden.numero_orden,
             diferencia_kg=str(kg), diferencia_pct=str(pct),
             tolerancia_kg=str(tolerancia))
    return evento


def _avisar_sin_tolerancia(sesion: Session, pesada: Pesada, orden: OrdenDespacho) -> None:
    """Sin tolerancia no se puede decidir, y callarse seria lo peor.

    La pesada queda registrada, no se crea evento y el hueco de configuracion se
    hace visible en GET /salud y en la auditoria. Quedarse en silencio dejaria
    creer que esa carga se reviso y salio limpia.
    """
    mensaje = (f"El producto '{orden.producto}' no tiene tolerancia configurada: "
               f"la pesada {pesada.id} no se pudo evaluar")
    auditoria.registrar(
        sesion, entidad="pesada", entidad_id=pesada.id,
        accion="incidencia_sin_tolerancia",
        detalle={"numero_orden": orden.numero_orden, "producto": orden.producto},
    )
    salud.registrar_si_cambia(sesion, "configuracion", "error", mensaje)
    sesion.commit()
    log.warning("sin_tolerancia_configurada", pesada_id=pesada.id,
                producto=orden.producto)


def reevaluar(sesion: Session, pesada_id: int) -> Evento | None:
    """Vuelve a evaluar una pesada ya registrada.

    Sirve para las pesadas que quedaron sin evaluar porque faltaba la tolerancia:
    una vez configurada, se recuperan sin tener que volver a pesar el camion.
    """
    pesada = sesion.get(Pesada, pesada_id)
    if pesada is None:
        raise PesadaNoEncontrada(f"No existe la pesada {pesada_id}")
    orden = sesion.get(OrdenDespacho, pesada.orden_id)
    return evaluar(sesion, pesada, orden)
