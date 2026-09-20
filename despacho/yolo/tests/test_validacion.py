"""El medidor de la precision. HU-07, criterio 2.

Con modelo inyectado y un set de dos cargas: lo que se prueba aqui es la regla
de medida y lo que dice el reporte, no el modelo. La cifra de verdad la produce
`python -m sim.validar` con los pesos entrenados, y queda en
reporte_validacion.txt.
"""
from __future__ import annotations

import pathlib

import pytest

from app.config import PRECISION_MINIMA_PCT, Ajustes
from sim import validar as medidor
from tests.conftest import ModeloFalso, sacos_cruzando


@pytest.fixture()
def ajustes(tmp_path) -> Ajustes:
    return Ajustes(ruta_pesos=tmp_path / "sacos.pt", salto_de_fotogramas=1)


def informe_de(ajustes, cargas, modelo, tmp_path) -> medidor.Informe:
    return medidor.validar(ajustes, carpeta=tmp_path / "set", cargas=cargas,
                           modelo=modelo)


# ------------------------------------------------------------------ la medida
def test_un_conteo_exacto_da_cien(ajustes, tmp_path):
    """Dos cargas de dos sacos y un modelo que ve justo esos dos."""
    informe = informe_de(ajustes, ((2, 0, 0, 1), (2, 0, 0, 2)),
                         ModeloFalso(sacos_cruzando(2)), tmp_path)

    assert informe.precision_media_pct == 100.0
    assert informe.cargas_exactas == 2
    assert informe.error_medio_sacos == 0.0
    assert informe.cumple is True


def test_contar_de_menos_baja_la_precision(ajustes, tmp_path):
    """Cuatro sacos y el modelo solo ve tres: 75 %, por debajo del umbral."""
    informe = informe_de(ajustes, ((4, 0, 0, 1),),
                         ModeloFalso(sacos_cruzando(3)), tmp_path)

    assert informe.precision_media_pct == 75.0
    assert informe.cargas_exactas == 0
    assert informe.cumple is False


def test_el_umbral_es_el_del_criterio(ajustes, tmp_path):
    informe = informe_de(ajustes, ((2, 0, 0, 1),),
                         ModeloFalso(sacos_cruzando(2)), tmp_path)
    assert informe.umbral_pct == PRECISION_MINIMA_PCT == 95.0


def test_se_informa_tambien_de_la_peor_carga(ajustes, tmp_path):
    """La media puede tapar una carga desastrosa, y una carga desastrosa es un
    camion al que no se le reviso lo que habia que revisar."""
    class PorCarga:
        """Acierta la primera carga y falla la segunda."""

        def __init__(self):
            self.veces = 0

        def track(self, **kwargs):
            self.veces += 1
            cuantos = 4 if self.veces == 1 else 1
            return ModeloFalso(sacos_cruzando(cuantos)).track(**kwargs)

    informe = informe_de(ajustes, ((4, 0, 0, 1), (4, 0, 0, 2)), PorCarga(), tmp_path)

    assert informe.precision_media_pct == pytest.approx(62.5)
    assert informe.precision_minima_pct == 25.0


def test_el_set_tiene_cargas_variadas():
    """Una carga sin nada que la complique no diria si el contador aguanta una
    rampa real: hacen falta oclusiones y sacos que vuelven."""
    con_personas = [c for c in medidor.CARGAS if c[2] > 0]
    con_retorno = [c for c in medidor.CARGAS if c[1] > 0]

    assert len(medidor.CARGAS) >= 8
    assert len(con_personas) >= 5
    assert len(con_retorno) >= 2


# ----------------------------------------------------------------- el reporte
def test_el_reporte_avisa_de_que_el_set_es_sintetico(ajustes, tmp_path):
    """Sin esa advertencia, la cifra se leeria como si midiera la rampa de
    QUINOR, y el 100 % de un set sintetico no es una promesa de planta."""
    informe = informe_de(ajustes, ((2, 0, 0, 1),),
                         ModeloFalso(sacos_cruzando(2)), tmp_path)

    texto = medidor.formatear(informe, pathlib.Path("modelos/sacos.pt"))

    assert "ADVERTENCIA" in texto
    assert "sintetico" in texto
    assert "HU-19" in texto
    assert "piloto" in texto


def test_el_reporte_dice_si_cumple_o_no(ajustes, tmp_path):
    bueno = informe_de(ajustes, ((2, 0, 0, 1),),
                       ModeloFalso(sacos_cruzando(2)), tmp_path)
    malo = informe_de(ajustes, ((4, 0, 0, 2),),
                      ModeloFalso(sacos_cruzando(1)), tmp_path)

    assert "Resultado:               CUMPLE" in medidor.formatear(bueno, pathlib.Path("x"))
    assert "NO CUMPLE" in medidor.formatear(malo, pathlib.Path("x"))


def test_el_reporte_separa_la_velocidad_de_la_precision(ajustes, tmp_path):
    """El criterio 2 mide precision. La velocidad es del RNF-01 y en una maquina
    sin GPU no se cumple: mejor que el reporte lo diga a que alguien suponga que
    el mismo numero sirve para las dos cosas."""
    informe = informe_de(ajustes, ((2, 0, 0, 1),),
                         ModeloFalso(sacos_cruzando(2)), tmp_path)

    texto = medidor.formatear(informe, pathlib.Path("x"))

    assert "RNF-01" in texto
    assert informe.veces_el_video >= 0.0


def test_el_objetivo_de_velocidad_es_el_del_rnf01():
    """7 minutos de clip en menos de 3."""
    assert medidor.RNF01_VECES_EL_VIDEO == pytest.approx(3 / 7)


def test_un_informe_sin_cargas_no_divide_por_cero():
    vacio = medidor.Informe(mediciones=(), precision_media_pct=0.0,
                            precision_minima_pct=0.0, cargas_exactas=0,
                            error_medio_sacos=0.0, umbral_pct=95.0)
    assert vacio.veces_el_video == 0.0
    assert vacio.total_cargas == 0


def test_el_reporte_de_verdad_esta_guardado_y_cumple():
    """El que produjo `python -m sim.validar` con los pesos entrenados. Es la
    evidencia del criterio 2, y vive junto al codigo para que se pueda leer sin
    volver a entrenar nada."""
    reporte = pathlib.Path(__file__).resolve().parent.parent / "reporte_validacion.txt"
    if not reporte.exists():
        pytest.skip("Sin reporte: se genera con python -m sim.validar")

    texto = reporte.read_text(encoding="utf-8")
    assert "Resultado:               CUMPLE" in texto
    assert "ADVERTENCIA" in texto
