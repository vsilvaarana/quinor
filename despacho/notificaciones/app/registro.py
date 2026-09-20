"""Lo que el servicio lee y escribe en la base. HU-10.

Tres cosas:

  - de `usuario` salen los destinatarios del criterio 1, por rol y solo los
    activos;
  - de `evento`, `pesada` y `orden_despacho` sale el contenido del criterio 2,
    que es la orden y la diferencia;
  - en `notificacion` queda escrito el aviso, salga bien o salga mal.

Lo tercero es lo que mas se agradece meses despues. Cuando el cliente reclama y
alguien pregunta si se aviso, la respuesta no puede depender de que un supervisor
conserve el correo: tiene que estar en la base, con la hora, los destinatarios y
el asunto tal como salieron.

Sobre no avisar dos veces. El grabador sondea, y sondear significa que el mismo
evento pasa por aqui en cada vuelta. La defensa real es la clave unica
(evento_id, canal) de la tabla: la comprobacion previa evita el trabajo, pero es
la clave la que evita el segundo correo si dos procesos coinciden. Por eso el
duplicado se trata como un resultado normal y no como un error del servicio.
"""
from __future__ import annotations

import datetime as dt
import json

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app import tablas
from app.destinatarios import Persona, Reparto, repartir
from app.plantilla import Contexto


class EventoDesconocido(LookupError):
    """El evento no existe. Casi siempre es una peticion con el id equivocado."""


def personas_activas(motor) -> list[Persona]:
    """Los usuarios que pueden recibir avisos, tal como estan ahora mismo."""
    consulta = sa.select(
        tablas.usuario.c.nombre, tablas.usuario.c.correo,
        tablas.usuario.c.rol, tablas.usuario.c.activo,
    ).where(tablas.usuario.c.activo.is_(True))
    with motor.connect() as conexion:
        filas = conexion.execute(consulta).mappings().all()
    return [Persona(nombre=f["nombre"], correo=f["correo"], rol=f["rol"],
                    activo=bool(f["activo"])) for f in filas]


def reparto_de(motor, severidad: str | None) -> Reparto:
    """Criterio 1: la severidad decide a quien se avisa y con que urgencia."""
    return repartir(severidad, personas_activas(motor))


def _texto(valor) -> str:
    return "" if valor is None else str(valor)


def _numero(valor):
    return None if valor is None else float(valor)


def _descripcion(bruto):
    """El JSON que dejo HU-09. Puede venir como dict o como texto."""
    if not bruto:
        return "", ()
    datos = bruto
    if isinstance(bruto, (str, bytes)):
        try:
            datos = json.loads(bruto)
        except (ValueError, TypeError):
            return str(bruto), ()
    if not isinstance(datos, dict):
        return "", ()
    evidencia = datos.get("evidencia") or []
    if not isinstance(evidencia, list):
        evidencia = [str(evidencia)]
    return str(datos.get("descripcion") or ""), tuple(str(x) for x in evidencia)


