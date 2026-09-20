"""Interpretacion del evento con el modelo de vision-lenguaje. HU-09.

  1. Solo se invoca cuando YOLO confirma diferencia de sacos o personal anomalo.
  2. La respuesta es un JSON con descripcion, severidad y evidencia observada.
  3. Si la API falla se reintenta 3 veces y luego se marca Pendiente de analisis.

Describir es trabajo del servicio de vision-lenguaje, que vive aparte porque es
el unico del sistema que sale a internet. Lo que pasa aqui es lo otro: juntar lo
que el evento sabe, pedir la interpretacion, y escribir el resultado o marcar el
fallo. El criterio 1 lo comprueba el propio servicio, que es donde vive la RN-03
junto al prompt y a la regla de severidad.

Por que aqui y no en el orquestador. El apartado 6.4 dice que quien llama es el
worker, que es HU-17 y todavia no existe; mientras tanto el bucle de sondeo de
este servicio hace de worker, y es ademas quien tiene el clip, los fotogramas y
la conexion a la base. Cuando llegue HU-17, lo unico que cambia es quien llama a
`interpretar`.

Los fotogramas. Se suben a MinIO junto al clip antes de mandarlos, porque sirven
para dos cosas mas: el reintento cuando el modelo falla, que asi no obliga a
reanalizar el video, y el criterio 3 de HU-12, que pedira mostrar el fotograma de
la anomalia.
"""
from __future__ import annotations

import base64
import dataclasses
import datetime as dt
import decimal
import tempfile
import time

import httpx
import structlog
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from app import almacen, tablas
from app.config import Ajustes
from app.conteo import Conteo, FotogramaClave

log = structlog.get_logger("quinor.interpretacion")

RUTA_DE_ANALISIS = "/analisis/vlm"
ACCION_OK = "interpretar_evento"
ACCION_FALLO = "interpretacion_fallida"
ACCION_NO_INVOCADO = "interpretacion_no_necesaria"

# Apartado 5.3: "Pendiente de analisis - el analisis de IA fallo tras los
# reintentos", y vuelve a Pendiente al reintentar.
PENDIENTE = "pendiente"
PENDIENTE_ANALISIS = "pendiente_analisis"
SIN_CLIP = "sin_clip"
# Estados finales o en curso que no se tocan: si un supervisor ya abrio el caso o
# lo cerro, un analisis tardio no puede devolverlo a la cola.
ESTADOS_QUE_NO_SE_TOCAN = ("en_revision", "confirmado", "falso_positivo")


class ServicioNoDisponible(RuntimeError):
    """El servicio de vision-lenguaje no respondio o respondio con error."""


@dataclasses.dataclass(frozen=True)
class Interpretacion:
    """Lo que el servicio devolvio de un evento."""

    invocado: bool
    motivo_de_invocacion: str
    severidad: str | None
    motivo_de_severidad: str
    analisis: dict | None = None
    concuerdan: bool | None = None
    fallo: bool = False
    motivo_del_fallo: str = ""
    intentos: int = 0

    @property
    def hay_descripcion(self) -> bool:
        return bool(self.analisis)


# --------------------------------------------------------- hablar con el servicio
def _contexto(fila: dict, conteo: Conteo | None,
              fotogramas: list[dict]) -> dict:
    """Los datos estructurados del apartado 9.2, en el formato del servicio."""
    def numero(valor):
        if isinstance(valor, decimal.Decimal):
            return float(valor)
        return valor

    cuerpo = {
        "evento_id": fila["id"],
        "numero_orden": fila.get("numero_orden", ""),
        "producto": fila.get("producto", ""),
        "peso_esperado_kg": numero(fila.get("peso_esperado_kg")),
        "peso_real_kg": numero(fila.get("peso_real_kg")),
        "diferencia_kg": numero(fila.get("diferencia_kg")),
        "diferencia_pct": numero(fila.get("diferencia_pct")),
        "sacos_esperados": fila.get("sacos_esperados"),
        "sacos_contados": fila.get("sacos_contados"),
        "diferencia_sacos": fila.get("diferencia_sacos"),
        "personas_detectadas": fila.get("personas_detectadas"),
        "personal_anomalo": fila.get("personal_anomalo"),
        "fotogramas": fotogramas,
    }
    if conteo is not None:
        # Del analisis recien hecho salen cosas que no estan en la tabla.
        cuerpo.update({
            "sacos_salientes": conteo.sacos_salientes,
            "maximo_simultaneo": conteo.maximo_simultaneo,
            "permanencia_maxima_s": conteo.permanencia_maxima_s,
            "motivos_de_anomalia": list(conteo.motivos_de_anomalia),
        })
    return cuerpo


