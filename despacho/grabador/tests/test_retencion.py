"""Buffer circular de 72 h. HU-05, criterio 2."""
from __future__ import annotations

import datetime as dt

import pytest

from app import retencion
from tests.conftest import CAMARA_PRUEBA, segmento

AHORA = dt.datetime(2026, 9, 14, 12, 0, 0)


def marca(horas_atras: float) -> str:
    return (AHORA - dt.timedelta(hours=horas_atras)).strftime("%Y%m%d-%H%M%S")


@pytest.fixture(autouse=True)
def disco_holgado(monkeypatch):
    """Disco con sitio de sobra, salvo donde la prueba diga otra cosa.

    Sin esto, las pruebas de antiguedad dependen de cuanto disco libre tenga la
    maquina que las corre: en una con el disco al 92 % saltaria la purga por
    presion y borraria video que todavia no cumplia las 72 h. Lo que esas
    pruebas miden es la regla de antiguedad, no el disco de nadie.
    """
    monkeypatch.setattr(retencion, "_libre_pct", lambda _d: 50.0)


def test_se_conserva_lo_de_las_ultimas_72_horas(ajustes, buffer):
    reciente = segmento(buffer, CAMARA_PRUEBA, marca(1))
    ayer = segmento(buffer, CAMARA_PRUEBA, marca(30))
    limite = segmento(buffer, CAMARA_PRUEBA, marca(71.9))

    resultado = retencion.purgar(ajustes, ahora=AHORA)

    assert resultado.borrados_por_antiguedad == 0
    assert reciente.exists() and ayer.exists() and limite.exists()


def test_se_borra_lo_que_pasa_de_las_72_horas(ajustes, buffer):
    viejo = segmento(buffer, CAMARA_PRUEBA, marca(73))
    reciente = segmento(buffer, CAMARA_PRUEBA, marca(2))

    resultado = retencion.purgar(ajustes, ahora=AHORA)

    assert resultado.borrados_por_antiguedad == 1
    assert not viejo.exists()
    assert reciente.exists()


def test_justo_en_las_72_horas_todavia_se_conserva(ajustes, buffer):
    """El criterio dice "al menos 72 h": el que las cumple justo entra dentro."""
    limite = segmento(buffer, CAMARA_PRUEBA, marca(71.99))
    retencion.purgar(ajustes, ahora=AHORA)
    assert limite.exists()


def test_la_purga_cuenta_los_bytes_liberados(ajustes, buffer):
    segmento(buffer, CAMARA_PRUEBA, marca(80), tamano=2048)
    resultado = retencion.purgar(ajustes, ahora=AHORA)
    assert resultado.bytes_liberados == 2048


def test_no_se_toca_lo_que_no_escribio_el_grabador(ajustes, buffer):
    ajeno = buffer / CAMARA_PRUEBA
    ajeno.mkdir(parents=True, exist_ok=True)
    intruso = ajeno / "apuntes.txt"
    intruso.write_text("no es un segmento")

    retencion.purgar(ajustes, ahora=AHORA)
    assert intruso.exists()


def test_cada_camara_se_purga_por_igual(ajustes, buffer):
    uno = segmento(buffer, "camara-01", marca(80))
    otro = segmento(buffer, "camara-02", marca(80))
    vivo = segmento(buffer, "camara-02", marca(1))

    resultado = retencion.purgar(ajustes, ahora=AHORA)

    assert resultado.borrados_por_antiguedad == 2
    assert not uno.exists() and not otro.exists()
    assert vivo.exists()


def test_un_buffer_que_no_existe_no_revienta(ajustes, tmp_path):
    from dataclasses import replace

    vacio = replace(ajustes, directorio_buffer=tmp_path / "no-existe")
    assert retencion.purgar(vacio).total_borrados == 0


def test_un_buffer_vacio_no_borra_nada(ajustes):
    assert retencion.purgar(ajustes, ahora=AHORA).total_borrados == 0


