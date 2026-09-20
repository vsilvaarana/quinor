"""Criterio 1 de HU-10: a quien se avisa y con que urgencia.

  1. La notificacion se envia por correo en los tres niveles. Alta: a
     supervisores y administradores, con asunto marcado y prioridad alta;
     Media: a supervisores; Baja: a supervisores, con prioridad normal.
"""
from __future__ import annotations

import pytest

from app.destinatarios import (ADMINISTRADOR, ALTA, BAJA, CONSULTA, MEDIA,
                               PRIORIDAD_ALTA, PRIORIDAD_NORMAL, Persona,
                               repartir, roles_de)


def personas() -> list[Persona]:
    return [
        Persona("Ana", "ana@quinor.com.pe", "supervisor"),
        Persona("Luis", "luis@quinor.com.pe", "supervisor"),
        Persona("Rosa", "rosa@quinor.com.pe", "administrador"),
        Persona("Auditor", "auditor@quinor.com.pe", "consulta"),
    ]


def test_la_alta_va_a_supervisores_y_administradores():
    reparto = repartir(ALTA, personas())
    assert set(reparto.destinatarios) == {"ana@quinor.com.pe",
                                          "luis@quinor.com.pe",
                                          "rosa@quinor.com.pe"}


def test_la_media_solo_va_a_supervisores():
    reparto = repartir(MEDIA, personas())
    assert set(reparto.destinatarios) == {"ana@quinor.com.pe",
                                          "luis@quinor.com.pe"}


def test_la_baja_solo_va_a_supervisores():
    reparto = repartir(BAJA, personas())
    assert set(reparto.destinatarios) == {"ana@quinor.com.pe",
                                          "luis@quinor.com.pe"}


def test_solo_la_alta_sale_con_prioridad():
    """"Alta: con asunto marcado y prioridad alta". La Baja, normal."""
    assert repartir(ALTA, personas()).prioridad == PRIORIDAD_ALTA
    assert repartir(ALTA, personas()).urgente is True
    for nivel in (MEDIA, BAJA):
        assert repartir(nivel, personas()).prioridad == PRIORIDAD_NORMAL
        assert repartir(nivel, personas()).urgente is False


def test_el_rol_consulta_no_recibe_alertas_de_ningun_nivel():
    """Es un rol de solo lectura del dashboard: no le toca actuar sobre una
    carga, y meterlo en la lista solo conseguiria que la ignorase."""
    for nivel in (ALTA, MEDIA, BAJA):
        assert "auditor@quinor.com.pe" not in repartir(nivel, personas()).destinatarios
        assert CONSULTA not in roles_de(nivel)


def test_un_usuario_dado_de_baja_deja_de_recibir():
    gente = personas() + [Persona("Jorge", "jorge@quinor.com.pe", "supervisor",
                                  activo=False)]
    assert "jorge@quinor.com.pe" not in repartir(ALTA, gente).destinatarios


def test_una_direccion_repetida_se_manda_una_sola_vez():
    """Dos filas con el mismo correo no son dos correos. La base tiene una clave
    unica, pero una diferencia de mayusculas la esquiva."""
    gente = [Persona("Ana", "ana@quinor.com.pe", "supervisor"),
             Persona("Ana turno noche", "ANA@Quinor.com.pe ", "administrador")]
    assert repartir(ALTA, gente).destinatarios == ("ana@quinor.com.pe",)


def test_una_severidad_desconocida_se_trata_como_alta():
    """Si el sistema no sabe clasificar algo, es mejor que lo vea quien puede
    actuar. El error contrario, mandarlo como Baja, lo deja sin leer."""
    reparto = repartir("rarisima", personas())
    assert reparto.roles == (  # los mismos que la Alta
        roles_de(ALTA))
    assert reparto.urgente is True
    assert ADMINISTRADOR in reparto.roles


def test_sin_severidad_tambien_se_avisa():
    """Un evento sin clasificar es justo el que conviene mirar."""
    reparto = repartir(None, personas())
    assert reparto.hay_a_quien_avisar is True
    assert reparto.severidad == ALTA


def test_sin_nadie_activo_lo_dice_en_lugar_de_fingir():
    reparto = repartir(ALTA, [Persona("Jorge", "j@quinor.com.pe", "supervisor",
                                      activo=False)])
    assert reparto.hay_a_quien_avisar is False
    assert reparto.destinatarios == ()


def test_una_direccion_vacia_no_entra_en_la_lista():
    gente = [Persona("Sin correo", "   ", "supervisor"),
             Persona("Ana", "ana@quinor.com.pe", "supervisor")]
    assert repartir(MEDIA, gente).destinatarios == ("ana@quinor.com.pe",)


@pytest.mark.parametrize("nivel", [ALTA, MEDIA, BAJA])
def test_los_tres_niveles_tienen_destinatario(nivel):
    """El criterio dice "en los tres niveles": ninguno se queda sin salir."""
    assert repartir(nivel, personas()).hay_a_quien_avisar is True
