"""Caso de uso de HU-06: recorte del clip de un evento.

Como supervisor de despacho, quiero que el sistema recorte automaticamente el
clip correspondiente a la ventana de tiempo de una carga con discrepancia, para
revisar solo el tramo relevante y no horas de video.

Criterios de aceptacion:
  1. Al crearse un evento se genera un clip desde 5 min antes del inicio de
     carga hasta 2 min despues del cierre.
  2. El clip se guarda en MinIO y se vincula al evento.
  3. Si falta video de ese rango, el evento pasa al estado Sin clip.

Vive en el grabador porque el buffer esta aqui: la API no tiene el volumen de
video ni ffmpeg. Ademas, asi el recorte no bloquea POST /pesadas, que es lo que
exige el RNF-03.

De momento los eventos se buscan sondeando la tabla cada pocos segundos. HU-17
sustituira ese sondeo por una cola con reintentos; cuando llegue, lo unico que
cambia es quien llama a `procesar_evento`.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import tempfile

import structlog
from sqlalchemy import select
from sqlalchemy.engine import Engine

from app import almacen, interpretacion, recorte, tablas
from app import conteo as conteo_de_sacos
from app.config import Ajustes

log = structlog.get_logger("quinor.clips")

SIN_CLIP = "sin_clip"
PENDIENTE = "pendiente"


@dataclasses.dataclass(frozen=True)
class Resultado:
    """Que paso con un evento."""

    evento_id: int
    clip_url: str | None = None
    estado: str = PENDIENTE
    motivo: str | None = None
    cobertura_pct: float = 0.0
    # HU-07, criterio 3. None cuando el conteo esta apagado o el servicio fallo.
    sacos_contados: int | None = None
    diferencia_sacos: int | None = None

    @property
    def tiene_clip(self) -> bool:
        return self.clip_url is not None

    @property
    def tiene_conteo(self) -> bool:
        return self.sacos_contados is not None


def _sacos_de_la_orden(fila: dict) -> int | None:
    """Los sacos que decia la orden. Es contra esto que se compara el video."""
    return fila.get("sacos_esperados")


def pendientes_de_clip(motor: Engine, ajustes: Ajustes,
                       limite: int = 20, ahora: dt.datetime | None = None) -> list[dict]:
    """Eventos ya creados a los que todavia les falta el clip.

    Solo entran los que ya tienen su ventana entera grabada. El criterio 1 pide
    2 minutos despues del cierre, y esos dos minutos tardan dos minutos en
    existir: recortar en cuanto nace el evento produciria un clip cortado justo
    donde hay que mirar. El evento espera y se recoge en una vuelta posterior.

    Se excluyen los que ya estan en Sin clip: ese estado es una conclusion, no
    un reintento pendiente. Si mas tarde apareciera el video, HU-13 permitira
    reabrir el caso; volver a intentarlo en bucle solo gastaria disco.
    """
    ahora = ahora or dt.datetime.now().replace(tzinfo=None)
    limite_de_cierre = ahora - dt.timedelta(seconds=ajustes.segundos_despues)
    consulta = (
        select(tablas.evento.c.id, tablas.evento.c.pesada_id,
               tablas.evento.c.estado, tablas.evento.c.creado_en,
               tablas.pesada.c.fecha_hora, tablas.pesada.c.inicio_carga,
               tablas.evento.c.diferencia_kg, tablas.evento.c.diferencia_pct,
               tablas.pesada.c.peso_real_kg,
               tablas.orden_despacho.c.numero_orden,
               tablas.orden_despacho.c.producto,
               tablas.orden_despacho.c.peso_esperado_kg,
               # HU-07: viaja aqui para no volver a consultar la orden cuando el
               # clip recien recortado se manda a contar.
               tablas.orden_despacho.c.sacos_esperados)
        .select_from(
            tablas.evento
            .join(tablas.pesada, tablas.evento.c.pesada_id == tablas.pesada.c.id)
            .join(tablas.orden_despacho,
                  tablas.pesada.c.orden_id == tablas.orden_despacho.c.id))
        .where(tablas.evento.c.clip_url.is_(None),
               tablas.evento.c.estado != SIN_CLIP,
               tablas.pesada.c.fecha_hora <= limite_de_cierre)
        .order_by(tablas.evento.c.creado_en.asc())
        .limit(limite))
    with motor.connect() as conexion:
        return [dict(f) for f in conexion.execute(consulta).mappings().all()]


def _anotar(motor: Engine, evento_id: int, accion: str, detalle: dict) -> None:
    with motor.begin() as conexion:
        conexion.execute(tablas.auditoria.insert().values(
            entidad="evento", entidad_id=evento_id, accion=accion,
            usuario_id=None, detalle=detalle,
            fecha=dt.datetime.now().replace(tzinfo=None)))


def _vincular(motor: Engine, evento_id: int, clip_url: str) -> None:
    """Criterio 2: el clip queda pegado al evento."""
    with motor.begin() as conexion:
        conexion.execute(tablas.evento.update()
                         .where(tablas.evento.c.id == evento_id)
                         .values(clip_url=clip_url))


def _marcar_sin_clip(motor: Engine, evento_id: int) -> None:
    """Criterio 3, con el estado del apartado 5.3."""
    with motor.begin() as conexion:
        conexion.execute(tablas.evento.update()
                         .where(tablas.evento.c.id == evento_id)
                         .values(estado=SIN_CLIP))


def procesar_evento(motor: Engine, ajustes: Ajustes, fila: dict,
                    cliente=None, analizador=None, interprete=None,
                    al_clasificar=None) -> Resultado:
    """Recorta, sube y vincula el clip de un evento. Criterios 1, 2 y 3 de HU-06.

    Y, si estan configurados, manda el clip a contar (HU-07) y el resultado a
    interpretar (HU-09) antes de soltarlo: es el momento mas barato para las dos
    cosas, porque el clip esta en disco local y los fotogramas en memoria.
    """
    conteo = None
    evento_id = fila["id"]
    ventana = recorte.ventana_de(fila["inicio_carga"], fila["fecha_hora"], ajustes)
    detalle_base = {
        "numero_orden": fila["numero_orden"],
        "camara": ajustes.camara_de_clips,
        "desde": ventana.desde.isoformat(),
        "hasta": ventana.hasta.isoformat(),
        "duracion_s": round(ventana.duracion_s, 1),
        "inicio_carga_marcado": fila["inicio_carga"] is not None,
    }

    with tempfile.TemporaryDirectory(prefix="quinor-clip-") as temporal:
        import pathlib

        destino = pathlib.Path(temporal) / f"evento-{evento_id}.mkv"
        try:
            clip = recorte.recortar(ajustes, ajustes.camara_de_clips, ventana, destino)
        except (recorte.SinVideoEnLaVentana, recorte.RecorteFallido) as exc:
            # Criterio 3. La causa queda escrita: no es lo mismo que la camara
            # estuviera caida que que el video ya se hubiera purgado.
            _marcar_sin_clip(motor, evento_id)
            _anotar(motor, evento_id, "evento_sin_clip",
                    {**detalle_base, "motivo": str(exc)})
            log.warning("evento_sin_clip", evento_id=evento_id, motivo=str(exc))
            return Resultado(evento_id=evento_id, estado=SIN_CLIP, motivo=str(exc))

        if not clip.completo and clip.cobertura_pct < ajustes.cobertura_minima_pct:
            # Hay video, pero tan poco que el clip no sirve para revisar nada.
            motivo = (f"solo hay {clip.cobertura_pct:.0f} % de la ventana en el "
                      f"buffer, por debajo del minimo de "
                      f"{ajustes.cobertura_minima_pct:.0f} %")
            _marcar_sin_clip(motor, evento_id)
            _anotar(motor, evento_id, "evento_sin_clip",
                    {**detalle_base, "motivo": motivo,
                     "cobertura_pct": round(clip.cobertura_pct, 1)})
            log.warning("evento_sin_clip", evento_id=evento_id, motivo=motivo)
            return Resultado(evento_id=evento_id, estado=SIN_CLIP, motivo=motivo,
                             cobertura_pct=clip.cobertura_pct)

        cliente = cliente or almacen.crear_cliente(ajustes)
        objeto = recorte.nombre_de_objeto(
            fila["numero_orden"], evento_id, ajustes.camara_de_clips, ventana)
        direccion = almacen.subir(cliente, ajustes.minio_bucket, objeto, destino)
        tamano = destino.stat().st_size

        _vincular(motor, evento_id, direccion)
        _anotar(motor, evento_id, "recortar_clip",
                {**detalle_base,
                 "clip_url": direccion,
                 "segmentos_usados": clip.segmentos_usados,
                 "cobertura_pct": round(clip.cobertura_pct, 1),
                 "bytes": tamano})
        log.info("clip_vinculado", evento_id=evento_id, clip=direccion,
                 cobertura_pct=round(clip.cobertura_pct, 1))

        # HU-07 en el mismo paso: el clip todavia esta en disco local, asi que
        # contar ahora ahorra bajarlo de MinIO. El evento ya quedo vinculado
        # arriba, de modo que si el servicio YOLO no responde no se pierde nada
        # y el reintento lo recoge desde el almacen.
        conteo = conteo_de_sacos.contar(
            motor, ajustes, evento_id, destino, _sacos_de_la_orden(fila),
            detalle={**detalle_base, "clip_url": direccion, "origen": "recorte"},
            analizador=analizador)

        # HU-09, en el mismo paso: los fotogramas clave acaban de llegar de YOLO
        # y todavia estan en memoria. Bajarlos luego de MinIO para lo mismo
        # seria pagar dos veces el viaje.
        if conteo is not None:
            interpretacion.interpretar(
                motor, ajustes,
                {**fila, "id": evento_id, "clip_url": direccion,
                 "sacos_contados": conteo.sacos_contados,
                 "diferencia_sacos": conteo.diferencia_sacos,
                 "personas_detectadas": conteo.personas_detectadas,
                 "personal_anomalo": conteo.personal_anomalo},
                conteo=conteo, cliente=cliente, peticion=interprete,
                al_clasificar=al_clasificar)

    return Resultado(evento_id=evento_id, clip_url=direccion,
                     estado=fila["estado"], cobertura_pct=clip.cobertura_pct,
                     sacos_contados=conteo.sacos_contados if conteo else None,
                     diferencia_sacos=conteo.diferencia_sacos if conteo else None)


def procesar_pendientes(motor: Engine, ajustes: Ajustes, limite: int = 20,
                        interprete=None, al_clasificar=None) -> list[Resultado]:
    """Una pasada por los eventos sin clip.

    Un fallo con un evento no detiene a los demas: el que reviente se reintenta
    en la siguiente vuelta, porque sigue sin clip_url.
    """
    resultados = []
    for fila in pendientes_de_clip(motor, ajustes, limite):
        try:
            resultados.append(procesar_evento(motor, ajustes, fila,
                                              interprete=interprete,
                                              al_clasificar=al_clasificar))
        except Exception as exc:      # noqa: BLE001
            log.error("clip_fallido", evento_id=fila["id"], error=str(exc))
    return resultados