def pedir(ajustes: Ajustes, cuerpo: dict) -> dict:
    """Una llamada al servicio de vision-lenguaje.

    Los reintentos son suyos, no de aqui: el criterio 3 los pone en un solo sitio
    y duplicarlos multiplicaria el gasto en un proveedor que cobra por llamada.
    """
    if not ajustes.interpreta_eventos:
        raise ServicioNoDisponible(
            "VLM_URL esta vacio: la interpretacion de HU-09 esta apagada en "
            "esta instalacion.")

    cabeceras = {"X-API-Key": ajustes.vlm_api_key} if ajustes.vlm_api_key else {}
    destino = ajustes.vlm_url.rstrip("/") + RUTA_DE_ANALISIS
    try:
        respuesta = httpx.post(destino, json=cuerpo, headers=cabeceras,
                               timeout=ajustes.vlm_timeout_s)
        respuesta.raise_for_status()
        return respuesta.json()
    except httpx.HTTPStatusError as exc:
        raise ServicioNoDisponible(
            f"El servicio de vision-lenguaje respondio "
            f"{exc.response.status_code}: {exc.response.text[:200]}") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise ServicioNoDisponible(
            f"No se pudo hablar con el servicio de vision-lenguaje: {exc}") from exc


# --------------------------------------------------------------- los fotogramas
def subir_fotogramas(cliente, ajustes: Ajustes, clip_url: str,
                     fotogramas: tuple[FotogramaClave, ...]) -> list[dict]:
    """Deja los fotogramas en MinIO junto al clip y devuelve su descripcion.

    Junto al clip y no en otro sitio: cuando alguien investigue un caso, la
    evidencia de ese evento esta en una sola carpeta.
    """
    partes = almacen.partes_de(clip_url)
    if partes is None or not fotogramas:
        return []
    bucket, objeto = partes
    prefijo = objeto.rsplit(".", 1)[0]

    guardados = []
    with tempfile.TemporaryDirectory(prefix="quinor-fotogramas-") as temporal:
        import pathlib

        for imagen in fotogramas:
            ruta = pathlib.Path(temporal) / imagen.nombre
            ruta.write_bytes(imagen.jpeg)
            destino = f"{prefijo}/fotogramas/{imagen.nombre}"
            direccion = almacen.subir(cliente, bucket, destino, ruta,
                                      tipo="image/jpeg")
            guardados.append({
                "url": direccion, "motivo": imagen.motivo,
                "detalle": imagen.detalle, "segundo": imagen.segundo,
                "fotograma": imagen.fotograma,
            })
    return guardados


def _para_el_modelo(cliente, guardados: list[dict],
                    fotogramas: tuple[FotogramaClave, ...]) -> list[dict]:
    """Los fotogramas en base64, que es como viajan al servicio."""
    del cliente, guardados
    return [{"jpeg_base64": base64.b64encode(f.jpeg).decode("ascii"),
             "motivo": f.motivo, "detalle": f.detalle,
             "segundo": f.segundo, "fotograma": f.fotograma}
            for f in fotogramas]


