"""Lo que el video dice de un evento: sacos y personas. HU-07 y HU-08.

HU-07, criterio 3: "el conteo y la diferencia con la orden se guardan en el
evento". HU-08, criterio 2: "se registra cuantas personas estuvieron en zona y el
tiempo de permanencia".

Contar es trabajo del servicio YOLO, que vive aparte porque PyTorch y la GPU no
tienen nada que hacer en este contenedor. Lo que pasa aqui es lo otro: elegir el
clip, pedirle el conteo a ese servicio, comparar con la orden y escribir el
resultado en el evento.

Por que aqui y no en el orquestador. El clip acaba de salir de `app/clips.py` y
todavia esta en disco local: analizarlo en este mismo paso ahorra bajarlo de
MinIO. Y sobre todo, el analisis tarda minutos y el RNF-03 exige que POST
/pesadas responda en menos de 2 s, asi que no puede colgar de esa peticion.

Cuando el servicio no responde. El clip ya esta guardado y vinculado, que es lo
que no se puede perder. El conteo se reintenta en vueltas posteriores bajando el
clip de MinIO, hasta `ajustes.intentos_de_conteo` veces. Se limita a proposito:
un YOLO caido un dia entero tendria al grabador bajando los mismos clips en
bucle, y un evento sin conteo se puede reanalizar despues, que es lo que HU-19
va a necesitar de todas formas cuando cambie el modelo.
"""
from __future__ import annotations

import base64
import dataclasses
import datetime as dt
import pathlib
import tempfile

import httpx
import structlog
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from app import almacen, tablas
from app.config import Ajustes

log = structlog.get_logger("quinor.conteo")

RUTA_DE_ANALISIS = "/analisis/yolo"
ACCION_OK = "contar_sacos"
ACCION_FALLO = "conteo_fallido"
SIN_CLIP = "sin_clip"


class ServicioNoDisponible(RuntimeError):
    """El servicio YOLO no respondio o respondio con error."""


@dataclasses.dataclass(frozen=True)
class FotogramaClave:
    """Un fotograma que explica la carga. HU-09, y el criterio 3 de HU-12.

    Llega en base64 dentro de la respuesta de YOLO y se sube a MinIO junto al
    clip: sin guardarlo, HU-12 tendria que volver a analizar el video cada vez
    que alguien abriera el evento, y el reintento del analisis tampoco tendria
    de donde sacar las imagenes.
    """

    jpeg: bytes
    motivo: str
    detalle: str
    segundo: float
    fotograma: int

    @property
    def nombre(self) -> str:
        return f"f{self.fotograma:06d}_{self.motivo}.jpg"


@dataclasses.dataclass(frozen=True)
class PersonaEnZona:
    """Una persona vista en la zona de carga. HU-08, criterios 1 y 2.

    Esto es todo lo que se recibe de ella y todo lo que se guarda. El
    identificador lo puso el rastreador, vale solo dentro de este clip y no se
    puede cruzar con otro video ni con ninguna lista de personal (RN-08).
    """

    id_temporal: int
    segundos_en_zona: float
    primer_fotograma: int
    ultimo_fotograma: int


@dataclasses.dataclass(frozen=True)
class Conteo:
    """Lo que el servicio YOLO devolvio de un clip."""

    sacos_contados: int
    sacos_entrantes: int
    sacos_salientes: int
    personas_detectadas: int
    sacos_esperados: int | None
    diferencia_sacos: int | None
    modelo: str
    segundos_de_proceso: float
    # HU-08
    personas: tuple[PersonaEnZona, ...] = ()
    maximo_simultaneo: int = 0
    permanencia_maxima_s: float = 0.0
    zona_completa: bool = True
    personal_anomalo: bool = False
    motivos_de_anomalia: tuple[str, ...] = ()
    # HU-09
    fotogramas: tuple[FotogramaClave, ...] = ()

    @property
    def cuadra(self) -> bool:
        """El video vio los sacos que decia la orden."""
        return self.diferencia_sacos == 0

    @property
    def faltan_sacos(self) -> bool:
        """Negativa es faltante, el mismo criterio de signo que la de peso."""
        return self.diferencia_sacos is not None and self.diferencia_sacos < 0


