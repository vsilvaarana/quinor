"""El modelo de verdad. HU-07, criterios 1 y 2.

Estas pruebas cargan los pesos entrenados y analizan video real, asi que se
saltan cuando no estan: entrenarlos lleva minutos y no puede ser un requisito
para correr la suite. Lo que comprueban es lo que ningun modelo falso puede
comprobar, que es el contrato con ultralytics: que el rastreador devuelve
identificadores, que las clases se llaman como el contador espera y que el
conteo de una carga conocida sale bien de punta a punta.

    python -m sim.entrenar --imagenes 200 --epocas 20 --tamano 416
"""
from __future__ import annotations

import pytest

from app.config import Ajustes
from app.analisis import analizar
from sim.rampa_sim import generar_carga
from tests.conftest import PESOS, hay_modelo_entrenado

pytestmark = pytest.mark.skipif(
    not hay_modelo_entrenado(),
    reason="Sin modelo entrenado en modelos/sacos.pt: se genera con sim/entrenar.py")


@pytest.fixture(scope="module")
def ajustes() -> Ajustes:
    return Ajustes(ruta_pesos=PESOS, dispositivo="cpu", salto_de_fotogramas=1)


def test_una_carga_conocida_se_cuenta_bien(ajustes, tmp_path_factory):
    """Cuatro sacos cruzan; el servicio tiene que decir cuatro."""
    carpeta = tmp_path_factory.mktemp("modelo")
    carga = generar_carga(carpeta / "carga.mp4", sacos=4, semilla=11,
                          con_personas=0)

    resultado = analizar(ajustes, carga.ruta)

    assert resultado.sacos_contados == 4
    assert resultado.sacos_entrantes == 4
    assert resultado.sacos_salientes == 0
    assert resultado.modelo == "sacos.pt"


def test_un_operario_tapando_sacos_no_cambia_el_conteo(ajustes, tmp_path_factory):
    """La oclusion que el apartado 11 senala como riesgo, con video de verdad."""
    carpeta = tmp_path_factory.mktemp("modelo")
    carga = generar_carga(carpeta / "con_gente.mp4", sacos=6, semilla=12,
                          con_personas=1)

    resultado = analizar(ajustes, carga.ruta)

    assert resultado.sacos_contados == 6
    assert resultado.personas_detectadas >= 1


def test_un_saco_que_vuelve_no_suma(ajustes, tmp_path_factory):
    """RN-04: cruza hacia el camion y se lo llevan de vuelta. El neto es cinco,
    y el retorno se informa aparte porque es senal de severidad Alta."""
    carpeta = tmp_path_factory.mktemp("modelo")
    carga = generar_carga(carpeta / "vuelve.mp4", sacos=5, semilla=15,
                          con_personas=1, sacos_que_vuelven=1)

    resultado = analizar(ajustes, carga.ruta)

    assert resultado.sacos_contados == 5
    assert resultado.sacos_entrantes == 6
    assert resultado.sacos_salientes == 1


def test_el_rastreador_entrega_identificadores(ajustes, tmp_path_factory):
    """El contrato con ultralytics del que depende todo el conteo. Si una
    version futura dejara de dar identificadores, el conteo saldria cero y todo
    parecerian cargas vacias."""
    carpeta = tmp_path_factory.mktemp("modelo")
    carga = generar_carga(carpeta / "ids.mp4", sacos=3, semilla=17, con_personas=1)

    resultado = analizar(ajustes, carga.ruta)

    assert resultado.detecciones_de_saco > 0
    assert resultado.seguimiento_perdido is False


def test_el_salto_de_fotogramas_alto_se_delata(ajustes, tmp_path_factory):
    """Con salto 2 el rastreador pierde los sacos y el conteo da cero.

    Es la razon por la que el valor por defecto es 1. Lo importante no es que
    falle, que es una limitacion conocida de asociar por solapamiento, sino que
    el fallo se vea: sin el aviso, ese cero pareceria un camion sin cargar.
    """
    import dataclasses

    carpeta = tmp_path_factory.mktemp("modelo")
    carga = generar_carga(carpeta / "salto.mp4", sacos=4, semilla=11, con_personas=1)

    resultado = analizar(dataclasses.replace(ajustes, salto_de_fotogramas=2),
                         carga.ruta)

    if resultado.sacos_contados == 0:
        assert resultado.seguimiento_perdido is True


