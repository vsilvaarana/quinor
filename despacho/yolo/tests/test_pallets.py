"""Conteo por pallets: YOLO_MODO_CONTEO=pallets.

La camara real de la rampa esta alta y lejos, y un saco suelto ocupa unos pocos
pixeles. Un pallet si se ve. En este modo se cuentan los pallets que llegan a la
zona de carga y se quedan, y los sacos salen de multiplicar por los de un pallet
completo.

Igual que test_conteo.py, la regla se prueba sin YOLO y sin video. Al final hay
un recorrido completo con modelo inyectado y el contrato de la API.
"""
from __future__ import annotations

import dataclasses

import pytest

from app.analisis import analizar
from app.config import Ajustes, cargar_ajustes
from app.conteo import ContadorDePallets, Deteccion, Punto
from app.fotogramas import PRIMER_SACO, ULTIMO_SACO, momentos_del_fotograma
from tests.conftest import _Cajas

FPS = 10
# Zona de carga en la mitad derecha del cuadro.
ZONA = (0.5, 0.0, 1.0, 1.0)


def pallet(ident: int, x: float, y: float = 0.5, clase: str = "pallet") -> Deteccion:
    return Deteccion(id_seguimiento=ident, clase=clase, confianza=0.9,
                     centro=Punto(x=x, y=y))


def contador(**cambios) -> ContadorDePallets:
    base = dict(zona=ZONA, clase="pallet", fps=FPS, sacos_por_pallet=40,
                permanencia_s=2.0, ignorar_inicio_s=3.0, radio=0.06, memoria_s=6.0)
    base.update(cambios)
    return ContadorDePallets(**base)


def recorrer(c: ContadorDePallets, fotogramas: int, en_cada) -> int:
    for f in range(fotogramas):
        c.procesar(f, en_cada(f))
    return c.pallets


# ------------------------------------------------------------------ la regla
def test_un_pallet_que_llega_y_se_queda_cuenta_una_vez():
    c = contador()
    # Aparece abajo a la izquierda a los 5 s y lo dejan en la zona.
    pallets = recorrer(c, 200, lambda f: [pallet(1, 0.3 if f < 60 else 0.7)] if f >= 50 else [])
    assert pallets == 1
    assert c.entrantes == 40 and c.total == 40 and c.salientes == 0


def test_un_pallet_que_ya_estaba_al_empezar_no_llego_en_esta_carga():
    assert recorrer(contador(), 200, lambda f: [pallet(1, 0.7)]) == 0


def test_un_pallet_que_solo_pasa_no_se_cargo_aqui():
    """El montacargas lo cruza camino de otra rampa: menos de 2 s en la zona."""
    def pasa(f):
        return [pallet(1, 0.4 + (f - 100) * 0.05)] if 100 <= f < 115 else []
    assert recorrer(contador(), 200, pasa) == 0


def test_si_sale_antes_de_tiempo_la_espera_empieza_de_cero():
    def entra_sale_entra(f):
        if 50 <= f < 60:
            return [pallet(1, 0.7)]          # 1 s dentro
        if 60 <= f < 70:
            return [pallet(1, 0.3)]          # sale
        if 70 <= f < 85:
            return [pallet(1, 0.7)]          # 1,5 s: aun no
        return []
    c = contador()
    assert recorrer(c, 85, entra_sale_entra) == 0
    c.procesar(95, [pallet(1, 0.7)])         # 2,5 s desde que volvio a entrar
    assert c.pallets == 1


def test_un_pallet_al_que_el_rastreador_cambia_el_numero_no_se_cuenta_dos_veces():
    def oclusion(f):
        if 50 <= f < 120:
            return [pallet(4, 0.70, 0.50)]
        if 125 <= f < 300:
            return [pallet(5, 0.71, 0.51)]   # mismo sitio, numero nuevo
        return []
    assert recorrer(contador(), 300, oclusion) == 1


def test_si_le_cambian_el_numero_antes_de_contarlo_se_cuenta_igual_una_vez():
    """El viejo numero no sumo nada, asi que el nuevo no puede ser un alias."""
    def temprano(f):
        if 50 <= f < 60:
            return [pallet(7, 0.70)]          # 1 s, aun no cuenta
        if f >= 62:
            return [pallet(8, 0.71)]          # mismo sitio, numero nuevo
        return []
    c = contador()
    assert recorrer(c, 200, temprano) == 1
    assert c.llegadas[0].id_seguimiento == 8


