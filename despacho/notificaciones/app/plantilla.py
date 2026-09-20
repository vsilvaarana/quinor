"""El correo que recibe el supervisor. HU-10, criterios 1 y 2.

  2. La notificacion incluye orden, diferencia y enlace al evento.

Esos tres datos son el minimo exigido, y el modulo los garantiza con pruebas
que los buscan en el cuerpo del mensaje. Lo demas del contenido responde a una
idea sencilla: el supervisor lee esto en el telefono, de pie, y de esa lectura
sale una decision, que es ir a la rampa o no ir. Todo lo que no ayude a esa
decision sobra.

De ahi tres elecciones:

  - El asunto lleva la orden y la diferencia. Un asunto que dijera "Alerta de
    despacho" obligaria a abrir todos los correos para saber cual importa.
  - La diferencia se da en sacos y en kilos, y con el signo puesto. "Faltan 8
    sacos" y "sobran 8 sacos" son dos situaciones distintas y un numero suelto
    no las distingue.
  - El mensaje va en texto plano y en HTML. El HTML es el que se lee; el texto
    plano es el que sobrevive al cliente de correo del telefono corporativo y a
    las reglas que bloquean el HTML remoto.

El correo no lleva fotogramas adjuntos. Son imagenes de la zona de carga con
personas dentro, y el apartado 8 las quiere en la red interna: un adjunto sale
del control del sistema en cuanto alguien reenvia el correo. El enlace del
criterio 2 lleva al dashboard, que pide sesion.
"""
from __future__ import annotations

import dataclasses
import html

from app.destinatarios import ALTA, BAJA, MEDIA

# Marca del asunto del criterio 1: "Alta: ... con asunto marcado y prioridad
# alta". El corchete se lee antes que ninguna otra cosa y permite al supervisor
# filtrar en su cliente de correo sin depender de nosotros.
ETIQUETAS = {
    ALTA: "[ALERTA ALTA]",
    MEDIA: "[Alerta media]",
    BAJA: "[Aviso]",
}

QUE_HACER = {
    ALTA: ("Revisar el contenedor antes de que salga de planta y confirmar o "
           "descartar el evento en el dashboard."),
    MEDIA: ("Revisar el clip y clasificar el evento en el dashboard antes del "
            "cierre del turno."),
    BAJA: "Queda registrado para la revision del turno.",
}


@dataclasses.dataclass(frozen=True)
class Contexto:
    """Los datos del evento que entran en el correo.

    Todo es opcional menos el identificador del evento porque el correo tiene
    que salir igual cuando falta un dato. Un aviso con un hueco llega a tiempo;
    un aviso que no sale por falta de un campo no sirve de nada.
    """

    evento_id: int
    severidad: str = ALTA
    numero_orden: str = ""
    cliente: str = ""
    producto: str = ""

    peso_esperado_kg: float | None = None
    peso_real_kg: float | None = None
    diferencia_kg: float | None = None
    diferencia_pct: float | None = None

    sacos_esperados: int | None = None
    sacos_contados: int | None = None
    diferencia_sacos: int | None = None

    personas_detectadas: int | None = None
    personal_anomalo: bool | None = None
    motivos_de_anomalia: tuple[str, ...] = ()

    descripcion_ia: str = ""
    evidencia: tuple[str, ...] = ()

    fecha_del_evento: str = ""


@dataclasses.dataclass(frozen=True)
class Mensaje:
    """El correo ya compuesto."""

    asunto: str
    texto: str
    html: str


def etiqueta_de(severidad: str) -> str:
    return ETIQUETAS.get(severidad, ETIQUETAS[ALTA])


def _numero(valor, decimales: int = 2) -> str:
    if valor is None:
        return "sin dato"
    return f"{float(valor):,.{decimales}f}".replace(",", " ")


def _con_signo(valor, unidad: str) -> str:
    """La diferencia con el signo delante. 'faltan' y 'sobran' no son lo mismo."""
    if valor is None:
        return "sin dato"
    numero = float(valor)
    if abs(numero) < 1e-9:
        return f"0 {unidad}"
    verbo = "faltan" if numero < 0 else "sobran"
    magnitud = _numero(abs(numero), 0 if unidad == "sacos" else 2)
    return f"{verbo} {magnitud} {unidad}"


