"""Estado de los componentes: sondeo, registro y consulta.

El criterio 2 de HU-01 exige que un fallo de la bascula quede registrado en la
tabla salud_componente y sea visible en GET /salud. El panel visual llega con
HU-18 en el Sprint 5; lo que este modulo aporta es el dato que ese panel leera.

Solo se inserta cuando el estado o el mensaje cambian respecto a la ultima
lectura del componente. Sondear cada 30 segundos, como pedira HU-18, generaria
miles de filas identicas al dia y enterraria justo lo que interesa: el momento en
que algo dejo de funcionar.
"""
from __future__ import annotations

import datetime as dt

import httpx
import structlog
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import bascula
from app.config import Ajustes
from app.models import SaludComponente

log = structlog.get_logger("quinor.salud")

OK = "ok"
ADVERTENCIA = "advertencia"
ERROR = "error"

MYSQL = "mysql"
ERP = "erp"
BASCULA = "bascula"


def _ahora() -> dt.datetime:
    return dt.datetime.now().replace(tzinfo=None)


# ------------------------------------------------------------------ registro
def ultimo(sesion: Session, componente: str) -> SaludComponente | None:
    return sesion.scalars(
        select(SaludComponente)
        .where(SaludComponente.componente == componente)
        .order_by(SaludComponente.verificado_en.desc(), SaludComponente.id.desc())
        .limit(1)
    ).first()


def registrar_si_cambia(
    sesion: Session, componente: str, estado: str, mensaje: str | None = None
) -> SaludComponente | None:
    """Inserta una fila solo si el estado o el mensaje difieren del ultimo.

    Devuelve la fila insertada, o None si no hubo cambio. No hace commit: lo
    decide quien llama, porque un fallo de bascula debe persistirse aunque la
    operacion que lo detecto termine en error.
    """
    previo = ultimo(sesion, componente)
    if previo is not None and previo.estado == estado and (previo.mensaje or "") == (mensaje or ""):
        return None

    fila = SaludComponente(
        componente=componente,
        estado=estado,
        mensaje=(mensaje or "")[:500] or None,
        verificado_en=_ahora(),
    )
    sesion.add(fila)
    sesion.flush()
    log.info("salud_cambio", componente=componente, estado=estado, mensaje=mensaje)
    return fila


# ------------------------------------------------------------------ consulta
def estado_actual(sesion: Session) -> list[dict]:
    """Ultimo estado conocido de cada componente, desde la vista v_salud_actual."""
    filas = sesion.execute(
        text("SELECT componente, estado, mensaje, verificado_en FROM v_salud_actual "
             "ORDER BY componente")
    ).mappings().all()
    return [dict(f) for f in filas]


def historial(sesion: Session, componente: str | None = None, limite: int = 50) -> list[dict]:
    consulta = select(SaludComponente).order_by(SaludComponente.id.desc()).limit(limite)
    if componente:
        consulta = consulta.where(SaludComponente.componente == componente)
    return [
        {
            "componente": f.componente,
            "estado": f.estado,
            "mensaje": f.mensaje,
            "verificado_en": f.verificado_en,
        }
        for f in sesion.scalars(consulta).all()
    ]


# ------------------------------------------------------------------- sondeos
def _resultado(componente: str, estado: str, mensaje: str) -> dict:
    # verificado_en es el momento del sondeo, no el de la ultima fila guardada:
    # como solo se persisten los cambios de estado, la fila puede ser de ayer
    # aunque la comprobacion sea de hace un segundo. HU-18 necesita saber que la
    # verificacion es reciente.
    return {"componente": componente, "estado": estado, "mensaje": mensaje,
            "verificado_en": _ahora()}


def sondear_mysql(sesion: Session) -> dict:
    try:
        version = sesion.execute(text("SELECT VERSION()")).scalar_one()
        return _resultado(MYSQL, OK, f"conectado, version {version}")
    except Exception as exc:  # noqa: BLE001
        return _resultado(MYSQL, ERROR, f"{type(exc).__name__}: {exc}")


async def sondear_erp(sesion: Session, ajustes: Ajustes) -> dict:
    url = f"{ajustes.erp_base_url}/salud"
    try:
        async with httpx.AsyncClient(timeout=ajustes.erp_timeout_seconds) as cliente:
            resp = await cliente.get(url)
            resp.raise_for_status()
        estado, mensaje = OK, f"{url} responde {resp.status_code}"
    except Exception as exc:  # noqa: BLE001
        estado, mensaje = ERROR, f"{type(exc).__name__}: {exc}"
    registrar_si_cambia(sesion, ERP, estado, mensaje)
    return _resultado(ERP, estado, mensaje)


async def sondear_bascula(sesion: Session, ajustes: Ajustes) -> dict:
    try:
        lectura = await bascula.leer_peso(
            host=ajustes.scale_host,
            puerto=ajustes.scale_port,
            unit_id=ajustes.scale_unit_id,
            presupuesto_s=ajustes.scale_timeout_seconds,
            bascula_id=ajustes.bascula_id,
        )
    except bascula.ErrorBascula as exc:
        registrar_si_cambia(sesion, BASCULA, ERROR, str(exc))
        return _resultado(BASCULA, ERROR, str(exc))

    mensaje = f"ultima lectura {lectura.peso_kg} kg, contador {lectura.contador}"
    estado = OK if lectura.estable else ADVERTENCIA
    if not lectura.estable:
        mensaje = "bascula en movimiento; " + mensaje
    registrar_si_cambia(sesion, BASCULA, estado, mensaje)
    return _resultado(BASCULA, estado, mensaje)


async def sondear_todo(sesion: Session, ajustes: Ajustes) -> dict:
    """Sondea los tres componentes y persiste los cambios de estado.

    Si MySQL no responde, los otros dos no se sondean: sin base de datos no hay
    donde registrar el resultado, y el diagnostico util ya esta dado.
    """
    mysql = sondear_mysql(sesion)
    componentes = [mysql]
    if mysql["estado"] == OK:
        componentes.append(await sondear_erp(sesion, ajustes))
        componentes.append(await sondear_bascula(sesion, ajustes))
        sesion.commit()
        # Hay componentes que no se sondean porque no son un equipo al que
        # preguntar, sino un fallo que quedo anotado: una tolerancia que falta
        # (HU-03) o una evaluacion que reviento. Se traen del ultimo estado
        # conocido, porque si no, nunca llegarian a esta respuesta.
        sondeados = {c["componente"] for c in componentes}
        componentes += [c for c in estado_actual(sesion)
                        if c["componente"] not in sondeados]
    return {
        "estado": OK if all(c["estado"] == OK for c in componentes) else ERROR,
        "componentes": componentes,
    }