def test_dos_pallets_en_sitios_distintos_son_dos():
    def dos(f):
        out = []
        if f >= 50:
            out.append(pallet(1, 0.6, 0.3))
        if f >= 150:
            out.append(pallet(2, 0.9, 0.8))
        return out
    c = contador()
    assert recorrer(c, 300, dos) == 2
    assert c.total == 80


def test_otro_pallet_en_el_mismo_sitio_mucho_despues_si_cuenta():
    """Vaciaron el primero y el montacargas trae otro al mismo lugar."""
    def reemplazo(f):
        if 50 <= f < 150:
            return [pallet(20, 0.7)]
        if f >= 350:
            return [pallet(21, 0.7)]
        return []
    assert recorrer(contador(), 500, reemplazo) == 2


def test_las_personas_no_son_pallets():
    c = contador()
    assert recorrer(c, 200, lambda f: [pallet(9, 0.7, clase="person")] if f >= 50 else []) == 0


def test_la_permanencia_se_mide_en_fotogramas_de_video_y_no_en_apariciones():
    """Con un salto de fotogramas de 5, contar apariciones multiplicaria la espera."""
    c = contador()
    for f in range(50, 200, 5):
        c.procesar(f, [pallet(1, 0.7)])
    assert c.llegadas[0].fotograma == 70


def test_sin_fps_se_usa_una_escala_razonable_y_no_se_divide_por_cero():
    c = contador(fps=0)
    assert c.fps == 15.0


def test_la_llegada_se_devuelve_como_un_cruce_hacia_el_camion():
    c = contador(ignorar_inicio_s=0, permanencia_s=0)
    llegadas = c.procesar(0, [pallet(1, 0.7)])
    assert len(llegadas) == 1 and llegadas[0].sentido == 1


# ---------------------------------------------------------- fotogramas clave
def test_los_fotogramas_clave_hablan_de_pallets_con_los_mismos_motivos():
    c = contador(ignorar_inicio_s=0, permanencia_s=0)
    llegadas = c.procesar(0, [pallet(1, 0.7)])
    momentos = momentos_del_fotograma(llegadas, 0, 0, es_primer_cruce=True,
                                      por_pallets=True)
    por_motivo = {m.motivo: m.detalle for m in momentos}
    assert "pallet" in por_motivo[PRIMER_SACO]
    assert "pallet" in por_motivo[ULTIMO_SACO]


# ------------------------------------------------------------- configuracion
def test_por_defecto_se_cuenta_con_la_linea(monkeypatch):
    monkeypatch.delenv("YOLO_MODO_CONTEO", raising=False)
    ajustes = cargar_ajustes()
    assert ajustes.modo_conteo == "linea" and not ajustes.por_pallets


def test_el_modo_pallets_se_lee_del_entorno(monkeypatch):
    monkeypatch.setenv("YOLO_MODO_CONTEO", "Pallets")
    monkeypatch.setenv("SACOS_POR_PALLET", "40")
    monkeypatch.setenv("ZONA_PALLETS", "0.38,0.05,0.80,0.70")
    monkeypatch.setenv("PALLET_PERMANENCIA_SEGUNDOS", "3")
    ajustes = cargar_ajustes()
    assert ajustes.por_pallets
    assert ajustes.sacos_por_pallet == 40
    assert ajustes.zona_pallets == (0.38, 0.05, 0.80, 0.70)
    assert ajustes.permanencia_pallet_s == 3.0


@pytest.mark.parametrize("variable,valor,frase", [
    ("YOLO_MODO_CONTEO", "cajas", "linea' o 'pallets"),
    ("SACOS_POR_PALLET", "0", "SACOS_POR_PALLET"),
    ("PALLET_PERMANENCIA_SEGUNDOS", "-1", "negativos"),
    ("PALLET_IGNORAR_INICIO_SEGUNDOS", "-1", "negativos"),
    ("PALLET_MEMORIA_SEGUNDOS", "-1", "negativos"),
    ("PALLET_RADIO", "1.5", "PALLET_RADIO"),
    ("ZONA_PALLETS", "0.8,0,0.2,1", "esquina superior izquierda"),
])
def test_una_configuracion_imposible_no_arranca(monkeypatch, variable, valor, frase):
    monkeypatch.setenv(variable, valor)
    with pytest.raises(ValueError, match=frase):
        cargar_ajustes()


