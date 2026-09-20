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
from decimal import ROUND_HALF_UP, Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auditoria, bascula, cargas, eventos, ordenes, salud
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
        try:
            lectura = await leer_bascula(ajustes, bascula_id)
        except bascula.ErrorBascula as exc:
            # Criterio 2. El registro de salud se confirma en su propia
            # transaccion: la peticion termina en error, pero la constancia de
            # que la bascula fallo tiene que sobrevivir.
            salud.registrar_si_cambia(sesion, COMPONENTE_BASCULA, salud.ERROR, str(exc))
            sesion.commit()
            log.warning("bascula_sin_respuesta", bascula=bascula_id, error=str(exc))
            raise BasculaNoResponde(str(exc)) from exc

        salud.registrar_si_cambia(
            sesion, COMPONENTE_BASCULA, salud.OK,
            f"ultima lectura {lectura.peso_kg} kg, contador {lectura.contador}",
        )

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