def analizar(ajustes: Ajustes, clip: pathlib.Path,
             sacos_esperados: int | None) -> Conteo:
    """Pide el conteo al servicio YOLO.

    El clip viaja por ruta y no por el cuerpo de la peticion: son cientos de
    megas y los dos contenedores comparten el volumen del buffer. Subirlo por
    HTTP para que el otro lo escriba otra vez en disco seria copiar gigas al dia
    sin motivo.
    """
    if not ajustes.cuenta_sacos:
        raise ServicioNoDisponible(
            "YOLO_URL esta vacio: el conteo de HU-07 esta apagado en esta instalacion.")

    cabeceras = {"X-API-Key": ajustes.yolo_api_key} if ajustes.yolo_api_key else {}
    cuerpo = {"clip": str(clip), "sacos_esperados": sacos_esperados}
    destino = ajustes.yolo_url.rstrip("/") + RUTA_DE_ANALISIS
    try:
        respuesta = httpx.post(destino, json=cuerpo, headers=cabeceras,
                               timeout=ajustes.yolo_timeout_s)
        respuesta.raise_for_status()
        datos = respuesta.json()
    except httpx.HTTPStatusError as exc:
        raise ServicioNoDisponible(
            f"El servicio YOLO respondio {exc.response.status_code}: "
            f"{exc.response.text[:200]}") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise ServicioNoDisponible(f"No se pudo hablar con el servicio YOLO: {exc}") from exc

    presencia = datos.get("presencia") or {}
    return Conteo(
        sacos_contados=int(datos["sacos_contados"]),
        sacos_entrantes=int(datos["sacos_entrantes"]),
        sacos_salientes=int(datos["sacos_salientes"]),
        personas_detectadas=int(datos["personas_detectadas"]),
        sacos_esperados=datos.get("sacos_esperados"),
        diferencia_sacos=datos.get("diferencia_sacos"),
        modelo=str(datos.get("modelo", "")),
        segundos_de_proceso=float(datos.get("segundos_de_proceso", 0.0)),
        personas=tuple(
            PersonaEnZona(
                id_temporal=int(p["id_temporal"]),
                segundos_en_zona=float(p["segundos_en_zona"]),
                primer_fotograma=int(p["primer_fotograma"]),
                ultimo_fotograma=int(p["ultimo_fotograma"]))
            for p in presencia.get("personas", [])),
        maximo_simultaneo=int(presencia.get("maximo_simultaneo", 0)),
        permanencia_maxima_s=float(presencia.get("permanencia_maxima_s", 0.0)),
        zona_completa=bool(presencia.get("zona_completa", True)),
        personal_anomalo=bool(datos.get("anomalia_de_personal", False)),
        motivos_de_anomalia=tuple(
            str(m.get("codigo", "")) for m in datos.get("motivos_de_anomalia", [])),
        fotogramas=tuple(
            FotogramaClave(
                jpeg=base64.b64decode(f["jpeg_base64"]),
                motivo=str(f.get("motivo", "")),
                detalle=str(f.get("detalle", "")),
                segundo=float(f.get("segundo", 0.0)),
                fotograma=int(f.get("fotograma", 0)))
            for f in datos.get("fotogramas_clave", [])),
    )


# ------------------------------------------------------------------ escritura
def _anotar(motor: Engine, evento_id: int, accion: str, detalle: dict) -> None:
    with motor.begin() as conexion:
        conexion.execute(tablas.auditoria.insert().values(
            entidad="evento", entidad_id=evento_id, accion=accion,
            usuario_id=None, detalle=detalle,
            fecha=dt.datetime.now().replace(tzinfo=None)))


