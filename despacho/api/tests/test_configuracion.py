"""Tolerancias por producto. HU-04.

Las pruebas corren contra MySQL de verdad porque los limites de la tolerancia
viven en los CHECK del esquema y en el tipo DECIMAL(8,2), y ninguno de los dos
sobrevive a una base sustituta.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app import configuracion as servicio
from app.models import Auditoria, Configuracion, Usuario
from tests.conftest import (PRODUCTO, PRODUCTO_NEGRA, TOLERANCIA_KG,
                            TOLERANCIA_PCT, TOLERANCIA_PCT_NEGRA)


@pytest.fixture()
def admin(sesion):
    from app import usuarios
    return usuarios.crear(sesion, "Admin", "admin@quinor.local",
                          "administrador", "clave-admin-de-prueba")


# ------------------------------------------------------ lectura de lo sembrado
def test_el_esquema_siembra_los_tres_productos(sesion):
    """Sin filas sembradas, HU-03 no tendria contra que comparar en el Sprint 2."""
    productos = [c.producto for c in servicio.listar(sesion)]
    assert len(productos) == 3
    assert PRODUCTO in productos
    assert productos == sorted(productos)


def test_obtener_trae_kg_y_porcentaje(sesion):
    fila = servicio.obtener(sesion, PRODUCTO)
    assert fila.tolerancia_kg == TOLERANCIA_KG
    assert fila.tolerancia_pct == TOLERANCIA_PCT


def test_obtener_ignora_espacios_alrededor(sesion):
    assert servicio.obtener(sesion, f"  {PRODUCTO}  ").producto == PRODUCTO


def test_un_producto_sin_configurar_se_avisa(sesion):
    with pytest.raises(servicio.ProductoNoConfigurado):
        servicio.obtener(sesion, "Kiwicha")


def test_cada_producto_tiene_su_propia_tolerancia(sesion):
    """Es el sentido de la historia: ajustar la sensibilidad por tipo de producto."""
    assert servicio.obtener(sesion, PRODUCTO_NEGRA).tolerancia_pct == TOLERANCIA_PCT_NEGRA
    assert servicio.obtener(sesion, PRODUCTO).tolerancia_pct == TOLERANCIA_PCT


# ---------------------------------------------------- criterio 1: kg y porcentaje
def test_editar_los_dos_campos(sesion, admin):
    fila = servicio.actualizar(sesion, PRODUCTO, Decimal("80"), Decimal("1.25"), admin.id)
    assert fila.tolerancia_kg == Decimal("80.00")
    assert fila.tolerancia_pct == Decimal("1.25")


def test_editar_solo_los_kg_no_toca_el_porcentaje(sesion, admin):
    """Ajustar un campo no obliga a reescribir el otro: asi se usa en la practica."""
    fila = servicio.actualizar(sesion, PRODUCTO, Decimal("120"), None, admin.id)
    assert fila.tolerancia_kg == Decimal("120.00")
    assert fila.tolerancia_pct == TOLERANCIA_PCT


def test_editar_solo_el_porcentaje_no_toca_los_kg(sesion, admin):
    fila = servicio.actualizar(sesion, PRODUCTO, None, Decimal("2"), admin.id)
    assert fila.tolerancia_kg == TOLERANCIA_KG
    assert fila.tolerancia_pct == Decimal("2.00")


def test_el_cambio_se_persiste(sesion, admin):
    servicio.actualizar(sesion, PRODUCTO, Decimal("77"), None, admin.id)
    sesion.expunge_all()
    assert servicio.obtener(sesion, PRODUCTO).tolerancia_kg == Decimal("77.00")


def test_editar_un_producto_no_altera_a_los_demas(sesion, admin):
    servicio.actualizar(sesion, PRODUCTO, Decimal("10"), Decimal("0.10"), admin.id)
    otra = servicio.obtener(sesion, PRODUCTO_NEGRA)
    assert otra.tolerancia_kg == TOLERANCIA_KG
    assert otra.tolerancia_pct == TOLERANCIA_PCT_NEGRA


@pytest.mark.parametrize("entrada,esperado", [
    ("45.678", Decimal("45.68")),        # HALF_UP, como el peso de HU-01
    ("45.674", Decimal("45.67")),
    (45.5, Decimal("45.50")),
    ("45", Decimal("45.00")),
    (0, Decimal("0.00")),                # cero es valido: tolerancia nula
])
def test_los_kg_se_guardan_con_dos_decimales(sesion, admin, entrada, esperado):
    fila = servicio.actualizar(sesion, PRODUCTO, entrada, None, admin.id)
    assert fila.tolerancia_kg == esperado


def test_editar_un_producto_inexistente(sesion, admin):
    with pytest.raises(servicio.ProductoNoConfigurado):
        servicio.actualizar(sesion, "Kiwicha", Decimal("10"), None, admin.id)


@pytest.mark.parametrize("kg,pct", [
    (Decimal("-1"), None),               # los CHECK del esquema dicen lo mismo
    (None, Decimal("-0.01")),
    (None, Decimal("100.01")),
    (Decimal("1000000"), None),          # no cabe en DECIMAL(8,2)
])
def test_valores_fuera_de_rango_se_rechazan(sesion, admin, kg, pct):
    with pytest.raises(servicio.ToleranciaInvalida):
        servicio.actualizar(sesion, PRODUCTO, kg, pct, admin.id)


def test_un_valor_que_no_es_numero_se_rechaza(sesion, admin):
    """Lo que llega de un formulario es texto: aqui es donde se para."""
    with pytest.raises(servicio.ToleranciaInvalida):
        servicio.actualizar(sesion, PRODUCTO, "mucho", None, admin.id)


def test_un_valor_invalido_no_deja_el_cambio_a_medias(sesion, admin):
    with pytest.raises(servicio.ToleranciaInvalida):
        servicio.actualizar(sesion, PRODUCTO, Decimal("90"), Decimal("200"), admin.id)
    sesion.expunge_all()
    fila = servicio.obtener(sesion, PRODUCTO)
    assert fila.tolerancia_kg == TOLERANCIA_KG
    assert fila.tolerancia_pct == TOLERANCIA_PCT


# ------------------------------------------- criterio 3: usuario y fecha del cambio
def test_la_fila_guarda_quien_y_cuando(sesion, admin):
    antes = servicio.obtener(sesion, PRODUCTO).fecha
    fila = servicio.actualizar(sesion, PRODUCTO, Decimal("90"), None, admin.id)
    assert fila.actualizado_por == admin.id
    assert fila.fecha >= antes


def test_el_cambio_queda_en_auditoria_con_los_valores_de_antes_y_despues(sesion, admin):
    """La fila solo recuerda el ultimo cambio; el historial esta en auditoria."""
    servicio.actualizar(sesion, PRODUCTO, Decimal("90"), Decimal("0.90"), admin.id)
    registro = sesion.scalars(
        select(Auditoria).where(Auditoria.accion == "editar_tolerancia")).one()
    assert registro.usuario_id == admin.id
    assert registro.entidad == "configuracion"
    assert registro.detalle["producto"] == PRODUCTO
    assert registro.detalle["antes"] == {"kg": "50.00", "pct": "0.50"}
    assert registro.detalle["despues"] == {"kg": "90.00", "pct": "0.90"}


def test_el_historial_conserva_los_cambios_intermedios(sesion, admin):
    for kg in ("60", "70", "80"):
        servicio.actualizar(sesion, PRODUCTO, Decimal(kg), None, admin.id)
    cambios = servicio.historial(sesion, PRODUCTO)
    assert len(cambios) == 3
    # Del mas reciente al mas antiguo: el ultimo cambio es el primero de la lista.
    assert [c.detalle["despues"]["kg"] for c in cambios] == ["80.00", "70.00", "60.00"]


def test_el_historial_es_por_producto(sesion, admin):
    servicio.actualizar(sesion, PRODUCTO, Decimal("60"), None, admin.id)
    servicio.actualizar(sesion, PRODUCTO_NEGRA, Decimal("70"), None, admin.id)
    assert len(servicio.historial(sesion, PRODUCTO)) == 1
    assert len(servicio.historial(sesion, PRODUCTO_NEGRA)) == 1
    assert len(servicio.historial(sesion)) == 2


def test_un_cambio_que_no_cambia_nada_no_ensucia_la_auditoria(sesion, admin):
    """Llenarla de filas identicas la vuelve inutil justo cuando hay que leerla."""
    servicio.actualizar(sesion, PRODUCTO, TOLERANCIA_KG, TOLERANCIA_PCT, admin.id)
    assert servicio.historial(sesion, PRODUCTO) == []
    assert servicio.obtener(sesion, PRODUCTO).actualizado_por is None


def test_la_auditoria_de_tolerancias_no_se_puede_borrar(sesion, admin):
    """El trigger del esquema protege la evidencia del criterio 3."""
    from sqlalchemy.exc import OperationalError

    servicio.actualizar(sesion, PRODUCTO, Decimal("90"), None, admin.id)
    with pytest.raises(OperationalError):
        sesion.execute(
            Auditoria.__table__.delete().where(Auditoria.accion == "editar_tolerancia"))
        sesion.commit()
    sesion.rollback()


def test_los_nombres_de_los_autores_se_resuelven_de_una_vez(sesion, admin):
    servicio.actualizar(sesion, PRODUCTO, Decimal("90"), None, admin.id)
    cambios = servicio.historial(sesion, PRODUCTO)
    assert servicio.nombres_de(sesion, {c.usuario_id for c in cambios}) == {admin.id: "Admin"}


def test_sin_autores_no_se_consulta_la_tabla(sesion):
    assert servicio.nombres_de(sesion, set()) == {}
    assert servicio.nombres_de(sesion, {None}) == {}


def test_el_autor_del_ultimo_cambio_se_puede_leer(sesion, admin):
    fila = servicio.actualizar(sesion, PRODUCTO, Decimal("90"), None, admin.id)
    sesion.expunge_all()
    fila = servicio.obtener(sesion, PRODUCTO)
    assert fila.autor.nombre == "Admin"


def test_no_se_puede_borrar_un_usuario_que_edito_una_tolerancia(sesion, admin):
    """ON DELETE RESTRICT: la constancia del criterio 3 tiene que seguir apuntando
    a alguien identificable."""
    from sqlalchemy.exc import IntegrityError

    servicio.actualizar(sesion, PRODUCTO, Decimal("90"), None, admin.id)
    with pytest.raises(IntegrityError):
        sesion.execute(Usuario.__table__.delete().where(Usuario.id == admin.id))
        sesion.commit()
    sesion.rollback()


# --------------------------------------------------- RN-01: la mas restrictiva
@pytest.mark.parametrize("peso,esperado", [
    # 0,5 % de 20 000 son 100 kg: mandan los 50 kg configurados.
    (Decimal("20000.00"), Decimal("50.00")),
    # 0,5 % de 10 000 son exactamente 50: empatan y da igual cual se tome.
    (Decimal("10000.00"), Decimal("50.00")),
    # 0,5 % de 5 000 son 25 kg: ahora manda el porcentaje.
    (Decimal("5000.00"), Decimal("25.00")),
    (Decimal("1000.00"), Decimal("5.00")),
])
def test_se_aplica_la_tolerancia_mas_restrictiva(sesion, peso, esperado):
    assert servicio.tolerancia_de(sesion, PRODUCTO, peso) == esperado


def test_el_equivalente_del_porcentaje_se_redondea_a_dos_decimales(sesion):
    fila = servicio.obtener(sesion, PRODUCTO)
    # 0,5 % de 3 333,33 son 16,66665 kg.
    assert fila.tolerancia_efectiva_kg(Decimal("3333.33")) == Decimal("16.67")


def test_una_tolerancia_en_cero_no_admite_diferencia(sesion, admin):
    servicio.actualizar(sesion, PRODUCTO, Decimal("0"), None, admin.id)
    assert servicio.tolerancia_de(sesion, PRODUCTO, Decimal("20000")) == Decimal("0.00")


def test_subir_el_porcentaje_cambia_la_tolerancia_efectiva(sesion, admin):
    """Es el objetivo de la historia: ajustar la sensibilidad sin tocar codigo."""
    antes = servicio.tolerancia_de(sesion, PRODUCTO, Decimal("5000"))
    servicio.actualizar(sesion, PRODUCTO, None, Decimal("0.20"), admin.id)
    assert servicio.tolerancia_de(sesion, PRODUCTO, Decimal("5000")) < antes


def test_la_tolerancia_de_un_producto_sin_configurar(sesion):
    with pytest.raises(servicio.ProductoNoConfigurado):
        servicio.tolerancia_de(sesion, "Kiwicha", Decimal("1000"))


def test_validar_acepta_los_limites_exactos():
    servicio.validar(Decimal("0"), Decimal("0"))
    servicio.validar(servicio.KG_MAXIMO, Decimal("100"))


def test_el_modelo_calcula_sin_tocar_la_base():
    """La regla es una funcion del modelo: HU-03 podra evaluarla en memoria."""
    fila = Configuracion(producto="X", tolerancia_kg=Decimal("50.00"),
                         tolerancia_pct=Decimal("1.00"), canales_por_severidad={})
    assert fila.tolerancia_efectiva_kg(Decimal("2000")) == Decimal("20.00")
    assert fila.tolerancia_efectiva_kg(Decimal("200000")) == Decimal("50.00")