# ------------------------------------------------------ recorrido completo
class _FotogramaPallet:
    def __init__(self, filas):
        self.boxes = _Cajas(filas)
        self.names = {0: "pallet", 1: "person"}


class _ModeloDePallets:
    def __init__(self, fotogramas):
        self.fotogramas = fotogramas

    def track(self, **kwargs):
        return iter([_FotogramaPallet(f) for f in self.fotogramas])


def llega_un_pallet(fotogramas: int = 60):
    """Un pallet que estaba (id 1) y otro que llega al fotograma 10 (id 2)."""
    salida = []
    for f in range(fotogramas):
        filas = [(1, 0, 0.9, 0.9, 0.2), (900, 1, 0.8, 0.3, 0.6)]
        if f >= 10:
            filas.append((2, 0, 0.9, 0.3 if f < 15 else 0.7, 0.7))
        salida.append(filas)
    return salida


def ajustes_pallets(pesos) -> Ajustes:
    return Ajustes(ruta_pesos=pesos, modo_conteo="pallets", zona_pallets=ZONA,
                   permanencia_pallet_s=1.0, ignorar_inicio_s=0.5)


def test_analizar_por_pallets_estima_los_sacos(clip, tmp_path):
    resultado = analizar(ajustes_pallets(tmp_path / "pallets.pt"), clip,
                         modelo=_ModeloDePallets(llega_un_pallet()))
    assert resultado.modo_conteo == "pallets"
    assert resultado.pallets_contados == 1
    assert resultado.sacos_por_pallet == 40
    assert resultado.sacos_contados == 40
    assert resultado.sacos_salientes == 0
    assert resultado.modelo == "pallets.pt"
    assert not resultado.seguimiento_perdido


def test_con_la_linea_no_se_informan_pallets(clip, tmp_path):
    from tests.conftest import ModeloFalso, sacos_cruzando
    resultado = analizar(Ajustes(ruta_pesos=tmp_path / "sacos.pt"), clip,
                         modelo=ModeloFalso(sacos_cruzando(2)))
    assert resultado.modo_conteo == "linea"
    assert resultado.pallets_contados is None and resultado.sacos_por_pallet is None


def test_la_api_dice_que_el_conteo_es_una_estimacion_por_pallets(clip, tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    pesos = tmp_path / "pallets.pt"
    pesos.write_bytes(b"pesos de prueba")
    app = create_app(ajustes=ajustes_pallets(pesos), api_key="",
                     modelo=_ModeloDePallets(llega_un_pallet()))
    with TestClient(app) as cliente:
        salud = cliente.get("/salud").json()
        assert salud["modo_conteo"] == "pallets"
        assert salud["zona_pallets"] == list(ZONA)

        cuerpo = cliente.post("/analisis/yolo", json={
            "clip": str(clip), "sacos_esperados": 80}).json()
    assert cuerpo["modo_conteo"] == "pallets"
    assert cuerpo["pallets_contados"] == 1
    assert cuerpo["sacos_por_pallet"] == 40
    assert cuerpo["sacos_contados"] == 40
    # Falta un pallet entero: la diferencia es de 40 sacos, como si los hubiese
    # contado uno a uno, y el grabador la guarda sin saber del modo.
    assert cuerpo["diferencia_sacos"] == -40


def test_en_modo_linea_la_salud_no_muestra_zona_de_pallets(cliente):
    salud = cliente.get("/salud").json()
    assert salud["modo_conteo"] == "linea"
    assert salud["zona_pallets"] is None


def test_la_api_en_modo_linea_no_informa_pallets(cliente, clip):
    cuerpo = cliente.post("/analisis/yolo", json={"clip": str(clip)}).json()
    assert cuerpo["modo_conteo"] == "linea"
    assert cuerpo["pallets_contados"] is None


def test_cambiar_de_modo_no_toca_lo_demas(tmp_path):
    base = Ajustes(ruta_pesos=tmp_path / "x.pt")
    otro = dataclasses.replace(base, modo_conteo="pallets")
    assert otro.linea == base.linea and otro.zona == base.zona
