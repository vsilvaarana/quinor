"""Los ajustes del servicio.

La linea de carga es lo unico que hay que calibrar en planta (apartado 9.1), asi
que lo que mas se prueba aqui es que una linea mal escrita en el entorno no
arranque el servicio en silencio contando cualquier cosa.
"""
from __future__ import annotations

import pathlib

import pytest

from app.config import (LINEA_POR_DEFECTO, PRECISION_MINIMA_PCT,
                        ZONA_POR_DEFECTO, Ajustes, cargar_ajustes,
                        parsear_linea, parsear_zona)


# ------------------------------------------------------------------- la linea
def test_la_linea_se_lee_del_formato_del_entorno():
    assert parsear_linea("0.4,0.1,0.4,0.9") == (0.4, 0.1, 0.4, 0.9)


def test_los_espacios_no_molestan():
    assert parsear_linea(" 0.4 , 0.1 , 0.4 , 0.9 ") == (0.4, 0.1, 0.4, 0.9)


@pytest.mark.parametrize("crudo", ["0.5,0.0,0.5", "0.5,0.0,0.5,1.0,0.2", ""])
def test_una_linea_con_otro_numero_de_valores_se_rechaza(crudo):
    with pytest.raises(ValueError, match="cuatro numeros"):
        parsear_linea(crudo)


def test_una_linea_con_letras_se_rechaza():
    with pytest.raises(ValueError, match="no numericos"):
        parsear_linea("0.5,arriba,0.5,1.0")


@pytest.mark.parametrize("crudo", ["0.5,0.0,0.5,1.5", "-0.1,0.0,0.5,1.0"])
def test_una_linea_en_pixeles_se_rechaza(crudo):
    """El error tipico de calibracion: escribir 960,0,960,1080 en lugar de
    coordenadas relativas. Mejor no arrancar que contar con la linea fuera."""
    with pytest.raises(ValueError, match="de 0 a 1"):
        parsear_linea(crudo)


def test_una_linea_de_longitud_cero_no_es_una_linea():
    with pytest.raises(ValueError, match="no pueden coincidir"):
        parsear_linea("0.5,0.5,0.5,0.5")


def test_linea_valida_avisa_de_una_linea_degenerada():
    assert Ajustes().linea_valida is True
    assert Ajustes(linea=(0.5, 0.5, 0.5, 0.5)).linea_valida is False
    assert Ajustes(linea=(0.5, 0.0, 1.4, 1.0)).linea_valida is False


# ------------------------------------------------------------------ el entorno
def test_sin_entorno_quedan_los_valores_del_documento():
    ajustes = cargar_ajustes()
    assert ajustes.linea == LINEA_POR_DEFECTO
    assert ajustes.clase_saco == "saco"
    assert ajustes.dispositivo == "cpu"
    # 1 y no 2: con salto 2 el rastreador perdia los sacos y el conteo daba cero.
    assert ajustes.salto_de_fotogramas == 1


def test_el_entorno_manda_sobre_los_valores_por_defecto(monkeypatch):
    monkeypatch.setenv("YOLO_WEIGHTS", "/modelos/v3.pt")
    monkeypatch.setenv("LINEA_CARGA", "0.3,0.0,0.3,1.0")
    monkeypatch.setenv("LINEA_INVERTIDA", "true")
    monkeypatch.setenv("YOLO_DEVICE", "cuda:0")
    monkeypatch.setenv("YOLO_CONF", "0.6")

    ajustes = cargar_ajustes()

    assert ajustes.ruta_pesos == pathlib.Path("/modelos/v3.pt")
    assert ajustes.linea == (0.3, 0.0, 0.3, 1.0)
    assert ajustes.invertir_sentido is True
    assert ajustes.dispositivo == "cuda:0"
    assert ajustes.confianza_minima == 0.6


def test_una_variable_vacia_cuenta_como_ausente(monkeypatch):
    """docker-compose deja variables vacias cuando el .env no las define; una
    ruta de pesos vacia dejaria el servicio sin modelo sin decir por que."""
    monkeypatch.setenv("YOLO_WEIGHTS", "")
    assert cargar_ajustes().ruta_pesos == pathlib.Path("modelos/sacos.pt")


def test_lo_que_se_pasa_por_parametro_manda_sobre_el_entorno(monkeypatch):
    monkeypatch.setenv("YOLO_DEVICE", "cuda:0")
    assert cargar_ajustes(dispositivo="cpu").dispositivo == "cpu"


def test_un_parametro_en_none_no_pisa_el_entorno(monkeypatch):
    """create_app pasa None en lo que no recibe; eso no debe borrar el entorno."""
    monkeypatch.setenv("YOLO_DEVICE", "cuda:0")
    assert cargar_ajustes(dispositivo=None).dispositivo == "cuda:0"


@pytest.mark.parametrize("valor", ["0", "-1"])
def test_un_salto_de_fotogramas_imposible_se_rechaza(monkeypatch, valor):
    """Con 0 no se mira ningun fotograma y el conteo daria cero siempre."""
    monkeypatch.setenv("YOLO_FRAME_STRIDE", valor)
    with pytest.raises(ValueError, match="1 o mas"):
        cargar_ajustes()


@pytest.mark.parametrize("valor", ["0", "1.4", "-0.2"])
def test_una_confianza_fuera_de_rango_se_rechaza(monkeypatch, valor):
    monkeypatch.setenv("YOLO_CONF", valor)
    with pytest.raises(ValueError, match="entre 0 y 1"):
        cargar_ajustes()


