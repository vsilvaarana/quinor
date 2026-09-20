"""Criterio 2 de HU-10: que dice el correo.

  2. La notificacion incluye orden, diferencia y enlace al evento.

Las tres cosas se buscan en el cuerpo del mensaje, no en la estructura de datos
que lo genero: lo que el supervisor lee es el texto, y una plantilla puede
perder un campo sin que ningun objeto cambie.
"""
from __future__ import annotations

import pytest

from app.destinatarios import ALTA, BAJA, MEDIA
from app.plantilla import (Contexto, _con_signo, asunto, componer,
                           cuerpo_html, diferencia_corta, etiqueta_de, texto)

ENLACE = "http://dashboard.quinor.local:8050/eventos/41"


def contexto(**cambios) -> Contexto:
    base = dict(
        evento_id=41, severidad=ALTA, numero_orden="OD-2026-0148",
        cliente="Andean Grains LLC", producto="Quinua organica blanca",
        peso_esperado_kg=20000.0, peso_real_kg=19600.0,
        diferencia_kg=-400.0, diferencia_pct=-2.0,
        sacos_esperados=400, sacos_contados=392, diferencia_sacos=-8,
        personas_detectadas=5, personal_anomalo=True,
        descripcion_ia="Dos personas retiran sacos del pallet junto a la rampa.",
        evidencia=("Sacos salientes en el minuto 4",),
        fecha_del_evento="18/09/2026 09:41")
    base.update(cambios)
    return Contexto(**base)


# ------------------------------------------------------------------ criterio 2
def test_el_correo_lleva_la_orden():
    mensaje = componer(contexto(), ENLACE)
    assert "OD-2026-0148" in mensaje.asunto
    assert "OD-2026-0148" in mensaje.texto
    assert "OD-2026-0148" in mensaje.html


def test_el_correo_lleva_la_diferencia():
    mensaje = componer(contexto(), ENLACE)
    for cuerpo in (mensaje.asunto, mensaje.texto, mensaje.html):
        assert "8" in cuerpo and "sacos" in cuerpo.lower()
    assert "400.00" in mensaje.texto and "kg" in mensaje.texto


def test_el_correo_lleva_el_enlace_al_evento():
    mensaje = componer(contexto(), ENLACE)
    assert ENLACE in mensaje.texto
    assert ENLACE in mensaje.html


def test_el_enlace_esta_tambien_como_texto_en_el_html():
    """Hay clientes que no pintan el boton. El criterio pide que el enlace este,
    no que sea bonito."""
    html = cuerpo_html(contexto(), ENLACE)
    assert html.count(ENLACE) >= 2


# ------------------------------------------------------- la diferencia con signo
def test_un_faltante_dice_faltan():
    assert diferencia_corta(contexto(diferencia_sacos=-8)) == "faltan 8 sacos"


def test_un_sobrante_dice_sobran():
    """"Faltan 8" y "sobran 8" son dos situaciones distintas, y un numero suelto
    no las distingue. Un sobrante suele ser un error de carga, no un hurto."""
    assert diferencia_corta(contexto(diferencia_sacos=8)) == "sobran 8 sacos"


def test_sin_diferencia_de_sacos_se_informa_la_de_peso():
    dicho = diferencia_corta(contexto(diferencia_sacos=None,
                                      diferencia_kg=-125.5))
    assert dicho == "faltan 125.50 kg"


def test_con_los_sacos_cuadrados_y_peso_corto_manda_el_peso():
    """El conteo cuadra pero faltan kilos: puede ser sustitucion del contenido,
    que es justo el problema de QUINOR. El correo no puede decir '0 sacos' y
    callarse los kilos."""
    dicho = diferencia_corta(contexto(diferencia_sacos=0, diferencia_kg=-310.0))
    assert dicho == "faltan 310.00 kg"


def test_sin_ninguna_diferencia_medible_lo_dice():
    dicho = diferencia_corta(contexto(diferencia_sacos=None,
                                      diferencia_kg=None))
    assert dicho == "diferencia sin cuantificar"


def test_una_diferencia_de_cero_no_se_convierte_en_faltante():
    dicho = diferencia_corta(contexto(diferencia_sacos=None, diferencia_kg=0.0))
    assert dicho == "0 kg"


# ------------------------------------------------------------------ criterio 1
def test_la_alta_lleva_el_asunto_marcado():
    """"Alta: con asunto marcado". El corchete se lee antes que nada y permite
    filtrar en el cliente de correo sin depender de nosotros."""
    assert asunto(contexto(severidad=ALTA)).startswith("[ALERTA ALTA]")


