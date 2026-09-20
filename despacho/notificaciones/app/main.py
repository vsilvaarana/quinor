"""Servicio de notificaciones de QUINOR S.A.C. HU-10.

Como supervisor de despacho, quiero recibir una notificacion inmediata segun la
severidad del evento, para actuar antes de que el contenedor salga de planta.

Criterios de aceptacion (tras el cambio de alcance del 18/09/2026):
  1. La notificacion se envia por correo en los tres niveles. Alta: a
     supervisores y administradores, con asunto marcado y prioridad alta;
     Media: a supervisores; Baja: a supervisores, con prioridad normal.
  2. La notificacion incluye orden, diferencia y enlace al evento.
  3. La notificacion se envia en menos de 60 s tras el analisis.

El criterio 1 cambio: antes repartia por canal, con SMS y Slack para la Alta.
Slack salio porque se esta evaluando Teams en su lugar, y el SMS salio con el.
Al quedar un solo canal, la severidad pasa a decidir a quien se avisa y con que
urgencia. Sin eso, las tres alertas serian el mismo correo, que es la forma mas
rapida de que un supervisor deje de abrirlos.

El apartado 6.4 lo lista como componente propio y fija la libreria: aiosmtplib.
Va en su contenedor por la misma razon que el de vision-lenguaje: es el unico
servicio que habla con un servidor de fuera, y tenerlo aparte deja esa salida en
un sitio que se puede cortar y vigilar.

El servicio no decide cuando avisar. Eso lo decide quien llama, que es el
grabador al terminar el analisis de HU-09, y por eso puede medir el criterio 3.
Aqui solo se decide a quien, con que urgencia y que dice el correo.
"""
from __future__ import annotations

import contextlib
import logging
import secrets as _secrets

import structlog
from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader
from sqlalchemy import create_engine, text

