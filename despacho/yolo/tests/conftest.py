"""Fixtures del servicio YOLO.

Las pruebas de la regla de conteo no necesitan nada. Las del endpoint usan un
modelo inyectado que devuelve detecciones preparadas: lo que se comprueba ahi es
el contrato de la API y el recorrido completo, no la inferencia de ultralytics,
que ya tiene sus propias pruebas.

Las pruebas que si ejercitan el modelo de verdad viven en test_modelo.py y se
saltan cuando los pesos no estan entrenados, porque entrenarlos lleva minutos y
no puede ser un requisito para correr la suite.
"""
from __future__ import annotations

import pathlib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
PESOS = RAIZ / "modelos" / "sacos.pt"

CLASES = {0: "saco", 1: "person"}


class _Cajas:
    """Imita boxes de ultralytics: lo que app/analisis.py lee de cada fotograma."""

    def __init__(self, filas, con_id=True):
        # filas: (id, clase, confianza, x, y)
        self._filas = filas
        # id a None es lo que devuelve ultralytics cuando el rastreador no llego
        # a seguir nada de lo detectado, que es el fallo silencioso del salto de
        # fotogramas.
        self.id = _Columna([f[0] for f in filas]) if (filas and con_id) else None
        self.cls = _Columna([f[1] for f in filas])
        self.conf = _Lista([f[2] for f in filas])
        self.xywhn = _Lista([[f[3], f[4], 0.1, 0.07] for f in filas])


class _Columna:
    def __init__(self, valores):
        self._valores = valores

    def int(self):
        return self

    def tolist(self):
        return list(self._valores)


class _Lista:
    def __init__(self, valores):
        self._valores = valores

    def tolist(self):
        return list(self._valores)


class _Fotograma:
    def __init__(self, filas, con_id=True):
        self.boxes = _Cajas(filas, con_id=con_id)
        self.names = CLASES


class ModeloFalso:
    """Devuelve una secuencia de fotogramas preparada.

    No imita a YOLO: imita lo poco que el servicio le pide, que es una secuencia
    de detecciones con identificador. Si ultralytics cambia ese contrato, lo
    dira test_modelo.py, que usa el modelo de verdad.
    """

    def __init__(self, fotogramas, con_id=True):
        self.fotogramas = fotogramas
        self.con_id = con_id
        self.llamadas = []

    def track(self, **kwargs):
        self.llamadas.append(kwargs)
        return iter([_Fotograma(filas, con_id=self.con_id)
                     for filas in self.fotogramas])


def sacos_cruzando(cantidad: int, personas: int = 0):
    """Fotogramas en los que `cantidad` sacos pasan de izquierda a derecha."""
    fotogramas = []
    for paso, x in enumerate((0.2, 0.5, 0.8)):
        filas = [(identificador, 0, 0.9, x, 0.4 + identificador * 0.02)
                 for identificador in range(1, cantidad + 1)]
        filas += [(900 + p, 1, 0.8, 0.3, 0.6) for p in range(personas)]
        fotogramas.append(filas)
        del paso
    return fotogramas


@pytest.fixture()
def clip(tmp_path) -> pathlib.Path:
    """Un clip de verdad, corto: el servicio lo abre para medir su duracion."""
    from sim.rampa_sim import generar_carga

    carga = generar_carga(tmp_path / "carga.mp4", sacos=2, semilla=3,
                          con_personas=0)
    return carga.ruta


@pytest.fixture()
def modelo_con_dos_sacos():
    return ModeloFalso(sacos_cruzando(2))


@pytest.fixture()
def app_con_modelo(modelo_con_dos_sacos, tmp_path):
    from app.main import create_app

    pesos = tmp_path / "sacos.pt"
    pesos.write_bytes(b"pesos de prueba")
    return create_app(ruta_pesos=pesos, dispositivo="cpu",
                      modelo=modelo_con_dos_sacos, api_key="")


@pytest.fixture()
def cliente(app_con_modelo):
    from fastapi.testclient import TestClient

    with TestClient(app_con_modelo) as test_client:
        yield test_client


def hay_modelo_entrenado() -> bool:
    return PESOS.exists()