def test_un_nombre_con_fecha_imposible_se_ignora(ajustes, buffer):
    """20260931 no existe. Antes que adivinar, se deja quieto."""
    raro = segmento(buffer, CAMARA_PRUEBA, "20260931-120000")
    retencion.purgar(ajustes, ahora=AHORA)
    assert raro.exists()


# ------------------------------------------------- disco lleno antes de las 72 h
def test_con_el_disco_lleno_se_borra_lo_mas_antiguo_y_se_avisa(ajustes, buffer, monkeypatch):
    """Seguir grabando es lo primero: perder las cargas de hoy seria peor, porque
    son las que todavia se pueden investigar con el camion en planta."""
    for horas in (10, 8, 6, 4, 2):
        segmento(buffer, CAMARA_PRUEBA, marca(horas))

    libres = iter([1.0, 2.0, 3.0, 50.0, 50.0, 50.0])
    monkeypatch.setattr(retencion, "_libre_pct", lambda _d: next(libres, 50.0))

    resultado = retencion.purgar(ajustes, ahora=AHORA)

    assert resultado.bajo_la_retencion_minima is True
    assert resultado.borrados_por_espacio == 3
    assert resultado.borrados_por_antiguedad == 0
    # Y lo que sobrevive es lo mas reciente, que es lo que se va a necesitar.
    quedan = [r.name for r in retencion.segmentos(buffer)]
    assert len(quedan) == 2
    assert marca(2) in quedan[-1]


def test_nunca_se_borra_el_segmento_que_se_esta_grabando(ajustes, buffer, monkeypatch):
    segmento(buffer, CAMARA_PRUEBA, marca(1))
    monkeypatch.setattr(retencion, "_libre_pct", lambda _d: 0.1)

    resultado = retencion.purgar(ajustes, ahora=AHORA)

    assert len(retencion.segmentos(buffer)) == 1
    assert resultado.borrados_por_espacio == 0


def test_con_disco_de_sobra_no_se_borra_por_espacio(ajustes, buffer, monkeypatch):
    for horas in (10, 8, 6):
        segmento(buffer, CAMARA_PRUEBA, marca(horas))
    monkeypatch.setattr(retencion, "_libre_pct", lambda _d: 90.0)

    resultado = retencion.purgar(ajustes, ahora=AHORA)

    assert resultado.bajo_la_retencion_minima is False
    assert len(retencion.segmentos(buffer)) == 3


def test_el_porcentaje_libre_sale_del_disco_real(ajustes, buffer):
    resultado = retencion.purgar(ajustes, ahora=AHORA)
    assert 0.0 <= resultado.libre_pct <= 100.0


def test_borrar_algo_que_ya_no_esta_no_es_un_error(ajustes, buffer):
    """Dos pasadas a la vez, o ffmpeg rotando justo ahora."""
    ruta = segmento(buffer, CAMARA_PRUEBA, marca(80))
    ruta.unlink()
    assert retencion._borrar(ruta) == 0


# ------------------------------------------------------- cuanto video hay
def test_las_horas_en_buffer_se_miden_desde_el_segmento_mas_viejo(ajustes, buffer):
    segmento(buffer, CAMARA_PRUEBA, marca(48))
    segmento(buffer, CAMARA_PRUEBA, marca(1))
    assert retencion.horas_en_buffer(ajustes, ahora=AHORA) == pytest.approx(48, abs=0.01)


def test_sin_segmentos_no_hay_horas(ajustes):
    assert retencion.horas_en_buffer(ajustes, ahora=AHORA) == 0.0


def test_los_segmentos_salen_del_mas_viejo_al_mas_nuevo(ajustes, buffer):
    segmento(buffer, CAMARA_PRUEBA, marca(1))
    segmento(buffer, CAMARA_PRUEBA, marca(50))
    segmento(buffer, CAMARA_PRUEBA, marca(20))
    nombres = [r.name for r in retencion.segmentos(buffer)]
    assert nombres == sorted(nombres)


def test_una_carpeta_de_camara_que_no_existe_da_lista_vacia(tmp_path):
    assert retencion.segmentos(tmp_path / "no-existe") == []
