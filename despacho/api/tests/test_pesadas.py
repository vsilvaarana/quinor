"""Tests del caso de uso de HU-01 y del registro de salud, contra MySQL real."""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app import auditoria, bascula, pesadas, salud
from app.config import Ajustes
from app.models import Auditoria, Pesada
from tests.conftest import PESO_FIJO, SIN_NADIE, URL_PRUEBAS


@pytest.fixture()
def ajustes(bascula_estable) -> Ajustes:
    from tests.conftest import ERP_URL

    return Ajustes(database_url=URL_PRUEBAS, scale_host="127.0.0.1",
                   scale_port=bascula_estable, scale_timeout_seconds=5.0,
                   erp_base_url=ERP_URL)


# ---------- Criterio 1: lectura y persistencia ----------

async def test_registra_la_pesada_con_fecha_hora_carga_y_bascula(sesion, ajustes, orden):
    pesada = await pesadas.registrar_pesada(sesion, ajustes, "ORD-2026-0001",
                                            bascula_id="BASCULA-01")
    assert pesada.id is not None
    assert pesada.orden_id == orden.id                 # ID de carga
    assert pesada.bascula_id == "BASCULA-01"           # ID de bascula
    assert pesada.fecha_hora is not None               # fecha y hora
    assert pesada.peso_real_kg == PESO_FIJO
    assert pesada.origen == "bascula"


async def test_la_orden_se_resuelve_sin_distinguir_mayusculas(sesion, ajustes, orden):
    pesada = await pesadas.registrar_pesada(sesion, ajustes, "ord-2026-0001")
    assert pesada.orden_id == orden.id


async def test_sin_orden_valida_no_hay_pesada(sesion, ajustes, erp_sin_orden):
    """RN-02: si el ERP no reconoce la orden, no se registra la carga."""
    from app.ordenes import OrdenNoDisponible

    with pytest.raises(OrdenNoDisponible):
        await pesadas.registrar_pesada(sesion, ajustes, "ORD-INEXISTENTE")
    assert sesion.scalars(select(Pesada)).all() == []


async def test_la_pesada_guarda_la_respuesta_del_erp(sesion, ajustes, erp_sano):
    """Criterio 3 de HU-02: la respuesta se guarda junto a la pesada."""
    pesada = await pesadas.registrar_pesada(sesion, ajustes, "ORD-2026-0001")
    fila = sesion.scalars(
        select(Auditoria).where(Auditoria.entidad_id == pesada.id,
                                Auditoria.accion == "registrar_pesada")
    ).one()
    assert fila.detalle["peso_esperado_kg"] == "20000.00"
    assert fila.detalle["sacos_esperados"] == 400
    assert fila.detalle["orden_sincronizada_en"]


async def test_la_pesada_queda_en_auditoria(sesion, ajustes, orden):
    """Toda accion sobre la evidencia deja rastro (RNF-07)."""
    pesada = await pesadas.registrar_pesada(sesion, ajustes, "ORD-2026-0001")
    fila = sesion.scalars(
        select(Auditoria).where(Auditoria.entidad == "pesada",
                                Auditoria.entidad_id == pesada.id)
    ).one()
    assert fila.accion == "registrar_pesada"
    assert fila.usuario_id is None            # accion del sistema, no de una persona
    assert fila.detalle["numero_orden"] == "ORD-2026-0001"
    assert fila.detalle["contador_bascula"] == 42


async def test_una_pesada_de_un_usuario_registra_quien_fue(sesion, ajustes, orden):
    from app.models import Usuario

    usuario = Usuario(nombre="Ana Quispe", correo="ana@quinor.local",
                      rol="supervisor", hash_password="x")
    sesion.add(usuario)
    sesion.commit()

    pesada = await pesadas.registrar_pesada(sesion, ajustes, "ORD-2026-0001",
                                            usuario_id=usuario.id)
    # Filtrando tambien por entidad: desde HU-03 la misma pesada puede tener a
    # su lado la fila de auditoria del evento, con otro entidad_id que coincide.
    fila = sesion.scalars(
        select(Auditoria).where(Auditoria.entidad == "pesada",
                                Auditoria.entidad_id == pesada.id)
    ).one()
    assert fila.usuario_id == usuario.id


# ---------- Criterio 2: fallo de bascula ----------