from app import correo as envio
from app import plantilla, registro
from app.config import SEGUNDOS_DEL_CRITERIO, Ajustes, cargar_ajustes
from app.destinatarios import ALTA
from app.schemas import PeticionDeAviso, RespuestaDeAviso, RespuestaDeSalud

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _configurar_logging(nivel: str) -> None:
    logging.basicConfig(format="%(message)s",
                        level=getattr(logging, nivel.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )


def crear_motor(database_url: str):
    """pool_pre_ping y pool_recycle: este proceso vive semanas y MySQL cierra
    las conexiones ociosas mucho antes de eso."""
    return create_engine(database_url, pool_pre_ping=True, pool_recycle=3600,
                         pool_size=2, max_overflow=2, future=True)


def create_app(
    database_url: str = None,
    smtp_host: str = None,
    smtp_port: int = None,
    cifrado: str = None,
    remitente: str = None,
    dashboard_url: str = None,
    intentos: int = None,
    espera_inicial_s: float = None,
    api_key: str = None,
    ajustes: Ajustes = None,
    motor=None,
    enviador=None,
    dormir=None,
) -> FastAPI:
    """Construye una instancia del servicio.

    `enviador` y `dormir` se pueden inyectar: es lo que permite comprobar los
    reintentos sin esperarlos de verdad. El envio de verdad se prueba aparte,
    contra un servidor SMTP real levantado en las pruebas.
    """
    ajustes = ajustes or cargar_ajustes(
        database_url=database_url, smtp_host=smtp_host, smtp_port=smtp_port,
        cifrado=cifrado, remitente=remitente, dashboard_url=dashboard_url,
        intentos=intentos, espera_inicial_s=espera_inicial_s)
    _configurar_logging(ajustes.log_level)
    log = structlog.get_logger("quinor.notificaciones.api")

    motor = motor if motor is not None else (
        crear_motor(ajustes.database_url) if ajustes.database_url else None)

    # Este servicio vive en la red interna del apartado 8 y solo lo llama el
    # grabador. La clave evita que cualquier cosa de esa red pueda mandar
    # correos a nombre de la empresa.
    clave = api_key if api_key is not None else _api_key_del_entorno()

    @contextlib.asynccontextmanager
    async def ciclo_de_vida(app_: FastAPI):
        if not ajustes.configurado:
            log.error("sin_servidor_de_correo",
                      detalle=("Falta SMTP_HOST o SMTP_FROM. El servicio "
                               "arranca y responde 503 hasta que existan."))
        if motor is None:
            log.error("sin_base_de_datos",
                      detalle=("Falta DATABASE_URL. Sin ella no se sabe a quien "
                               "avisar ni queda constancia del aviso."))
        if ajustes.viaja_en_claro:
            log.warning("correo_sin_cifrar",
                        detalle=("SMTP_SECURITY esta en 'ninguno' con "
                                 "APP_ENV de produccion: el correo y las "
                                 "credenciales viajan en claro."))
        yield

    app = FastAPI(
        title="QUINOR - Servicio de notificaciones",
        description="Avisa por correo del evento segun su severidad (HU-10). "
                    "La severidad decide destinatarios y urgencia; el correo "
                    "lleva orden, diferencia y enlace al evento.",
        version="1.0.0",
        lifespan=ciclo_de_vida,
    )
    app.state.ajustes = ajustes
    app.state.motor = motor

    def requiere_clave(entregada: str = Security(api_key_header)) -> None:
        if not clave:
            return
        if not entregada or not _secrets.compare_digest(entregada, clave):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                                detail="Clave de servicio invalida")

    def motor_o_503():
        if motor is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="El servicio no tiene base de datos configurada "
                       "(DATABASE_URL).")
        return motor

    @app.get("/", tags=["servicio"])
    def info():
        """Lo unico publico: healthcheck del compose, sin enviar nada."""
        return {
            "servicio": "Servicio de notificaciones de QUINOR",
            "version": app.version,
            "historia": "HU-10 alerta por correo segun severidad",
            "documentacion": "/docs",
        }

    @app.get("/salud", response_model=RespuestaDeSalud, tags=["servicio"],
             dependencies=[Depends(requiere_clave)])
    def salud() -> RespuestaDeSalud:
        """Un servicio de alertas que no puede alertar tiene que decirlo antes
        del primer evento, no con el camion en la rampa."""
        base_viva = False
        destinatarios_alta = 0
        if motor is not None:
            try:
                with motor.connect() as conexion:
                    conexion.execute(text("SELECT 1"))
                base_viva = True
                destinatarios_alta = len(
                    registro.reparto_de(motor, ALTA).destinatarios)
            except Exception as exc:      # noqa: BLE001
                log.error("base_inalcanzable", error=str(exc))

        avisos = []
        if not ajustes.configurado:
            avisos.append("Falta SMTP_HOST o SMTP_FROM: no se puede enviar.")
        if not base_viva:
            avisos.append("Sin base de datos: no se sabe a quien avisar.")
        elif destinatarios_alta == 0:
            # Es el fallo silencioso que mas duele: todo responde 200 y nadie
            # recibe nada porque no hay un supervisor activo dado de alta.
            avisos.append("No hay ningun usuario activo que reciba alertas "
                          "Altas: los avisos se registran pero no salen.")
        if ajustes.viaja_en_claro:
            avisos.append("El correo viaja sin cifrar.")

        listo = ajustes.configurado and base_viva
        return RespuestaDeSalud(
            estado=("ok" if listo and not avisos else
                    ("degradado" if listo else "error")),
            servidor=f"{ajustes.smtp_host}:{ajustes.smtp_port}",
            remitente=ajustes.remitente,
            cifrado=ajustes.cifrado,
            configurado=ajustes.configurado,
            base_de_datos=base_viva,
            destinatarios_alta=destinatarios_alta,
            intentos=ajustes.intentos,
            mensaje=" ".join(avisos) or None,
        )

    @app.post("/notificaciones", response_model=RespuestaDeAviso,
              tags=["alertas"], dependencies=[Depends(requiere_clave)],
              summary="Avisa por correo de un evento (HU-10)")
    async def notificar(cuerpo: PeticionDeAviso) -> RespuestaDeAviso:
        """Los tres criterios, en este orden: a quien, que dice, y cuanto tardo."""
        base = motor_o_503()

        try:
            contexto = registro.contexto_del_evento(base, cuerpo.evento_id)
        except registro.EventoDesconocido as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                detail=str(exc)) from exc

        enlace = ajustes.enlace_del_evento(cuerpo.evento_id)

        # Sondear significa que el mismo evento pasa por aqui en cada vuelta del
        # grabador. Sin esto, el supervisor recibiria un correo por vuelta.
        if not cuerpo.forzar and registro.ya_avisado(base, cuerpo.evento_id):
            log.info("ya_avisado", evento_id=cuerpo.evento_id)
            return RespuestaDeAviso(
                evento_id=cuerpo.evento_id, enviado=False, duplicado=True,
                severidad=contexto.severidad, enlace=enlace,
                error="Este evento ya tenia un aviso enviado.")

        # --- Criterio 1 -------------------------------------------------
        reparto = registro.reparto_de(base, contexto.severidad)
        # Si el evento no trae severidad, el correo se manda igual y como Alta:
        # un evento sin clasificar es justo el que conviene mirar.
        contexto = (contexto if contexto.severidad
                    else _con_severidad(contexto, reparto.severidad))

        # --- Criterio 2 -------------------------------------------------
        mensaje = plantilla.componer(contexto, enlace)

        # --- Criterio 3 -------------------------------------------------
        try:
            resultado = await envio.enviar(ajustes, mensaje, reparto,
                                           cuerpo.evento_id,
                                           enviador=enviador, dormir=dormir)
        except envio.SinConfigurar as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                                detail=str(exc)) from exc

        retraso = cuerpo.segundos_desde_analisis
        total = None if retraso is None else retraso + resultado.segundos

        notificacion_id = registro.registrar(
            base, cuerpo.evento_id, reparto, mensaje.asunto,
            enviado=resultado.enviado, intentos=resultado.intentos,
            error=resultado.error, segundos_desde_analisis=total)

        if resultado.enviado:
            log.info("aviso_enviado", evento_id=cuerpo.evento_id,
                     severidad=reparto.severidad,
                     destinatarios=len(reparto.destinatarios),
                     intentos=resultado.intentos,
                     segundos=round(resultado.segundos, 2))
            if total is not None and total > SEGUNDOS_DEL_CRITERIO:
                # No se oculta: el criterio 3 se mide con lo que pasa de verdad,
                # y un aviso tardio hay que verlo antes de que sea costumbre.
                log.warning("aviso_tardio", evento_id=cuerpo.evento_id,
                            segundos=round(total, 2),
                            limite=SEGUNDOS_DEL_CRITERIO)
        else:
            log.error("aviso_no_enviado", evento_id=cuerpo.evento_id,
                      severidad=reparto.severidad, error=resultado.error,
                      intentos=resultado.intentos)

        return RespuestaDeAviso(
            evento_id=cuerpo.evento_id,
            enviado=resultado.enviado,
            duplicado=(notificacion_id is None),
            severidad=reparto.severidad,
            destinatarios=list(reparto.destinatarios),
            roles=list(reparto.roles),
            urgente=reparto.urgente,
            asunto=mensaje.asunto,
            enlace=enlace,
            intentos=resultado.intentos,
            segundos_de_envio=round(resultado.segundos, 3),
            segundos_desde_analisis=(None if total is None else round(total, 2)),
            dentro_del_criterio=(None if total is None
                                 else total <= SEGUNDOS_DEL_CRITERIO),
            notificacion_id=notificacion_id,
            error=resultado.error,
            rechazados=list(resultado.rechazados),
        )

    return app


def _con_severidad(contexto: plantilla.Contexto, severidad: str):
    import dataclasses

    return dataclasses.replace(contexto, severidad=severidad)


def _api_key_del_entorno() -> str:
    import os

    return os.environ.get("NOTIFY_SERVICE_API_KEY", "")


if __name__ == "__main__":      # pragma: no cover
    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=8004)
