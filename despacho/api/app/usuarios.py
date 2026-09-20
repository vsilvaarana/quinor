"""Caso de uso de HU-15: usuarios, roles y tokens de acceso.

Como administrador del sistema, quiero gestionar usuarios y roles
(Administrador, Supervisor, Consulta), para que cada persona solo acceda a lo
que le corresponde.

Criterios de aceptacion:
  1. Se pueden crear, desactivar y asignar roles a usuarios.
  2. El rol Consulta no puede cambiar estados ni configuraciones.
  3. Las contrasenas se almacenan con hash bcrypt.
  4. La autenticacion de la API usa token opaco almacenado en la tabla
     api_token, revocable desde el dashboard.

Los usuarios no se borran, se desactivan: la auditoria tiene que seguir
apuntando a una persona identificable, y el esquema lo impone con ON DELETE
RESTRICT.
"""
from __future__ import annotations

import datetime as dt

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auditoria, seguridad
from app.config import Ajustes
from app.models import ROLES, ApiToken, Usuario

log = structlog.get_logger("quinor.usuarios")


class CorreoYaRegistrado(ValueError):
    """Dos personas no pueden compartir identificador de acceso."""


class RolInvalido(ValueError):
    """Solo existen los tres roles de la seccion 4."""


class UsuarioNoEncontrado(LookupError):
    pass


class CredencialesInvalidas(PermissionError):
    """Correo desconocido, contrasena incorrecta o cuenta desactivada."""


class TokenNoEncontrado(LookupError):
    pass


def _ahora() -> dt.datetime:
    return dt.datetime.now().replace(tzinfo=None)


def buscar_por_correo(sesion: Session, correo: str) -> Usuario | None:
    return sesion.scalars(
        select(Usuario).where(Usuario.correo == correo.strip().lower())
    ).first()


def obtener(sesion: Session, usuario_id: int) -> Usuario:
    usuario = sesion.get(Usuario, usuario_id)
    if usuario is None:
        raise UsuarioNoEncontrado(f"No existe el usuario {usuario_id}")
    return usuario


def listar(sesion: Session, incluir_inactivos: bool = True) -> list[Usuario]:
    consulta = select(Usuario).order_by(Usuario.nombre)
    if not incluir_inactivos:
        consulta = consulta.where(Usuario.activo.is_(True))
    return list(sesion.scalars(consulta).all())


# ------------------------------------------------------------ criterio 1 y 3
def crear(
    sesion: Session,
    nombre: str,
    correo: str,
    rol: str,
    clave: str,
    actor_id: int | None = None,
) -> Usuario:
    correo = correo.strip().lower()
    if rol not in ROLES:
        raise RolInvalido(f"Rol '{rol}' desconocido. Los validos son: {', '.join(ROLES)}")
    if buscar_por_correo(sesion, correo) is not None:
        raise CorreoYaRegistrado(f"Ya hay un usuario con el correo {correo}")

    usuario = Usuario(
        nombre=nombre.strip(),
        correo=correo,
        rol=rol,
        hash_password=seguridad.hash_password(clave),   # criterio 3
        activo=True,
    )
    sesion.add(usuario)
    sesion.flush()
    auditoria.registrar(
        sesion, entidad="usuario", entidad_id=usuario.id, accion="crear_usuario",
        usuario_id=actor_id, detalle={"correo": correo, "rol": rol},
    )
    sesion.commit()
    sesion.refresh(usuario)
    log.info("usuario_creado", usuario=correo, rol=rol)
    return usuario


def cambiar_rol(sesion: Session, usuario_id: int, rol: str, actor_id: int | None = None) -> Usuario:
    if rol not in ROLES:
        raise RolInvalido(f"Rol '{rol}' desconocido. Los validos son: {', '.join(ROLES)}")
    usuario = obtener(sesion, usuario_id)
    anterior, usuario.rol = usuario.rol, rol
    auditoria.registrar(
        sesion, entidad="usuario", entidad_id=usuario.id, accion="cambiar_rol",
        usuario_id=actor_id, detalle={"correo": usuario.correo, "de": anterior, "a": rol},
    )
    sesion.commit()
    sesion.refresh(usuario)
    log.info("rol_cambiado", usuario=usuario.correo, de=anterior, a=rol)
    return usuario


def cambiar_activacion(
    sesion: Session, usuario_id: int, activo: bool, actor_id: int | None = None
) -> Usuario:
    """Desactiva o reactiva. Nunca borra: la auditoria debe seguir apuntando aqui.

    Al desactivar se revocan sus tokens: dejar vivo el token de una cuenta cerrada
    seria desactivarla solo de nombre.
    """
    usuario = obtener(sesion, usuario_id)
    usuario.activo = activo
    revocados = 0
    if not activo:
        revocados = revocar_tokens_de(sesion, usuario_id, actor_id)
    auditoria.registrar(
        sesion, entidad="usuario", entidad_id=usuario.id,
        accion="activar_usuario" if activo else "desactivar_usuario",
        usuario_id=actor_id,
        detalle={"correo": usuario.correo, "tokens_revocados": revocados},
    )
    sesion.commit()
    sesion.refresh(usuario)
    log.info("activacion_cambiada", usuario=usuario.correo, activo=activo,
             tokens_revocados=revocados)
    return usuario