# ------------------------------------------------- HU-08 con el modelo de verdad
def test_se_sigue_a_las_personas_del_clip(ajustes, tmp_path_factory):
    """Criterios 1 y 2 con video real: dos operarios cruzan la rampa mientras se
    carga, y el servicio dice cuantos fueron y cuanto estuvieron."""
    import dataclasses

    carpeta = tmp_path_factory.mktemp("personas")
    carga = generar_carga(carpeta / "con_dos.mp4", sacos=6, semilla=13,
                          con_personas=2)

    resultado = analizar(dataclasses.replace(ajustes, permanencia_minima_s=0.5),
                         carga.ruta)

    assert resultado.personas_detectadas == 2
    assert resultado.personas.maximo_simultaneo >= 1
    assert all(p.segundos_en_zona > 0 for p in resultado.personas.personas)
    # Y el conteo de sacos sigue saliendo bien con gente por delante.
    assert resultado.sacos_contados == 6


def test_una_zona_calibrada_deja_fuera_al_resto_del_cuadro(ajustes,
                                                           tmp_path_factory):
    """Con video real: los operarios del simulador recorren el cuadro de derecha
    a izquierda, asi que una zona pegada al borde izquierdo apenas los ve."""
    import dataclasses

    carpeta = tmp_path_factory.mktemp("zona")
    carga = generar_carga(carpeta / "zona.mp4", sacos=4, semilla=11,
                          con_personas=2)

    completo = analizar(dataclasses.replace(ajustes, permanencia_minima_s=0.5),
                        carga.ruta)
    estrecha = analizar(
        dataclasses.replace(ajustes, zona=(0.0, 0.0, 0.05, 1.0),
                            permanencia_minima_s=0.5),
        carga.ruta)

    assert completo.personas_detectadas == 2
    assert estrecha.personas_detectadas < completo.personas_detectadas
    assert completo.personas.zona_completa is True
    assert estrecha.personas.zona_completa is False


def test_la_permanencia_no_pasa_de_lo_que_dura_el_clip(ajustes, tmp_path_factory):
    """Una permanencia mayor que el clip seria un error de unidades, y es el
    tipo de cifra que nadie discute hasta que decide sobre alguien."""
    import dataclasses

    carpeta = tmp_path_factory.mktemp("duracion")
    carga = generar_carga(carpeta / "dur.mp4", sacos=5, semilla=15,
                          con_personas=1)

    resultado = analizar(dataclasses.replace(ajustes, permanencia_minima_s=0.5),
                         carga.ruta)

    for persona in resultado.personas.personas:
        assert 0 < persona.segundos_en_zona <= resultado.duracion_del_clip_s


def test_una_rampa_sin_nadie_no_inventa_personas(ajustes, tmp_path_factory):
    carpeta = tmp_path_factory.mktemp("vacia")
    carga = generar_carga(carpeta / "sola.mp4", sacos=4, semilla=11,
                          con_personas=0)

    resultado = analizar(ajustes, carga.ruta)

    assert resultado.personas_detectadas == 0
    assert resultado.anomalia.hay is False


def test_demasiada_gente_a_la_vez_se_detecta_con_video_real(ajustes,
                                                            tmp_path_factory):
    """El disparo de la RN-03, de punta a punta: dos operarios con el umbral
    puesto en uno."""
    import dataclasses

    carpeta = tmp_path_factory.mktemp("anomalia")
    carga = generar_carga(carpeta / "gente.mp4", sacos=6, semilla=13,
                          con_personas=2)

    resultado = analizar(
        dataclasses.replace(ajustes, personas_habituales=1,
                            permanencia_minima_s=0.5),
        carga.ruta)

    assert resultado.anomalia.hay is True
    assert "demasiadas_personas_a_la_vez" in resultado.anomalia.codigos