def diferencia_corta(contexto: Contexto) -> str:
    """El resumen de la diferencia, tal como aparece en el asunto.

    Los sacos van primero cuando los hay: un saco que falta es un saco que
    alguien se llevo, mientras que una diferencia en kilos puede ser humedad.
    """
    if contexto.diferencia_sacos is not None and contexto.diferencia_sacos != 0:
        return _con_signo(contexto.diferencia_sacos, "sacos")
    if contexto.diferencia_kg is not None:
        return _con_signo(contexto.diferencia_kg, "kg")
    if contexto.diferencia_sacos is not None:
        return _con_signo(contexto.diferencia_sacos, "sacos")
    return "diferencia sin cuantificar"


def asunto(contexto: Contexto) -> str:
    """Criterio 1 (asunto marcado) y criterio 2 (orden y diferencia)."""
    orden = contexto.numero_orden or f"evento {contexto.evento_id}"
    partes = [etiqueta_de(contexto.severidad), f"Orden {orden}:",
              diferencia_corta(contexto)]
    if contexto.cliente:
        partes.append(f"({contexto.cliente})")
    # La columna asunto de la tabla admite 300; el limite real es el cliente de
    # correo, que corta mucho antes.
    return " ".join(partes)[:300]


def _lineas_de_datos(contexto: Contexto, enlace: str) -> list[tuple[str, str]]:
    """Las filas del cuerpo, en el orden en que se leen."""
    filas: list[tuple[str, str]] = [
        ("Orden", contexto.numero_orden or "sin orden asociada"),
    ]
    if contexto.cliente:
        filas.append(("Cliente", contexto.cliente))
    if contexto.producto:
        filas.append(("Producto", contexto.producto))
    if contexto.fecha_del_evento:
        filas.append(("Fecha del evento", contexto.fecha_del_evento))

    filas.append(("Severidad", contexto.severidad.capitalize()))

    if contexto.sacos_esperados is not None or contexto.sacos_contados is not None:
        filas.append(("Sacos", f"{_numero(contexto.sacos_contados, 0)} contados "
                               f"de {_numero(contexto.sacos_esperados, 0)} "
                               f"esperados"))
    if contexto.diferencia_sacos is not None:
        filas.append(("Diferencia en sacos",
                      _con_signo(contexto.diferencia_sacos, "sacos")))
    if contexto.peso_esperado_kg is not None or contexto.peso_real_kg is not None:
        filas.append(("Peso", f"{_numero(contexto.peso_real_kg)} kg reales "
                              f"de {_numero(contexto.peso_esperado_kg)} kg "
                              f"esperados"))
    if contexto.diferencia_kg is not None:
        detalle = _con_signo(contexto.diferencia_kg, "kg")
        if contexto.diferencia_pct is not None:
            detalle += f" ({_numero(contexto.diferencia_pct)} %)"
        filas.append(("Diferencia en peso", detalle))

    if contexto.personas_detectadas is not None:
        detalle = f"{contexto.personas_detectadas} en la zona de carga"
        if contexto.personal_anomalo:
            detalle += ", fuera de lo habitual"
        filas.append(("Personas", detalle))

    filas.append(("Evento", enlace))
    return filas


def texto(contexto: Contexto, enlace: str) -> str:
    """La version en texto plano. Es la que sobrevive a cualquier cliente."""
    lineas = [asunto(contexto), "=" * min(len(asunto(contexto)), 72), ""]
    for etiqueta, valor in _lineas_de_datos(contexto, enlace):
        lineas.append(f"{etiqueta}: {valor}")

    if contexto.descripcion_ia:
        lineas += ["", "Que se vio en el video:", contexto.descripcion_ia]
    if contexto.evidencia:
        lineas.append("")
        lineas += [f"  - {dato}" for dato in contexto.evidencia]
    if contexto.motivos_de_anomalia:
        lineas += ["", "Anomalias de personal:"]
        lineas += [f"  - {motivo}" for motivo in contexto.motivos_de_anomalia]

    lineas += ["", QUE_HACER.get(contexto.severidad, QUE_HACER[ALTA]),
               "", enlace, "",
               "Mensaje automatico del sistema de control de despacho de "
               "QUINOR S.A.C. No responder a este correo."]
    return "\n".join(lineas)