def guardar(motor: Engine, evento_id: int, conteo: Conteo) -> None:
    """Criterio 3 de HU-07 y criterio 2 de HU-08, en la misma transaccion.

    La diferencia se guarda en lugar de recalcularse al mirarla porque la orden
    se resincroniza desde el ERP: si manana cambia sacos_esperados, un evento ya
    investigado no debe cambiar de cifra a posteriori.

    Las personas se reemplazan en lugar de anadirse: reanalizar el mismo clip
    (HU-19 cambiara el modelo) tiene que dejar el registro que corresponde a ese
    analisis, no la suma de todos los que se hicieron.
    """
    with motor.begin() as conexion:
        conexion.execute(tablas.evento.update()
                         .where(tablas.evento.c.id == evento_id)
                         .values(sacos_contados=conteo.sacos_contados,
                                 diferencia_sacos=conteo.diferencia_sacos,
                                 personas_detectadas=conteo.personas_detectadas,
                                 personal_anomalo=conteo.personal_anomalo))
        conexion.execute(tablas.persona_en_evento.delete()
                         .where(tablas.persona_en_evento.c.evento_id == evento_id))
        if conteo.personas:
            conexion.execute(tablas.persona_en_evento.insert(), [
                {"evento_id": evento_id,
                 "id_temporal": p.id_temporal,
                 "segundos_en_zona": p.segundos_en_zona,
                 "primer_fotograma": p.primer_fotograma,
                 "ultimo_fotograma": p.ultimo_fotograma}
                for p in conteo.personas])


def contar(motor: Engine, ajustes: Ajustes, evento_id: int, clip: pathlib.Path,
           sacos_esperados: int | None, detalle: dict | None = None,
           analizador=None) -> Conteo | None:
    """Analiza el clip y guarda el resultado. Devuelve None si no se pudo.

    Un fallo aqui no tumba nada: el clip ya esta guardado y vinculado, que es lo
    que no se puede perder. Queda el rastro en auditoria y el reintento lo hace
    `procesar_pendientes`.
    """
    if not ajustes.cuenta_sacos:
        return None
    analizador = analizador or analizar
    try:
        conteo = analizador(ajustes, clip, sacos_esperados)
    except ServicioNoDisponible as exc:
        _anotar(motor, evento_id, ACCION_FALLO,
                {**(detalle or {}), "motivo": str(exc)})
        log.warning("conteo_fallido", evento_id=evento_id, motivo=str(exc))
        return None

    guardar(motor, evento_id, conteo)
    _anotar(motor, evento_id, ACCION_OK, {
        **(detalle or {}),
        "sacos_contados": conteo.sacos_contados,
        "sacos_entrantes": conteo.sacos_entrantes,
        "sacos_salientes": conteo.sacos_salientes,
        "sacos_esperados": conteo.sacos_esperados,
        "diferencia_sacos": conteo.diferencia_sacos,
        "personas_detectadas": conteo.personas_detectadas,
        # HU-08. En auditoria van los numeros que sostienen el aviso, no quien
        # es nadie: cuantos a la vez, cuanto duro la permanencia mas larga y con
        # que zona se midio.
        "maximo_simultaneo": conteo.maximo_simultaneo,
        "permanencia_maxima_s": conteo.permanencia_maxima_s,
        "zona_completa": conteo.zona_completa,
        "personal_anomalo": conteo.personal_anomalo,
        "motivos_de_anomalia": list(conteo.motivos_de_anomalia),
        "modelo": conteo.modelo,
        "segundos_de_proceso": conteo.segundos_de_proceso,
    })
    log.info("clip_analizado", evento_id=evento_id,
             sacos=conteo.sacos_contados, esperados=conteo.sacos_esperados,
             diferencia=conteo.diferencia_sacos,
             personas=conteo.personas_detectadas,
             personal_anomalo=conteo.personal_anomalo,
             motivos=list(conteo.motivos_de_anomalia),
             modelo=conteo.modelo, segundos=conteo.segundos_de_proceso)
    return conteo