def test_el_umbral_del_criterio_2_esta_donde_dice_la_historia():
    assert PRECISION_MINIMA_PCT == 95.0


# ------------------------------------------------- HU-08 zona y personal
def test_la_zona_se_lee_del_formato_del_entorno():
    assert parsear_zona("0.4,0.1,1.0,0.9") == (0.4, 0.1, 1.0, 0.9)


@pytest.mark.parametrize("crudo", ["0.4,0.0,1.0", "0.4,0.0,1.0,1.0,0.2", ""])
def test_una_zona_con_otro_numero_de_valores_se_rechaza(crudo):
    with pytest.raises(ValueError, match="cuatro numeros"):
        parsear_zona(crudo)


def test_una_zona_con_letras_se_rechaza():
    with pytest.raises(ValueError, match="no numericos"):
        parsear_zona("0.4,rampa,1.0,1.0")


@pytest.mark.parametrize("crudo", ["0.4,0.0,1.2,1.0", "-0.1,0.0,1.0,1.0"])
def test_una_zona_en_pixeles_se_rechaza(crudo):
    with pytest.raises(ValueError, match="de 0 a 1"):
        parsear_zona(crudo)


@pytest.mark.parametrize("crudo", ["1.0,0.0,0.4,1.0", "0.4,1.0,1.0,0.2",
                                   "0.4,0.0,0.4,1.0"])
def test_una_zona_escrita_al_reves_se_rechaza(crudo):
    """Un rectangulo invertido deja una zona vacia: todas las cargas saldrian sin
    nadie en rampa, y eso desde fuera se ve igual que una rampa vacia de verdad.
    Es el tipo de fallo que no se nota hasta que hace falta el dato."""
    with pytest.raises(ValueError, match="esquina superior izquierda"):
        parsear_zona(crudo)


def test_zona_valida_avisa_de_un_rectangulo_imposible():
    assert Ajustes().zona_valida is True
    assert Ajustes(zona=(1.0, 0.0, 0.4, 1.0)).zona_valida is False
    assert Ajustes(zona=(0.0, 0.0, 1.4, 1.0)).zona_valida is False


def test_sin_zona_configurada_se_toma_el_cuadro_entero():
    """Elegir una zona mas estrecha a ciegas dejaria fuera a gente que si estuvo
    en la rampa. La calibra el piloto, como la linea (apartado 9.1)."""
    ajustes = cargar_ajustes()
    assert ajustes.zona == ZONA_POR_DEFECTO == (0.0, 0.0, 1.0, 1.0)


def test_la_zona_y_los_umbrales_se_leen_del_entorno(monkeypatch):
    monkeypatch.setenv("ZONA_CARGA", "0.35,0.1,0.95,0.9")
    monkeypatch.setenv("PERSONAS_HABITUALES", "5")
    monkeypatch.setenv("PERMANENCIA_MAX_SEGUNDOS", "900")
    monkeypatch.setenv("PERMANENCIA_MIN_SEGUNDOS", "2")

    ajustes = cargar_ajustes()

    assert ajustes.zona == (0.35, 0.1, 0.95, 0.9)
    assert ajustes.personas_habituales == 5
    assert ajustes.permanencia_maxima_s == 900.0
    assert ajustes.permanencia_minima_s == 2.0


def test_cero_personas_habituales_es_valido(monkeypatch):
    """Una rampa donde no deberia haber nadie: cualquiera llama la atencion."""
    monkeypatch.setenv("PERSONAS_HABITUALES", "0")
    assert cargar_ajustes().personas_habituales == 0


def test_un_numero_negativo_de_personas_no_tiene_sentido(monkeypatch):
    monkeypatch.setenv("PERSONAS_HABITUALES", "-1")
    with pytest.raises(ValueError, match="negativo"):
        cargar_ajustes()


@pytest.mark.parametrize("valor", ["0", "-10"])
def test_una_permanencia_maxima_imposible_se_rechaza(monkeypatch, valor):
    """Con cero, toda carga con alguien en rampa saldria anomala y el aviso
    dejaria de significar nada."""
    monkeypatch.setenv("PERMANENCIA_MAX_SEGUNDOS", valor)
    with pytest.raises(ValueError, match="mayor que cero"):
        cargar_ajustes()


def test_una_permanencia_minima_negativa_se_rechaza(monkeypatch):
    monkeypatch.setenv("PERMANENCIA_MIN_SEGUNDOS", "-1")
    with pytest.raises(ValueError, match="negativo"):
        cargar_ajustes()


# ------------------------------------------------- HU-09 fotogramas clave
def test_sin_fotogramas_clave_el_supervisor_se_queda_sin_nada(monkeypatch):
    """Cero imagenes significa abrir un evento y no tener que mirar."""
    monkeypatch.setenv("FOTOGRAMAS_CLAVE", "0")
    with pytest.raises(ValueError, match="1 o mas"):
        cargar_ajustes()


@pytest.mark.parametrize("valor", ["0", "101", "-5"])
def test_una_calidad_jpeg_fuera_de_rango_se_rechaza(monkeypatch, valor):
    monkeypatch.setenv("CALIDAD_JPEG", valor)
    with pytest.raises(ValueError, match="de 1 a 100"):
        cargar_ajustes()


def test_los_fotogramas_clave_se_leen_del_entorno(monkeypatch):
    monkeypatch.setenv("FOTOGRAMAS_CLAVE", "6")
    monkeypatch.setenv("CALIDAD_JPEG", "60")

    ajustes = cargar_ajustes()

    assert ajustes.fotogramas_clave == 6
    assert ajustes.calidad_jpeg == 60
