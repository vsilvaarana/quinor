"""Caso de uso de HU-01: registrar la pesada al cerrar una carga.

Como operador de despacho, quiero que el sistema registre automaticamente el peso
de la bascula al cerrar cada carga, para no depender de anotaciones manuales que
pueden alterarse.

Criterios de aceptacion:
  1. Al finalizar la pesada, el sistema lee el peso via Modbus o serial y lo
     guarda con fecha, hora, ID de carga y ID de bascula.
  2. Si la bascula no responde en 5 s se registra un error en salud_componente,
     expuesto por GET /salud.
  3. El peso se almacena con dos decimales en kg.

Desde HU-03, registrar la pesada tambien dispara su evaluacion contra la
tolerancia del producto. Va despues de confirmar la pesada, nunca dentro de la
misma transaccion: la pesada es la evidencia y no puede perderse porque falle
una comparacion.

Los ajustes llegan por parametro: este modulo no conoce el entorno.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auditoria, bascula, cargas, configuracion, eventos, ordenes, salud
from app.config import Ajustes
from app.models import OrdenDespacho, Pesada

log = structlog.get_logger("quinor.pesadas")

COMPONENTE_BASCULA = "bascula"
COMPONENTE_EVALUACION = "evaluacion"
DOS_DECIMALES = Decimal("0.01")


class BasculaNoResponde(RuntimeError):
    """Se agoto el presupuesto de lectura. El fallo queda en salud_componente."""


class PesoNoEstable(RuntimeError):
    """La bascula sigue en movimiento: el peso todavia no es un dato."""


async def leer_bascula(ajustes: Ajustes, bascula_id: str) -> bascula.LecturaBascula:
    """Adaptador entre los ajustes de la aplicacion y el cliente Modbus."""
    return await bascula.leer_peso(
        host=ajustes.scale_host,
        puerto=ajustes.scale_port,
        unit_id=ajustes.scale_unit_id,
        presupuesto_s=ajustes.scale_timeout_seconds,
        bascula_id=bascula_id,
    )


async def _leer_anotando_la_salud(
    sesion: Session, ajustes: Ajustes, bascula_id: str,
) -> bascula.LecturaBascula:
    """Lee la bascula y deja en salud_componente como fue. Criterio 2 de HU-01.

    Lo comparten el registro de la pesada y la lectura previa: las dos tocan el
    mismo equipo, y una bascula que no contesta tiene que verse en GET /salud la
    pregunte quien la pregunte.

    Si falla, el registro de salud se confirma en su propia transaccion: la
    peticion termina en error, pero la constancia de que la bascula fallo tiene
    que sobrevivir. Si responde, la anotacion queda pendiente de confirmar para
    quien llama.
    """
    try:
        lectura = await leer_bascula(ajustes, bascula_id)
    except bascula.ErrorBascula as exc:
        salud.registrar_si_cambia(sesion, COMPONENTE_BASCULA, salud.ERROR, str(exc))
        sesion.commit()
        log.warning("bascula_sin_respuesta", bascula=bascula_id, error=str(exc))
        raise BasculaNoResponde(str(exc)) from exc

    salud.registrar_si_cambia(
        sesion, COMPONENTE_BASCULA, salud.OK,
        f"ultima lectura {lectura.peso_kg} kg, contador {lectura.contador}",
    )
    return lectura


@dataclass(frozen=True)
class LecturaPrevia:
    """Lo que marca la bascula ahora, contra la orden, sin registrar la pesada."""

    numero_orden: str
    bascula_id: str
    peso_kg: Decimal
    estable: bool
    leido_en: dt.datetime
    peso_esperado_kg: Decimal
    # Convencion 7, NULL no es cero. Con la bascula en movimiento el peso
    # todavia no es un dato, asi que no hay diferencia que dar. Y sin tolerancia
    # configurada no se sabe si habria evento: decir "no" seria dar por limpia
    # una carga que nadie pudo comparar.
    diferencia_kg: Decimal | None
    diferencia_pct: Decimal | None
    tolerancia_kg: Decimal | None
    generaria_evento: bool | None


async def lectura_previa(
    sesion: Session,
    ajustes: Ajustes,
    numero_orden: str,
    bascula_id: str | None = None,
    usuario_id: int | None = None,
) -> LecturaPrevia:
    """Lee la bascula y dice que pasaria al registrar, sin registrar nada.

    Existe para que el operador sepa antes de confirmar si esa pesada va a abrir
    un evento, igual que ya lo sabia con el ingreso manual (critica de UX del
    15/11/2026, fase 5).

    Tiene un coste que hay que pagar a proposito. Hasta ahora la pesada con
    bascula era atomica: se leia y se guardaba en la misma peticion, sin vuelta
    atras. Con esta lectura alguien puede ver el faltante cuando todavia no
    existe ningun registro, y no registrar. Por eso **cada lectura previa deja
    una fila en auditoria**, con quien la pidio, para que orden y que marcaba la
    bascula. Una lectura previa fuera de tolerancia sin pesada posterior deja de
    ser invisible: es una pregunta que se puede hacer a la tabla.

    No sustituye a la pesada. Al registrar, la API vuelve a leer la bascula: el
    peso que se guarda nunca viaja desde el navegador.

    No crea pesada ni evento, y no consume la marca de inicio de carga (HU-06).
    """
    bascula_id = bascula_id or ajustes.bascula_id
    orden = await ordenes.obtener_orden(sesion, ajustes, numero_orden,
                                        usuario_id=usuario_id)
    lectura = await _leer_anotando_la_salud(sesion, ajustes, bascula_id)

    diferencia_kg = diferencia_pct = tolerancia_kg = generaria_evento = None
    if lectura.estable:
        diferencia_kg, diferencia_pct = eventos.diferencias(
            lectura.peso_kg, orden.peso_esperado_kg)
        try:
            tolerancia_kg = configuracion.tolerancia_de(
                sesion, orden.producto, orden.peso_esperado_kg)
        except configuracion.ProductoNoConfigurado:
            pass
        else:
            generaria_evento = eventos.hay_discrepancia(diferencia_kg, tolerancia_kg)

    def _texto(valor: Decimal | None) -> str | None:
        return None if valor is None else str(valor)

    auditoria.registrar(
        sesion,
        entidad="orden_despacho",
        entidad_id=orden.id,
        accion="lectura_previa",
        usuario_id=usuario_id,
        detalle={
            "numero_orden": orden.numero_orden,
            "bascula_id": bascula_id,
            "peso_kg": str(lectura.peso_kg),
            "estable": lectura.estable,
            "contador_bascula": lectura.contador,
            "peso_esperado_kg": str(orden.peso_esperado_kg),
            "diferencia_kg": _texto(diferencia_kg),
            "tolerancia_kg": _texto(tolerancia_kg),
            "generaria_evento": generaria_evento,
        },
    )
    sesion.commit()
    log.info("lectura_previa", orden=orden.numero_orden, bascula=bascula_id,
             peso=str(lectura.peso_kg), estable=lectura.estable,
             generaria_evento=generaria_evento)

    return LecturaPrevia(
        numero_orden=orden.numero_orden,
        bascula_id=bascula_id,
        peso_kg=lectura.peso_kg,
        estable=lectura.estable,
        leido_en=lectura.leido_en,
        peso_esperado_kg=orden.peso_esperado_kg,
        diferencia_kg=diferencia_kg,
        diferencia_pct=diferencia_pct,
        tolerancia_kg=tolerancia_kg,
        generaria_evento=generaria_evento,
    )


async def registrar_pesada(
    sesion: Session,
    ajustes: Ajustes,
    numero_orden: str,
    bascula_id: str | None = None,
    peso_manual: Decimal | None = None,
    motivo_manual: str | None = None,
    usuario_id: int | None = None,
) -> Pesada:
    """Cierra una carga: lee el peso, lo persiste y deja constancia en auditoria."""
    bascula_id = bascula_id or ajustes.bascula_id
    # HU-02: la orden sale del ERP, con la copia local como cache y como
    # respaldo si el ERP no contesta.
    orden = await ordenes.obtener_orden(sesion, ajustes, numero_orden,
                                        usuario_id=usuario_id)

    if peso_manual is not None:
        # Registro manual del supervisor. No toca la bascula, asi que tampoco
        # dice nada sobre su salud.
        peso = Decimal(peso_manual).quantize(DOS_DECIMALES, rounding=ROUND_HALF_UP)
        origen = "manual"
        momento = dt.datetime.now().replace(tzinfo=None)
        detalle_extra = {"motivo_manual": motivo_manual}
    else:
        # Criterio 2: si la bascula no responde, el fallo queda en
        # salud_componente antes de que esta funcion termine en error.
        lectura = await _leer_anotando_la_salud(sesion, ajustes, bascula_id)

        if not lectura.estable:
            sesion.commit()
            raise PesoNoEstable(
                f"La bascula {bascula_id} sigue en movimiento. Esperar al peso estable."
            )

        peso = lectura.peso_kg          # ya viene cuantizado a dos decimales
        origen = "bascula"
        momento = lectura.leido_en
        detalle_extra = {"contador_bascula": lectura.contador}

    pesada = Pesada(
        orden_id=orden.id,
        bascula_id=bascula_id,
        peso_real_kg=peso,
        fecha_hora=momento,
        origen=origen,
    )
    sesion.add(pesada)
    sesion.flush()

    # HU-06: la pesada se queda con el instante en que empezo la carga, si
    # alguien lo marco. Guardarlo aqui y no dejarlo en la tabla carga hace que
    # el recorte del clip no dependa de una fila que podria no estar.
    pesada.inicio_carga = cargas.cerrar(sesion, orden.id, pesada)

    auditoria.registrar(
        sesion,
        entidad="pesada",
        entidad_id=pesada.id,
        accion="registrar_pesada",
        usuario_id=usuario_id,
        detalle={
            "numero_orden": orden.numero_orden,
            "bascula_id": bascula_id,
            "peso_real_kg": str(peso),
            "peso_esperado_kg": str(orden.peso_esperado_kg),
            "sacos_esperados": orden.sacos_esperados,
            # Criterio 3 de HU-02: la respuesta del ERP queda junto a la pesada,
            # con la marca de cuando se leyo. Si manana el ERP corrige la orden,
            # el historial conserva contra que valores se peso aquel dia.
            "orden_sincronizada_en": orden.sincronizado_en.isoformat(),
            "origen": origen,
            # HU-06: de aqui sale la ventana del clip.
            "inicio_carga": (pesada.inicio_carga.isoformat()
                             if pesada.inicio_carga else None),
            **detalle_extra,
        },
    )
    sesion.commit()
    sesion.refresh(pesada)

    log.info("pesada_registrada", pesada_id=pesada.id, orden=orden.numero_orden,
             peso=str(peso), origen=origen)

    # HU-03. Va despues del commit y no dentro de el: la pesada es la evidencia
    # y tiene que sobrevivir aunque la evaluacion falle. Como la clave unica de
    # evento es la pesada, reevaluarla despues no duplica el aviso.
    pesada.evaluada, pesada.motivo_sin_evaluar = True, None
    try:
        eventos.evaluar(sesion, pesada, orden)
    except eventos.SinToleranciaConfigurada as exc:
        # Falta configurar el producto. La incidencia ya quedo registrada y
        # visible en GET /salud; aqui solo se marca para que quien reciba la
        # respuesta no confunda "no se pudo comparar" con "carga limpia".
        pesada.evaluada, pesada.motivo_sin_evaluar = False, str(exc)
    except Exception as exc:      # noqa: BLE001
        sesion.rollback()
        log.error("evaluacion_fallida", pesada_id=pesada.id, error=str(exc))
        salud.registrar_si_cambia(
            sesion, COMPONENTE_EVALUACION, salud.ERROR,
            f"No se pudo evaluar la pesada {pesada.id}: {exc}")
        sesion.commit()
        pesada.evaluada, pesada.motivo_sin_evaluar = False, str(exc)

    return pesada


def listar_pesadas(
    sesion: Session, numero_orden: str | None = None, limite: int = 50
) -> list[tuple[Pesada, OrdenDespacho]]:
    consulta = (
        select(Pesada, OrdenDespacho)
        .join(OrdenDespacho, OrdenDespacho.id == Pesada.orden_id)
        .order_by(Pesada.fecha_hora.desc(), Pesada.id.desc())
        .limit(limite)
    )
    if numero_orden:
        consulta = consulta.where(OrdenDespacho.numero_orden == numero_orden.upper())
    return list(sesion.execute(consulta).all())