def contexto_del_evento(motor, evento_id: int) -> Contexto:
    """Reune la orden y la diferencia del criterio 2.

    Se leen de la base y no de lo que mande quien llama: el correo dice lo que
    dice el sistema, y no lo que crea saber el proceso que pidio el aviso. Si los
    dos discrepan, el dashboard y el correo tienen que contar lo mismo.
    """
    e, p, o = tablas.evento, tablas.pesada, tablas.orden_despacho
    consulta = (
        sa.select(
            e.c.id, e.c.estado, e.c.severidad, e.c.diferencia_kg,
            e.c.diferencia_pct, e.c.sacos_contados, e.c.diferencia_sacos,
            e.c.personas_detectadas, e.c.personal_anomalo, e.c.descripcion_ia,
            e.c.creado_en,
            p.c.peso_real_kg, p.c.fecha_hora,
            o.c.numero_orden, o.c.cliente, o.c.producto,
            o.c.peso_esperado_kg, o.c.sacos_esperados,
        )
        .select_from(e.join(p, e.c.pesada_id == p.c.id)
                      .join(o, p.c.orden_id == o.c.id))
        .where(e.c.id == evento_id))

    with motor.connect() as conexion:
        fila = conexion.execute(consulta).mappings().first()
    if fila is None:
        raise EventoDesconocido(f"No existe el evento {evento_id}.")

    descripcion, evidencia = _descripcion(fila["descripcion_ia"])
    cuando = fila["fecha_hora"] or fila["creado_en"]
    return Contexto(
        evento_id=int(fila["id"]),
        severidad=fila["severidad"] or "",
        numero_orden=_texto(fila["numero_orden"]),
        cliente=_texto(fila["cliente"]),
        producto=_texto(fila["producto"]),
        peso_esperado_kg=_numero(fila["peso_esperado_kg"]),
        peso_real_kg=_numero(fila["peso_real_kg"]),
        diferencia_kg=_numero(fila["diferencia_kg"]),
        diferencia_pct=_numero(fila["diferencia_pct"]),
        sacos_esperados=fila["sacos_esperados"],
        sacos_contados=fila["sacos_contados"],
        diferencia_sacos=fila["diferencia_sacos"],
        personas_detectadas=fila["personas_detectadas"],
        personal_anomalo=(None if fila["personal_anomalo"] is None
                          else bool(fila["personal_anomalo"])),
        descripcion_ia=descripcion,
        evidencia=evidencia,
        fecha_del_evento=(cuando.strftime("%d/%m/%Y %H:%M")
                          if isinstance(cuando, dt.datetime) else ""),
    )


def ya_avisado(motor, evento_id: int) -> bool:
    """Si ya hay un correo enviado para este evento.

    Una notificacion fallida no cuenta: el evento sigue sin avisar y el
    siguiente intento tiene que poder salir. Por eso la fila fallida se borra
    antes de reintentar, en lugar de dejar que la clave unica bloquee el aviso
    para siempre.
    """
    consulta = sa.select(tablas.notificacion.c.id).where(
        sa.and_(tablas.notificacion.c.evento_id == evento_id,
                tablas.notificacion.c.canal == tablas.CORREO,
                tablas.notificacion.c.estado == tablas.ENVIADA))
    with motor.connect() as conexion:
        return conexion.execute(consulta).first() is not None


def _limpiar_fallida(conexion, evento_id: int) -> None:
    """Quita el registro de un intento anterior que no salio.

    Se conserva el ultimo estado y no el historico de intentos fallidos porque
    la pregunta que importa es "se aviso de este evento", y para eso la fila
    vigente basta. El detalle de cada intento queda en el log del servicio.
    """
    conexion.execute(sa.delete(tablas.notificacion).where(
        sa.and_(tablas.notificacion.c.evento_id == evento_id,
                tablas.notificacion.c.canal == tablas.CORREO,
                tablas.notificacion.c.estado == tablas.FALLIDA)))


def registrar(motor, evento_id: int, reparto: Reparto, asunto: str,
              enviado: bool, intentos: int, error: str = "",
              segundos_desde_analisis: float | None = None) -> int | None:
    """Deja constancia del aviso. Devuelve el id, o None si ya estaba.

    Que devuelva None en vez de lanzar es deliberado: dos procesos avisando del
    mismo evento a la vez no es un error, es el caso que la clave unica esta ahi
    para resolver, y quien llama solo necesita saber que no hace falta insistir.
    """
    valores = {
        "evento_id": evento_id,
        "canal": tablas.CORREO,
        "severidad": reparto.severidad,
        "destinatarios": list(reparto.destinatarios),
        "asunto": asunto[:300],
        "estado": tablas.ENVIADA if enviado else tablas.FALLIDA,
        # La tabla exige 1 o mas. Un envio que ni se intento por no tener
        # destinatarios se registra como un intento, que es lo que fue.
        "intentos": max(1, int(intentos)),
        "error": (error or None) if not enviado else None,
        "segundos_desde_analisis": (None if segundos_desde_analisis is None
                                    else round(segundos_desde_analisis, 2)),
        "enviada_en": dt.datetime.now() if enviado else None,
    }
    try:
        with motor.begin() as conexion:
            _limpiar_fallida(conexion, evento_id)
            resultado = conexion.execute(
                sa.insert(tablas.notificacion).values(**valores))
            return int(resultado.inserted_primary_key[0])
    except IntegrityError:
        return None
