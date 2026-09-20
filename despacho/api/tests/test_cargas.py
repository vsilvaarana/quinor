"""Marca de inicio de carga. Apoyo del criterio 1 de HU-06.

Sin esta marca, la ventana del clip solo puede empezar en el cierre, y una carga
de veinte minutos se quedaria con los ultimos cinco. Aqui se comprueba que la
marca se abre, que la consume la pesada y que sobrevive donde tiene que estar.
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from app import cargas
from app.models import Auditoria, Carga


@pytest.fixture()
def admin(sesion):
    from app import usuarios
    return usuarios.crear(sesion, "Admin", "admin@quinor.local",
                          "administrador", "clave-admin-de-prueba")


# --------------------------------------------------------------- abrir
def test_abrir_una_carga_deja_la_marca(sesion, orden, admin):
    carga = cargas.abrir(sesion, orden, "BASCULA-01", admin.id)

    assert carga.id is not None
    assert carga.abierta() is True
    assert carga.orden_id == orden.id
    assert carga.usuario_id == admin.id


def test_la_apertura_queda_en_auditoria(sesion, orden, admin):
    cargas.abrir(sesion, orden, "BASCULA-01", admin.id)
    registro = sesion.scalars(
        select(Auditoria).where(Auditoria.accion == "abrir_carga")).one()

    assert registro.usuario_id == admin.id
    assert registro.detalle["numero_orden"] == orden.numero_orden
    assert registro.detalle["inicio"]


def test_una_orden_no_puede_tener_dos_cargas_abiertas(sesion, orden, admin):
    """Dos marcas abiertas dejarian a la pesada sin saber cual consumir."""
    cargas.abrir(sesion, orden, "BASCULA-01", admin.id)
    with pytest.raises(cargas.CargaYaAbierta):
        cargas.abrir(sesion, orden, "BASCULA-01", admin.id)


def test_la_base_tambien_lo_impide(sesion, orden, admin):
    """El indice unico parcial protege aunque dos procesos marquen a la vez."""
    from sqlalchemy.exc import IntegrityError

    cargas.abrir(sesion, orden, "BASCULA-01", admin.id)
    with pytest.raises(IntegrityError):
        sesion.add(Carga(orden_id=orden.id, bascula_id="BASCULA-02",
                         inicio=dt.datetime.now()))
        sesion.commit()
    sesion.rollback()


def test_se_puede_abrir_otra_vez_despues_de_cerrarla(sesion, orden, admin):
    """Un mismo camion puede volver a la rampa el mismo dia."""
    from app.models import Pesada

    primera = cargas.abrir(sesion, orden, "BASCULA-01", admin.id)
    pesada = Pesada(orden_id=orden.id, bascula_id="BASCULA-01", peso_real_kg=19850,
                    fecha_hora=dt.datetime.now(), origen="bascula")
    sesion.add(pesada)
    sesion.flush()
    cargas.cerrar(sesion, orden.id, pesada)
    sesion.commit()

    segunda = cargas.abrir(sesion, orden, "BASCULA-01", admin.id)
    assert segunda.id != primera.id


def test_una_carga_no_puede_cerrarse_sin_su_pesada(sesion, orden, admin):
    """CHECK del esquema: consumida_en y pesada_id van juntos o no van. Una carga
    cerrada por nadie dejaria la ventana del clip sin explicacion."""
    from sqlalchemy.exc import IntegrityError, OperationalError

    carga = cargas.abrir(sesion, orden, "BASCULA-01", admin.id)
    with pytest.raises((IntegrityError, OperationalError)):
        sesion.execute(Carga.__table__.update().where(Carga.id == carga.id)
                       .values(consumida_en=dt.datetime.now(), pesada_id=None))
        sesion.commit()
    sesion.rollback()


def test_la_carga_abierta_se_encuentra(sesion, orden, admin):
    carga = cargas.abrir(sesion, orden, "BASCULA-01", admin.id)
    assert cargas.abierta_de(sesion, orden.id).id == carga.id


def test_sin_carga_abierta_no_hay_nada_que_encontrar(sesion, orden):
    assert cargas.abierta_de(sesion, orden.id) is None


# --------------------------------------------------------------- cerrar
def test_cerrar_devuelve_el_inicio(sesion, orden, admin):
    inicio = dt.datetime.now().replace(tzinfo=None) - dt.timedelta(minutes=12)
    cargas.abrir(sesion, orden, "BASCULA-01", admin.id, momento=inicio)

    from app.models import Pesada

    pesada = Pesada(orden_id=orden.id, bascula_id="BASCULA-01",
                    peso_real_kg=19850, fecha_hora=dt.datetime.now(), origen="bascula")
    sesion.add(pesada)
    sesion.flush()

    devuelto = cargas.cerrar(sesion, orden.id, pesada)
    sesion.commit()

    assert devuelto == inicio
    assert cargas.abierta_de(sesion, orden.id) is None


def test_cerrar_sin_carga_abierta_no_es_un_error(sesion, orden):
    """La pesada nunca se rechaza por falta de marca: el peso del camion no puede
    perderse porque nadie anoto cuando empezo la carga."""
    assert cargas.cerrar(sesion, orden.id, pesada=None) is None


def test_la_carga_cerrada_apunta_a_su_pesada(sesion, orden, admin):
    from app.models import Pesada

    carga = cargas.abrir(sesion, orden, "BASCULA-01", admin.id)
    pesada = Pesada(orden_id=orden.id, bascula_id="BASCULA-01", peso_real_kg=19850,
                    fecha_hora=dt.datetime.now(), origen="bascula")
    sesion.add(pesada)
    sesion.flush()
    cargas.cerrar(sesion, orden.id, pesada)
    sesion.commit()
    sesion.refresh(carga)

    assert carga.pesada_id == pesada.id
    assert carga.abierta() is False


# --------------------------------------------------------------- listar
def test_listar_trae_abiertas_y_cerradas(sesion, orden, admin):
    cargas.abrir(sesion, orden, "BASCULA-01", admin.id)
    assert len(cargas.listar(sesion)) == 1
    assert len(cargas.listar(sesion, solo_abiertas=True)) == 1


def test_listar_solo_abiertas_excluye_las_cerradas(sesion, orden, admin):
    from app.models import Pesada

    carga = cargas.abrir(sesion, orden, "BASCULA-01", admin.id)
    pesada = Pesada(orden_id=orden.id, bascula_id="BASCULA-01", peso_real_kg=19850,
                    fecha_hora=dt.datetime.now(), origen="bascula")
    sesion.add(pesada)
    sesion.flush()
    cargas.cerrar(sesion, orden.id, pesada)
    sesion.commit()

    assert len(cargas.listar(sesion)) == 1
    assert cargas.listar(sesion, solo_abiertas=True) == []
    assert carga.pesada_id == pesada.id


def test_el_esquema_no_admite_un_inicio_posterior_al_cierre(sesion, orden):
    """CHECK del esquema: una ventana que empieza despues de terminar no existe."""
    from sqlalchemy.exc import IntegrityError, OperationalError

    from app.models import Pesada

    ahora = dt.datetime.now().replace(tzinfo=None)
    with pytest.raises((IntegrityError, OperationalError)):
        sesion.add(Pesada(orden_id=orden.id, bascula_id="BASCULA-01",
                          peso_real_kg=100, fecha_hora=ahora,
                          inicio_carga=ahora + dt.timedelta(minutes=5),
                          origen="bascula"))
        sesion.commit()
    sesion.rollback()
