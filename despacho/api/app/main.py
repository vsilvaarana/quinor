"""API REST del orquestador de despacho de QUINOR S.A.C.

Registro automatico de pesadas de bascula (HU-01), consulta de ordenes al ERP
(HU-02), evento de discrepancia (HU-03), tolerancias por producto (HU-04) y
gestion de usuarios, roles y tokens de acceso (HU-15), sobre MySQL 8.

Autenticacion por token opaco en el header X-API-Key. El token se emite en
POST /auth/login, vive en la tabla api_token y se revoca desde el dashboard.

Estado del Sprint 1:
    HU-01  Lectura de la bascula y registro de la pesada   IMPLEMENTADA
    HU-02  Consulta de la orden al ERP                     IMPLEMENTADA
    HU-15  Usuarios, roles y token de API                  IMPLEMENTADA
    HU-04  Configuracion de tolerancias por producto       IMPLEMENTADA
    HU-03  Evento de discrepancia (Sprint 2)               IMPLEMENTADA
    HU-06  Marca de inicio de carga (Sprint 2)             IMPLEMENTADA aqui;
           el recorte del clip vive en quinor/despacho/grabador
    HU-17  Cola de tareas                                  PENDING, depende de HU-03

La aplicacion se construye con create_app, que recibe su configuracion por
parametro y cae al entorno solo cuando no se le pasa nada. Ningun modulo guarda
estado global: el motor, la fabrica de sesiones y los ajustes viven en app.state.
"""
from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from decimal import ROUND_HALF_UP, Decimal

import structlog
from fastapi import Depends, FastAPI, HTTPException, Query, Security, status
from fastapi.security.api_key import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import cargas as servicio_cargas
from app import configuracion as servicio_configuracion
from app import eventos as servicio_eventos
from app import ordenes as servicio_ordenes
from app import pesadas as servicio_pesadas
from app import salud as servicio_salud
from app import seguridad
from app import usuarios as servicio_usuarios
from app.config import Ajustes, cargar_ajustes
from app.db import crear_fabrica_de_sesiones, crear_motor
from app.models import Usuario
from app.schemas import (AbrirCarga, AvisoDelEvento, CambiarActivacion,
                         CambiarClave, CambiarRol,
                         CambioDeTolerancia, CargaLeida,
                         CapturarPesada, Credenciales, CrearUsuario, EditarTolerancia,
                         EventoLeido, NotificacionLeida, OrdenLeida,
                         PersonaEnZonaLeida,
                         PesadaLeida, PesadaRegistrada, PresenciaLeida,
                         RespuestaSalud, SolicitarToken,
                         ToleranciaAplicada, ToleranciaLeida, TokenEmitido, TokenLeido,
                         UsuarioLeido)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

SIN_PERMISO = "Tu rol no permite esta operacion"

# Criterio 3 de HU-10: "La notificacion se envia en menos de 60 s tras el
# analisis". Aqui solo se usa para decir si aquel aviso lo cumplio; el limite
# de verdad vive en el servicio de notificaciones, que es quien lo mide.
SEGUNDOS_DEL_AVISO = 60.0


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


