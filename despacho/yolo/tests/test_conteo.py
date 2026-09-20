"""La regla de conteo. HU-07, criterio 1.

Sin YOLO y sin video: el contador recibe posiciones con identificador y decide.
Lo que se prueba aqui es la regla, que es lo nuestro, no la libreria de terceros.
"""
from __future__ import annotations

import pytest

from app.conteo import ContadorDeLinea, Deteccion, Punto, precision_de_conteo

# Linea vertical por el centro del cuadro, que es la disposicion tipica de una
# camara que mira la rampa de costado.
CENTRO = (0.5, 0.0, 0.5, 1.0)


def saco(identificador: int, x: float, y: float = 0.5) -> Deteccion:
    return Deteccion(id_seguimiento=identificador, clase="saco",
                     confianza=0.9, centro=Punto(x=x, y=y))


def cruzar(contador: ContadorDeLinea, identificador: int,
           desde: float = 0.2, hasta: float = 0.8, fotograma: int = 0) -> int:
    """Pasea un objeto de un lado al otro y devuelve el ultimo fotograma usado."""
    pasos = [desde, (desde + hasta) / 2, hasta]
    for indice, x in enumerate(pasos):
        contador.procesar(fotograma + indice, [saco(identificador, x)])
    return fotograma + len(pasos) - 1


# ------------------------------------------------------------------ geometria
@pytest.mark.parametrize("x,esperado", [(0.2, -1), (0.8, 1)])
def test_cada_punto_cae_de_su_lado(x, esperado):
    contador = ContadorDeLinea(CENTRO, "saco")
    assert contador.lado_de(Punto(x=x, y=0.5)) == esperado


def test_un_punto_sobre_la_linea_no_esta_en_ningun_lado():
    """Y por eso no se cuenta: un saco parado encima de la linea contaria una vez
    por cada temblor de la caja delimitadora."""
    contador = ContadorDeLinea(CENTRO, "saco")
    assert contador.lado_de(Punto(x=0.5, y=0.5)) == 0


def test_una_linea_horizontal_tambien_funciona():
    """Con la camara cenital, la linea de carga es horizontal."""
    contador = ContadorDeLinea((0.0, 0.5, 1.0, 0.5), "saco")
    assert contador.lado_de(Punto(x=0.5, y=0.2)) != contador.lado_de(Punto(x=0.5, y=0.8))


def test_una_linea_diagonal_tambien():
    contador = ContadorDeLinea((0.0, 0.0, 1.0, 1.0), "saco")
    assert contador.lado_de(Punto(x=0.8, y=0.2)) != contador.lado_de(Punto(x=0.2, y=0.8))


# ------------------------------------------------------- criterio 1: contar cruces
def test_un_saco_que_cruza_cuenta_una_vez():
    contador = ContadorDeLinea(CENTRO, "saco")
    cruzar(contador, 1)
    assert contador.total == 1
    assert contador.entrantes == 1


def test_un_saco_visto_muchas_veces_del_mismo_lado_no_cuenta():
    """Es la diferencia entre contar sacos y contar fotogramas: un saco aparece
    en decenas seguidos y sumar detecciones daria cientos por carga."""
    contador = ContadorDeLinea(CENTRO, "saco")
    for fotograma in range(50):
        contador.procesar(fotograma, [saco(1, 0.2)])
    assert contador.total == 0


def test_diez_sacos_dan_diez():
    contador = ContadorDeLinea(CENTRO, "saco")
    fotograma = 0
    for identificador in range(1, 11):
        fotograma = cruzar(contador, identificador, fotograma=fotograma) + 1
    assert contador.total == 10


def test_un_saco_que_aparece_encima_de_la_linea_espera_a_definirse():
    """Aparece justo sobre la linea, se aparta a un lado y luego cruza de verdad.

    El lado del que aparecio no se sabia, asi que el primer movimiento solo sirve
    para fijarlo: contar ahi seria contar un cruce que nadie vio.
    """
    contador = ContadorDeLinea(CENTRO, "saco")
    contador.procesar(0, [saco(1, 0.5)])          # encima: aun no se sabe
    contador.procesar(1, [saco(1, 0.2)])          # se define: lado izquierdo
    assert contador.total == 0

    contador.procesar(2, [saco(1, 0.8)])          # ahora si cruza
    assert contador.total == 1


def test_un_saco_que_se_para_sobre_la_linea_no_cuenta_dos_veces():
    """El temblor de la caja delimitadora sobre la linea es el caso que mas
    inflaria el conteo si cada oscilacion contara."""
    contador = ContadorDeLinea(CENTRO, "saco")
    contador.procesar(0, [saco(1, 0.2)])
    for fotograma in range(1, 10):
        contador.procesar(fotograma, [saco(1, 0.5)])     # parado encima
    contador.procesar(10, [saco(1, 0.8)])

    assert contador.total == 1