def bajar_fotogramas(cliente, guardados: list[dict]) -> list[dict]:
    """Recupera de MinIO los fotogramas de un evento, para el reintento.

    Asi un fallo del modelo no obliga a reanalizar el video, que es lo caro.
    """
    import pathlib

    recuperados = []
    with tempfile.TemporaryDirectory(prefix="quinor-fotogramas-") as temporal:
        for guardado in guardados or []:
            destino = pathlib.Path(temporal) / f"{len(recuperados)}.jpg"
            try:
                almacen.descargar(cliente, guardado["url"], destino)
            except almacen.ErrorDeAlmacen as exc:
                log.warning("fotograma_no_recuperado", url=guardado.get("url"),
                            error=str(exc))
                continue
            recuperados.append({
                "jpeg_base64": base64.b64encode(destino.read_bytes()).decode("ascii"),
                "motivo": guardado.get("motivo", ""),
                "detalle": guardado.get("detalle", ""),
                "segundo": guardado.get("segundo", 0.0),
                "fotograma": guardado.get("fotograma", 0),
            })
    return recuperados


# ------------------------------------------------------------------- escritura
def _anotar(motor: Engine, evento_id: int, accion: str, detalle: dict) -> None:
    with motor.begin() as conexion:
        conexion.execute(tablas.auditoria.insert().values(
            entidad="evento", entidad_id=evento_id, accion=accion,
            usuario_id=None, detalle=detalle,
            fecha=dt.datetime.now().replace(tzinfo=None)))


def guardar(motor: Engine, evento_id: int, resultado: Interpretacion,
            fotogramas: list[dict] | None = None) -> None:
    """Criterio 2: la descripcion, la severidad y la evidencia en el evento."""
    valores = {"severidad": resultado.severidad}
    if resultado.analisis is not None:
        valores["descripcion_ia"] = resultado.analisis
    if fotogramas:
        valores["fotogramas_clave"] = fotogramas
    with motor.begin() as conexion:
        conexion.execute(tablas.evento.update()
                         .where(tablas.evento.c.id == evento_id)
                         .values(**valores))


def marcar_pendiente_de_analisis(motor: Engine, evento_id: int) -> None:
    """Criterio 3 y apartado 5.3.

    Solo desde Pendiente: si un supervisor ya abrio el caso o lo cerro, un
    analisis que falla tarde no puede devolverlo a la cola, y la RN-06 prohibe
    que un Confirmado retroceda.
    """
    with motor.begin() as conexion:
        conexion.execute(
            tablas.evento.update()
            .where(tablas.evento.c.id == evento_id,
                   tablas.evento.c.estado == PENDIENTE)
            .values(estado=PENDIENTE_ANALISIS))


def devolver_a_pendiente(motor: Engine, evento_id: int) -> None:
    """La transicion de vuelta del apartado 5.3, al reintentar con exito."""
    with motor.begin() as conexion:
        conexion.execute(
            tablas.evento.update()
            .where(tablas.evento.c.id == evento_id,
                   tablas.evento.c.estado == PENDIENTE_ANALISIS)
            .values(estado=PENDIENTE))


