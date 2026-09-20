"""Evento de discrepancia. HU-03.

La comparacion es una resta, pero de ella depende que el faltante se vea el
mismo dia o cuando reclama el cliente. Las pruebas cubren la frontera exacta de
la tolerancia, el faltante y el sobrepeso, la idempotencia por pesada y el caso
en que el producto no tiene tolerancia configurada.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app import configuracion, eventos
from app.models import Auditoria, Evento, Pesada
from tests.conftest import PRODUCTO, TOLERANCIA_KG


@pytest.fixture()
def admin(sesion):
    from app import usuarios
    return usuarios.crear(sesion, "Admin", "admin@quinor.local",
                          "administrador", "clave-admin-de-prueba")


@pytest.fixture()
def pesar(sesion, orden):
    """Registra una pesada con el peso que pida la prueba, sin tocar la bascula."""
    def _pesar(peso: str | Decimal, momento: dt.datetime | None = None) -> Pesada:
        pesada = Pesada(
            orden_id=orden.id,
            bascula_id="BASCULA-01",
            peso_real_kg=Decimal(str(peso)),
            fecha_hora=momento or dt.datetime.now().replace(tzinfo=None),
            origen="bascula",
        )
        sesion.add(pesada)
        sesion.commit()
        sesion.refresh(pesada)
        return pesada
    return _pesar


# --------------------------------------------------- criterio 2: las cifras
@pytest.mark.parametrize("real,esperado,kg,pct", [
    ("19850.00", "20000.00", "-150.00", "-0.75"),     # faltante de tres sacos
    ("20150.00", "20000.00", "150.00", "0.75"),       # sobrepeso
    ("20000.00", "20000.00", "0.00", "0.00"),
    ("19999.99", "20000.00", "-0.01", "-0.00"),
])
def test_la_diferencia_se_calcula_en_kg_y_en_porcentaje(real, esperado, kg, pct):
    d_kg, d_pct = eventos.diferencias(Decimal(real), Decimal(esperado))
    assert d_kg == Decimal(kg)
    assert d_pct == Decimal(pct)


def test_el_faltante_queda_con_signo_negativo():
    """Distinguir faltante de sobrepeso es lo que orienta la investigacion."""
    kg, _ = eventos.diferencias(Decimal("19000"), Decimal("20000"))
    assert kg < 0


def test_el_porcentaje_se_recorta_al_maximo_de_la_columna():
    """DECIMAL(6,2) no admite mas. Perder precision es mejor que perder el aviso."""
    _, pct = eventos.diferencias(Decimal("50000"), Decimal("1.00"))
    assert pct == eventos.PCT_MAXIMO


# --------------------------------------------------- criterio 1: la frontera
@pytest.mark.parametrize("diferencia,esperado", [
    ("49.99", False),
    ("50.00", False),      # igual a la tolerancia todavia se acepta
    ("50.01", True),
    ("-50.00", False),
    ("-50.01", True),      # el faltante se mide en valor absoluto
])
def test_solo_se_pasa_de_la_tolerancia_estrictamente(diferencia, esperado):
    assert eventos.hay_discrepancia(Decimal(diferencia), TOLERANCIA_KG) is esperado


def test_una_carga_dentro_de_tolerancia_no_genera_evento(sesion, orden, pesar):
    pesada = pesar("19960.00")          # faltan 40 kg, la tolerancia son 50
    assert eventos.evaluar(sesion, pesada, orden) is None
    assert sesion.scalars(select(Evento)).all() == []


def test_una_carga_fuera_de_tolerancia_genera_evento_pendiente(sesion, orden, pesar):
    pesada = pesar("19850.00")          # faltan 150 kg
    evento = eventos.evaluar(sesion, pesada, orden)
    assert evento is not None
    assert evento.estado == "pendiente"          # criterio 1
    assert evento.diferencia_kg == Decimal("-150.00")
    assert evento.diferencia_pct == Decimal("-0.75")
    assert evento.pesada_id == pesada.id


def test_el_sobrepeso_tambien_genera_evento(sesion, orden, pesar):
    """Un contenedor mas pesado de lo planificado apunta a sustitucion igual
    que uno mas ligero."""
    evento = eventos.evaluar(sesion, pesar("20200.00"), orden)
    assert evento is not None
    assert evento.es_faltante() is False


def test_justo_en_la_frontera_no_hay_evento(sesion, orden, pesar):
    assert eventos.evaluar(sesion, pesar("19950.00"), orden) is None


def test_un_kilo_mas_alla_de_la_frontera_si(sesion, orden, pesar):
    assert eventos.evaluar(sesion, pesar("19949.99"), orden) is not None


def test_las_columnas_de_sprints_posteriores_nacen_vacias(sesion, orden, pesar):
    evento = eventos.evaluar(sesion, pesar("19850.00"), orden)
    assert evento.sacos_contados is None          # HU-07
    assert evento.personas_detectadas is None     # HU-08
    assert evento.severidad is None               # HU-09
    assert evento.clip_url is None                # HU-06


# ------------------------------------------------------------ idempotencia
def test_reprocesar_la_misma_pesada_no_duplica_el_evento(sesion, orden, pesar):
    """Para eso esta la clave unica sobre pesada_id: el supervisor recibe un
    aviso por carga, no uno por reintento."""
    pesada = pesar("19850.00")
    primero = eventos.evaluar(sesion, pesada, orden)
    segundo = eventos.evaluar(sesion, pesada, orden)
    assert primero.id == segundo.id
    assert len(sesion.scalars(select(Evento)).all()) == 1


def test_la_base_impide_dos_eventos_por_pesada(sesion, orden, pesar):
    from sqlalchemy.exc import IntegrityError

    pesada = pesar("19850.00")
    eventos.evaluar(sesion, pesada, orden)
    with pytest.raises(IntegrityError):
        sesion.add(Evento(pesada_id=pesada.id, diferencia_kg=Decimal("-1"),
                          diferencia_pct=Decimal("-1"), estado="pendiente",
                          creado_en=dt.datetime.now()))
        sesion.commit()
    sesion.rollback()


def test_dos_pesadas_distintas_generan_dos_eventos(sesion, orden, pesar):
    eventos.evaluar(sesion, pesar("19850.00"), orden)
    eventos.evaluar(sesion, pesar("19800.00"), orden)
    assert len(sesion.scalars(select(Evento)).all()) == 2


# ------------------------------------------------------------- la auditoria
def test_el_evento_queda_en_auditoria_con_las_cifras_que_lo_motivaron(sesion, orden, pesar):
    evento = eventos.evaluar(sesion, pesar("19850.00"), orden)
    registro = sesion.scalars(
        select(Auditoria).where(Auditoria.accion == "crear_evento")).one()
    assert registro.entidad_id == evento.id
    detalle = registro.detalle
    assert detalle["numero_orden"] == orden.numero_orden
    assert detalle["peso_esperado_kg"] == "20000.00"
    assert detalle["peso_real_kg"] == "19850.00"
    assert detalle["diferencia_kg"] == "-150.00"
    assert detalle["diferencia_pct"] == "-0.75"
    # Contra que umbral se juzgo aquella carga, aunque manana se cambie.
    assert detalle["tolerancia_aplicada_kg"] == "50.00"


def test_cambiar_la_tolerancia_no_reescribe_los_eventos_ya_creados(sesion, orden, pesar, admin):
    eventos.evaluar(sesion, pesar("19850.00"), orden)
    configuracion.actualizar(sesion, PRODUCTO, Decimal("500"), None, admin.id)
    registro = sesion.scalars(
        select(Auditoria).where(Auditoria.accion == "crear_evento")).one()
    assert registro.detalle["tolerancia_aplicada_kg"] == "50.00"


# --------------------------------------------------------- HU-04 de por medio
def test_la_tolerancia_aplicada_es_la_de_la_RN_01(sesion, orden, pesar, admin):
    """Con una orden de 20 000 kg mandan los 50 kg; al subir el porcentaje al
    5 % siguen mandando los 50, pero al bajar los kg manda el porcentaje."""
    configuracion.actualizar(sesion, PRODUCTO, Decimal("500"), Decimal("0.50"), admin.id)
    # 0,5 % de 20 000 son 100 kg, por debajo de los 500 configurados.
    assert eventos.evaluar(sesion, pesar("19950.00"), orden) is None     # faltan 50
    assert eventos.evaluar(sesion, pesar("19800.00"), orden) is not None  # faltan 200


def test_subir_la_tolerancia_deja_de_generar_eventos(sesion, orden, pesar, admin):
    configuracion.actualizar(sesion, PRODUCTO, Decimal("500"), Decimal("100"), admin.id)
    assert eventos.evaluar(sesion, pesar("19850.00"), orden) is None


def test_bajar_la_tolerancia_los_genera_antes(sesion, orden, pesar, admin):
    configuracion.actualizar(sesion, PRODUCTO, Decimal("10"), Decimal("100"), admin.id)
    assert eventos.evaluar(sesion, pesar("19980.00"), orden) is not None


# ---------------------------------------- sin tolerancia configurada
@pytest.fixture()
def sin_tolerancia(sesion, orden):
    """Deja al producto de la orden sin fila en configuracion."""
    sesion.execute(text("DELETE FROM configuracion WHERE producto = :p"),
                   {"p": orden.producto})
    sesion.commit()
    yield
    sesion.execute(
        text("INSERT INTO configuracion (producto, tolerancia_kg, tolerancia_pct, "
             "canales_por_severidad) VALUES (:p, 50.00, 0.50, JSON_OBJECT())"),
        {"p": orden.producto})
    sesion.commit()


def test_sin_tolerancia_no_se_inventa_un_evento(sesion, orden, pesar, sin_tolerancia):
    """Y se distingue de una carga limpia: quien llama recibe un aviso explicito."""
    with pytest.raises(eventos.SinToleranciaConfigurada):
        eventos.evaluar(sesion, pesar("19850.00"), orden)
    assert sesion.scalars(select(Evento)).all() == []


def test_sin_tolerancia_el_hueco_queda_a_la_vista(sesion, orden, pesar, sin_tolerancia):
    """Callarse seria lo peor: dejaria creer que esa carga se reviso y salio limpia."""
    from app import salud

    with pytest.raises(eventos.SinToleranciaConfigurada):
        eventos.evaluar(sesion, pesar("19850.00"), orden)
    registro = sesion.scalars(
        select(Auditoria).where(Auditoria.accion == "incidencia_sin_tolerancia")).one()
    assert registro.detalle["producto"] == orden.producto

    estado = {c["componente"]: c for c in salud.estado_actual(sesion)}
    assert estado["configuracion"]["estado"] == "error"
    assert "no tiene tolerancia configurada" in estado["configuracion"]["mensaje"]


def test_la_pesada_se_recupera_cuando_se_configura_la_tolerancia(sesion, orden, pesar):
    """El camion no se vuelve a pesar: la pesada ya esta, solo faltaba el umbral."""
    sesion.execute(text("DELETE FROM configuracion WHERE producto = :p"),
                   {"p": orden.producto})
    sesion.commit()
    pesada = pesar("19850.00")
    with pytest.raises(eventos.SinToleranciaConfigurada):
        eventos.evaluar(sesion, pesada, orden)

    sesion.execute(
        text("INSERT INTO configuracion (producto, tolerancia_kg, tolerancia_pct, "
             "canales_por_severidad) VALUES (:p, 50.00, 0.50, JSON_OBJECT())"),
        {"p": orden.producto})
    sesion.commit()
    evento = eventos.reevaluar(sesion, pesada.id)
    assert evento is not None
    assert evento.diferencia_kg == Decimal("-150.00")


def test_reevaluar_una_pesada_inexistente(sesion):
    with pytest.raises(eventos.PesadaNoEncontrada):
        eventos.reevaluar(sesion, 9999)


def test_reevaluar_es_idempotente(sesion, orden, pesar):
    pesada = pesar("19850.00")
    primero = eventos.evaluar(sesion, pesada, orden)
    assert eventos.reevaluar(sesion, pesada.id).id == primero.id


# ------------------------------------------------------------ consultas
def test_listar_devuelve_lo_mas_reciente_primero(sesion, orden, pesar):
    viejo = eventos.evaluar(
        sesion, pesar("19800.00", dt.datetime.now() - dt.timedelta(hours=2)), orden)
    nuevo = eventos.evaluar(sesion, pesar("19700.00"), orden)
    sesion.execute(text("UPDATE evento SET creado_en = :c WHERE id = :i"),
                   {"c": dt.datetime.now() - dt.timedelta(hours=2), "i": viejo.id})
    sesion.commit()
    sesion.expunge_all()
    assert [e.id for e in eventos.listar(sesion)] == [nuevo.id, viejo.id]


def test_listar_filtra_por_estado(sesion, orden, pesar):
    eventos.evaluar(sesion, pesar("19850.00"), orden)
    assert len(eventos.listar(sesion, estado="pendiente")) == 1
    assert eventos.listar(sesion, estado="confirmado") == []


def test_listar_filtra_por_orden(sesion, orden, pesar):
    eventos.evaluar(sesion, pesar("19850.00"), orden)
    assert len(eventos.listar(sesion, numero_orden=orden.numero_orden)) == 1
    assert eventos.listar(sesion, numero_orden="ORD-2026-9999") == []


def test_listar_respeta_el_limite(sesion, orden, pesar):
    for peso in ("19800.00", "19700.00", "19600.00"):
        eventos.evaluar(sesion, pesar(peso), orden)
    assert len(eventos.listar(sesion, limite=2)) == 2


def test_obtener_por_id(sesion, orden, pesar):
    evento = eventos.evaluar(sesion, pesar("19850.00"), orden)
    assert eventos.obtener(sesion, evento.id).id == evento.id
    assert eventos.obtener(sesion, 9999) is None


# ------------------------------------------------------------ la RN-06
def test_un_evento_confirmado_no_vuelve_a_pendiente(sesion, orden, pesar):
    """El trigger del esquema lo impide. HU-13 se apoyara en esto."""
    from sqlalchemy.exc import OperationalError

    evento = eventos.evaluar(sesion, pesar("19850.00"), orden)
    sesion.execute(text("UPDATE evento SET estado = 'confirmado' WHERE id = :i"),
                   {"i": evento.id})
    sesion.commit()
    with pytest.raises(OperationalError):
        sesion.execute(text("UPDATE evento SET estado = 'pendiente' WHERE id = :i"),
                       {"i": evento.id})
        sesion.commit()
    sesion.rollback()
