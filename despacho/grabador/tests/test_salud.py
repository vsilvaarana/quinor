"""Registro de la desconexion de camaras. HU-05, criterio 3.

Contra MySQL de verdad: la tabla la define el esquema del orquestador y es la
misma que lee GET /salud. Probarlo contra una base sustituta no diria nada sobre
si las dos piezas encajan.
"""
from __future__ import annotations

from sqlalchemy import func, select

from app import salud
from tests.conftest import CAMARA_PRUEBA


def cuantas(motor, componente: str) -> int:
    with motor.connect() as conexion:
        return conexion.execute(
            select(func.count()).select_from(salud.salud_componente)
            .where(salud.salud_componente.c.componente == componente)
        ).scalar_one()


def test_una_camara_caida_queda_registrada(motor):
    assert salud.camara_desconectada(motor, CAMARA_PRUEBA, "se perdio la conexion RTSP")
    fila = salud.ultimo(motor, CAMARA_PRUEBA)
    assert fila["estado"] == "error"
    assert "RTSP" in fila["mensaje"]


def test_el_motivo_de_ffmpeg_se_conserva(motor):
    """Es lo que explica que paso: sin el, el panel solo dice que algo fallo."""
    salud.camara_desconectada(motor, CAMARA_PRUEBA,
                              "Connection timed out | Server returned 404")
    assert "404" in salud.ultimo(motor, CAMARA_PRUEBA)["mensaje"]


def test_sin_motivo_se_escribe_uno_entendible(motor):
    salud.camara_desconectada(motor, CAMARA_PRUEBA, "")
    assert "no pudo reconectar" in salud.ultimo(motor, CAMARA_PRUEBA)["mensaje"]


def test_una_camara_que_vuelve_queda_registrada(motor):
    salud.camara_desconectada(motor, CAMARA_PRUEBA, "caida")
    assert salud.camara_conectada(motor, CAMARA_PRUEBA, "grabando en segmentos de 60 s")
    assert salud.ultimo(motor, CAMARA_PRUEBA)["estado"] == "ok"


def test_solo_se_inserta_cuando_algo_cambia(motor):
    """Una camara caida de noche generaria miles de filas identicas y enterraria
    justo lo que interesa: el minuto en que se cayo."""
    salud.camara_desconectada(motor, CAMARA_PRUEBA, "misma causa")
    for _ in range(20):
        assert salud.camara_desconectada(motor, CAMARA_PRUEBA, "misma causa") is False
    assert cuantas(motor, CAMARA_PRUEBA) == 1


def test_un_motivo_distinto_si_se_registra(motor):
    salud.camara_desconectada(motor, CAMARA_PRUEBA, "timeout")
    salud.camara_desconectada(motor, CAMARA_PRUEBA, "404 del servidor")
    assert cuantas(motor, CAMARA_PRUEBA) == 2


def test_la_ida_y_la_vuelta_quedan_las_dos(motor):
    salud.camara_desconectada(motor, CAMARA_PRUEBA, "caida")
    salud.camara_conectada(motor, CAMARA_PRUEBA, "grabando")
    salud.camara_desconectada(motor, CAMARA_PRUEBA, "caida")
    assert cuantas(motor, CAMARA_PRUEBA) == 3


def test_cada_camara_lleva_su_propio_estado(motor):
    salud.camara_desconectada(motor, "camara-01", "caida")
    salud.camara_conectada(motor, "camara-02", "grabando")
    assert salud.ultimo(motor, "camara-01")["estado"] == "error"
    assert salud.ultimo(motor, "camara-02")["estado"] == "ok"


def test_un_componente_sin_historial_no_devuelve_nada(motor):
    assert salud.ultimo(motor, "camara-99") is None


def test_un_mensaje_larguisimo_no_rompe_la_insercion(motor):
    """La columna admite 500 caracteres y ffmpeg puede ser mas hablador."""
    salud.camara_desconectada(motor, CAMARA_PRUEBA, "x" * 900)
    assert len(salud.ultimo(motor, CAMARA_PRUEBA)["mensaje"]) == 500


def test_el_estado_del_disco_tambien_se_registra(motor):
    salud.registrar_si_cambia(motor, salud.COMPONENTE_DISCO, salud.ERROR,
                              "disco al limite")
    assert salud.ultimo(motor, salud.COMPONENTE_DISCO)["estado"] == "error"


def test_la_fila_queda_donde_la_lee_el_orquestador(motor):
    """Misma tabla y mismo nombre de componente que usa GET /salud."""
    salud.camara_desconectada(motor, CAMARA_PRUEBA, "caida")
    with motor.connect() as conexion:
        fila = conexion.exec_driver_sql(
            "SELECT componente, estado FROM v_salud_actual WHERE componente = %s",
            (CAMARA_PRUEBA,)).mappings().one()
    assert fila["estado"] == "error"
