"""Bandeja de eventos. HU-11.

  1. La tabla muestra ID, fecha, orden, diferencia, severidad y estado.
  2. Los filtros se combinan y la tabla se actualiza en menos de 2 s.
  3. Por defecto se muestran los eventos Pendientes de los ultimos 7 dias.

Contra MySQL de verdad, como el resto de la suite. El criterio 2 no se puede
probar contra un diccionario en memoria: lo que tarda es la consulta, y lo que
la hace tardar es el plan que elige el motor con los indices que existen.

La prueba que mas vale de este modulo es `test_la_bandeja_no_crece_en_consultas`:
cuenta las sentencias que se ejecutan de verdad y falla si alguien vuelve a meter
un acceso por fila. Es la regresion que hundiria esta pantalla, y es silenciosa
hasta que hay volumen.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from tests.conftest import ContadorDeConsultas

from app import bandeja
from app.bandeja import FiltroInvalido, Filtros, listar, resolver_filtros

ORDENES = ["ORD-2026-0001", "ORD-2026-0148", "ORD-2026-0777"]


# ------------------------------------------------------------------ utilidades
def sembrar(sesion, cuantos=1, *, dias_atras=0, estado="pendiente",
            severidad=None, diferencia_sacos=None, sacos_contados=None,
            numero_orden="ORD-2026-0001", personal_anomalo=None,
            diferencia_kg=Decimal("-150.00"), clip_url=None):
    """Crea ordenes, pesadas y eventos como los deja el resto del sistema.

    Con SQL de la propia sesion y no por la API, porque aqui se prueba la
    lectura: crear mil eventos por HTTP tardaria mas que la consulta que se
    quiere medir.
    """
    from app.models import Evento, OrdenDespacho, Pesada

    orden = sesion.query(OrdenDespacho).filter_by(
        numero_orden=numero_orden).first()
    if orden is None:
        orden = OrdenDespacho(
            numero_orden=numero_orden, cliente="Andean Grains LLC",
            producto="Quinua blanca organica", peso_esperado_kg=Decimal("20000.00"),
            sacos_esperados=400, fecha=dt.date.today(),
            sincronizado_en=dt.datetime.now())
        sesion.add(orden)
        sesion.flush()

    creados = []
    cuando = dt.datetime.now() - dt.timedelta(days=dias_atras)
    for i in range(cuantos):
        # Microsegundos distintos por fila: dos eventos con la misma marca
        # dejarian el orden al azar y la paginacion repetiria o saltaria filas.
        marca = cuando - dt.timedelta(microseconds=i * 1000)
        pesada = Pesada(orden_id=orden.id, bascula_id="BASCULA-01",
                        peso_real_kg=Decimal("19850.00"), fecha_hora=marca,
                        origen="bascula")
        sesion.add(pesada)
        sesion.flush()
        evento = Evento(
            pesada_id=pesada.id, diferencia_kg=diferencia_kg,
            diferencia_pct=Decimal("-0.75"), estado=estado,
            severidad=severidad, sacos_contados=sacos_contados,
            diferencia_sacos=diferencia_sacos,
            personal_anomalo=personal_anomalo, clip_url=clip_url,
            creado_en=marca)
        sesion.add(evento)
        creados.append(evento)
    sesion.commit()
    return creados


# ------------------------------------------------------------------ criterio 3
def test_sin_filtros_se_ven_los_pendientes_de_la_ultima_semana(sesion):
    """"Por defecto se muestran los eventos Pendientes de los ultimos 7 dias"."""
    sembrar(sesion, 3, dias_atras=1)
    sembrar(sesion, 2, dias_atras=30, numero_orden="ORD-2026-0148")
    sembrar(sesion, 4, dias_atras=1, estado="confirmado",
            numero_orden="ORD-2026-0777")

    pagina = listar(sesion, resolver_filtros())

    assert pagina.total == 3
    assert {f.estado for f in pagina.filas} == {"pendiente"}


def test_la_respuesta_dice_que_filtros_puso_el_sistema(sesion):
    """Sin esto, un supervisor que ve tres eventos puede creer que son todos los
    que existen, cuando esta viendo los pendientes de la ultima semana."""
    filtros = resolver_filtros()

    assert set(filtros.aplicados_por_defecto) == {"estado", "desde"}
    assert filtros.estado == "pendiente"
    assert filtros.desde == dt.date.today() - dt.timedelta(days=7)


def test_pedir_un_estado_concreto_no_arrastra_el_defecto_de_estado(sesion):
    sembrar(sesion, 2, dias_atras=1, estado="confirmado")

    filtros = resolver_filtros(estado="confirmado")

    assert filtros.estado == "confirmado"
    assert "estado" not in filtros.aplicados_por_defecto
    assert listar(sesion, filtros).total == 2


def test_pedir_fechas_no_arrastra_la_ventana_de_siete_dias(sesion):
    sembrar(sesion, 2, dias_atras=20)

    filtros = resolver_filtros(desde=dt.date.today() - dt.timedelta(days=30))

    assert "desde" not in filtros.aplicados_por_defecto
    assert listar(sesion, filtros).total == 2


def test_filtrar_por_severidad_releva_al_defecto_de_estado(sesion):
    """Quien busca "todas las Altas" quiere verlas en cualquier estado. Si el
    defecto de Pendiente siguiera puesto, las confirmadas desaparecerian sin que
    nadie lo hubiera pedido."""
    sembrar(sesion, 1, dias_atras=1, severidad="alta", estado="confirmado")
    sembrar(sesion, 1, dias_atras=1, severidad="alta",
            numero_orden="ORD-2026-0148")

    pagina = listar(sesion, resolver_filtros(severidad="alta"))

    assert pagina.total == 2
    assert pagina.filtros.estado is None


def test_sin_defectos_busca_en_todo_el_historico(sesion):
    """Para HU-14 y para quien sepa lo que pide. Es explicito a proposito."""
    sembrar(sesion, 2, dias_atras=400, estado="confirmado")

    filtros = resolver_filtros(sin_defectos=True)

    assert filtros.aplicados_por_defecto == ()
    assert listar(sesion, filtros).total == 2


# ------------------------------------------------------------------ criterio 1
def test_la_fila_trae_las_columnas_que_pide_el_criterio(sesion):
    sembrar(sesion, 1, dias_atras=1, severidad="alta", sacos_contados=392,
            diferencia_sacos=-8)

    fila = listar(sesion, resolver_filtros()).filas[0]

    assert fila.id > 0
    assert isinstance(fila.creado_en, dt.datetime)
    assert fila.numero_orden == "ORD-2026-0001"
    assert fila.diferencia_kg == Decimal("-150.00")
    assert fila.severidad == "alta"
    assert fila.estado == "pendiente"


def test_un_evento_sin_analizar_no_aparenta_tener_cero_sacos(sesion):
    """None no es cero: cero sacos en el video es un dato grave, sin analizar es
    la ausencia de dato. La tabla no puede confundirlos."""
    sembrar(sesion, 1, dias_atras=1)

    fila = listar(sesion, resolver_filtros()).filas[0]

    assert fila.sacos_contados is None
    assert fila.diferencia_sacos is None
    assert fila.personal_anomalo is None


def test_la_severidad_vacia_se_distingue_de_la_baja(sesion):
    """El criterio 1 dice que la severidad queda vacia hasta que HU-09 la
    asigne. Vacia y Baja son cosas distintas."""
    sembrar(sesion, 1, dias_atras=1)
    sembrar(sesion, 1, dias_atras=1, severidad="baja",
            numero_orden="ORD-2026-0148")

    severidades = {f.severidad for f in
                   listar(sesion, resolver_filtros()).filas}

    assert severidades == {None, "baja"}


def test_se_sabe_si_el_evento_tiene_clip_sin_traer_la_url(sesion):
    """La tabla solo necesita el indicador. La ruta del clip es del detalle."""
    sembrar(sesion, 1, dias_atras=1, clip_url="s3://clips/x.mkv")
    sembrar(sesion, 1, dias_atras=1, numero_orden="ORD-2026-0148")

    assert {f.tiene_clip for f in listar(sesion, resolver_filtros()).filas} == {
        True, False}


# -------------------------------------------------------- filtros combinados
def test_los_filtros_se_combinan(sesion):
    """Criterio 2: "los filtros se combinan". Cuatro a la vez, y solo sobrevive
    el evento que cumple los cuatro."""
    sembrar(sesion, 1, dias_atras=1, severidad="alta", diferencia_sacos=-8,
            sacos_contados=392, numero_orden="ORD-2026-0148")
    sembrar(sesion, 1, dias_atras=1, severidad="baja", diferencia_sacos=-8,
            sacos_contados=392, numero_orden="ORD-2026-0148")
    sembrar(sesion, 1, dias_atras=1, severidad="alta", diferencia_sacos=0,
            sacos_contados=400, numero_orden="ORD-2026-0001")
    sembrar(sesion, 1, dias_atras=40, severidad="alta", diferencia_sacos=-8,
            sacos_contados=392, numero_orden="ORD-2026-0777")

    pagina = listar(sesion, resolver_filtros(
        severidad="alta", numero_orden="0148", solo_con_faltante=True,
        desde=dt.date.today() - dt.timedelta(days=7)))

    assert pagina.total == 1
    assert pagina.filas[0].numero_orden == "ORD-2026-0148"


def test_la_orden_se_busca_por_un_trozo(sesion):
    """El supervisor recuerda "0148", no la orden entera."""
    sembrar(sesion, 1, dias_atras=1, numero_orden="ORD-2026-0148")
    sembrar(sesion, 1, dias_atras=1, numero_orden="ORD-2026-0777")

    assert listar(sesion, resolver_filtros(numero_orden="0148")).total == 1


def test_el_filtro_hasta_incluye_ese_dia_entero(sesion):
    """Quien pone "hasta hoy" espera ver lo de hoy, no lo anterior a su
    medianoche."""
    sembrar(sesion, 1, dias_atras=0)

    pagina = listar(sesion, resolver_filtros(
        desde=dt.date.today(), hasta=dt.date.today()))

    assert pagina.total == 1


def test_solo_con_faltante_deja_fuera_la_carga_que_cuadra(sesion):
    """Separa "falta producto" de "la bascula se movio". Un evento con los sacos
    cuadrados pero peso corto no tiene faltante de sacos, aunque si de kilos."""
    sembrar(sesion, 1, dias_atras=1, diferencia_sacos=-8, sacos_contados=392)
    sembrar(sesion, 1, dias_atras=1, diferencia_sacos=0, sacos_contados=400,
            numero_orden="ORD-2026-0148")
    sembrar(sesion, 1, dias_atras=1, numero_orden="ORD-2026-0777")

    assert listar(sesion, resolver_filtros(solo_con_faltante=True)).total == 1


# ------------------------------------------------------------------ paginacion
def test_la_pagina_dice_cuantos_hay_en_total(sesion):
    sembrar(sesion, 120, dias_atras=1)

    pagina = listar(sesion, resolver_filtros(tamano=50))

    assert pagina.total == 120
    assert len(pagina.filas) == 50
    assert pagina.paginas == 3
    assert (pagina.desde_fila, pagina.hasta_fila) == (1, 50)


def test_la_segunda_pagina_no_repite_ni_salta_filas(sesion):
    """Sin desempate por id, dos eventos del mismo instante podrian salir en
    distinto orden entre una pagina y otra, y alguno se veria dos veces."""
    sembrar(sesion, 75, dias_atras=1)

    primera = listar(sesion, resolver_filtros(tamano=50, pagina=1))
    segunda = listar(sesion, resolver_filtros(tamano=50, pagina=2))

    ids_1 = [f.id for f in primera.filas]
    ids_2 = [f.id for f in segunda.filas]
    assert len(ids_2) == 25
    assert set(ids_1).isdisjoint(ids_2)
    assert len(set(ids_1 + ids_2)) == 75
    assert (segunda.desde_fila, segunda.hasta_fila) == (51, 75)


def test_una_pagina_mas_alla_del_final_sale_vacia_y_no_revienta(sesion):
    sembrar(sesion, 3, dias_atras=1)

    pagina = listar(sesion, resolver_filtros(pagina=9))

    assert pagina.filas == ()
    assert pagina.total == 3


def test_sin_resultados_sigue_habiendo_una_pagina(sesion):
    pagina = listar(sesion, resolver_filtros())

    assert (pagina.total, pagina.paginas, pagina.desde_fila) == (0, 1, 0)


def test_el_orden_es_el_mas_reciente_primero(sesion):
    sembrar(sesion, 1, dias_atras=5)
    sembrar(sesion, 1, dias_atras=1, numero_orden="ORD-2026-0148")
    sembrar(sesion, 1, dias_atras=3, numero_orden="ORD-2026-0777")

    fechas = [f.creado_en for f in listar(sesion, resolver_filtros()).filas]

    assert fechas == sorted(fechas, reverse=True)


# ------------------------------------------------------------------ criterio 2
def test_la_bandeja_no_crece_en_consultas(sesion):
    """La regresion que hundiria esta pantalla.

    El listado anterior gastaba cuatro consultas por evento: pesada, orden y dos
    de auditoria. Aqui son dos en total, el conteo y las filas, y siguen siendo
    dos con 1 fila o con 200. Si alguien vuelve a leer algo por fila, este
    numero sube y la prueba lo dice.
    """
    sembrar(sesion, 1, dias_atras=1)
    with ContadorDeConsultas(sesion.get_bind()) as pocas:
        listar(sesion, resolver_filtros())

    sembrar(sesion, 199, dias_atras=1)
    with ContadorDeConsultas(sesion.get_bind()) as muchas:
        listar(sesion, resolver_filtros(tamano=200))

    assert len(pocas) == 2
    assert len(muchas) == 2


def test_con_volumen_la_bandeja_responde_dentro_del_criterio(sesion):
    """"La tabla se actualiza en menos de 2 s", con 500 eventos y los filtros
    combinados, que es cuando cuesta de verdad."""
    sembrar(sesion, 500, dias_atras=1, severidad="alta", diferencia_sacos=-8,
            sacos_contados=392)

    pagina = listar(sesion, resolver_filtros(
        severidad="alta", solo_con_faltante=True, numero_orden="ORD",
        desde=dt.date.today() - dt.timedelta(days=7)))

    assert pagina.total == 500
    assert pagina.dentro_del_criterio, (
        f"La bandeja tardo {pagina.segundos:.2f} s, por encima de los "
        f"{bandeja.SEGUNDOS_DEL_CRITERIO} s del criterio 2")


def test_el_tiempo_que_informa_es_el_que_tardo(sesion):
    """Se mide, no se supone. Si la cifra fuera decorativa, el criterio 2 no
    estaria comprobado por nadie."""
    sembrar(sesion, 5, dias_atras=1)

    pagina = listar(sesion, resolver_filtros())

    assert pagina.segundos > 0
    assert pagina.dentro_del_criterio is True


# ------------------------------------------------------------ filtros invalidos
@pytest.mark.parametrize("kwargs,trozo", [
    ({"estado": "inventado"}, "Estado"),
    ({"severidad": "gravisima"}, "Severidad"),
    ({"pagina": 0}, "pagina"),
    ({"tamano": 0}, "tamano"),
    ({"tamano": 5000}, "tamano"),
])
def test_un_filtro_imposible_se_rechaza_con_un_mensaje_util(kwargs, trozo):
    """Mejor un mensaje que diga que corregir que un error de motor."""
    with pytest.raises(FiltroInvalido, match=trozo):
        resolver_filtros(**kwargs)


def test_las_fechas_al_reves_no_se_corrigen_en_silencio(sesion):
    """Invertirlas mostraria un rango que nadie pidio, y el supervisor creeria
    estar viendo lo que pidio."""
    with pytest.raises(FiltroInvalido, match="posterior"):
        resolver_filtros(desde=dt.date(2026, 9, 30), hasta=dt.date(2026, 9, 1))


# ------------------------------------------------------------------- el resumen
def test_el_resumen_cuenta_lo_que_se_esta_viendo(sesion):
    sembrar(sesion, 2, dias_atras=1, severidad="alta", diferencia_sacos=-8,
            sacos_contados=392, personal_anomalo=True)
    sembrar(sesion, 1, dias_atras=1, severidad="baja", diferencia_sacos=0,
            sacos_contados=400, numero_orden="ORD-2026-0148")
    sembrar(sesion, 1, dias_atras=1, numero_orden="ORD-2026-0777")

    resumen = bandeja.resumen(listar(sesion, resolver_filtros()))

    assert resumen["en_pantalla"] == 4
    assert resumen["con_faltante_de_sacos"] == 2
    assert resumen["con_personal_anomalo"] == 2
    assert resumen["sin_analizar"] == 1
    assert resumen["altas"] == 2


def test_los_abiertos_son_los_que_esperan_a_alguien(sesion):
    sembrar(sesion, 2, dias_atras=1, estado="pendiente")
    sembrar(sesion, 1, dias_atras=1, estado="en_revision",
            numero_orden="ORD-2026-0148")
    sembrar(sesion, 3, dias_atras=1, estado="confirmado",
            numero_orden="ORD-2026-0777")

    pagina = listar(sesion, resolver_filtros(sin_defectos=True))

    assert pagina.total == 6
    assert pagina.abiertos == 3


def test_un_filtro_sin_estado_no_mezcla_el_desplazamiento(sesion):
    """El conteo y las filas tienen que filtrar igual. Si el total contara una
    cosa y las filas otra, el paginador mandaria a paginas vacias."""
    sembrar(sesion, 60, dias_atras=1, estado="pendiente")
    sembrar(sesion, 40, dias_atras=1, estado="confirmado",
            numero_orden="ORD-2026-0148")

    pagina = listar(sesion, resolver_filtros(estado="confirmado", tamano=25,
                                             pagina=2))

    assert pagina.total == 40
    assert len(pagina.filas) == 15
    assert {f.estado for f in pagina.filas} == {"confirmado"}


def test_el_peso_corto_con_los_sacos_cuadrados_se_cuenta_aparte(sesion):
    """Es la firma de la sustitucion de producto: subieron los 400 sacos pero
    pesan menos. Si se mezclara con los faltantes de bultos, el caso que motiva
    el proyecto quedaria escondido entre los otros."""
    sembrar(sesion, 2, dias_atras=1, diferencia_sacos=0, sacos_contados=400,
            diferencia_kg=Decimal("-310.00"))
    sembrar(sesion, 1, dias_atras=1, diferencia_sacos=-8, sacos_contados=392,
            numero_orden="ORD-2026-0148")

    resumen = bandeja.resumen(listar(sesion, resolver_filtros()))

    assert resumen["con_peso_corto_y_sacos_completos"] == 2
    assert resumen["con_faltante_de_sacos"] == 1


def test_una_bandeja_lenta_se_declara_lenta(sesion, monkeypatch):
    """El criterio 2 se mide con lo que pasa de verdad. Con el limite en cero,
    cualquier consulta queda fuera, y lo que se comprueba es que la respuesta lo
    diga en lugar de disimularlo."""
    sembrar(sesion, 1, dias_atras=1)
    monkeypatch.setattr(bandeja, "SEGUNDOS_DEL_CRITERIO", 0.0)

    pagina = listar(sesion, resolver_filtros())

    assert pagina.dentro_del_criterio is False
