"""Detalle de un evento. HU-12.

Como supervisor de despacho, quiero abrir el detalle de un evento y reproducir su
clip junto con el analisis, para verificar con mis propios ojos lo que reporto el
sistema.

Criterios de aceptacion:
  1. El detalle muestra pesos, conteo de sacos, personas detectadas, descripcion
     y severidad.
  2. El clip se reproduce en el navegador con controles de pausa y avance.
  3. Se muestra el fotograma donde se detecto la anomalia.

Por que este modulo existe aparte de app/bandeja.py
---------------------------------------------------
La bandeja de HU-11 es el problema contrario a este. Alli hay que traer muchas
filas y cada columna extra se paga cincuenta veces, asi que la consulta devuelve
lo justo para pintar la tabla. Aqui hay **un** evento y el supervisor ya decidio
que le interesa: todo lo que cuesta una consulta se puede pagar, porque se paga
una sola vez y responde a la pregunta por la que abrio la pantalla.

Lo que no cambia es la regla de la casa: nada se lee por fila. Las presencias de
HU-08 pueden ser decenas y los fotogramas de HU-09 hasta cuatro, y ninguno de los
dos se recorre pidiendo datos de uno en uno. Son **tres consultas fijas**, y hay
una prueba que las cuenta:

  1. el evento con su pesada y su orden, de un JOIN;
  2. las presencias del evento;
  3. la auditoria, de donde salen la tolerancia con la que se juzgo aquella carga
     y la ventana que el grabador recorto de verdad.

La tolerancia sale de la auditoria y no de `configuracion` a proposito: si
manana alguien la cambia, el evento tiene que seguir diciendo contra que umbral
se juzgo. Y la ventana del clip sale de lo que el grabador anoto, no de repetir
aqui la cuenta de "cinco minutos antes y dos despues": dos copias de la misma
regla acaban discrepando y entonces la pantalla miente sobre lo que el video
contiene.

Lo que falta cuando falta
------------------------
Un evento recien creado no tiene conteo, ni personas, ni descripcion, ni clip, y
eso no es un error: es el estado normal durante los segundos o minutos que tarda
el analisis, y es definitivo cuando el clip se perdio. El detalle se arma igual y
cada parte ausente dice por que. La discrepancia de peso, que es lo que de verdad
motiva la revision, existe desde el primer momento y se ve desde el primer
momento.

Lo que este modulo no tiene
---------------------------
Nada que identifique a una persona. Las presencias llevan el numero temporal que
asigno el rastreador dentro de ese clip y el tiempo en zona, que es lo que HU-08
guarda, y ni una foto, ni un recorte, ni un nombre: la RN-08 y el apartado 8
prohiben la identificacion facial y la forma de cumplirlo es no tener nada que
identificar. El detalle es la pantalla donde esa tentacion seria mas grande, asi
que conviene decirlo aqui.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.almacen import ALMACEN_NO_CONFIGURADO, SIN_OBJETO, Enlace, Firmador
from app.models import Auditoria, Evento, OrdenDespacho, Pesada, PersonaEnEvento

# Acciones de auditoria que el detalle necesita leer. Una sola consulta con un
# IN, no tres: son la misma tabla y el mismo evento.
ACCION_CREACION = "crear_evento"
ACCION_RECORTE = "recortar_clip"
ACCION_SIN_CLIP = "evento_sin_clip"
ACCIONES = (ACCION_CREACION, ACCION_RECORTE, ACCION_SIN_CLIP)

# Criterio 3. Mayor gana. Es la misma escala con la que el servicio YOLO elige
# que fotogramas guardar (`yolo/app/fotogramas.py`), repetida aqui porque son dos
# servicios con su propio despliegue: el saco que sale es lo primero que hay que
# ver, porque es lo unico de la lista que por si solo ya es severidad Alta.
PRIORIDAD_DEL_MOTIVO = {
    "saco_saliente": 100,
    "pico_de_personas": 80,
    "primer_saco": 60,
    "ultimo_saco": 50,
    "centro_del_clip": 10,
}

# Los dos motivos que explican una anomalia, frente a los que solo sirven para
# situarse en el video. El criterio 3 pide "el fotograma donde se detecto la
# anomalia", y el primer saco de la carga no es una anomalia.
MOTIVOS_DE_ANOMALIA = ("saco_saliente", "pico_de_personas")

CERO = Decimal("0.00")


# --------------------------------------------------------------------- piezas
@dataclasses.dataclass(frozen=True)
class Pesos:
    """Criterio 1, la parte que existe desde que nace el evento."""

    esperado_kg: Decimal
    real_kg: Decimal
    diferencia_kg: Decimal
    diferencia_pct: Decimal
    tolerancia_aplicada_kg: Decimal | None = None

    @property
    def falta_producto(self) -> bool:
        """Lo contrario, un sobrepeso, tambien es una senal: se informa igual."""
        return self.diferencia_kg < 0

    @property
    def exceso_sobre_la_tolerancia_kg(self) -> Decimal | None:
        """Cuanto se paso de lo que se aceptaba. None si no se sabe el umbral.

        Es la cifra que convierte "faltan 150 kg" en "faltan 150 kg donde se
        toleraban 100": sin ella, el supervisor no sabe si el evento esta al
        borde o muy lejos.
        """
        if self.tolerancia_aplicada_kg is None:
            return None
        return abs(self.diferencia_kg) - self.tolerancia_aplicada_kg


@dataclasses.dataclass(frozen=True)
class Sacos:
    """Criterio 1, el conteo del video de HU-07. En None mientras no se analiza."""

    esperados: int
    contados: int | None = None
    diferencia: int | None = None

    @property
    def analizado(self) -> bool:
        """None no es cero: un cero fingido diria que no cruzo ningun saco."""
        return self.contados is not None

    @property
    def cuadran(self) -> bool | None:
        return None if self.diferencia is None else self.diferencia == 0


@dataclasses.dataclass(frozen=True)
class Presencia:
    """Una persona vista en la zona de carga durante el clip. HU-08.

    `id_temporal` es el numero del rastreador dentro de este video y solo dentro
    de este video: el 1 de un evento no tiene nada que ver con el 1 de otro.
    """

    id_temporal: int
    segundos_en_zona: Decimal
    primer_fotograma: int
    ultimo_fotograma: int


@dataclasses.dataclass(frozen=True)
class Personas:
    """Criterio 1, las personas detectadas. HU-08, criterio 2."""

    detectadas: int | None = None
    personal_anomalo: bool | None = None
    presencias: tuple[Presencia, ...] = ()

    @property
    def analizado(self) -> bool:
        return self.detectadas is not None

    @property
    def segundos_totales(self) -> Decimal:
        return sum((p.segundos_en_zona for p in self.presencias), CERO)

    @property
    def permanencia_maxima_s(self) -> Decimal:
        return max((p.segundos_en_zona for p in self.presencias), default=CERO)


@dataclasses.dataclass(frozen=True)
class Analisis:
    """Criterio 1, la descripcion y la severidad. HU-09.

    Las dos severidades viajan juntas. `severidad` sale de la RN-04, que es una
    regla con umbrales exactos, y es la que manda; `severidad_ia` es la que
    propuso el modelo. De comparar las dos sale la concordancia semanal del
    apartado 9.2, y por eso no se esconde la que no manda.
    """

    severidad: str | None = None
    severidad_ia: str | None = None
    descripcion: str | None = None
    evidencia: tuple[str, ...] = ()
    modelo: str | None = None
    proveedor: str | None = None
    confianza: float | None = None
    intentos: int | None = None

    @property
    def hay_descripcion(self) -> bool:
        return bool(self.descripcion)

    @property
    def discrepan(self) -> bool:
        """El modelo propuso una severidad distinta de la que dicta la regla."""
        return bool(self.severidad_ia and self.severidad
                    and self.severidad_ia != self.severidad)


@dataclasses.dataclass(frozen=True)
class Fotograma:
    """Criterio 3: un fotograma guardado, con por que se guardo y en que segundo.

    `segundo` es la posicion dentro del clip, que es lo que permite al
    reproductor abrir justo ahi en lugar de dejar al supervisor buscandolo.
    """

    motivo: str
    detalle: str
    segundo: float
    fotograma: int
    enlace: Enlace

    @property
    def prioridad(self) -> int:
        return PRIORIDAD_DEL_MOTIVO.get(self.motivo, 0)

    @property
    def es_anomalia(self) -> bool:
        return self.motivo in MOTIVOS_DE_ANOMALIA


@dataclasses.dataclass(frozen=True)
class Clip:
    """Criterio 2: el video y la ventana que cubre.

    `motivo_sin_clip` lleva lo que el grabador anoto cuando no pudo recortar.
    No es lo mismo que la camara estuviera caida que que el video ya se hubiera
    purgado del buffer, y el supervisor que no puede ver nada merece saber cual
    de las dos cosas paso.
    """

    enlace: Enlace
    desde: dt.datetime | None = None
    hasta: dt.datetime | None = None
    duracion_s: float | None = None
    camara: str | None = None
    cobertura_pct: float | None = None
    motivo_sin_clip: str | None = None

    @property
    def reproducible(self) -> bool:
        return self.enlace.reproducible

    @property
    def formato(self) -> str | None:
        """La extension del objeto guardado, sin el punto. None si no hay clip.

        Importa para el criterio 2 y no es un detalle tecnico: el grabador
        escribe Matroska porque un corte de luz no se lleva el fichero entero
        (`grabador/app/ffmpeg.py`), y ese contenedor lo reproducen Chrome y Edge
        pero no Firefox ni Safari. La pantalla lo advierte en lugar de dejar al
        supervisor con un recuadro negro y ninguna explicacion.
        """
        if not self.enlace.direccion or "." not in self.enlace.direccion:
            return None
        return self.enlace.direccion.rsplit(".", 1)[1].lower()

    @property
    def completo(self) -> bool | None:
        """None cuando no se sabe. Un clip al 60 % se reproduce pero no lo cubre
        todo, y quien lo mira tiene que saberlo antes de concluir."""
        return None if self.cobertura_pct is None else self.cobertura_pct >= 99.5


@dataclasses.dataclass(frozen=True)
class Detalle:
    """Todo lo que la pantalla del criterio 1 necesita, en un solo objeto."""

    id: int
    estado: str
    creado_en: dt.datetime
    numero_orden: str
    cliente: str
    producto: str
    pesada_id: int
    bascula_id: str
    pesada_fecha_hora: dt.datetime
    inicio_carga: dt.datetime | None
    pesos: Pesos
    sacos: Sacos
    personas: Personas
    analisis: Analisis
    clip: Clip
    fotogramas: tuple[Fotograma, ...] = ()

    @property
    def analizado(self) -> bool:
        """Si el video ya paso por YOLO. Es lo que separa un detalle completo de
        uno que todavia solo tiene la discrepancia de peso."""
        return self.sacos.analizado

    @property
    def anomalia(self) -> Fotograma | None:
        """Criterio 3: el fotograma donde se detecto la anomalia.

        Se elige por prioridad y no por orden de aparicion: entre un saco que
        sale y el primer saco de la carga, lo que hay que mirar primero es el
        que sale. Si ninguno es una anomalia se devuelve el de mayor prioridad
        igualmente, porque "este es el momento mas relevante del clip" sigue
        siendo mejor que no abrir ninguno.
        """
        if not self.fotogramas:
            return None
        anomalias = [f for f in self.fotogramas if f.es_anomalia]
        return max(anomalias or list(self.fotogramas),
                   key=lambda f: (f.prioridad, -f.segundo))

    @property
    def segundo_de_entrada(self) -> float:
        """Donde abrir el reproductor. El criterio 2 pide poder ver el clip; el 3
        pide ver la anomalia, y empezar ahi ahorra buscarla a mano."""
        anomalia = self.anomalia
        return anomalia.segundo if anomalia else 0.0

    @property
    def peso_corto_con_sacos_completos(self) -> bool:
        """La firma de la sustitucion de producto, que es lo que motiva todo esto.

        Falta peso y los bultos cuadran: no se llevaron sacos, cambiaron lo que
        hay dentro. Es la conclusion que el supervisor tiene que poder sacar de
        un vistazo.
        """
        return self.pesos.falta_producto and self.sacos.cuadran is True


# --------------------------------------------------------------------- armado
def _a_fecha(valor) -> dt.datetime | None:
    """Las marcas viajan como texto ISO dentro del detalle JSON de auditoria."""
    try:
        return dt.datetime.fromisoformat(valor) if valor else None
    except (TypeError, ValueError):
        return None


def _a_decimal(valor) -> Decimal | None:
    """La tolerancia se guardo como texto en el detalle de auditoria."""
    try:
        return Decimal(str(valor)) if valor is not None else None
    except (ArithmeticError, TypeError, ValueError):
        return None


def _a_float(valor) -> float | None:
    try:
        return float(valor) if valor is not None else None
    except (TypeError, ValueError):
        return None


def _firmar(firmador: Firmador | None, direccion: str | None) -> Enlace:
    """Sin firmador el objeto no deja de existir: solo no se puede enlazar."""
    if firmador is None:
        return (Enlace(direccion=direccion, motivo=ALMACEN_NO_CONFIGURADO)
                if direccion else Enlace(motivo=SIN_OBJETO))
    return firmador.firmar(direccion)


def _analisis_de(severidad: str | None, descripcion_ia) -> Analisis:
    """Desarma el JSON del modelo. Tolerante a proposito.

    `descripcion_ia` lo escribe otro servicio y puede quedarse a medias si el
    modelo respondio raro. Un detalle que falla por una clave ausente dejaria al
    supervisor sin ver el peso, que es lo que de verdad importa.
    """
    if not isinstance(descripcion_ia, dict):
        return Analisis(severidad=severidad)
    evidencia = descripcion_ia.get("evidencia")
    return Analisis(
        severidad=severidad,
        severidad_ia=descripcion_ia.get("severidad_ia"),
        descripcion=descripcion_ia.get("descripcion"),
        evidencia=tuple(str(p) for p in evidencia) if isinstance(evidencia, list) else (),
        modelo=descripcion_ia.get("modelo"),
        proveedor=descripcion_ia.get("proveedor"),
        confianza=_a_float(descripcion_ia.get("confianza")),
        intentos=descripcion_ia.get("intentos"),
    )


def _fotogramas_de(guardados, firmador: Firmador | None) -> tuple[Fotograma, ...]:
    """Criterio 3. Ordenados por prioridad: lo que hay que mirar primero, primero."""
    if not isinstance(guardados, list):
        return ()
    fotogramas = [
        Fotograma(
            motivo=str(f.get("motivo", "")),
            detalle=str(f.get("detalle", "")),
            segundo=_a_float(f.get("segundo")) or 0.0,
            fotograma=int(f.get("fotograma") or 0),
            enlace=_firmar(firmador, f.get("url")),
        )
        for f in guardados if isinstance(f, dict)
    ]
    return tuple(sorted(fotogramas, key=lambda f: (-f.prioridad, f.segundo)))


def _clip_de(clip_url: str | None, recorte: dict, sin_clip: dict,
             firmador: Firmador | None) -> Clip:
    """La ventana sale de lo que el grabador anoto, no de repetir aqui su cuenta."""
    ventana = recorte or sin_clip
    return Clip(
        enlace=_firmar(firmador, clip_url),
        desde=_a_fecha(ventana.get("desde")),
        hasta=_a_fecha(ventana.get("hasta")),
        duracion_s=_a_float(ventana.get("duracion_s")),
        camara=ventana.get("camara"),
        cobertura_pct=_a_float(ventana.get("cobertura_pct")),
        motivo_sin_clip=sin_clip.get("motivo") if sin_clip else None,
    )


def armar(sesion: Session, evento_id: int,
          firmador: Firmador | None = None) -> Detalle | None:
    """El detalle completo de un evento, o None si no existe.

    Tres consultas fijas, sea cuantas sean las presencias y los fotogramas. Es
    la invariante que `test_el_detalle_no_crece_en_consultas` protege.
    """
    fila = sesion.execute(
        select(
            Evento.id, Evento.estado, Evento.creado_en,
            Evento.diferencia_kg, Evento.diferencia_pct,
            Evento.sacos_contados, Evento.diferencia_sacos,
            Evento.personas_detectadas, Evento.personal_anomalo,
            Evento.severidad, Evento.descripcion_ia, Evento.fotogramas_clave,
            Evento.clip_url,
            Pesada.id.label("pesada_id"), Pesada.bascula_id,
            Pesada.peso_real_kg, Pesada.fecha_hora, Pesada.inicio_carga,
            OrdenDespacho.numero_orden, OrdenDespacho.cliente,
            OrdenDespacho.producto, OrdenDespacho.peso_esperado_kg,
            OrdenDespacho.sacos_esperados)
        .join(Pesada, Evento.pesada_id == Pesada.id)
        .join(OrdenDespacho, Pesada.orden_id == OrdenDespacho.id)
        .where(Evento.id == evento_id)
    ).first()
    if fila is None:
        return None

    presencias = tuple(
        Presencia(
            id_temporal=p.id_temporal,
            segundos_en_zona=p.segundos_en_zona,
            primer_fotograma=p.primer_fotograma,
            ultimo_fotograma=p.ultimo_fotograma)
        for p in sesion.execute(
            select(PersonaEnEvento.id_temporal, PersonaEnEvento.segundos_en_zona,
                   PersonaEnEvento.primer_fotograma, PersonaEnEvento.ultimo_fotograma)
            .where(PersonaEnEvento.evento_id == evento_id)
            .order_by(PersonaEnEvento.primer_fotograma,
                      PersonaEnEvento.id_temporal)).all())

    # Una consulta para las tres acciones. Se queda la ultima de cada una: el
    # grabador reintenta, y lo que vale es el ultimo intento.
    anotaciones: dict[str, dict] = {}
    for registro in sesion.execute(
        select(Auditoria.accion, Auditoria.detalle)
        .where(Auditoria.entidad == "evento",
               Auditoria.entidad_id == evento_id,
               Auditoria.accion.in_(ACCIONES))
        .order_by(Auditoria.id)
    ).all():
        anotaciones[registro.accion] = registro.detalle or {}

    creacion = anotaciones.get(ACCION_CREACION, {})

    return Detalle(
        id=fila.id,
        estado=fila.estado,
        creado_en=fila.creado_en,
        numero_orden=fila.numero_orden,
        cliente=fila.cliente,
        producto=fila.producto,
        pesada_id=fila.pesada_id,
        bascula_id=fila.bascula_id,
        pesada_fecha_hora=fila.fecha_hora,
        inicio_carga=fila.inicio_carga,
        pesos=Pesos(
            esperado_kg=fila.peso_esperado_kg,
            real_kg=fila.peso_real_kg,
            diferencia_kg=fila.diferencia_kg,
            diferencia_pct=fila.diferencia_pct,
            tolerancia_aplicada_kg=_a_decimal(
                creacion.get("tolerancia_aplicada_kg"))),
        sacos=Sacos(
            esperados=fila.sacos_esperados,
            contados=fila.sacos_contados,
            diferencia=fila.diferencia_sacos),
        personas=Personas(
            detectadas=fila.personas_detectadas,
            personal_anomalo=(None if fila.personal_anomalo is None
                              else bool(fila.personal_anomalo)),
            presencias=presencias),
        analisis=_analisis_de(fila.severidad, fila.descripcion_ia),
        clip=_clip_de(fila.clip_url,
                      anotaciones.get(ACCION_RECORTE, {}),
                      anotaciones.get(ACCION_SIN_CLIP, {}),
                      firmador),
        fotogramas=_fotogramas_de(fila.fotogramas_clave, firmador),
    )