def test_cada_nivel_tiene_su_marca_y_no_se_confunden():
    marcas = {etiqueta_de(n) for n in (ALTA, MEDIA, BAJA)}
    assert len(marcas) == 3


def test_una_severidad_inventada_se_marca_como_alta():
    assert etiqueta_de("rarisima") == etiqueta_de(ALTA)


def test_el_asunto_cabe_en_la_columna_de_la_tabla():
    largo = contexto(numero_orden="OD-" + "9" * 300, cliente="C" * 300)
    assert len(asunto(largo)) <= 300


# ------------------------------------------------ el correo sale con lo que haya
def test_sin_orden_el_correo_sale_igual():
    """Un aviso con un hueco llega a tiempo; un aviso que no sale por falta de
    un campo no sirve de nada."""
    mensaje = componer(contexto(numero_orden="", cliente=""), ENLACE)
    assert "evento 41" in mensaje.asunto
    assert ENLACE in mensaje.texto


def test_sin_analisis_del_modelo_el_correo_sale_igual():
    mensaje = componer(contexto(descripcion_ia="", evidencia=()), ENLACE)
    assert ENLACE in mensaje.texto
    assert "Que se vio en el video" not in mensaje.texto


def test_sin_conteo_de_sacos_no_se_inventa_un_cero():
    """None no es cero: significa que el clip no se analizo, y decir '0 sacos
    contados' mandaria a alguien a la rampa por nada."""
    cuerpo = texto(contexto(sacos_contados=None, sacos_esperados=None,
                            diferencia_sacos=None), ENLACE)
    assert "Diferencia en sacos" not in cuerpo


def test_los_motivos_de_anomalia_aparecen_cuando_los_hay():
    cuerpo = componer(contexto(motivos_de_anomalia=("5 personas en zona, lo "
                                                    "habitual son 3",)), ENLACE)
    assert "5 personas en zona" in cuerpo.texto
    assert "5 personas en zona" in cuerpo.html


# ---------------------------------------------------------------------- formato
def test_el_html_escapa_lo_que_viene_de_fuera():
    """La descripcion la escribe un modelo y el cliente lo pone el ERP. Ni uno
    ni otro son sitios donde confiar en que no llegue un '<'."""
    html = cuerpo_html(contexto(cliente="<script>alert(1)</script>"), ENLACE)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_hay_version_en_texto_y_version_html():
    """El HTML es el que se lee; el texto plano es el que sobrevive al cliente
    de correo del telefono corporativo."""
    mensaje = componer(contexto(), ENLACE)
    assert mensaje.texto and "<" not in mensaje.texto.split("http")[0]
    assert mensaje.html.startswith("<html>")


@pytest.mark.parametrize("nivel", [ALTA, MEDIA, BAJA])
def test_los_tres_niveles_dicen_que_hacer(nivel):
    """Un aviso sin una accion asociada es ruido."""
    mensaje = componer(contexto(severidad=nivel), ENLACE)
    assert "dashboard" in mensaje.texto.lower()


def test_el_correo_no_lleva_fotogramas_adjuntos():
    """Son imagenes de la zona de carga con personas dentro. El apartado 8 las
    quiere en la red interna, y un adjunto sale de ese control en cuanto alguien
    reenvia el correo. El enlace lleva al dashboard, que pide sesion."""
    mensaje = componer(contexto(), ENLACE)
    assert "base64" not in mensaje.html
    assert "data:image" not in mensaje.html


def test_un_dato_que_falta_se_dice_y_no_se_inventa():
    """"sin dato" y "0" son cosas distintas, y confundirlas en un correo de
    alerta manda a alguien a la rampa o le deja tranquilo sin motivo.

    El caso es real: la pesada existe pero la orden llego del ERP sin peso
    esperado, o al reves.
    """
    cuerpo = texto(contexto(peso_esperado_kg=None), ENLACE)

    assert "19 600.00 kg reales de sin dato" in cuerpo


def test_ningun_hueco_se_convierte_en_un_numero():
    """La guarda de la funcion que escribe las diferencias. Que un None acabe
    como '0' en un correo de alerta es exactamente el error que no se puede
    cometer, asi que se comprueba aunque hoy ningun camino llegue hasta ella."""
    assert _con_signo(None, "sacos") == "sin dato"


def test_con_los_sacos_cuadrados_y_sin_peso_se_informan_los_sacos():
    """El conteo cuadra y no hay medida de peso: lo unico que se puede decir es
    que los sacos cuadran, y decirlo es mejor que callarse."""
    dicho = diferencia_corta(contexto(diferencia_sacos=0, diferencia_kg=None))

    assert dicho == "0 sacos"