# --------------------------------------------------------------- el caso de uso
def interpretar(motor: Engine, ajustes: Ajustes, fila: dict,
                conteo: Conteo | None = None, cliente=None,
                peticion=None, al_clasificar=None) -> Interpretacion | None:
    """Pide la interpretacion y guarda el resultado. Criterios 1, 2 y 3.

    `al_clasificar` es el enganche de HU-10: se llama con el identificador del
    evento y una marca de `time.monotonic()` tomada en el instante en que la
    severidad quedo escrita, que es de donde sale el "menos de 60 s tras el
    analisis" de su criterio 3. Es un parametro y no una llamada directa a
    app/aviso para que este modulo no dependa de que exista HU-10: quien enchufa
    las dos cosas es el grabador, que es quien conoce las dos.

    Devuelve None cuando la interpretacion esta apagada en esta instalacion.
    """
    if not ajustes.interpreta_eventos:
        return None
    evento_id = fila["id"]
    peticion = peticion or pedir

    # Los fotogramas del analisis recien hecho se suben; los de un reintento ya
    # estan en MinIO y se bajan de alli.
    guardados = list(fila.get("fotogramas_clave") or [])
    if conteo is not None and conteo.fotogramas and cliente is not None:
        guardados = subir_fotogramas(cliente, ajustes, fila.get("clip_url", ""),
                                     conteo.fotogramas)
        imagenes = _para_el_modelo(cliente, guardados, conteo.fotogramas)
    elif guardados and cliente is not None:
        imagenes = bajar_fotogramas(cliente, guardados)
    else:
        imagenes = []

    try:
        datos = peticion(ajustes, _contexto(fila, conteo, imagenes))
    except ServicioNoDisponible as exc:
        _anotar(motor, evento_id, ACCION_FALLO, {"motivo": str(exc)})
        marcar_pendiente_de_analisis(motor, evento_id)
        log.error("interpretacion_fallida", evento_id=evento_id, motivo=str(exc))
        return Interpretacion(
            invocado=True, motivo_de_invocacion="", severidad=None,
            motivo_de_severidad="", fallo=True, motivo_del_fallo=str(exc))

    resultado = Interpretacion(
        invocado=bool(datos.get("invocado")),
        motivo_de_invocacion=str(datos.get("motivo_de_invocacion", "")),
        severidad=datos.get("severidad"),
        motivo_de_severidad=str(datos.get("motivo_de_severidad", "")),
        analisis=datos.get("analisis"),
        concuerdan=datos.get("concuerdan"),
        fallo=bool(datos.get("fallo")),
        motivo_del_fallo=str(datos.get("motivo_del_fallo", "")),
        intentos=int(datos.get("intentos", 0)),
    )

    # La severidad se guarda siempre que exista, invocado el modelo o no: sale
    # de la RN-04 y es lo que HU-10 y HU-11 necesitan para priorizar.
    guardar(motor, evento_id, resultado, guardados)
    clasificado_en = time.monotonic()

    if resultado.fallo:
        # Criterio 3: el modelo agoto sus intentos.
        marcar_pendiente_de_analisis(motor, evento_id)
        _anotar(motor, evento_id, ACCION_FALLO, {
            "motivo": resultado.motivo_del_fallo,
            "intentos": resultado.intentos,
            "severidad": resultado.severidad})
        log.error("interpretacion_fallida", evento_id=evento_id,
                  intentos=resultado.intentos, motivo=resultado.motivo_del_fallo)
        return resultado

    if not resultado.invocado:
        # Criterio 1: no habia nada que explicar, y eso tambien se registra para
        # que un evento sin descripcion no parezca un fallo del sistema.
        _anotar(motor, evento_id, ACCION_NO_INVOCADO, {
            "motivo": resultado.motivo_de_invocacion,
            "explicacion": datos.get("explicacion", ""),
            "severidad": resultado.severidad})
        log.info("interpretacion_no_necesaria", evento_id=evento_id,
                 motivo=resultado.motivo_de_invocacion,
                 severidad=resultado.severidad)
        # Tambien se avisa: la RN-04 ya dio una severidad y el criterio 1 de
        # HU-10 manda correo en los tres niveles, no solo cuando hubo modelo.
        _avisar(al_clasificar, evento_id, clasificado_en, resultado)
        return resultado

    devolver_a_pendiente(motor, evento_id)
    analisis = resultado.analisis or {}
    _anotar(motor, evento_id, ACCION_OK, {
        "severidad": resultado.severidad,
        "motivo_de_severidad": resultado.motivo_de_severidad,
        "severidad_ia": analisis.get("severidad_ia"),
        "concuerdan": resultado.concuerdan,
        "confianza": analisis.get("confianza"),
        "modelo": analisis.get("modelo"),
        "proveedor": analisis.get("proveedor"),
        "intentos": analisis.get("intentos"),
        "fotogramas": [f["url"] for f in guardados],
    })
    log.info("evento_interpretado", evento_id=evento_id,
             severidad=resultado.severidad,
             severidad_ia=analisis.get("severidad_ia"),
             concuerdan=resultado.concuerdan, modelo=analisis.get("modelo"))
    _avisar(al_clasificar, evento_id, clasificado_en, resultado)
    return resultado


