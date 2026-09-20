"""Servicio de grabacion continua y recorte de clips. HU-05 y HU-06.

Como supervisor de despacho, quiero que las camaras de la rampa graben de forma
continua en un buffer circular, para contar con el video de cualquier carga
reciente.

Criterios de aceptacion:
  1. Cada camara RTSP se graba en segmentos de 1 min con el muxer segment de
     ffmpeg (-c copy, -strftime 1), que no reencodifica.
  2. Se conservan al menos 72 h de video en disco local.
  3. Si una camara se desconecta se registra en salud_componente, expuesto por
     GET /salud.

Desde HU-06 este mismo servicio recorta el clip de cada evento de discrepancia:
el buffer esta aqui, la API no tiene ni el volumen de video ni ffmpeg, y asi el
recorte no bloquea el registro de pesadas. El caso de uso vive en app/clips.py.

El servicio es un supervisor, no un grabador: quien graba es ffmpeg, uno por
camara. Este proceso los arranca, mira si siguen vivos, los vuelve a levantar
cuando se caen, deja constancia de la caida y purga el buffer. Esa separacion es
la que permite que una camara caida no afecte a las otras tres.

Va aparte del orquestador a proposito. Un proceso que graba sin parar y una API
que atiende peticiones tienen ciclos de vida distintos, y un fallo del grabador
no puede llevarse por delante el registro de pesadas de HU-01.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import signal
import time

import structlog
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app import (aviso, clips, conteo, ffmpeg, interpretacion, retencion,
                 salud)
from app.config import Ajustes, Camara

log = structlog.get_logger("quinor.grabador")


@dataclasses.dataclass
class EstadoDeCamara:
    """Lo que el supervisor recuerda de cada camara entre vuelta y vuelta."""

    camara: Camara
    grabacion: ffmpeg.Grabacion | None = None
    conectada: bool = False
    caidas: int = 0
    proximo_intento: float = 0.0

    @property
    def componente(self) -> str:
        return self.camara.componente


class Grabador:
    """Supervisor de los ffmpeg de todas las camaras.

    Una vuelta del bucle no bloquea: revisa, actua y vuelve. Asi una camara que
    tarda en reconectar no retrasa la purga ni deja a las demas sin vigilancia.
    """

    def __init__(self, ajustes: Ajustes, motor: Engine):
        self.ajustes = ajustes
        self.motor = motor
        self.camaras = [EstadoDeCamara(camara=c) for c in ajustes.camaras]
        self.ultima_purga = 0.0
        self.ultimo_clip = 0.0
        self.clips_recortados = 0
        self.ultimo_conteo = 0.0
        self.sacos_contados = 0
        self.ultima_interpretacion = 0.0
        self.eventos_interpretados = 0
        self.ultimo_aviso = 0.0
        self.eventos_avisados = 0
        self._parar = False

    # ------------------------------------------------------------- criterio 1
    def arrancar_camara(self, estado: EstadoDeCamara) -> None:
        """Levanta ffmpeg para una camara. Si no arranca, queda para el reintento."""
        try:
            estado.grabacion = ffmpeg.iniciar(self.ajustes, estado.camara)
        except OSError as exc:
            # ffmpeg no esta instalado, o no hay permiso sobre la carpeta. Es un
            # fallo del servidor, no de la camara, pero se registra igual: sin
            # esto, el buffer estaria vacio y nadie lo sabria.
            self._registrar_caida(estado, f"no se pudo lanzar ffmpeg: {exc}")
            estado.grabacion = None
            estado.proximo_intento = time.monotonic() + self.ajustes.segundos_entre_reintentos
            return
        estado.proximo_intento = 0.0
        log.info("camara_grabando", camara=estado.componente,
                 comando=" ".join(estado.grabacion.comando))

    # ------------------------------------------------------------- criterio 3
    def _registrar_caida(self, estado: EstadoDeCamara, motivo: str) -> None:
        estado.conectada = False
        estado.caidas += 1
        log.warning("camara_caida", camara=estado.componente, motivo=motivo,
                    caidas=estado.caidas)
        self._anotar(salud.camara_desconectada, estado.componente, motivo)

    def _registrar_conexion(self, estado: EstadoDeCamara) -> None:
        if estado.conectada:
            return
        estado.conectada = True
        detalle = (f"grabando en segmentos de {self.ajustes.segundos_por_segmento} s "
                   f"en {ffmpeg.carpeta_de(self.ajustes, estado.camara)}")
        self._anotar(salud.camara_conectada, estado.componente, detalle)

    def _anotar(self, funcion, componente: str, mensaje: str) -> None:
        """Escribe en salud_componente sin dejar que un fallo de MySQL pare la grabacion.

        Grabar es lo primero: si la base no responde, el video sigue cayendo al
        disco y el registro se pierde. Al reves seria absurdo.
        """
        try:
            funcion(self.motor, componente, mensaje)
        except SQLAlchemyError as exc:
            log.error("salud_no_registrada", componente=componente, error=str(exc))

    # ------------------------------------------------------------------ bucle
    def revisar_camaras(self) -> None:
        """Una pasada por todas las camaras: levantar, vigilar y reintentar."""
        ahora = time.monotonic()
        for estado in self.camaras:
            if estado.grabacion is None:
                if ahora >= estado.proximo_intento:
                    self.arrancar_camara(estado)
                continue

            if estado.grabacion.sigue_viva():
                # ffmpeg vivo y escribiendo: la camara responde.
                self._registrar_conexion(estado)
                continue

            # ffmpeg termino. Con una fuente RTSP eso solo pasa si la camara
            # dejo de emitir: es la desconexion del criterio 3.
            #
            # Cuando la camara corta limpiamente, ffmpeg termina sin escribir
            # nada en stderr. Decir solo "termino" no ayudaria a nadie, asi que
            # el mensaje nombra la camara y su codigo de salida.
            codigo = estado.grabacion.proceso.poll()
            motivo = ffmpeg.ultimo_error(estado.grabacion) or (
                f"la camara {estado.camara.id} dejo de emitir: ffmpeg termino "
                f"con codigo {codigo} sin mensaje de error")
            self._registrar_caida(estado, motivo)
            estado.grabacion = None
            estado.proximo_intento = ahora + self.ajustes.segundos_entre_reintentos

    # ------------------------------------------------------------- criterio 2
    def revisar_retencion(self, forzar: bool = False) -> retencion.ResultadoDePurga | None:
        """Purga el buffer si toca, y deja el estado del disco en salud_componente."""
        ahora = time.monotonic()
        if not forzar and ahora - self.ultima_purga < self.ajustes.segundos_entre_purgas:
            return None
        self.ultima_purga = ahora

        resultado = retencion.purgar(self.ajustes)
        horas = retencion.horas_en_buffer(self.ajustes)
        if resultado.bajo_la_retencion_minima:
            self._anotar(
                _error_de_disco, salud.COMPONENTE_DISCO,
                f"disco al limite: se borro video de menos de "
                f"{self.ajustes.horas_de_retencion:.0f} h para poder seguir grabando. "
                f"Quedan {horas:.1f} h y {resultado.libre_pct:.1f} % libre",
            )
        else:
            self._anotar(
                _ok_de_disco, salud.COMPONENTE_DISCO,
                f"{horas:.1f} h de video en buffer, {resultado.libre_pct:.1f} % de disco libre",
            )
        return resultado

    # ------------------------------------------------------------- HU-10
    def _avisar(self, evento_id: int, analizado_en: float) -> None:
        """Enganche entre HU-09 y HU-10.

        Se llama en cuanto la severidad queda escrita, dentro de la misma
        pasada. Con un sondeo cada 30 segundos, esperar a la vuelta siguiente
        gastaria media ventana del criterio 3 sin hacer nada.
        """
        if not self.ajustes.avisa_eventos:
            return
        resultado = aviso.avisar(self.motor, self.ajustes, evento_id,
                                 analizado_en=analizado_en)
        if resultado is not None and resultado.enviado:
            self.eventos_avisados += 1

    # ------------------------------------------------------------- HU-06
    def revisar_clips(self, forzar: bool = False) -> list:
        """Recorta el clip de los eventos que todavia no lo tienen.

        Sondeo y no cola porque HU-17 aun no existe. Cuando llegue, lo unico que
        cambia es quien llama a clips.procesar_evento.

        Sin credenciales de MinIO no hay donde guardar nada, asi que no se
        intenta: marcar todos los eventos Sin clip por un fallo de configuracion
        seria destruir informacion que todavia esta en el buffer.
        """
        if not self.ajustes.recorta_clips:
            return []
        ahora = time.monotonic()
        if not forzar and ahora - self.ultimo_clip < self.ajustes.segundos_entre_clips:
            return []
        self.ultimo_clip = ahora

        try:
            resultados = clips.procesar_pendientes(self.motor, self.ajustes,
                                                   al_clasificar=self._avisar)
        except SQLAlchemyError as exc:
            log.error("clips_no_revisados", error=str(exc))
            return []
        self.clips_recortados += sum(1 for r in resultados if r.tiene_clip)
        self.sacos_contados += sum(1 for r in resultados if r.tiene_conteo)
        return resultados

    # ------------------------------------------------------------- HU-07
    def revisar_conteos(self, forzar: bool = False) -> list:
        """Reintenta el conteo de los eventos cuyo clip ya esta en MinIO.

        El camino normal cuenta en `revisar_clips`, con el clip todavia en disco.
        Aqui solo caen los que se quedaron sin conteo porque el servicio YOLO no
        respondio en aquel momento, y se bajan del almacen. Con el conteo
        apagado no se hace nada: en una instalacion sin GPU el grabador sigue
        haciendo su trabajo de HU-05 y HU-06.
        """
        if not (self.ajustes.cuenta_sacos and self.ajustes.recorta_clips):
            return []
        ahora = time.monotonic()
        if not forzar and ahora - self.ultimo_conteo < self.ajustes.segundos_entre_conteos:
            return []
        self.ultimo_conteo = ahora

        try:
            hechos = conteo.procesar_pendientes(self.motor, self.ajustes)
        except SQLAlchemyError as exc:
            log.error("conteos_no_revisados", error=str(exc))
            return []
        self.sacos_contados += len(hechos)
        return hechos

    # ------------------------------------------------------------- HU-09
    def revisar_interpretaciones(self, forzar: bool = False) -> list:
        """Reintenta la interpretacion de los eventos que se quedaron sin ella.

        El camino normal interpreta en `revisar_clips`, con los fotogramas
        recien llegados de YOLO. Aqui solo caen los que fallaron, y sus
        fotogramas se bajan de MinIO en lugar de reanalizar el video.

        Con la interpretacion apagada no se hace nada: el apartado 12 da la
        conectividad a internet como riesgo, y el sistema tiene que seguir
        detectando y guardando evidencia sin ella.
        """
        if not self.ajustes.interpreta_eventos:
            return []
        ahora = time.monotonic()
        if not forzar and (ahora - self.ultima_interpretacion
                           < self.ajustes.segundos_entre_interpretaciones):
            return []
        self.ultima_interpretacion = ahora

        try:
            hechos = interpretacion.procesar_pendientes(
                self.motor, self.ajustes, al_clasificar=self._avisar)
        except SQLAlchemyError as exc:
            log.error("interpretaciones_no_revisadas", error=str(exc))
            return []
        self.eventos_interpretados += sum(1 for h in hechos if h.hay_descripcion)
        return hechos

    # ------------------------------------------------------------- HU-10
    def revisar_avisos(self, forzar: bool = False) -> list:
        """Reintenta el correo de los eventos clasificados que se quedaron sin el.

        El camino normal avisa en la misma pasada del analisis, que es lo que
        permite cumplir el criterio 3. Aqui solo caen los que fallaron porque el
        servicio de notificaciones o el relay no respondieron en aquel momento.

        Con el aviso apagado no se hace nada: una instalacion sin servidor de
        correo sigue detectando, grabando y clasificando, y el supervisor lo ve
        en el dashboard.
        """
        if not self.ajustes.avisa_eventos:
            return []
        ahora = time.monotonic()
        if not forzar and ahora - self.ultimo_aviso < self.ajustes.segundos_entre_avisos:
            return []
        self.ultimo_aviso = ahora

        try:
            hechos = aviso.procesar_pendientes(self.motor, self.ajustes)
        except SQLAlchemyError as exc:
            log.error("avisos_no_revisados", error=str(exc))
            return []
        self.eventos_avisados += sum(1 for h in hechos if h.enviado)
        return hechos

    def una_vuelta(self) -> None:
        self.revisar_camaras()
        self.revisar_retencion()
        self.revisar_clips()
        self.revisar_conteos()
        self.revisar_interpretaciones()
        self.revisar_avisos()

    def detener(self, *_args) -> None:
        """SIGTERM: ffmpeg cierra el segmento en curso en lugar de dejarlo a medias."""
        self._parar = True

    def cerrar(self) -> None:
        for estado in self.camaras:
            if estado.grabacion is not None:
                estado.grabacion.detener()
                estado.grabacion = None
        log.info("grabador_detenido")

    def ejecutar(self, segundos_entre_vueltas: float = 2.0,
                 vueltas_maximas: int | None = None) -> int:
        """Bucle principal. Devuelve cuantas vueltas dio.

        `vueltas_maximas` existe para las pruebas: un servicio que solo sabe
        correr para siempre no se puede comprobar.
        """
        log.info("grabador_iniciado", camaras=[c.componente for c in self.camaras],
                 buffer=str(self.ajustes.directorio_buffer),
                 retencion_horas=self.ajustes.horas_de_retencion,
                 recorta_clips=self.ajustes.recorta_clips)
        if not self.ajustes.recorta_clips:
            log.warning("sin_minio_configurado",
                        detalle="MINIO_ACCESS_KEY vacia. No se recortaran clips (HU-06).")
        self.ajustes.directorio_buffer.mkdir(parents=True, exist_ok=True)
        self.revisar_retencion(forzar=True)

        vueltas = 0
        while not self._parar and (vueltas_maximas is None or vueltas < vueltas_maximas):
            self.una_vuelta()
            vueltas += 1
            if self._parar or (vueltas_maximas is not None and vueltas >= vueltas_maximas):
                break
            time.sleep(segundos_entre_vueltas)
        self.cerrar()
        return vueltas

    def resumen(self) -> dict:
        """Estado legible del servicio, para el log de arranque y las pruebas."""
        return {
            "camaras": {e.componente: ("grabando" if e.conectada else "caida")
                        for e in self.camaras},
            "horas_en_buffer": round(retencion.horas_en_buffer(self.ajustes), 2),
            "clips_recortados": self.clips_recortados,
            "recorta_clips": self.ajustes.recorta_clips,
            "eventos_contados": self.sacos_contados,
            "cuenta_sacos": self.ajustes.cuenta_sacos,
            "eventos_interpretados": self.eventos_interpretados,
            "interpreta_eventos": self.ajustes.interpreta_eventos,
            "eventos_avisados": self.eventos_avisados,
            "avisa_eventos": self.ajustes.avisa_eventos,
            "momento": dt.datetime.now().replace(tzinfo=None).isoformat(),
        }


def _error_de_disco(motor: Engine, componente: str, mensaje: str) -> bool:
    return salud.registrar_si_cambia(motor, componente, salud.ERROR, mensaje)


def _ok_de_disco(motor: Engine, componente: str, mensaje: str) -> bool:
    return salud.registrar_si_cambia(motor, componente, salud.OK, mensaje)


def crear_grabador(ajustes: Ajustes | None = None, **sobrescrituras) -> Grabador:
    """Fabrica del servicio, equivalente a create_app del orquestador.

    Cada parametro gana al entorno, de modo que una prueba apunta el grabador a
    otra carpeta y a otra camara sin tocar variables del proceso.
    """
    from app.config import cargar_ajustes
    from app.db import crear_motor

    ajustes = ajustes or cargar_ajustes(**sobrescrituras)
    return Grabador(ajustes, crear_motor(ajustes.database_url))


def main() -> None:                      # pragma: no cover - punto de entrada
    import logging

    ajustes = None
    grabador = crear_grabador(ajustes)
    logging.basicConfig(format="%(message)s",
                        level=getattr(logging, grabador.ajustes.log_level.upper(), logging.INFO))
    structlog.configure(processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ])
    signal.signal(signal.SIGTERM, grabador.detener)
    signal.signal(signal.SIGINT, grabador.detener)
    grabador.ejecutar()


if __name__ == "__main__":               # pragma: no cover
    main()