def test_un_saco_que_aparece_ya_pasada_la_linea_no_cruzo_nada():
    """Entra en cuadro al otro lado: nadie lo vio cruzar."""
    contador = ContadorDeLinea(CENTRO, "saco")
    for fotograma in range(10):
        contador.procesar(fotograma, [saco(1, 0.8)])
    assert contador.total == 0


def test_un_saco_que_va_y_vuelve_deja_el_neto_en_cero():
    """La RN-04 lo trata como severidad Alta: un saco que sale de la zona de
    carga no es un error de conteo, es una senal."""
    contador = ContadorDeLinea(CENTRO, "saco")
    ultimo = cruzar(contador, 1, 0.2, 0.8)
    cruzar(contador, 1, 0.8, 0.2, fotograma=ultimo + 1)

    assert contador.entrantes == 1
    assert contador.salientes == 1
    assert contador.total == 0


def test_los_salientes_se_informan_aparte():
    contador = ContadorDeLinea(CENTRO, "saco")
    ultimo = cruzar(contador, 1, 0.2, 0.8)
    ultimo = cruzar(contador, 2, 0.2, 0.8, fotograma=ultimo + 1)
    cruzar(contador, 3, 0.8, 0.2, fotograma=ultimo + 1)

    assert (contador.entrantes, contador.salientes, contador.total) == (2, 1, 1)


def test_el_sentido_se_puede_invertir():
    """Si la camara mira la rampa desde el otro costado, se invierte aqui en
    lugar de recablear nada."""
    contador = ContadorDeLinea(CENTRO, "saco", invertir=True)
    cruzar(contador, 1, 0.2, 0.8)
    assert contador.entrantes == 0
    assert contador.salientes == 1


def test_solo_cuenta_la_clase_que_se_le_pide():
    """Las personas cruzan la linea todo el rato y no son sacos."""
    contador = ContadorDeLinea(CENTRO, "saco")
    for fotograma, x in enumerate((0.2, 0.5, 0.8)):
        contador.procesar(fotograma, [
            Deteccion(id_seguimiento=9, clase="person", confianza=0.9,
                      centro=Punto(x=x, y=0.5))])
    assert contador.total == 0


def test_dos_sacos_a_la_vez_cuentan_los_dos():
    contador = ContadorDeLinea(CENTRO, "saco")
    for fotograma, x in enumerate((0.2, 0.5, 0.8)):
        contador.procesar(fotograma, [saco(1, x, y=0.3), saco(2, x, y=0.7)])
    assert contador.total == 2


# ------------------------------------------------------------- oclusiones
def test_un_saco_tapado_unos_fotogramas_sigue_contando_una_vez():
    """La oclusion que el apartado 11 senala como riesgo: alguien pasa por
    delante y el saco desaparece tres fotogramas."""
    contador = ContadorDeLinea(CENTRO, "saco", memoria=30)
    contador.procesar(0, [saco(1, 0.2)])
    for fotograma in range(1, 4):
        contador.procesar(fotograma, [])          # tapado
    contador.procesar(4, [saco(1, 0.8)])

    assert contador.total == 1


def test_un_identificador_olvidado_empieza_de_cero():
    """Sin olvido, un identificador reutilizado por el rastreador heredaria el
    lado de otro objeto e inventaria un cruce."""
    contador = ContadorDeLinea(CENTRO, "saco", memoria=5)
    contador.procesar(0, [saco(1, 0.2)])
    contador.procesar(100, [saco(2, 0.5)])        # pasa el tiempo, se olvida el 1
    contador.procesar(101, [saco(1, 0.8)])        # el 1 vuelve, ya del otro lado

    assert contador.total == 0
    assert 1 in contador.rastros


def test_los_rastros_no_crecen_sin_limite():
    """Un clip de 7 minutos acumularia miles."""
    contador = ContadorDeLinea(CENTRO, "saco", memoria=10)
    for fotograma in range(200):
        contador.procesar(fotograma, [saco(fotograma, 0.2)])
    assert len(contador.rastros) <= 12


# -------------------------------------------------- criterio 2: la precision
@pytest.mark.parametrize("contados,reales,esperado", [
    (100, 100, 100.0),
    (99, 100, 99.0),
    (101, 100, 99.0),      # pasarse cuenta igual que quedarse corto
    (95, 100, 95.0),
    (90, 100, 90.0),
    (0, 100, 0.0),
    (0, 0, 100.0),         # no habia nada que contar y no se conto nada
    (3, 0, 0.0),           # tres sacos inventados
])
def test_la_precision_es_el_error_relativo(contados, reales, esperado):
    assert precision_de_conteo(contados, reales) == pytest.approx(esperado)


def test_la_precision_nunca_baja_de_cero():
    """Contar el triple es un fallo total, no un menos doscientos por ciento."""
    assert precision_de_conteo(30, 10) == 0.0