def _avisar(al_clasificar, evento_id: int, clasificado_en: float,
            resultado: Interpretacion) -> None:
    """Enganche de HU-10, y nada mas.

    Un fallo avisando no puede tumbar la interpretacion: el analisis ya esta
    guardado y el evento ya es visible en el dashboard. Quedarse sin correo es
    peor que no tenerlo, pero perder el analisis por eso seria mucho peor.
    """
    if al_clasificar is None or resultado.severidad is None:
        return
    try:
        al_clasificar(evento_id, clasificado_en)
    except Exception as exc:          # noqa: BLE001
        log.error("aviso_no_lanzado", evento_id=evento_id, error=str(exc))


# ------------------------------------------------------------- los reintentos
def pendientes_de_interpretar(motor: Engine, ajustes: Ajustes,
                              limite: int = 10) -> list[dict]:
    """Eventos ya analizados por YOLO a los que les falta la severidad.

    Se excluyen los que agotaron los intentos, contando sus filas de auditoria,
    por lo mismo que en HU-07: un proveedor caido un dia entero tendria al
    grabador bajando fotogramas y pagando llamadas en bucle.
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
               tablas.evento.c.estado,
               tablas.evento.c.sacos_contados, tablas.evento.c.diferencia_sacos,
               tablas.evento.c.personas_detectadas,
               tablas.evento.c.personal_anomalo,
               tablas.evento.c.fotogramas_clave,
               tablas.evento.c.diferencia_kg, tablas.evento.c.diferencia_pct,
               tablas.pesada.c.peso_real_kg,
               tablas.orden_despacho.c.numero_orden,
               tablas.orden_despacho.c.producto,
               tablas.orden_despacho.c.peso_esperado_kg,
               tablas.orden_despacho.c.sacos_esperados)
        .select_from(
            tablas.evento
            .join(tablas.pesada, tablas.evento.c.pesada_id == tablas.pesada.c.id)
            .join(tablas.orden_despacho,
                  tablas.pesada.c.orden_id == tablas.orden_despacho.c.id))
        .where(tablas.evento.c.severidad.is_(None),
               tablas.evento.c.sacos_contados.is_not(None),
               tablas.evento.c.estado.not_in(ESTADOS_QUE_NO_SE_TOCAN),
               fallos < ajustes.intentos_de_interpretacion)
        .order_by(tablas.evento.c.creado_en.asc())
        .limit(limite))
    with motor.connect() as conexion:
        return [dict(f) for f in conexion.execute(consulta).mappings().all()]


def procesar_pendientes(motor: Engine, ajustes: Ajustes, limite: int = 10,
                        cliente=None, peticion=None,
                        al_clasificar=None) -> list[Interpretacion]:
    """Una pasada por los eventos analizados y sin severidad."""
    if not ajustes.interpreta_eventos:
        return []
    cliente = cliente or (almacen.crear_cliente(ajustes)
                          if ajustes.recorta_clips else None)
    hechos = []
    for fila in pendientes_de_interpretar(motor, ajustes, limite):
        try:
            resultado = interpretar(motor, ajustes, fila, cliente=cliente,
                                    peticion=peticion,
                                    al_clasificar=al_clasificar)
        except Exception as exc:      # noqa: BLE001
            log.error("interpretacion_reintento_fallido", evento_id=fila["id"],
                      error=str(exc))
            continue
        if resultado is not None:
            hechos.append(resultado)
    return hechos