async def test_si_la_bascula_no_responde_se_registra_en_salud(sesion, ajustes, orden):
    caida = Ajustes(**{**ajustes.__dict__, "scale_port": SIN_NADIE})
    with pytest.raises(pesadas.BasculaNoResponde):
        await pesadas.registrar_pesada(sesion, caida, "ORD-2026-0001")

    assert sesion.scalars(select(Pesada)).all() == []
    estado = salud.ultimo(sesion, "bascula")
    assert estado.estado == salud.ERROR
    assert "no respondio" in estado.mensaje
    # Y es lo que devuelve la vista que consulta GET /salud.
    actual = {c["componente"]: c for c in salud.estado_actual(sesion)}
    assert actual["bascula"]["estado"] == salud.ERROR


async def test_no_se_repite_la_misma_fila_de_salud(sesion, ajustes, orden):
    """Sondear cada 30 s no debe llenar la tabla de filas identicas."""
    caida = Ajustes(**{**ajustes.__dict__, "scale_port": SIN_NADIE})
    for _ in range(3):
        with pytest.raises(pesadas.BasculaNoResponde):
            await pesadas.registrar_pesada(sesion, caida, "ORD-2026-0001")

    filas = sesion.execute(
        text("SELECT COUNT(*) FROM salud_componente WHERE componente = 'bascula'")
    ).scalar_one()
    assert filas == 1


async def test_una_lectura_correcta_devuelve_la_bascula_a_ok(sesion, ajustes, orden):
    caida = Ajustes(**{**ajustes.__dict__, "scale_port": SIN_NADIE})
    with pytest.raises(pesadas.BasculaNoResponde):
        await pesadas.registrar_pesada(sesion, caida, "ORD-2026-0001")

    await pesadas.registrar_pesada(sesion, ajustes, "ORD-2026-0001")

    assert salud.ultimo(sesion, "bascula").estado == salud.OK
    assert [h["estado"] for h in salud.historial(sesion, "bascula")] == [salud.OK, salud.ERROR]


async def test_un_peso_en_movimiento_no_se_registra(sesion, ajustes, orden, bascula_inestable):
    oscilando = Ajustes(**{**ajustes.__dict__, "scale_port": bascula_inestable})
    with pytest.raises(pesadas.PesoNoEstable):
        await pesadas.registrar_pesada(sesion, oscilando, "ORD-2026-0001")
    assert sesion.scalars(select(Pesada)).all() == []
    # La lectura si ocurrio, asi que la salud se actualiza igual.
    assert salud.ultimo(sesion, "bascula").estado == salud.OK


# ---------- Criterio 3: dos decimales ----------

async def test_mysql_guarda_exactamente_dos_decimales(sesion, ajustes, orden):
    pesada = await pesadas.registrar_pesada(sesion, ajustes, "ORD-2026-0001")
    guardado = sesion.execute(
        text("SELECT peso_real_kg FROM pesada WHERE id = :i"), {"i": pesada.id}
    ).scalar_one()
    assert isinstance(guardado, Decimal)
    assert guardado.as_tuple().exponent == -2


async def test_el_peso_manual_tambien_se_cuantiza(sesion, ajustes, orden):
    pesada = await pesadas.registrar_pesada(
        sesion, ajustes, "ORD-2026-0001", peso_manual=Decimal("19850.456"),
        motivo_manual="bascula en mantenimiento",
    )
    assert pesada.peso_real_kg == Decimal("19850.46")
    assert pesada.origen == "manual"
    fila = sesion.scalars(
        select(Auditoria).where(Auditoria.entidad == "pesada",
                                Auditoria.entidad_id == pesada.id)).one()
    assert fila.detalle["motivo_manual"] == "bascula en mantenimiento"


async def test_el_peso_manual_no_toca_la_bascula(sesion, ajustes, orden):
    """Un registro manual no dice nada sobre la salud del equipo."""
    caida = Ajustes(**{**ajustes.__dict__, "scale_port": SIN_NADIE})
    await pesadas.registrar_pesada(sesion, caida, "ORD-2026-0001",
                                   peso_manual=Decimal("100"), motivo_manual="prueba")
    assert salud.ultimo(sesion, "bascula") is None


# ---------- HU-03: la evaluacion no pone en riesgo la pesada ----------