def cambiar_password(
    sesion: Session, usuario_id: int, clave: str, actor_id: int | None = None
) -> Usuario:
    usuario = obtener(sesion, usuario_id)
    usuario.hash_password = seguridad.hash_password(clave)
    auditoria.registrar(
        sesion, entidad="usuario", entidad_id=usuario.id, accion="cambiar_password",
        usuario_id=actor_id, detalle={"correo": usuario.correo},
    )
    sesion.commit()
    sesion.refresh(usuario)
    return usuario


# ---------------------------------------------------------------- criterio 4
def autenticar(sesion: Session, correo: str, clave: str) -> Usuario:
    """Valida credenciales. El mensaje de error no distingue que fallo.

    Decir 'ese correo no existe' le regala al atacante la mitad del trabajo.
    """
    usuario = buscar_por_correo(sesion, correo)
    if usuario is None or not usuario.activo:
        # Se verifica igualmente contra un hash de descarte para que el tiempo
        # de respuesta no delate si el correo existe.
        seguridad.verificar_password(clave, seguridad.hash_password("descarte"))
        raise CredencialesInvalidas("Correo o contrasena incorrectos")
    if not seguridad.verificar_password(clave, usuario.hash_password):
        raise CredencialesInvalidas("Correo o contrasena incorrectos")
    return usuario


def emitir_token(
    sesion: Session,
    usuario: Usuario,
    nombre: str,
    ttl_horas: float,
    actor_id: int | None = None,
) -> tuple[str, ApiToken]:
    """Emite un token. El valor en claro se devuelve una sola vez y no se guarda."""
    claro, hash_guardado = seguridad.generar_token()
    ahora = _ahora()
    token = ApiToken(
        usuario_id=usuario.id,
        token_hash=hash_guardado,
        nombre=nombre.strip() or "token",
        creado_en=ahora,
        expira_en=ahora + dt.timedelta(hours=ttl_horas),
    )
    sesion.add(token)
    sesion.flush()
    auditoria.registrar(
        sesion, entidad="api_token", entidad_id=token.id, accion="emitir_token",
        usuario_id=actor_id if actor_id is not None else usuario.id,
        detalle={"correo": usuario.correo, "nombre": token.nombre,
                 "expira_en": token.expira_en.isoformat()},
    )
    sesion.commit()
    sesion.refresh(token)
    log.info("token_emitido", usuario=usuario.correo, token_id=token.id)
    return claro, token


def resolver_token(sesion: Session, claro: str) -> Usuario | None:
    """Devuelve el usuario del token, o None si no sirve.

    No sirve un token desconocido, revocado, vencido, o de una cuenta
    desactivada. Como cada peticion pasa por aqui, la revocacion es inmediata.
    """
    if not claro:
        return None
    token = sesion.scalars(
        select(ApiToken).where(ApiToken.token_hash == seguridad.hash_token(claro))
    ).first()
    if token is None:
        return None
    ahora = _ahora()
    if not token.vigente(ahora):
        return None
    usuario = sesion.get(Usuario, token.usuario_id)
    if usuario is None or not usuario.activo:
        return None
    token.ultimo_uso_en = ahora
    sesion.commit()
    return usuario


def obtener_token(sesion: Session, token_id: int) -> ApiToken:
    token = sesion.get(ApiToken, token_id)
    if token is None:
        raise TokenNoEncontrado(f"No existe el token {token_id}")
    return token


def listar_tokens(sesion: Session, usuario_id: int) -> list[ApiToken]:
    return list(sesion.scalars(
        select(ApiToken).where(ApiToken.usuario_id == usuario_id)
        .order_by(ApiToken.id.desc())
    ).all())


def revocar_token(sesion: Session, token_id: int, actor_id: int) -> ApiToken:
    token = obtener_token(sesion, token_id)
    if token.revocado_en is None:
        token.revocado_en = _ahora()
        token.revocado_por = actor_id
        auditoria.registrar(
            sesion, entidad="api_token", entidad_id=token.id, accion="revocar_token",
            usuario_id=actor_id, detalle={"nombre": token.nombre},
        )
        sesion.commit()
        sesion.refresh(token)
        log.info("token_revocado", token_id=token.id, por=actor_id)
    return token


def revocar_tokens_de(sesion: Session, usuario_id: int, actor_id: int | None) -> int:
    """Revoca los tokens vigentes de un usuario. Devuelve cuantos."""
    ahora = _ahora()
    vigentes = [t for t in listar_tokens(sesion, usuario_id) if t.vigente(ahora)]
    for token in vigentes:
        token.revocado_en = ahora
        token.revocado_por = actor_id
    sesion.flush()
    return len(vigentes)


# ------------------------------------------------------------------ arranque
def asegurar_administrador(sesion: Session, ajustes: Ajustes) -> Usuario | None:
    """Crea el administrador inicial si no existe. No pisa el que ya este.

    Sin esto, una instalacion nueva no tendria por donde entrar. Y no sobrescribe
    la contrasena de un administrador existente: una variable de entorno filtrada
    no debe convertirse en una llave permanente.
    """
    if not ajustes.admin_password:
        log.warning("sin_administrador_inicial",
                    detalle="ADMIN_PASSWORD vacia. No se creo ningun usuario.")
        return None
    existente = buscar_por_correo(sesion, ajustes.admin_email)
    if existente is not None:
        return existente
    return crear(sesion, nombre="Administrador", correo=ajustes.admin_email,
                 rol="administrador", clave=ajustes.admin_password)