# ------------------------------------------------------------- los reintentos
def pendientes_de_conteo(motor: Engine, ajustes: Ajustes,
                         limite: int = 10) -> list[dict]:
    """Eventos con clip guardado a los que les falta el conteo.

    Solo los que no agotaron los intentos: cada fallo deja su fila en auditoria,
    y contarlas es lo que impide que un YOLO caido tenga al grabador bajando los
    mismos clips cada quince segundos hasta que alguien mire el log.
    """
    fallos = (
        select(func.count())
        .select_from(tablas.auditoria)
        .where(tablas.auditoria.c.entidad == "evento",
               tablas.auditoria.c.entidad_id == tablas.evento.c.id,
               tablas.auditoria.c.accion == ACCION_FALLO)
        .scalar_subquery())
    consulta = (
        select(tablas.evento.c.id, tablas.evento.c.clip_url,
               tablas.orden_despacho.c.numero_orden,
               tablas.orden_despacho.c.sacos_esperados)
        .select_from(
            tablas.evento
            .join(tablas.pesada, tablas.evento.c.pesada_id == tablas.pesada.c.id)
            .join(tablas.orden_despacho,
                  tablas.pesada.c.orden_id == tablas.orden_despacho.c.id))
        .where(tablas.evento.c.clip_url.is_not(None),
               tablas.evento.c.sacos_contados.is_(None),
               tablas.evento.c.estado != SIN_CLIP,
               fallos < ajustes.intentos_de_conteo)
        .order_by(tablas.evento.c.creado_en.asc())
        .limit(limite))
    with motor.connect() as conexion:
        return [dict(f) for f in conexion.execute(consulta).mappings().all()]


def procesar_evento(motor: Engine, ajustes: Ajustes, fila: dict,
                    cliente=None, analizador=None) -> Conteo | None:
    """Reintento: baja el clip de MinIO y lo analiza.

    Se baja en lugar de volver a recortarlo del buffer porque el buffer solo
    guarda 72 h y el clip de MinIO es exactamente el que ya se vinculo al evento:
    reanalizar otra cosa daria un conteo que no corresponde a la evidencia.
    """
    cliente = cliente or almacen.crear_cliente(ajustes)
    detalle = {"numero_orden": fila["numero_orden"],
               "clip_url": fila["clip_url"], "origen": "reintento"}
    with tempfile.TemporaryDirectory(prefix="quinor-conteo-") as temporal:
        destino = pathlib.Path(temporal) / f"evento-{fila['id']}.mkv"
        try:
            almacen.descargar(cliente, fila["clip_url"], destino)
        except almacen.ErrorDeAlmacen as exc:
            _anotar(motor, fila["id"], ACCION_FALLO,
                    {**detalle, "motivo": str(exc)})
            log.warning("conteo_fallido", evento_id=fila["id"], motivo=str(exc))
            return None
        return contar(motor, ajustes, fila["id"], destino,
                      fila["sacos_esperados"], detalle=detalle,
                      analizador=analizador)


def procesar_pendientes(motor: Engine, ajustes: Ajustes, limite: int = 10,
                        cliente=None, analizador=None) -> list[Conteo]:
    """Una pasada por los eventos con clip y sin conteo.

    Un fallo con un evento no detiene a los demas, igual que en HU-06.
    """
    hechos = []
    for fila in pendientes_de_conteo(motor, ajustes, limite):
        try:
            conteo = procesar_evento(motor, ajustes, fila, cliente=cliente,
                                     analizador=analizador)
        except Exception as exc:      # noqa: BLE001
            log.error("conteo_reintento_fallido", evento_id=fila["id"], error=str(exc))
            continue
        if conteo is not None:
            hechos.append(conteo)
    return hechos