_COLOR = {ALTA: "#b3261e", MEDIA: "#b26a00", BAJA: "#2f6f4f"}


def cuerpo_html(contexto: Contexto, enlace: str) -> str:
    """La version HTML. Tabla y estilos en linea porque los clientes de correo
    ignoran las hojas de estilo y buena parte del CSS moderno."""
    color = _COLOR.get(contexto.severidad, _COLOR[ALTA])
    e = html.escape

    filas = "".join(
        f'<tr><td style="padding:6px 14px 6px 0;color:#555;'
        f'white-space:nowrap;vertical-align:top">{e(etiqueta)}</td>'
        f'<td style="padding:6px 0;color:#111">{e(valor)}</td></tr>'
        for etiqueta, valor in _lineas_de_datos(contexto, enlace)
        if etiqueta != "Evento")

    bloques = [
        f'<div style="border-left:5px solid {color};padding:0 0 0 14px">'
        f'<h2 style="margin:0 0 4px;font-size:17px;color:{color}">'
        f'{e(etiqueta_de(contexto.severidad))} '
        f'{e(diferencia_corta(contexto))}</h2>'
        f'<p style="margin:0;color:#555;font-size:13px">Orden '
        f'{e(contexto.numero_orden or "sin orden asociada")}</p></div>',
        f'<table style="border-collapse:collapse;font-size:14px;'
        f'margin:18px 0">{filas}</table>',
    ]

    if contexto.descripcion_ia:
        bloques.append(
            f'<p style="margin:0 0 6px;font-weight:600;font-size:14px">'
            f'Que se vio en el video</p>'
            f'<p style="margin:0 0 16px;font-size:14px;color:#333;'
            f'line-height:1.5">{e(contexto.descripcion_ia)}</p>')
    if contexto.evidencia:
        puntos = "".join(f"<li>{e(dato)}</li>" for dato in contexto.evidencia)
        bloques.append(f'<ul style="margin:0 0 16px;padding-left:20px;'
                       f'font-size:14px;color:#333">{puntos}</ul>')
    if contexto.motivos_de_anomalia:
        puntos = "".join(f"<li>{e(m)}</li>" for m in contexto.motivos_de_anomalia)
        bloques.append(f'<p style="margin:0 0 6px;font-weight:600;'
                       f'font-size:14px">Anomalias de personal</p>'
                       f'<ul style="margin:0 0 16px;padding-left:20px;'
                       f'font-size:14px;color:#333">{puntos}</ul>')

    bloques.append(
        f'<p style="margin:0 0 18px;font-size:14px;color:#333">'
        f'{e(QUE_HACER.get(contexto.severidad, QUE_HACER[ALTA]))}</p>'
        f'<p style="margin:0 0 24px"><a href="{e(enlace)}" '
        f'style="background:{color};color:#fff;text-decoration:none;'
        f'padding:10px 18px;border-radius:4px;font-size:14px;'
        f'display:inline-block">Ver el evento</a></p>'
        # El enlace tambien en texto: hay clientes que no pintan el boton, y el
        # criterio 2 pide que el enlace este, no que sea bonito.
        f'<p style="margin:0 0 18px;font-size:12px;color:#777;'
        f'word-break:break-all">{e(enlace)}</p>'
        f'<p style="margin:0;font-size:12px;color:#888">Mensaje automatico del '
        f'sistema de control de despacho de QUINOR S.A.C. No responder a este '
        f'correo.</p>')

    return ('<html><body style="margin:0;padding:24px;'
            'font-family:Segoe UI,Arial,sans-serif;background:#f6f6f6">'
            '<div style="max-width:620px;margin:0 auto;background:#fff;'
            'padding:24px;border-radius:6px">'
            + "".join(bloques) + "</div></body></html>")


def componer(contexto: Contexto, enlace: str) -> Mensaje:
    """El correo completo. Criterios 1 y 2 de HU-10."""
    return Mensaje(asunto=asunto(contexto),
                   texto=texto(contexto, enlace),
                   html=cuerpo_html(contexto, enlace))