def create_app(
    database_url: str = None,
    admin_email: str = None,
    admin_password: str = None,
    token_ttl_hours: float = None,
    scale_host: str = None,
    scale_port: int = None,
    scale_timeout_seconds: float = None,
    bascula_id: str = None,
    erp_base_url: str = None,
    ajustes: Ajustes = None,
) -> FastAPI:
    """Construye una instancia de la aplicacion.

    Cada parametro gana al entorno. Es lo que permite a una prueba levantar la
    API contra otra base de datos y otra bascula sin tocar variables del proceso.
    """
    ajustes = ajustes or cargar_ajustes(
        database_url=database_url,
        admin_email=admin_email,
        admin_password=admin_password,
        token_ttl_hours=token_ttl_hours,
        scale_host=scale_host,
        scale_port=scale_port,
        scale_timeout_seconds=scale_timeout_seconds,
        bascula_id=bascula_id,
        erp_base_url=erp_base_url,
    )
    _configurar_logging(ajustes.log_level)
    log = structlog.get_logger("quinor.api")
    if ajustes.clave_por_defecto_en_uso:
        log.warning("clave_por_defecto_en_uso",
                    detalle="ADMIN_PASSWORD sin configurar. Cambiarla antes de salir de desarrollo.")

    motor = crear_motor(ajustes.database_url)
    fabrica = crear_fabrica_de_sesiones(motor)

    @contextlib.asynccontextmanager
    async def ciclo_de_vida(_app: FastAPI):
        # Una instalacion nueva no tendria por donde entrar sin un administrador.
        # Como el bloque genesis del ejemplo blockchain, se crea al arrancar y
        # solo si falta: nunca pisa el que ya exista.
        with fabrica() as sesion:
            servicio_usuarios.asegurar_administrador(sesion, ajustes)
        yield

    app = FastAPI(
        title="QUINOR - Orquestador Alternativa 1",
        description="Deteccion de sustraccion de quinua en despacho. Sprint 1: "
                    "HU-01, HU-02, HU-04 y HU-15. Sprint 2: HU-03.",
        version="1.2.0",
        lifespan=ciclo_de_vida,
    )
    app.state.ajustes = ajustes
    app.state.motor = motor
    app.state.fabrica = fabrica
    app.state.cerrar = motor.dispose

    def obtener_sesion() -> Iterator[Session]:
        sesion = app.state.fabrica()
        try:
            yield sesion
        finally:
            sesion.close()

    # ------------------------------------------------------- autenticacion
    def requiere_usuario(
        entregado: str = Security(api_key_header),
        sesion: Session = Depends(obtener_sesion),
    ) -> Usuario:
        """Resuelve el token contra api_token. HU-15, criterio 4.

        No hay clave estatica: un token desconocido, revocado, vencido o de una
        cuenta desactivada no pasa de aqui. Como cada peticion consulta la fila,
        la revocacion surte efecto de inmediato.
        """
        usuario = servicio_usuarios.resolver_token(sesion, entregado or "")
        if usuario is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                                detail="Token invalido, revocado o vencido")
        return usuario

    def requiere_escritura(usuario: Usuario = Depends(requiere_usuario)) -> Usuario:
        """Criterio 2: el rol Consulta no cambia estados ni configuraciones."""
        if not usuario.puede_escribir():
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=SIN_PERMISO)
        return usuario

    def requiere_administrador(usuario: Usuario = Depends(requiere_usuario)) -> Usuario:
        if not usuario.es_administrador():
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=SIN_PERMISO)
        return usuario

    autenticado = [Depends(requiere_usuario)]
    admin = [Depends(requiere_administrador)]

    # -------------------------------------------------- GET / (sin autenticacion)
    @app.get("/", tags=["servicio"])
    def info():
        """Lo unico publico: sirve de healthcheck sin exponer el estado interno."""
        return {
            "servicio": "Orquestador de despacho QUINOR",
            "version": app.version,
            "historias": ("HU-01 pesadas, HU-02 ordenes del ERP, "
                          "HU-03 eventos, HU-04 tolerancias, "
                          "HU-15 usuarios y tokens"),
            "autenticacion": "header X-API-Key con el token de POST /auth/login",
            "documentacion": "/docs",
        }

    # ------------------------------------------------------- HU-15 autenticacion
    @app.post("/auth/login", response_model=TokenEmitido, tags=["autenticacion"],
              summary="Valida credenciales y emite un token de acceso (HU-15)")
    def login(cuerpo: Credenciales, sesion: Session = Depends(obtener_sesion)) -> TokenEmitido:
        try:
            usuario = servicio_usuarios.autenticar(sesion, cuerpo.correo, cuerpo.clave)
        except servicio_usuarios.CredencialesInvalidas as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
        claro, token = servicio_usuarios.emitir_token(
            sesion, usuario, nombre="login", ttl_horas=ajustes.token_ttl_hours)
        return TokenEmitido(token=claro, detalle=TokenLeido.model_validate(token),
                            usuario=UsuarioLeido.model_validate(usuario))

    @app.get("/auth/yo", response_model=UsuarioLeido, tags=["autenticacion"],
             summary="Quien soy segun el token")
    def quien_soy(usuario: Usuario = Depends(requiere_usuario)) -> UsuarioLeido:
        return UsuarioLeido.model_validate(usuario)

    @app.post("/auth/tokens", response_model=TokenEmitido, status_code=201,
              tags=["autenticacion"],
              summary="Crea un token con nombre y vencimiento. Se muestra una sola vez")
    def crear_token(
        cuerpo: SolicitarToken,
        usuario: Usuario = Depends(requiere_usuario),
        sesion: Session = Depends(obtener_sesion),
    ) -> TokenEmitido:
        claro, token = servicio_usuarios.emitir_token(
            sesion, usuario, nombre=cuerpo.nombre,
            ttl_horas=cuerpo.ttl_horas or ajustes.token_ttl_hours)
        return TokenEmitido(token=claro, detalle=TokenLeido.model_validate(token),
                            usuario=UsuarioLeido.model_validate(usuario))

    @app.get("/auth/tokens", response_model=list[TokenLeido], tags=["autenticacion"],
             summary="Lista los tokens propios")
    def listar_tokens(
        usuario: Usuario = Depends(requiere_usuario),
        sesion: Session = Depends(obtener_sesion),
    ) -> list[TokenLeido]:
        return servicio_usuarios.listar_tokens(sesion, usuario.id)

    @app.delete("/auth/tokens/{token_id}", response_model=TokenLeido,
                tags=["autenticacion"],
                summary="Revoca un token y registra la accion en auditoria")
    def revocar_token(
        token_id: int,
        usuario: Usuario = Depends(requiere_usuario),
        sesion: Session = Depends(obtener_sesion),
    ) -> TokenLeido:
        try:
            token = servicio_usuarios.obtener_token(sesion, token_id)
        except servicio_usuarios.TokenNoEncontrado as exc:
            raise HTTPException(404, str(exc)) from exc
        # Cada cual revoca lo suyo; el administrador revoca cualquier cosa.
        if token.usuario_id != usuario.id and not usuario.es_administrador():
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=SIN_PERMISO)
        return servicio_usuarios.revocar_token(sesion, token_id, usuario.id)

    # ------------------------------------------------------- HU-15 usuarios
    @app.get("/usuarios", response_model=list[UsuarioLeido], dependencies=admin,
             tags=["usuarios"], summary="Lista los usuarios del sistema")
    def listar_usuarios(
        incluir_inactivos: bool = Query(default=True),
        sesion: Session = Depends(obtener_sesion),
    ) -> list[UsuarioLeido]:
        return servicio_usuarios.listar(sesion, incluir_inactivos)

    @app.post("/usuarios", response_model=UsuarioLeido, status_code=201,
              tags=["usuarios"], summary="Crea un usuario con su rol (HU-15)")
    def crear_usuario(
        cuerpo: CrearUsuario,
        actor: Usuario = Depends(requiere_administrador),
        sesion: Session = Depends(obtener_sesion),
    ) -> UsuarioLeido:
        try:
            return servicio_usuarios.crear(
                sesion, cuerpo.nombre, cuerpo.correo, cuerpo.rol, cuerpo.clave,
                actor_id=actor.id)
        except servicio_usuarios.CorreoYaRegistrado as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        except seguridad.ClaveDemasiadoLarga as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.patch("/usuarios/{usuario_id}/rol", response_model=UsuarioLeido,
               tags=["usuarios"], summary="Asigna otro rol a un usuario")
    def cambiar_rol(
        usuario_id: int,
        cuerpo: CambiarRol,
        actor: Usuario = Depends(requiere_administrador),
        sesion: Session = Depends(obtener_sesion),
    ) -> UsuarioLeido:
        try:
            return servicio_usuarios.cambiar_rol(sesion, usuario_id, cuerpo.rol, actor.id)
        except servicio_usuarios.UsuarioNoEncontrado as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.patch("/usuarios/{usuario_id}/activacion", response_model=UsuarioLeido,
               tags=["usuarios"],
               summary="Desactiva o reactiva un usuario y revoca sus tokens")
    def cambiar_activacion(
        usuario_id: int,
        cuerpo: CambiarActivacion,
        actor: Usuario = Depends(requiere_administrador),
        sesion: Session = Depends(obtener_sesion),
    ) -> UsuarioLeido:
        if usuario_id == actor.id and not cuerpo.activo:
            # Un administrador que se desactiva a si mismo deja el sistema sin
            # nadie que pueda revertirlo.
            raise HTTPException(status.HTTP_409_CONFLICT,
                                detail="No puedes desactivar tu propia cuenta")
        try:
            return servicio_usuarios.cambiar_activacion(
                sesion, usuario_id, cuerpo.activo, actor.id)
        except servicio_usuarios.UsuarioNoEncontrado as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.patch("/usuarios/{usuario_id}/clave", response_model=UsuarioLeido,
               tags=["usuarios"], summary="Cambia la contrasena de un usuario")
    def cambiar_clave(
        usuario_id: int,
        cuerpo: CambiarClave,
        actor: Usuario = Depends(requiere_administrador),
        sesion: Session = Depends(obtener_sesion),
    ) -> UsuarioLeido:
        try:
            return servicio_usuarios.cambiar_password(sesion, usuario_id, cuerpo.clave, actor.id)
        except servicio_usuarios.UsuarioNoEncontrado as exc:
            raise HTTPException(404, str(exc)) from exc
        except seguridad.ClaveDemasiadoLarga as exc:
            raise HTTPException(422, str(exc)) from exc

    # ------------------------------------------------------------ HU-01 pesadas
    @app.post("/pesadas", response_model=PesadaRegistrada, status_code=201,
              tags=["pesadas"],
              summary="Registra la pesada al cerrar una carga (HU-01)")
    async def crear_pesada(
        cuerpo: CapturarPesada,
        actor: Usuario = Depends(requiere_escritura),
        sesion: Session = Depends(obtener_sesion),
    ) -> PesadaRegistrada:
        try:
            pesada = await servicio_pesadas.registrar_pesada(
                sesion,
                ajustes,
                numero_orden=cuerpo.numero_orden,
                bascula_id=cuerpo.bascula_id,
                peso_manual=cuerpo.peso_real_kg,
                motivo_manual=cuerpo.motivo_manual,
                usuario_id=actor.id,
            )
        except servicio_ordenes.OrdenNoDisponible as exc:
            # Criterio 2 de HU-02: se muestra el mensaje y no se registra nada.
            raise HTTPException(404, str(exc)) from exc
        except servicio_pesadas.BasculaNoResponde as exc:
            # 503: el sistema esta bien, el equipo de planta no responde. El
            # fallo ya quedo registrado y se ve en GET /salud.
            raise HTTPException(503, str(exc)) from exc
        except servicio_pesadas.PesoNoEstable as exc:
            raise HTTPException(409, str(exc)) from exc
        # HU-03: si la carga se salio de la tolerancia, el aviso viaja en la
        # misma respuesta. Esperar a que alguien mire el dashboard seria
        # repetir el problema que la historia intenta resolver.
        evento = servicio_eventos.buscar_por_pesada(sesion, pesada.id)
        return PesadaRegistrada(
            **_a_esquema(pesada, pesada.orden).model_dump(),
            evento=_evento_a_esquema(sesion, evento) if evento else None,
            evaluada=pesada.evaluada,
            motivo_sin_evaluar=pesada.motivo_sin_evaluar,
        )

    @app.get("/pesadas", response_model=list[PesadaLeida], dependencies=autenticado,
             tags=["pesadas"], summary="Lista las pesadas registradas")
    def listar_pesadas(
        numero_orden: str = Query(default=None, max_length=40),
        limite: int = Query(default=50, ge=1, le=500),
        sesion: Session = Depends(obtener_sesion),
    ) -> list[PesadaLeida]:
        return [
            _a_esquema(p, o)
            for p, o in servicio_pesadas.listar_pesadas(sesion, numero_orden, limite)
        ]

    # ------------------------------------------------------------ HU-02 ordenes
    @app.get("/ordenes/{numero_orden}", response_model=OrdenLeida,
             dependencies=autenticado, tags=["ordenes"],
             summary="Consulta la orden al ERP y actualiza la copia local (HU-02)")
    async def obtener_orden(
        numero_orden: str,
        refrescar: bool = Query(default=False,
                                description="Consulta al ERP aunque la copia local siga vigente."),
        sesion: Session = Depends(obtener_sesion),
    ) -> OrdenLeida:
        try:
            return await servicio_ordenes.obtener_orden(
                sesion, ajustes, numero_orden, refrescar=refrescar)
        except servicio_ordenes.OrdenNoDisponible as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/ordenes", response_model=list[OrdenLeida], dependencies=autenticado,
             tags=["ordenes"], summary="Lista la copia local de ordenes")
    def listar_ordenes(
        limite: int = Query(default=50, ge=1, le=500),
        sesion: Session = Depends(obtener_sesion),
    ) -> list[OrdenLeida]:
        return servicio_ordenes.listar_ordenes(sesion, limite)

    # ------------------------------------------------- HU-06 marca de carga
    @app.post("/cargas/{numero_orden}/inicio", response_model=CargaLeida,
              status_code=201, tags=["cargas"],
              summary="Marca el inicio de la carga de una orden (HU-06)")
    async def abrir_carga(
        numero_orden: str,
        cuerpo: AbrirCarga = AbrirCarga(),
        actor: Usuario = Depends(requiere_escritura),
        sesion: Session = Depends(obtener_sesion),
    ) -> CargaLeida:
        """Da origen a la ventana del clip.

        El apartado 5.2 dice que el sistema marca el inicio de la ventana de
        carga; esto es esa marca. Sin ella la pesada se registra igual, pero el
        clip de HU-06 solo cubre los 5 minutos previos al cierre.
        """
        try:
            orden = await servicio_ordenes.obtener_orden(
                sesion, ajustes, numero_orden, usuario_id=actor.id)
        except servicio_ordenes.OrdenNoDisponible as exc:
            raise HTTPException(404, str(exc)) from exc
        try:
            carga = servicio_cargas.abrir(
                sesion, orden, cuerpo.bascula_id or ajustes.bascula_id, actor.id)
        except servicio_cargas.CargaYaAbierta as exc:
            raise HTTPException(409, str(exc)) from exc
        return _carga_a_esquema(carga, orden)

    @app.get("/cargas", response_model=list[CargaLeida], dependencies=autenticado,
             tags=["cargas"], summary="Cargas marcadas, abiertas y cerradas")
    def listar_cargas(
        solo_abiertas: bool = Query(default=False),
        limite: int = Query(default=50, ge=1, le=500),
        sesion: Session = Depends(obtener_sesion),
    ) -> list[CargaLeida]:
        return [_carga_a_esquema(c, c.orden)
                for c in servicio_cargas.listar(sesion, solo_abiertas, limite)]

    # ------------------------------------------------------ HU-03 eventos
    @app.get("/eventos", response_model=list[EventoLeido], dependencies=autenticado,
             tags=["eventos"],
             summary="Eventos de discrepancia registrados (HU-03)")
    def listar_eventos(
        estado: str = Query(default=None, max_length=30),
        numero_orden: str = Query(default=None, max_length=40),
        limite: int = Query(default=50, ge=1, le=500),
        sesion: Session = Depends(obtener_sesion),
    ) -> list[EventoLeido]:
        """Listado basico, del mas reciente al mas antiguo.

        La pantalla con filtros combinados y sus 2 s de respuesta es HU-11, que
        se construira sobre esto y sobre la vista v_evento_dashboard.
        """
        return [_evento_a_esquema(sesion, e)
                for e in servicio_eventos.listar(sesion, estado, numero_orden, limite)]

    @app.get("/eventos/{evento_id}", response_model=EventoLeido,
             dependencies=autenticado, tags=["eventos"],
             summary="Detalle de un evento de discrepancia")
    def obtener_evento(
        evento_id: int,
        sesion: Session = Depends(obtener_sesion),
    ) -> EventoLeido:
        evento = servicio_eventos.obtener(sesion, evento_id)
        if evento is None:
            raise HTTPException(404, detail=f"No existe el evento {evento_id}")
        return _evento_a_esquema(sesion, evento)

    @app.get("/eventos/{evento_id}/personas", response_model=PresenciaLeida,
             dependencies=autenticado, tags=["eventos"],
             summary="Personas que estuvieron en la zona de carga (HU-08)")
    def personas_del_evento(
        evento_id: int,
        sesion: Session = Depends(obtener_sesion),
    ) -> PresenciaLeida:
        """Criterio 2 de HU-08: cuantas estuvieron en zona y cuanto tiempo.

        Va en su propia ruta y no dentro del evento porque una carga larga puede
        tener decenas de presencias, y la lista de eventos de HU-11 tiene 2 s
        para responder: arrastrar esa lista en cada fila la haria pesada para
        quien solo quiere ver las diferencias de peso.
        """
        evento = servicio_eventos.obtener(sesion, evento_id)
        if evento is None:
            raise HTTPException(404, detail=f"No existe el evento {evento_id}")

        personas = list(evento.personas)
        return PresenciaLeida(
            evento_id=evento.id,
            cuantas=len(personas),
            segundos_totales=sum((p.segundos_en_zona for p in personas),
                                 Decimal("0.00")),
            permanencia_maxima_s=max((p.segundos_en_zona for p in personas),
                                     default=Decimal("0.00")),
            personal_anomalo=evento.personal_anomalo,
            personas=[PersonaEnZonaLeida(
                id_temporal=p.id_temporal,
                segundos_en_zona=p.segundos_en_zona,
                primer_fotograma=p.primer_fotograma,
                ultimo_fotograma=p.ultimo_fotograma) for p in personas],
        )

    @app.get("/eventos/{evento_id}/avisos", response_model=AvisoDelEvento,
             dependencies=autenticado, tags=["eventos"],
             summary="Avisos enviados por un evento (HU-10)")
    def avisos_del_evento(
        evento_id: int,
        sesion: Session = Depends(obtener_sesion),
    ) -> AvisoDelEvento:
        """Responde a "se aviso de esto", que es la pregunta que se hace cuando
        el cliente reclama meses despues.

        Va en su propia ruta por lo mismo que las personas de HU-08: la lista de
        eventos de HU-11 tiene 2 s para responder, y arrastrar los avisos en
        cada fila la haria pesada para quien solo quiere ver las diferencias.
        """
        evento = servicio_eventos.obtener(sesion, evento_id)
        if evento is None:
            raise HTTPException(404, detail=f"No existe el evento {evento_id}")

        avisos = list(evento.notificaciones)
        return AvisoDelEvento(
            evento_id=evento.id,
            # Un aviso fallido no cuenta como avisado: nadie lo recibio.
            avisado=any(a.estado == "enviada" for a in avisos),
            severidad=evento.severidad,
            notificaciones=[NotificacionLeida(
                id=a.id, canal=a.canal, severidad=a.severidad,
                destinatarios=list(a.destinatarios or []), asunto=a.asunto,
                estado=a.estado, intentos=a.intentos, error=a.error,
                segundos_desde_analisis=a.segundos_desde_analisis,
                dentro_del_criterio=(
                    None if a.segundos_desde_analisis is None
                    else float(a.segundos_desde_analisis) <= SEGUNDOS_DEL_AVISO),
                enviada_en=a.enviada_en, creado_en=a.creado_en)
                for a in avisos],
        )

    @app.post("/pesadas/{pesada_id}/evaluar", response_model=EventoLeido | None,
              tags=["eventos"],
              summary="Vuelve a evaluar una pesada ya registrada (HU-03)")
    def reevaluar_pesada(
        pesada_id: int,
        _actor: Usuario = Depends(requiere_escritura),
        sesion: Session = Depends(obtener_sesion),
    ) -> EventoLeido | None:
        """Rescata las pesadas que quedaron sin evaluar.

        Es el camino de vuelta cuando faltaba la tolerancia del producto: se
        configura y se recupera la pesada sin volver a pesar el camion. La clave
        unica sobre la pesada hace que repetirlo no duplique el evento.
        """
        try:
            evento = servicio_eventos.reevaluar(sesion, pesada_id)
        except servicio_eventos.PesadaNoEncontrada as exc:
            raise HTTPException(404, str(exc)) from exc
        except servicio_eventos.SinToleranciaConfigurada as exc:
            # 409: no es un error del que pide, es una configuracion que falta.
            raise HTTPException(409, str(exc)) from exc
        return _evento_a_esquema(sesion, evento) if evento else None

    # ------------------------------------------------------ HU-04 tolerancias
    @app.get("/configuracion", response_model=list[ToleranciaLeida],
             dependencies=autenticado, tags=["configuracion"],
             summary="Tolerancias configuradas por producto (HU-04)")
    def listar_configuracion(
        sesion: Session = Depends(obtener_sesion),
    ) -> list[ToleranciaLeida]:
        """Leerla no exige ser administrador: editarla si.

        El supervisor necesita saber contra que umbral se esta midiendo su rampa
        aunque no pueda moverlo.
        """
        return [_tolerancia_a_esquema(f) for f in servicio_configuracion.listar(sesion)]

    @app.get("/configuracion/{producto}", response_model=ToleranciaLeida,
             dependencies=autenticado, tags=["configuracion"],
             summary="Tolerancia de un producto")
    def obtener_configuracion(
        producto: str,
        sesion: Session = Depends(obtener_sesion),
    ) -> ToleranciaLeida:
        try:
            return _tolerancia_a_esquema(servicio_configuracion.obtener(sesion, producto))
        except servicio_configuracion.ProductoNoConfigurado as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/configuracion/{producto}/aplicada", response_model=ToleranciaAplicada,
             dependencies=autenticado, tags=["configuracion"],
             summary="Cual de las dos tolerancias manda para un peso dado (RN-01)")
    def calcular_tolerancia(
        producto: str,
        peso_esperado_kg: Decimal = Query(gt=0, le=999999.99),
        sesion: Session = Depends(obtener_sesion),
    ) -> ToleranciaAplicada:
        """Traduce la configuracion a kg concretos para una orden.

        Sin esto, ajustar un porcentaje es trabajar a ciegas: nadie calcula de
        cabeza si el 0,5 % de 20 000 kg queda por encima o por debajo de los 50 kg
        configurados.
        """
        try:
            fila = servicio_configuracion.obtener(sesion, producto)
        except servicio_configuracion.ProductoNoConfigurado as exc:
            raise HTTPException(404, str(exc)) from exc
        del_pct = (peso_esperado_kg * fila.tolerancia_pct / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
        efectiva = fila.tolerancia_efectiva_kg(peso_esperado_kg)
        return ToleranciaAplicada(
            producto=fila.producto,
            peso_esperado_kg=peso_esperado_kg,
            tolerancia_kg=fila.tolerancia_kg,
            tolerancia_pct=fila.tolerancia_pct,
            equivalente_del_pct_kg=del_pct,
            tolerancia_efectiva_kg=efectiva,
            manda="porcentaje" if del_pct < fila.tolerancia_kg else "kg",
        )

    @app.patch("/configuracion/{producto}", response_model=ToleranciaLeida,
               tags=["configuracion"],
               summary="Edita la tolerancia de un producto. Solo Administrador (HU-04)")
    def editar_configuracion(
        producto: str,
        cuerpo: EditarTolerancia,
        actor: Usuario = Depends(requiere_administrador),   # criterio 2
        sesion: Session = Depends(obtener_sesion),
    ) -> ToleranciaLeida:
        if cuerpo.tolerancia_kg is None and cuerpo.tolerancia_pct is None:
            raise HTTPException(
                422, detail="Indica al menos tolerancia_kg o tolerancia_pct")
        try:
            fila = servicio_configuracion.actualizar(
                sesion, producto, cuerpo.tolerancia_kg, cuerpo.tolerancia_pct, actor.id)
        except servicio_configuracion.ProductoNoConfigurado as exc:
            raise HTTPException(404, str(exc)) from exc
        except servicio_configuracion.ToleranciaInvalida as exc:
            raise HTTPException(422, str(exc)) from exc
        return _tolerancia_a_esquema(fila)

    @app.get("/configuracion/{producto}/historial",
             response_model=list[CambioDeTolerancia], dependencies=autenticado,
             tags=["configuracion"],
             summary="Cambios de tolerancia con usuario y fecha (HU-04, criterio 3)")
    def historial_de_configuracion(
        producto: str,
        limite: int = Query(default=50, ge=1, le=500),
        sesion: Session = Depends(obtener_sesion),
    ) -> list[CambioDeTolerancia]:
        try:
            servicio_configuracion.obtener(sesion, producto)
        except servicio_configuracion.ProductoNoConfigurado as exc:
            raise HTTPException(404, str(exc)) from exc
        cambios = servicio_configuracion.historial(sesion, producto, limite)
        nombres = servicio_configuracion.nombres_de(
            sesion, {c.usuario_id for c in cambios})
        return [CambioDeTolerancia(
            id=c.id, fecha=c.fecha, usuario_id=c.usuario_id,
            usuario_nombre=nombres.get(c.usuario_id), detalle=c.detalle)
            for c in cambios]

    # ---------------------------------------------------------------- salud
    @app.get("/salud", response_model=RespuestaSalud, dependencies=autenticado,
             tags=["salud"], summary="Estado de los componentes")
    async def obtener_salud(sesion: Session = Depends(obtener_sesion)) -> RespuestaSalud:
        """Sondea los componentes, registra los cambios y devuelve el resultado.

        Requiere autenticacion porque expone version de motor y detalle de
        fallos internos. Para comprobar que el servicio esta en pie basta GET /.
        """
        return RespuestaSalud(**await servicio_salud.sondear_todo(sesion, ajustes))

    @app.get("/salud/historial", dependencies=autenticado, tags=["salud"],
             summary="Cambios de estado registrados en salud_componente")
    def obtener_historial(
        componente: str = Query(default=None, max_length=60),
        limite: int = Query(default=50, ge=1, le=500),
        sesion: Session = Depends(obtener_sesion),
    ) -> list[dict]:
        return servicio_salud.historial(sesion, componente, limite)

    return app


def _carga_a_esquema(carga, orden) -> CargaLeida:
    """La duracion solo existe cuando la carga ya se cerro con su pesada."""
    duracion = None
    if carga.consumida_en is not None:
        duracion = round((carga.consumida_en - carga.inicio).total_seconds(), 1)
    return CargaLeida(
        id=carga.id,
        numero_orden=orden.numero_orden,
        bascula_id=carga.bascula_id,
        inicio=carga.inicio,
        consumida_en=carga.consumida_en,
        pesada_id=carga.pesada_id,
        duracion_s=duracion,
    )


def _a_fecha(valor):
    """Las marcas viajan como texto ISO dentro del detalle JSON de auditoria."""
    import datetime as _dt

    try:
        return _dt.datetime.fromisoformat(valor) if valor else None
    except (TypeError, ValueError):
        return None


def _evento_a_esquema(sesion: Session, evento) -> EventoLeido:
    """Junta el evento con su pesada y su orden. HU-03, criterio 2.

    La tolerancia aplicada se recupera de la auditoria del momento en que se
    creo el evento, no de la configuracion actual: si alguien la cambia manana,
    el evento tiene que seguir diciendo contra que umbral se juzgo aquella carga.
    """
    from app.models import Auditoria, OrdenDespacho, Pesada

    pesada = sesion.get(Pesada, evento.pesada_id)
    orden = sesion.get(OrdenDespacho, pesada.orden_id)
    registro = sesion.scalars(
        select(Auditoria)
        .where(Auditoria.entidad == "evento", Auditoria.entidad_id == evento.id,
               Auditoria.accion == "crear_evento")
    ).first()
    detalle = (registro.detalle or {}) if registro else {}
    tolerancia = detalle.get("tolerancia_aplicada_kg")

    # HU-06: la ventana es la que el grabador recorto de verdad, no una cuenta
    # repetida aqui. Las dos copias de "5 y 2 minutos" acabarian discrepando.
    recorte = sesion.scalars(
        select(Auditoria)
        .where(Auditoria.entidad == "evento", Auditoria.entidad_id == evento.id,
               Auditoria.accion.in_(("recortar_clip", "evento_sin_clip")))
        .order_by(Auditoria.id.desc())
    ).first()
    ventana = (recorte.detalle or {}) if recorte else {}

    return EventoLeido(
        id=evento.id,
        estado=evento.estado,
        creado_en=evento.creado_en,
        numero_orden=orden.numero_orden,
        cliente=orden.cliente,
        producto=orden.producto,
        peso_esperado_kg=orden.peso_esperado_kg,
        peso_real_kg=pesada.peso_real_kg,
        diferencia_kg=evento.diferencia_kg,
        diferencia_pct=evento.diferencia_pct,
        tolerancia_aplicada_kg=Decimal(tolerancia) if tolerancia is not None else None,
        pesada_id=pesada.id,
        bascula_id=pesada.bascula_id,
        pesada_fecha_hora=pesada.fecha_hora,
        inicio_carga=pesada.inicio_carga,
        clip_desde=_a_fecha(ventana.get("desde")),
        clip_hasta=_a_fecha(ventana.get("hasta")),
        sacos_contados=evento.sacos_contados,
        sacos_esperados=orden.sacos_esperados,
        diferencia_sacos=evento.diferencia_sacos,
        personas_detectadas=evento.personas_detectadas,
        personal_anomalo=evento.personal_anomalo,
        severidad=evento.severidad,
        descripcion_ia=evento.descripcion_ia,
        fotogramas_clave=list(evento.fotogramas_clave or []),
        clip_url=evento.clip_url,
    )


def _tolerancia_a_esquema(fila) -> ToleranciaLeida:
    """Anade el nombre de quien hizo el ultimo cambio. Criterio 3 de HU-04.

    Un numero de usuario en la pantalla no le dice nada a nadie; el nombre si.
    """
    return ToleranciaLeida(
        id=fila.id,
        producto=fila.producto,
        tolerancia_kg=fila.tolerancia_kg,
        tolerancia_pct=fila.tolerancia_pct,
        canales_por_severidad=fila.canales_por_severidad,
        actualizado_por=fila.actualizado_por,
        actualizado_por_nombre=fila.autor.nombre if fila.autor else None,
        fecha=fila.fecha,
    )


def _a_esquema(pesada, orden) -> PesadaLeida:
    return PesadaLeida(
        id=pesada.id,
        numero_orden=orden.numero_orden,
        cliente=orden.cliente,
        producto=orden.producto,
        bascula_id=pesada.bascula_id,
        peso_real_kg=pesada.peso_real_kg,
        peso_esperado_kg=orden.peso_esperado_kg,
        fecha_hora=pesada.fecha_hora,
        origen=pesada.origen,
    )


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=8000)