async def test_la_pesada_sobrevive_aunque_falle_la_evaluacion(
        sesion, ajustes, orden, monkeypatch):
    """La pesada es la evidencia. Si la comparacion revienta, se pierde el aviso,
    nunca el dato: por eso la evaluacion va despues del commit y no dentro."""
    from app import eventos

    def revienta(*_a, **_k):
        raise RuntimeError("fallo simulado de la evaluacion")

    monkeypatch.setattr(eventos, "evaluar", revienta)
    pesada = await pesadas.registrar_pesada(sesion, ajustes, "ORD-2026-0001")

    assert pesada.id is not None
    assert sesion.get(Pesada, pesada.id) is not None
    # Y el fallo queda a la vista en GET /salud, no solo en el log.
    registro = salud.ultimo(sesion, "evaluacion")
    assert registro.estado == "error"
    assert f"pesada {pesada.id}" in registro.mensaje


async def test_una_pesada_fuera_de_tolerancia_deja_su_evento(sesion, ajustes, orden):
    """19 850 kg contra 20 000 esperados: faltan 150, la tolerancia son 50."""
    from app.models import Evento

    pesada = await pesadas.registrar_pesada(sesion, ajustes, "ORD-2026-0001")
    evento = sesion.scalars(select(Evento).where(Evento.pesada_id == pesada.id)).one()
    assert evento.estado == "pendiente"
    assert evento.diferencia_kg == Decimal("-150.00")


async def test_la_evaluacion_no_retrasa_la_pesada(sesion, ajustes, orden):
    """Criterio 3 de HU-03: el evento llega en menos de 10 s desde la pesada."""
    import time

    inicio = time.monotonic()
    pesada = await pesadas.registrar_pesada(sesion, ajustes, "ORD-2026-0001")
    assert time.monotonic() - inicio < 10

    from app.models import Evento
    evento = sesion.scalars(select(Evento).where(Evento.pesada_id == pesada.id)).one()
    assert (evento.creado_en - pesada.fecha_hora).total_seconds() < 10


# ---------- Modulo salud ----------

def test_registrar_si_cambia_ignora_lo_identico(sesion):
    assert salud.registrar_si_cambia(sesion, "camara-01", salud.OK, "todo bien") is not None
    assert salud.registrar_si_cambia(sesion, "camara-01", salud.OK, "todo bien") is None
    assert salud.registrar_si_cambia(sesion, "camara-01", salud.OK, "otro mensaje") is not None


def test_el_mensaje_se_recorta_a_lo_que_cabe(sesion):
    fila = salud.registrar_si_cambia(sesion, "camara-01", salud.ERROR, "x" * 900)
    assert len(fila.mensaje) == 500


def test_un_mensaje_vacio_se_guarda_como_nulo(sesion):
    assert salud.registrar_si_cambia(sesion, "camara-01", salud.OK, "").mensaje is None


def test_sondear_mysql_reporta_el_fallo_sin_reventar(sesion):
    sesion.close()
    sesion.bind = None
    resultado = salud.sondear_mysql(sesion)
    assert resultado["estado"] == salud.ERROR


async def test_sondear_todo_se_detiene_si_mysql_no_responde(sesion, ajustes, monkeypatch):
    monkeypatch.setattr(salud, "sondear_mysql",
                        lambda _s: {"componente": "mysql", "estado": salud.ERROR,
                                    "mensaje": "caido", "verificado_en": dt.datetime.now()})
    resultado = await salud.sondear_todo(sesion, ajustes)
    assert resultado["estado"] == salud.ERROR
    assert [c["componente"] for c in resultado["componentes"]] == ["mysql"]


# ---------- Modulo auditoria ----------

def test_auditoria_acepta_detalle_vacio(sesion):
    fila = auditoria.registrar(sesion, entidad="configuracion", accion="revisar")
    sesion.commit()
    assert fila.id is not None
    assert fila.detalle is None
    assert fila.entidad_id is None


def test_la_auditoria_no_se_puede_modificar(sesion):
    """El trigger del esquema lo impide, no la aplicacion (HU-16, criterio 3)."""
    from sqlalchemy.exc import OperationalError

    auditoria.registrar(sesion, entidad="pesada", accion="registrar_pesada")
    sesion.commit()
    with pytest.raises(OperationalError, match="solo insercion"):
        sesion.execute(text("DELETE FROM auditoria"))


# ---------- Adaptador de bascula ----------

async def test_leer_bascula_usa_los_ajustes(ajustes):
    lectura = await pesadas.leer_bascula(ajustes, "BASCULA-09")
    assert lectura.bascula_id == "BASCULA-09"
    assert isinstance(lectura, bascula.LecturaBascula)
