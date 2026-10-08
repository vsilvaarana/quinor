"""Detalle del evento. HU-12.

  1. El detalle muestra pesos, conteo de sacos, personas detectadas, descripcion
     y severidad.
  2. El clip se reproduce en el navegador con controles de pausa y avance.
  3. Se muestra el fotograma donde se detecto la anomalia.

Contra MySQL de verdad, como el resto de la suite: la mitad de lo que esta
pantalla muestra sale de columnas JSON y de una tabla de auditoria con triggers,
y ninguna de las dos cosas sobrevive a una base sustituta.

Dos pruebas valen mas que las demas. `test_el_detalle_no_crece_en_consultas`
cuenta las sentencias que se ejecutan de verdad y falla si alguien mete un acceso
por fila: es la regresion que hundio al listado antes de HU-11 y es silenciosa
hasta que hay volumen. Y `test_el_detalle_no_lleva_nada_que_identifique_a_nadie`
revisa el payload campo por campo, porque esta es la pantalla donde la tentacion
de poner una cara seria mas grande, y la RN-08 lo prohibe.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from tests.conftest import ContadorDeConsultas

from app.almacen import ALMACEN_NO_CONFIGURADO, NO_SE_PUDO_FIRMAR, SIN_OBJETO, Firmador
from app.config import cargar_ajustes
from app.detalle import armar

CLIP = "s3://clips/ORD-2026-0001/evento-1-rampa.mkv"
FOTO = "s3://clips/ORD-2026-0001/evento-1-rampa/fotogramas/f000420_saco_saliente.jpg"

ANALISIS = {
    "descripcion": "Un operario retira un saco de la rampa y lo deja fuera del "
                   "contenedor mientras la carga continua.",
    "severidad_ia": "alta",
    "evidencia": ["un saco sale de la zona de carga en el segundo 14",
                  "dos personas permanecen mas de un minuto junto a la rampa"],
    "modelo": "vlm-stub-1",
    "proveedor": "stub",
    "confianza": 0.82,
    "intentos": 1,
}

VENTANA = {
    "numero_orden": "ORD-2026-0001",
    "camara": "rampa-01",
    "desde": "2026-10-03T08:55:00",
    "hasta": "2026-10-03T09:02:00",
    "duracion_s": 420.0,
    "inicio_carga_marcado": True,
    "clip_url": CLIP,
    "segmentos_usados": 7,
    "cobertura_pct": 100.0,
    "bytes": 48_000_000,
}


# ------------------------------------------------------------------ utilidades
def firmador(**extra) -> Firmador:
    """Firmador con credenciales de pega: firmar no sale a la red."""
    base = {"database_url": "mysql+pymysql://sin/uso",
            "minio_access_key": "llave", "minio_secret_key": "secreto"}
    base.update(extra)
    return Firmador(cargar_ajustes(**base))


def sembrar(sesion, *, estado="pendiente", diferencia_kg=Decimal("-150.00"),
            diferencia_pct=Decimal("-0.75"), peso_real=Decimal("19850.00"),
            sacos_contados=None, diferencia_sacos=None,
            personas_detectadas=None, personal_anomalo=None,
            severidad=None, descripcion_ia=None, fotogramas_clave=None,
            clip_url=None, inicio_carga=None,
            numero_orden="ORD-2026-0001") -> int:
    """Crea orden, pesada y evento como los deja el resto del sistema."""
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

    cuando = dt.datetime(2026, 10, 3, 9, 0, 0)
    pesada = Pesada(orden_id=orden.id, bascula_id="BASCULA-01",
                    peso_real_kg=peso_real, fecha_hora=cuando,
                    inicio_carga=inicio_carga, origen="bascula")
    sesion.add(pesada)
    sesion.flush()
    evento = Evento(
        pesada_id=pesada.id, diferencia_kg=diferencia_kg,
        diferencia_pct=diferencia_pct, estado=estado,
        sacos_contados=sacos_contados, diferencia_sacos=diferencia_sacos,
        personas_detectadas=personas_detectadas,
        personal_anomalo=personal_anomalo, severidad=severidad,
        descripcion_ia=descripcion_ia, fotogramas_clave=fotogramas_clave,
        clip_url=clip_url, creado_en=cuando)
    sesion.add(evento)
    sesion.commit()
    return evento.id


def anotar(sesion, evento_id: int, accion: str, detalle: dict) -> None:
    """Una fila de auditoria, por donde la escribe el sistema de verdad."""
    from app.models import Auditoria

    sesion.add(Auditoria(entidad="evento", entidad_id=evento_id, accion=accion,
                         usuario_id=None, detalle=detalle,
                         fecha=dt.datetime.now()))
    sesion.commit()


def sembrar_presencias(sesion, evento_id: int, cuantas: int) -> None:
    """Presencias de HU-08. Sin nada que identifique a nadie: RN-08."""
    from app.models import PersonaEnEvento

    for i in range(cuantas):
        sesion.add(PersonaEnEvento(
            evento_id=evento_id, id_temporal=i + 1,
            segundos_en_zona=Decimal("30.00") + i,
            primer_fotograma=100 + i * 10, ultimo_fotograma=200 + i * 10,
            creado_en=dt.datetime.now()))
    sesion.commit()


def fotograma(motivo: str, segundo: float, fotograma_num: int = 1,
              url: str = FOTO, detalle: str = "sale un saco de la zona") -> dict:
    return {"url": url, "motivo": motivo, "detalle": detalle,
            "segundo": segundo, "fotograma": fotograma_num}


# ------------------------------------------------------------------ criterio 1
def test_el_detalle_trae_las_cinco_cosas_del_criterio_1(sesion):
    """Pesos, conteo de sacos, personas, descripcion y severidad."""
    evento_id = sembrar(
        sesion, sacos_contados=397, diferencia_sacos=-3,
        personas_detectadas=2, personal_anomalo=True, severidad="alta",
        descripcion_ia=ANALISIS, clip_url=CLIP)
    sembrar_presencias(sesion, evento_id, 2)

    detalle = armar(sesion, evento_id, firmador())

    assert detalle.pesos.esperado_kg == Decimal("20000.00")
    assert detalle.pesos.real_kg == Decimal("19850.00")
    assert detalle.pesos.diferencia_kg == Decimal("-150.00")
    assert detalle.sacos.contados == 397
    assert detalle.sacos.diferencia == -3
    assert detalle.personas.detectadas == 2
    assert len(detalle.personas.presencias) == 2
    assert detalle.analisis.descripcion == ANALISIS["descripcion"]
    assert detalle.analisis.severidad == "alta"


def test_el_detalle_identifica_la_orden_y_la_pesada(sesion):
    """Sin la orden y el cliente, el supervisor no sabe de que carga se habla."""
    evento_id = sembrar(sesion, inicio_carga=dt.datetime(2026, 10, 3, 8, 55))

    detalle = armar(sesion, evento_id, firmador())

    assert detalle.id == evento_id
    assert detalle.estado == "pendiente"
    assert detalle.numero_orden == "ORD-2026-0001"
    assert detalle.cliente == "Andean Grains LLC"
    assert detalle.producto == "Quinua blanca organica"
    assert detalle.bascula_id == "BASCULA-01"
    assert detalle.pesada_fecha_hora == dt.datetime(2026, 10, 3, 9, 0)
    assert detalle.inicio_carga == dt.datetime(2026, 10, 3, 8, 55)


def test_la_tolerancia_es_la_de_aquel_dia_y_no_la_de_hoy(sesion):
    """Sale de la auditoria del momento en que se creo el evento.

    Si manana alguien sube la tolerancia, este evento tiene que seguir diciendo
    contra que umbral se juzgo aquella carga.
    """
    evento_id = sembrar(sesion)
    anotar(sesion, evento_id, "crear_evento",
           {"numero_orden": "ORD-2026-0001", "tolerancia_aplicada_kg": "100.00"})

    detalle = armar(sesion, evento_id, firmador())

    assert detalle.pesos.tolerancia_aplicada_kg == Decimal("100.00")
    # Faltan 150 donde se toleraban 100: el caso no esta al borde.
    assert detalle.pesos.exceso_sobre_la_tolerancia_kg == Decimal("50.00")


def test_sin_auditoria_de_creacion_no_se_inventa_la_tolerancia(sesion):
    detalle = armar(sesion, sembrar(sesion), firmador())

    assert detalle.pesos.tolerancia_aplicada_kg is None
    assert detalle.pesos.exceso_sobre_la_tolerancia_kg is None


def test_una_tolerancia_corrupta_en_la_auditoria_no_tumba_el_detalle(sesion):
    evento_id = sembrar(sesion)
    anotar(sesion, evento_id, "crear_evento", {"tolerancia_aplicada_kg": "ninguna"})

    assert armar(sesion, evento_id, firmador()).pesos.tolerancia_aplicada_kg is None


def test_el_sobrepeso_tambien_es_una_senal(sesion):
    """Un contenedor mas pesado de lo planificado apunta a sustitucion igual."""
    evento_id = sembrar(sesion, diferencia_kg=Decimal("180.00"),
                        diferencia_pct=Decimal("0.90"),
                        peso_real=Decimal("20180.00"))

    detalle = armar(sesion, evento_id, firmador())

    assert detalle.pesos.falta_producto is False
    assert detalle.pesos.diferencia_kg == Decimal("180.00")


def test_sin_conteo_los_sacos_no_estan_analizados(sesion):
    """None no es cero: un cero diria que no cruzo ningun saco."""
    detalle = armar(sesion, sembrar(sesion), firmador())

    assert detalle.sacos.contados is None
    assert detalle.sacos.analizado is False
    assert detalle.sacos.cuadran is None
    assert detalle.analizado is False
    assert detalle.sacos.esperados == 400


def test_los_sacos_pueden_cuadrar_con_el_peso_corto(sesion):
    """La firma de la sustitucion de producto, que es lo que motiva todo esto."""
    evento_id = sembrar(sesion, sacos_contados=400, diferencia_sacos=0,
                        severidad="alta")

    detalle = armar(sesion, evento_id, firmador())

    assert detalle.sacos.cuadran is True
    assert detalle.analizado is True
    assert detalle.peso_corto_con_sacos_completos is True


def test_con_sacos_de_menos_no_es_sustitucion_sino_faltante(sesion):
    evento_id = sembrar(sesion, sacos_contados=397, diferencia_sacos=-3)

    detalle = armar(sesion, evento_id, firmador())

    assert detalle.sacos.cuadran is False
    assert detalle.peso_corto_con_sacos_completos is False


def test_las_presencias_llegan_con_sus_totales(sesion):
    """Criterio 2 de HU-08: cuantas estuvieron y cuanto tiempo."""
    evento_id = sembrar(sesion, personas_detectadas=3, personal_anomalo=False)
    sembrar_presencias(sesion, evento_id, 3)

    personas = armar(sesion, evento_id, firmador()).personas

    assert personas.analizado is True
    assert personas.personal_anomalo is False
    assert [p.id_temporal for p in personas.presencias] == [1, 2, 3]
    assert personas.segundos_totales == Decimal("93.00")
    assert personas.permanencia_maxima_s == Decimal("32.00")


def test_sin_analisis_de_video_no_hay_personas_ni_cero_personas(sesion):
    personas = armar(sesion, sembrar(sesion), firmador()).personas

    assert personas.detectadas is None
    assert personas.analizado is False
    assert personas.presencias == ()
    assert personas.segundos_totales == Decimal("0.00")
    assert personas.permanencia_maxima_s == Decimal("0.00")
    assert personas.personal_anomalo is None


def test_el_analisis_trae_lo_que_el_modelo_dijo_y_con_que_modelo(sesion):
    evento_id = sembrar(sesion, severidad="alta", descripcion_ia=ANALISIS)

    analisis = armar(sesion, evento_id, firmador()).analisis

    assert analisis.hay_descripcion is True
    assert analisis.evidencia == tuple(ANALISIS["evidencia"])
    assert analisis.modelo == "vlm-stub-1"
    assert analisis.proveedor == "stub"
    assert analisis.confianza == pytest.approx(0.82)
    assert analisis.intentos == 1
    # Las dos coinciden: no hay nada que revisar esta semana.
    assert analisis.discrepan is False


def test_cuando_el_modelo_y_la_regla_discrepan_se_ve(sesion):
    """De estas discrepancias sale la concordancia semanal del apartado 9.2."""
    evento_id = sembrar(sesion, severidad="media",
                        descripcion_ia={**ANALISIS, "severidad_ia": "alta"})

    analisis = armar(sesion, evento_id, firmador()).analisis

    assert analisis.severidad == "media"
    assert analisis.severidad_ia == "alta"
    assert analisis.discrepan is True


def test_la_severidad_de_la_regla_existe_aunque_el_modelo_fallara(sesion):
    """Estado pendiente_analisis: la RN-04 ya dio severidad, el modelo no llego."""
    evento_id = sembrar(sesion, estado="pendiente_analisis", severidad="alta",
                        descripcion_ia=None, clip_url=CLIP)

    analisis = armar(sesion, evento_id, firmador()).analisis

    assert analisis.severidad == "alta"
    assert analisis.hay_descripcion is False
    assert analisis.descripcion is None
    assert analisis.discrepan is False


@pytest.mark.parametrize("guardado", [
    "una cadena donde deberia haber un objeto",
    ["una lista"],
    42,
])
def test_un_analisis_con_otra_forma_no_tumba_el_detalle(sesion, guardado):
    """Lo escribe otro servicio: si llega raro, se pierde el analisis, no la pantalla."""
    evento_id = sembrar(sesion, severidad="baja", descripcion_ia=guardado)

    analisis = armar(sesion, evento_id, firmador()).analisis

    assert analisis.severidad == "baja"
    assert analisis.descripcion is None
    assert analisis.evidencia == ()


def test_una_evidencia_que_no_es_lista_se_descarta_sin_ruido(sesion):
    evento_id = sembrar(sesion, severidad="baja",
                        descripcion_ia={**ANALISIS, "evidencia": "un saco sale"})

    assert armar(sesion, evento_id, firmador()).analisis.evidencia == ()


def test_una_confianza_que_no_es_numero_no_se_inventa(sesion):
    evento_id = sembrar(sesion, descripcion_ia={**ANALISIS, "confianza": "mucha"})

    assert armar(sesion, evento_id, firmador()).analisis.confianza is None


# ------------------------------------------------------------------ criterio 2
def test_el_clip_llega_firmado_y_listo_para_el_reproductor(sesion):
    evento_id = sembrar(sesion, clip_url=CLIP)

    clip = armar(sesion, evento_id, firmador()).clip

    assert clip.reproducible is True
    assert "X-Amz-Signature=" in clip.enlace.url
    assert clip.enlace.direccion == CLIP
    assert clip.enlace.minutos == 15


def test_la_ventana_del_clip_es_la_que_el_grabador_recorto(sesion):
    """No se repite aqui la cuenta de los cinco minutos: dos copias discrepan."""
    evento_id = sembrar(sesion, clip_url=CLIP)
    anotar(sesion, evento_id, "recortar_clip", VENTANA)

    clip = armar(sesion, evento_id, firmador()).clip

    assert clip.desde == dt.datetime(2026, 10, 3, 8, 55)
    assert clip.hasta == dt.datetime(2026, 10, 3, 9, 2)
    assert clip.duracion_s == pytest.approx(420.0)
    assert clip.camara == "rampa-01"
    assert clip.cobertura_pct == pytest.approx(100.0)
    assert clip.completo is True
    assert clip.motivo_sin_clip is None


def test_un_clip_a_medias_se_reproduce_pero_se_avisa(sesion):
    """Quien lo mira tiene que saber que no lo cubre todo antes de concluir."""
    evento_id = sembrar(sesion, clip_url=CLIP)
    anotar(sesion, evento_id, "recortar_clip", {**VENTANA, "cobertura_pct": 62.5})

    clip = armar(sesion, evento_id, firmador()).clip

    assert clip.reproducible is True
    assert clip.completo is False


def test_sin_anotacion_de_recorte_no_se_sabe_la_cobertura(sesion):
    clip = armar(sesion, sembrar(sesion, clip_url=CLIP), firmador()).clip

    assert clip.completo is None
    assert clip.desde is None


def test_un_evento_sin_clip_dice_por_que_no_lo_tiene(sesion):
    """No es lo mismo la camara caida que el video ya purgado del buffer."""
    evento_id = sembrar(sesion, estado="sin_clip", clip_url=None)
    anotar(sesion, evento_id, "evento_sin_clip",
           {**VENTANA, "clip_url": None,
            "motivo": "no hay video de esa ventana en el buffer"})

    clip = armar(sesion, evento_id, firmador()).clip

    assert clip.reproducible is False
    assert clip.enlace.motivo == SIN_OBJETO
    assert clip.motivo_sin_clip == "no hay video de esa ventana en el buffer"
    # La ventana que se intento recortar se conserva: dice que se busco.
    assert clip.desde == dt.datetime(2026, 10, 3, 8, 55)


def test_de_dos_intentos_de_recorte_vale_el_ultimo(sesion):
    """El grabador reintenta, y lo que cuenta es como quedo la cosa."""
    evento_id = sembrar(sesion, clip_url=CLIP)
    anotar(sesion, evento_id, "recortar_clip", {**VENTANA, "cobertura_pct": 40.0})
    anotar(sesion, evento_id, "recortar_clip", {**VENTANA, "cobertura_pct": 100.0})

    assert armar(sesion, evento_id, firmador()).clip.cobertura_pct == 100.0


def test_una_fecha_corrupta_en_la_auditoria_no_tumba_el_detalle(sesion):
    evento_id = sembrar(sesion, clip_url=CLIP)
    anotar(sesion, evento_id, "recortar_clip",
           {**VENTANA, "desde": "ayer por la tarde", "duracion_s": "un rato"})

    clip = armar(sesion, evento_id, firmador()).clip

    assert clip.desde is None
    assert clip.duracion_s is None
    assert clip.reproducible is True


def test_sin_credenciales_del_almacen_el_detalle_se_arma_igual(sesion):
    """El supervisor tiene delante una discrepancia real: no se le deja sin ella."""
    evento_id = sembrar(sesion, clip_url=CLIP, sacos_contados=397,
                        diferencia_sacos=-3)

    detalle = armar(sesion, evento_id, None)

    assert detalle.clip.reproducible is False
    assert detalle.clip.enlace.motivo == ALMACEN_NO_CONFIGURADO
    assert detalle.clip.enlace.direccion == CLIP
    assert detalle.sacos.contados == 397


def test_sin_firmador_y_sin_clip_el_motivo_es_que_no_hay_nada(sesion):
    detalle = armar(sesion, sembrar(sesion), None)

    assert detalle.clip.enlace.motivo == SIN_OBJETO


def test_si_el_almacen_rechaza_la_firma_se_dice_en_su_sitio(sesion):
    class ClienteQueFalla:
        def presigned_get_object(self, *_a, **_k):
            raise OSError("el almacen no responde")

    evento_id = sembrar(sesion, clip_url=CLIP)
    firma = Firmador(cargar_ajustes(database_url="mysql+pymysql://sin/uso",
                                    minio_access_key="llave",
                                    minio_secret_key="secreto"),
                     fabrica=lambda _a: ClienteQueFalla())

    clip = armar(sesion, evento_id, firma).clip

    assert clip.enlace.motivo == NO_SE_PUDO_FIRMAR
    assert clip.enlace.explicacion


# ------------------------------------------------------------------ criterio 3
def test_los_fotogramas_llegan_firmados_y_ordenados_por_lo_que_hay_que_ver(sesion):
    evento_id = sembrar(sesion, clip_url=CLIP, severidad="alta", fotogramas_clave=[
        fotograma("primer_saco", 2.0, 60),
        fotograma("saco_saliente", 14.5, 435),
        fotograma("pico_de_personas", 31.0, 930),
        fotograma("ultimo_saco", 400.0, 12000),
    ])

    fotogramas = armar(sesion, evento_id, firmador()).fotogramas

    assert [f.motivo for f in fotogramas] == [
        "saco_saliente", "pico_de_personas", "primer_saco", "ultimo_saco"]
    assert all(f.enlace.reproducible for f in fotogramas)
    assert "X-Amz-Signature=" in fotogramas[0].enlace.url


def test_la_anomalia_es_el_saco_que_sale_y_no_el_primero_de_la_carga(sesion):
    """El criterio 3 pide la anomalia; el primer saco de la carga no lo es."""
    evento_id = sembrar(sesion, clip_url=CLIP, fotogramas_clave=[
        fotograma("primer_saco", 2.0, 60),
        fotograma("saco_saliente", 14.5, 435),
    ])

    detalle = armar(sesion, evento_id, firmador())

    assert detalle.anomalia.motivo == "saco_saliente"
    assert detalle.anomalia.es_anomalia is True
    # Y el reproductor abre ahi, para no dejarlo buscandola a mano.
    assert detalle.segundo_de_entrada == pytest.approx(14.5)


def test_entre_dos_sacos_salientes_se_elige_el_primero(sesion):
    """Igual de graves: el de antes explica mejor como empezo."""
    evento_id = sembrar(sesion, clip_url=CLIP, fotogramas_clave=[
        fotograma("saco_saliente", 240.0, 7200),
        fotograma("saco_saliente", 14.5, 435),
    ])

    assert armar(sesion, evento_id, firmador()).anomalia.segundo == pytest.approx(14.5)


def test_sin_anomalias_se_abre_el_momento_mas_relevante(sesion):
    """Mejor que no abrir ninguno: sigue siendo el fotograma que mas dice."""
    evento_id = sembrar(sesion, clip_url=CLIP, fotogramas_clave=[
        fotograma("ultimo_saco", 400.0, 12000),
        fotograma("primer_saco", 2.0, 60),
    ])

    detalle = armar(sesion, evento_id, firmador())

    assert detalle.anomalia.motivo == "primer_saco"
    assert detalle.anomalia.es_anomalia is False
    assert detalle.segundo_de_entrada == pytest.approx(2.0)


def test_un_motivo_que_este_modulo_no_conoce_va_al_final(sesion):
    """HU-19 puede traer motivos nuevos: no se pierden, se ordenan detras."""
    evento_id = sembrar(sesion, clip_url=CLIP, fotogramas_clave=[
        fotograma("motivo_de_otro_sprint", 10.0, 300),
        fotograma("primer_saco", 2.0, 60),
    ])

    fotogramas = armar(sesion, evento_id, firmador()).fotogramas

    assert [f.motivo for f in fotogramas] == ["primer_saco", "motivo_de_otro_sprint"]
    assert fotogramas[1].prioridad == 0


def test_un_evento_sin_fotogramas_no_tiene_anomalia_que_abrir(sesion):
    detalle = armar(sesion, sembrar(sesion, clip_url=CLIP), firmador())

    assert detalle.fotogramas == ()
    assert detalle.anomalia is None
    assert detalle.segundo_de_entrada == 0.0


@pytest.mark.parametrize("guardado", ["no es una lista", {"url": FOTO}, 7])
def test_unos_fotogramas_con_otra_forma_se_descartan_sin_ruido(sesion, guardado):
    evento_id = sembrar(sesion, clip_url=CLIP, fotogramas_clave=guardado)

    assert armar(sesion, evento_id, firmador()).fotogramas == ()


def test_un_fotograma_a_medias_se_aprovecha_lo_que_tenga(sesion):
    """Lo escribe otro servicio. Falta el segundo: se abre al principio."""
    evento_id = sembrar(sesion, clip_url=CLIP,
                        fotogramas_clave=[{"url": FOTO}, "basura"])

    fotogramas = armar(sesion, evento_id, firmador()).fotogramas

    assert len(fotogramas) == 1
    assert fotogramas[0].motivo == ""
    assert fotogramas[0].segundo == 0.0
    assert fotogramas[0].fotograma == 0
    assert fotogramas[0].enlace.reproducible is True


def test_un_fotograma_sin_url_dice_que_no_hay_imagen(sesion):
    evento_id = sembrar(sesion, clip_url=CLIP,
                        fotogramas_clave=[fotograma("saco_saliente", 5.0, url=None)])

    fotogramas = armar(sesion, evento_id, firmador()).fotogramas

    assert fotogramas[0].enlace.motivo == SIN_OBJETO
    assert fotogramas[0].enlace.explicacion


# -------------------------------------------------------------- la invariante
def test_el_detalle_no_crece_en_consultas(sesion, motor):
    """Tres consultas, con una presencia y con cuarenta.

    Es la prueba que impide que esta pantalla se degrade en silencio. Si alguien
    vuelve a leer la auditoria o las personas por fila, aqui se ve.
    """
    uno = sembrar(sesion, clip_url=CLIP, personas_detectadas=1, severidad="alta",
                  descripcion_ia=ANALISIS, fotogramas_clave=[
                      fotograma("saco_saliente", 14.5, 435)])
    sembrar_presencias(sesion, uno, 1)
    anotar(sesion, uno, "crear_evento", {"tolerancia_aplicada_kg": "100.00"})
    anotar(sesion, uno, "recortar_clip", VENTANA)

    with ContadorDeConsultas(motor) as contador:
        armar(sesion, uno, firmador())
    assert len(contador) == 3, contador.sentencias

    muchos = sembrar(sesion, clip_url=CLIP, personas_detectadas=40,
                     severidad="alta", descripcion_ia=ANALISIS,
                     numero_orden="ORD-2026-0148",
                     fotogramas_clave=[fotograma("saco_saliente", 14.5, 435),
                                       fotograma("pico_de_personas", 31.0, 930),
                                       fotograma("primer_saco", 2.0, 60),
                                       fotograma("ultimo_saco", 400.0, 12000)])
    sembrar_presencias(sesion, muchos, 40)
    anotar(sesion, muchos, "crear_evento", {"tolerancia_aplicada_kg": "100.00"})
    anotar(sesion, muchos, "recortar_clip", VENTANA)

    with ContadorDeConsultas(motor) as contador:
        detalle = armar(sesion, muchos, firmador())
    assert len(contador) == 3, contador.sentencias
    assert len(detalle.personas.presencias) == 40
    assert len(detalle.fotogramas) == 4


def test_un_evento_que_no_existe_no_es_un_detalle_vacio(sesion):
    assert armar(sesion, 999_999, firmador()) is None


# ------------------------------------------------------------------- por HTTP
def test_el_endpoint_devuelve_el_detalle_completo(client, sesion):
    evento_id = sembrar(sesion, clip_url=CLIP, sacos_contados=400,
                        diferencia_sacos=0, personas_detectadas=2,
                        personal_anomalo=True, severidad="alta",
                        descripcion_ia=ANALISIS,
                        fotogramas_clave=[fotograma("saco_saliente", 14.5, 435),
                                          fotograma("primer_saco", 2.0, 60)])
    sembrar_presencias(sesion, evento_id, 2)
    anotar(sesion, evento_id, "crear_evento", {"tolerancia_aplicada_kg": "100.00"})
    anotar(sesion, evento_id, "recortar_clip", VENTANA)

    respuesta = client.get(f"/eventos/{evento_id}/detalle")

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["numero_orden"] == "ORD-2026-0001"
    assert cuerpo["pesos"]["diferencia_kg"] == "-150.00"
    assert cuerpo["pesos"]["tolerancia_aplicada_kg"] == "100.00"
    assert cuerpo["pesos"]["falta_producto"] is True
    assert cuerpo["sacos"]["cuadran"] is True
    assert cuerpo["peso_corto_con_sacos_completos"] is True
    assert len(cuerpo["personas"]["presencias"]) == 2
    assert cuerpo["personas"]["nota"].endswith("(RN-08).")
    assert cuerpo["analisis"]["severidad"] == "alta"
    assert cuerpo["analisis"]["hay_descripcion"] is True
    assert cuerpo["clip"]["camara"] == "rampa-01"
    assert cuerpo["anomalia"]["motivo"] == "saco_saliente"
    assert cuerpo["segundo_de_entrada"] == pytest.approx(14.5)
    assert cuerpo["analizado"] is True


def test_el_endpoint_firma_el_clip_cuando_hay_credenciales(crear_cliente, sesion):
    cliente = crear_cliente(minio_access_key="llave", minio_secret_key="secreto",
                            clip_url_minutos=5)
    evento_id = sembrar(sesion, clip_url=CLIP,
                        fotogramas_clave=[fotograma("saco_saliente", 14.5, 435)])

    cuerpo = cliente.get(f"/eventos/{evento_id}/detalle").json()

    assert cuerpo["clip"]["reproducible"] is True
    assert "X-Amz-Signature=" in cuerpo["clip"]["enlace"]["url"]
    assert cuerpo["clip"]["enlace"]["minutos"] == 5
    assert cuerpo["fotogramas"][0]["enlace"]["reproducible"] is True


def test_sin_credenciales_el_endpoint_explica_el_hueco(client, sesion):
    """La aplicacion de las pruebas no tiene MinIO, y la respuesta lo dice."""
    evento_id = sembrar(sesion, clip_url=CLIP)

    enlace = client.get(f"/eventos/{evento_id}/detalle").json()["clip"]["enlace"]

    assert enlace["reproducible"] is False
    assert enlace["motivo"] == ALMACEN_NO_CONFIGURADO
    assert enlace["explicacion"]
    assert enlace["direccion"] == CLIP


def test_el_endpoint_contesta_404_cuando_el_evento_no_existe(client):
    respuesta = client.get("/eventos/999999/detalle")

    assert respuesta.status_code == 404
    assert "999999" in respuesta.json()["detail"]


def test_el_detalle_exige_token(app, sesion):
    """Un clip de la rampa no se mira sin identificarse. HU-15, criterio 4."""
    from fastapi.testclient import TestClient

    evento_id = sembrar(sesion, clip_url=CLIP)
    with TestClient(app) as sin_token:
        assert sin_token.get(f"/eventos/{evento_id}/detalle").status_code == 401


def test_el_rol_consulta_puede_ver_el_detalle(client_consulta, sesion):
    """Leer es justo lo que el rol Consulta puede hacer."""
    evento_id = sembrar(sesion, clip_url=CLIP)

    assert client_consulta.get(f"/eventos/{evento_id}/detalle").status_code == 200


def test_el_detalle_no_lleva_nada_que_identifique_a_nadie(client, sesion):
    """RN-08 y apartado 8, revisado campo por campo.

    Esta es la pantalla donde la tentacion de poner una cara seria mas grande.
    Lo unico que sale de cada presencia es el numero que puso el rastreador y el
    tiempo en zona, y el payload no tiene por donde colar otra cosa.
    """
    evento_id = sembrar(sesion, personas_detectadas=2, personal_anomalo=True)
    sembrar_presencias(sesion, evento_id, 2)

    personas = client.get(f"/eventos/{evento_id}/detalle").json()["personas"]

    for presencia in personas["presencias"]:
        assert set(presencia) == {"id_temporal", "segundos_en_zona",
                                  "primer_fotograma", "ultimo_fotograma"}
    # "foto" a secas no sirve de sonda: casa con `primer_fotograma`, que es un
    # numero de cuadro del video y no una fotografia de nadie.
    prohibido = ("fotografia", "imagen", "recorte", "rostro", "cara", "nombre",
                 "empleado", "dni", "biometr")
    # Sobre las presencias, no sobre la nota: la nota es justo el aviso de la
    # RN-08 y menciona los datos biometricos para decir que no hay ninguno.
    texto = repr(personas["presencias"]).lower()
    assert not any(palabra in texto for palabra in prohibido)
    assert "biometricos" in personas["nota"]


def test_el_detalle_de_un_evento_recien_creado_ya_sirve_de_algo(client, sesion):
    """Sin clip, sin conteo y sin analisis: la discrepancia de peso ya esta."""
    evento_id = sembrar(sesion)

    cuerpo = client.get(f"/eventos/{evento_id}/detalle").json()

    assert cuerpo["pesos"]["diferencia_kg"] == "-150.00"
    assert cuerpo["analizado"] is False
    assert cuerpo["sacos"]["analizado"] is False
    assert cuerpo["personas"]["analizado"] is False
    assert cuerpo["analisis"]["severidad"] is None
    assert cuerpo["clip"]["reproducible"] is False
    assert cuerpo["clip"]["enlace"]["motivo"] == SIN_OBJETO
    assert cuerpo["fotogramas"] == []
    assert cuerpo["anomalia"] is None


def test_el_detalle_no_cambia_el_contrato_de_la_bandeja(client, sesion):
    """`GET /eventos/{id}` sigue siendo lo que era: lo consume HU-11."""
    evento_id = sembrar(sesion, clip_url=CLIP)

    viejo = client.get(f"/eventos/{evento_id}")

    assert viejo.status_code == 200
    assert viejo.json()["clip_url"] == CLIP
    assert "clip" not in viejo.json()


# ---------------------------------------------- el contenedor del clip (crit. 2)
@pytest.mark.parametrize("direccion, formato", [
    (CLIP, "mkv"),
    ("s3://clips/a/b.webm", "webm"),
    ("s3://clips/a/b.MP4", "mp4"),
    ("s3://clips/a/sin-extension", None),
])
def test_el_detalle_dice_en_que_formato_esta_el_clip(sesion, direccion, formato):
    """Chrome y Edge reproducen Matroska; Firefox y Safari no.

    El criterio 2 habla del navegador, asi que la pantalla tiene que poder
    advertirlo en lugar de dejar un recuadro negro sin explicacion.
    """
    evento_id = sembrar(sesion, clip_url=direccion)

    assert armar(sesion, evento_id, firmador()).clip.formato == formato


def test_sin_clip_no_hay_formato_que_advertir(sesion):
    assert armar(sesion, sembrar(sesion), firmador()).clip.formato is None
