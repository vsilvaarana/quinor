"""Clasificacion de un evento por el supervisor. HU-13.

Como supervisor de despacho, quiero clasificar un evento como Confirmado o
Falso positivo con un comentario, para alimentar la mejora continua del sistema.

Criterios de aceptacion:
  1. El cambio de estado exige un comentario de al menos 10 caracteres.
  2. Se registra el usuario y la fecha del cambio.
  3. Un evento Confirmado no puede volver al estado Pendiente.

Por que hay una tabla y no solo una columna
-------------------------------------------
`evento.estado` responde "en que quedo esto". El veredicto responde "por que", y
esa es la pregunta que llega meses despues, cuando el cliente reclama y alguien
tiene que explicar quien decidio que aquello era un falso positivo. Una columna
sola guarda la ultima decision y pierde las anteriores, que es justo lo que se
busca cuando un evento aparece cerrado y el faltante existia.

De ahi que la tabla sea de solo insercion por uso: una correccion no edita el
veredicto anterior, escribe uno nuevo. La secuencia completa queda legible, y el
estado del evento es siempre el del ultimo veredicto.

El comentario no es burocracia
------------------------------
El criterio 1 pide diez caracteres y aqui se cuentan sobre el texto ya recortado,
asi que diez espacios no pasan. La razon es la mejora continua del apartado 2:
un "ok" no le dice nada al que revise el historial, y la clasificacion existe
para que dentro de seis meses se pueda separar lo que el sistema acerto de lo que
no. La misma regla vive tambien en la restriccion `ck_veredicto_comentario` del
esquema, porque un formulario puede fallar y la base no.

Que transiciones se permiten
----------------------------
El paso por `en_revision` es opcional: un supervisor que ya mira el clip en la
pantalla de HU-12 puede cerrar el evento directamente, y obligarle a marcar
"en revision" primero solo conseguiria que ese estado no signifique nada.

  pendiente, pendiente_analisis, sin_clip  ->  en_revision | confirmado | falso_positivo
  en_revision                              ->  confirmado | falso_positivo
  confirmado                               ->  falso_positivo
  falso_positivo                           ->  confirmado

Las dos ultimas son la correccion de una decision equivocada, que ocurre: el
clip se vuelve a mirar con mas calma y la conclusion cambia. Lo que no se puede
es reabrir, es decir volver de un estado final a uno abierto. La RN-06 lo exige
para Confirmado y aqui se extiende a Falso positivo por el mismo motivo: un
evento reabierto desaparece de los cerrados y vuelve a la bandeja como si nadie
lo hubiera mirado, perdiendo la decision y el nombre de quien la tomo.

El criterio 3 queda cubierto tres veces, y eso es intencionado: esta tabla de
transiciones no nombra `pendiente` como destino, la API solo acepta los tres
veredictos, y el trigger `trg_evento_no_reabrir` lo rechaza en el motor aunque la
escritura llegue por fuera de la aplicacion.

Un evento sin clip o sin analisis se clasifica igual
----------------------------------------------------
Es el caso que mas importa cerrar. Un evento en `sin_clip` tiene una discrepancia
de peso real y ningun video que mirar: el supervisor va al almacen, cuenta sacos
y decide. Si la pantalla se lo impidiera, los eventos sin video se quedarian
abiertos para siempre y la bandeja de HU-11 dejaria de servir para saber que
falta por revisar.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

import structlog
from sqlalchemy import select
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from app import auditoria
from app.models import Evento, Usuario, Veredicto

log = structlog.get_logger(__name__)

ACCION = "clasificar_evento"

EN_REVISION = "en_revision"
CONFIRMADO = "confirmado"
FALSO_POSITIVO = "falso_positivo"

# Los tres estados que un veredicto puede dejar. `pendiente` no esta, y no por
# descuido: es el estado con el que nace el evento y al que nadie puede volver.
VEREDICTOS = (EN_REVISION, CONFIRMADO, FALSO_POSITIVO)
FINALES = (CONFIRMADO, FALSO_POSITIVO)

TRANSICIONES: dict[str, tuple[str, ...]] = {
    "pendiente": VEREDICTOS,
    "pendiente_analisis": VEREDICTOS,
    "sin_clip": VEREDICTOS,
    EN_REVISION: FINALES,
    CONFIRMADO: (FALSO_POSITIVO,),
    FALSO_POSITIVO: (CONFIRMADO,),
}

# Criterio 1. Se cuentan sobre el texto recortado.
COMENTARIO_MINIMO = 10
# Lo que cabe en la columna. Mas que esto se rechaza en vez de truncarse: un
# comentario cortado a la mitad dice algo distinto de lo que se escribio.
COMENTARIO_MAXIMO = 1000

# El numero con el que MySQL devuelve un SIGNAL SQLSTATE '45000', que es como
# estan escritos los triggers del esquema. Se mira el numero y no el texto
# porque pymysql no expone el SQLSTATE, solo el errno y el mensaje, y porque el
# mensaje del trigger esta en castellano y puede reescribirse. Se traduce para
# que la pantalla reciba un 409 con una frase legible y no un 500 con SQL dentro.
CODIGO_DE_REGLA = 1644

NOMBRES = {
    EN_REVISION: "En revision",
    CONFIRMADO: "Confirmado",
    FALSO_POSITIVO: "Falso positivo",
    "pendiente": "Pendiente",
    "pendiente_analisis": "Pendiente de analisis",
    "sin_clip": "Sin clip",
}


class EventoNoEncontrado(LookupError):
    """No hay evento con ese numero."""


class ComentarioInsuficiente(ValueError):
    """Criterio 1: el comentario no llega al minimo o no cabe en la columna."""


class EstadoDesconocido(ValueError):
    """El destino no es uno de los tres veredictos."""


class TransicionProhibida(RuntimeError):
    """El evento no puede pasar de donde esta a donde se pide."""


def nombre_de(estado: str | None) -> str:
    """El estado como se escribe en pantalla. Sin la traduccion, la interfaz
    muestra `falso_positivo` y el supervisor lee codigo."""
    return NOMBRES.get(estado or "", estado or "")


def destinos_desde(estado: str | None) -> tuple[str, ...]:
    """A que estados puede pasar un evento que esta en `estado`.

    La pantalla la usa para ofrecer solo lo posible. Un boton que existe para
    dar error es peor que un boton que no existe.
    """
    return TRANSICIONES.get(estado or "", ())


def se_puede_clasificar(estado: str | None) -> bool:
    return bool(destinos_desde(estado))


def es_final(estado: str | None) -> bool:
    return estado in FINALES


def normalizar_comentario(comentario: str | None) -> str:
    """El comentario del criterio 1, recortado y validado.

    Cuenta caracteres sobre el texto sin espacios de los extremos: diez espacios
    cumplirian la letra del criterio y ninguna de sus razones.
    """
    texto = (comentario or "").strip()
    if len(texto) < COMENTARIO_MINIMO:
        raise ComentarioInsuficiente(
            f"El comentario tiene {len(texto)} caracteres y la clasificacion "
            f"exige al menos {COMENTARIO_MINIMO}: explique en que se basa la "
            f"decision, que es lo que se leera cuando se revise este evento.")
    if len(texto) > COMENTARIO_MAXIMO:
        raise ComentarioInsuficiente(
            f"El comentario tiene {len(texto)} caracteres y el maximo es "
            f"{COMENTARIO_MAXIMO}.")
    return texto


def _por_que_no(estado: str, destino: str) -> str:
    """La frase que explica el rechazo. La lee una persona, no un log."""
    if destino not in VEREDICTOS:
        return (f"'{destino}' no es una clasificacion valida: "
                f"{', '.join(VEREDICTOS)}.")
    if estado == destino:
        return (f"El evento ya esta en {nombre_de(destino)}. "
                f"Para cambiar la decision elija la otra clasificacion.")
    if es_final(estado) and destino == EN_REVISION:
        return (f"Un evento {nombre_de(estado)} no puede volver a revision "
                f"(RN-06). Se puede corregir a {nombre_de(FALSO_POSITIVO if estado == CONFIRMADO else CONFIRMADO)}, "
                f"con su comentario, y la decision anterior queda en el historial.")
    return (f"Un evento en {nombre_de(estado)} no puede pasar a "
            f"{nombre_de(destino)}.")


@dataclasses.dataclass(frozen=True)
class Clasificacion:
    """Lo que ocurrio al clasificar. Es lo que la pantalla confirma."""

    evento_id: int
    estado_anterior: str
    estado: str
    veredicto_id: int
    usuario_id: int
    usuario_nombre: str
    comentario: str
    fecha: dt.datetime

    @property
    def cerrado(self) -> bool:
        """El evento queda cerrado: ya no esta pendiente de revisar."""
        return es_final(self.estado)

    @property
    def fue_correccion(self) -> bool:
        """Se cambio una decision ya tomada, no se cerro un evento abierto."""
        return es_final(self.estado_anterior)


def clasificar(sesion: Session, evento_id: int, estado_nuevo: str,
               comentario: str | None, usuario: Usuario) -> Clasificacion:
    """Registra la decision del supervisor y mueve el evento a ese estado.

    Todo en una transaccion: el veredicto, el estado del evento y la fila de
    auditoria. Un veredicto escrito sin que el evento cambie de estado, o al
    contrario, dejaria la pantalla contando una historia y la bandeja otra.

    El usuario llega entero y no como numero porque el criterio 2 pide registrar
    quien decidio, y la respuesta tiene que decir el nombre: un id en pantalla no
    le dice nada a quien revisa el historial, y pedirlo otra vez a la base seria
    una consulta para un dato que el llamador ya tiene en la mano.
    """
    texto = normalizar_comentario(comentario)
    if estado_nuevo not in VEREDICTOS:
        raise EstadoDesconocido(_por_que_no("", estado_nuevo))

    # FOR UPDATE: dos supervisores pueden abrir el mismo evento a la vez. Sin el
    # bloqueo los dos leerian `pendiente`, los dos verian la transicion como
    # valida y el segundo sobrescribiria la decision del primero sin saberlo.
    evento = sesion.execute(
        select(Evento).where(Evento.id == evento_id).with_for_update()
    ).scalar_one_or_none()
    if evento is None:
        raise EventoNoEncontrado(f"No existe el evento {evento_id}")

    anterior = evento.estado
    if estado_nuevo not in destinos_desde(anterior):
        raise TransicionProhibida(_por_que_no(anterior, estado_nuevo))

    ahora = dt.datetime.now().replace(tzinfo=None)
    fila = Veredicto(evento_id=evento.id, usuario_id=usuario.id,
                     estado_nuevo=estado_nuevo, comentario=texto, fecha=ahora)
    sesion.add(fila)
    evento.estado = estado_nuevo

    auditoria.registrar(
        sesion, entidad="evento", entidad_id=evento.id, accion=ACCION,
        usuario_id=usuario.id,
        detalle={"estado_anterior": anterior, "estado_nuevo": estado_nuevo,
                 "comentario": texto, "correccion": es_final(anterior)})
    try:
        sesion.commit()
    except DatabaseError as exc:
        # Ultima linea de defensa del criterio 3. Hoy no deberia saltar nunca,
        # porque la tabla de transiciones es mas estricta que el trigger; si
        # alguien la relaja, esto responde 409 con la frase de la regla en vez
        # de un 500 con SQL dentro.
        sesion.rollback()
        if _es_rechazo_de_regla(exc):
            raise TransicionProhibida(_mensaje_del_motor(exc)) from exc
        raise

    log.info("evento_clasificado", evento=evento.id, de=anterior,
             a=estado_nuevo, por=usuario.id)
    return Clasificacion(
        evento_id=evento.id, estado_anterior=anterior, estado=estado_nuevo,
        veredicto_id=fila.id, usuario_id=usuario.id,
        usuario_nombre=usuario.nombre, comentario=texto, fecha=fila.fecha)


def _es_rechazo_de_regla(exc: DatabaseError) -> bool:
    """Si el motor rechazo la escritura por un trigger y no por estar roto."""
    argumentos = getattr(getattr(exc, "orig", None), "args", ())
    return bool(argumentos) and argumentos[0] == CODIGO_DE_REGLA


def _mensaje_del_motor(exc: DatabaseError) -> str:
    """El texto del SIGNAL, sin el codigo ni el envoltorio de SQLAlchemy."""
    argumentos = getattr(getattr(exc, "orig", None), "args", ())
    for parte in argumentos:
        if isinstance(parte, str) and parte.strip():
            return parte
    return "El motor rechazo el cambio de estado."


def historial(sesion: Session, evento_id: int,
              limite: int = 50) -> list[Veredicto]:
    """Los veredictos del evento, del primero al ultimo.

    En orden cronologico y no al contrario: la secuencia de decisiones se lee
    como se tomo, y la correccion solo se entiende despues de la decision que
    corrige.
    """
    return list(sesion.scalars(
        select(Veredicto)
        .where(Veredicto.evento_id == evento_id)
        .order_by(Veredicto.fecha, Veredicto.id)
        .limit(limite)))
