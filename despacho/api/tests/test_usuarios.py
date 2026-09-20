"""Tests del caso de uso de HU-15 contra MySQL real: usuarios, roles y tokens."""

import datetime as dt

import pytest
from sqlalchemy import select, text

from app import seguridad, usuarios
from app.config import Ajustes
from app.models import ApiToken, Auditoria, Usuario
from tests.conftest import ADMIN_CLAVE, ADMIN_CORREO, URL_PRUEBAS


@pytest.fixture()
def ajustes() -> Ajustes:
    return Ajustes(database_url=URL_PRUEBAS, admin_email=ADMIN_CORREO,
                   admin_password=ADMIN_CLAVE, token_ttl_hours=12.0)


@pytest.fixture()
def admin(sesion, ajustes) -> Usuario:
    return usuarios.asegurar_administrador(sesion, ajustes)


# ---------- Criterio 1: crear, desactivar y asignar roles ----------

def test_crear_usuario_con_su_rol(sesion, admin):
    usuario = usuarios.crear(sesion, "Ana Quispe", "ana@quinor.local",
                             "supervisor", "clave-de-ana-123", actor_id=admin.id)
    assert usuario.id is not None
    assert usuario.rol == "supervisor"
    assert usuario.activo is True


def test_el_correo_se_normaliza(sesion, admin):
    usuario = usuarios.crear(sesion, "  Ana  ", "  Ana@QUINOR.local ",
                             "consulta", "clave-de-ana-123")
    assert usuario.correo == "ana@quinor.local"
    assert usuario.nombre == "Ana"
    assert usuarios.buscar_por_correo(sesion, "ANA@quinor.local").id == usuario.id


def test_no_se_repite_el_correo(sesion, admin):
    usuarios.crear(sesion, "Ana", "ana@quinor.local", "consulta", "clave-de-ana-123")
    with pytest.raises(usuarios.CorreoYaRegistrado):
        usuarios.crear(sesion, "Otra Ana", "ana@quinor.local", "supervisor", "otra-clave-123")


@pytest.mark.parametrize("rol", ["root", "Administrador", "", "admin"])
def test_un_rol_inventado_se_rechaza(sesion, admin, rol):
    """Solo existen los tres de la seccion 4, y el ENUM del esquema dice lo mismo."""
    with pytest.raises(usuarios.RolInvalido):
        usuarios.crear(sesion, "X", "x@quinor.local", rol, "clave-cualquiera-123")


def test_asignar_otro_rol(sesion, admin):
    usuario = usuarios.crear(sesion, "Ana", "ana@quinor.local", "consulta", "clave-de-ana-123")
    cambiado = usuarios.cambiar_rol(sesion, usuario.id, "supervisor", admin.id)
    assert cambiado.rol == "supervisor"
    fila = sesion.scalars(select(Auditoria).where(Auditoria.accion == "cambiar_rol")).one()
    assert fila.detalle == {"correo": "ana@quinor.local", "de": "consulta", "a": "supervisor"}


def test_cambiar_a_un_rol_inventado_se_rechaza(sesion, admin):
    with pytest.raises(usuarios.RolInvalido):
        usuarios.cambiar_rol(sesion, admin.id, "root", admin.id)


def test_desactivar_y_reactivar(sesion, admin):
    usuario = usuarios.crear(sesion, "Ana", "ana@quinor.local", "supervisor", "clave-de-ana-123")
    assert usuarios.cambiar_activacion(sesion, usuario.id, False, admin.id).activo is False
    assert usuarios.cambiar_activacion(sesion, usuario.id, True, admin.id).activo is True


def test_desactivar_revoca_los_tokens_del_usuario(sesion, admin):
    """Dejar vivo el token de una cuenta cerrada seria cerrarla solo de nombre."""
    usuario = usuarios.crear(sesion, "Ana", "ana@quinor.local", "supervisor", "clave-de-ana-123")
    claro, _ = usuarios.emitir_token(sesion, usuario, "laptop", ttl_horas=12)
    assert usuarios.resolver_token(sesion, claro) is not None

    usuarios.cambiar_activacion(sesion, usuario.id, False, admin.id)

    assert usuarios.resolver_token(sesion, claro) is None
    fila = sesion.scalars(
        select(Auditoria).where(Auditoria.accion == "desactivar_usuario")).one()
    assert fila.detalle["tokens_revocados"] == 1


def test_un_usuario_desconocido_no_se_puede_modificar(sesion, admin):
    for operacion in (
        lambda: usuarios.cambiar_rol(sesion, 9999, "consulta", admin.id),
        lambda: usuarios.cambiar_activacion(sesion, 9999, False, admin.id),
        lambda: usuarios.cambiar_password(sesion, 9999, "clave-nueva-123", admin.id),
        lambda: usuarios.obtener(sesion, 9999),
    ):
        with pytest.raises(usuarios.UsuarioNoEncontrado):
            operacion()


def test_listar_puede_excluir_inactivos(sesion, admin):
    usuario = usuarios.crear(sesion, "Ana", "ana@quinor.local", "consulta", "clave-de-ana-123")
    usuarios.cambiar_activacion(sesion, usuario.id, False, admin.id)
    assert len(usuarios.listar(sesion)) == 2
    assert [u.correo for u in usuarios.listar(sesion, incluir_inactivos=False)] == [ADMIN_CORREO]


# ---------- Criterio 3: la contrasena no se guarda en claro ----------

def test_en_la_base_solo_hay_hash(sesion, admin):
    usuarios.crear(sesion, "Ana", "ana@quinor.local", "consulta", "clave-de-ana-123")
    guardado = sesion.execute(
        text("SELECT hash_password FROM usuario WHERE correo = 'ana@quinor.local'")
    ).scalar_one()
    assert guardado.startswith("$2b$")
    assert "clave-de-ana-123" not in guardado


def test_cambiar_la_contrasena_invalida_la_anterior(sesion, admin):
    usuario = usuarios.crear(sesion, "Ana", "ana@quinor.local", "consulta", "clave-de-ana-123")
    usuarios.cambiar_password(sesion, usuario.id, "clave-nueva-de-ana-456", admin.id)

    with pytest.raises(usuarios.CredencialesInvalidas):
        usuarios.autenticar(sesion, "ana@quinor.local", "clave-de-ana-123")
    assert usuarios.autenticar(sesion, "ana@quinor.local", "clave-nueva-de-ana-456").id == usuario.id


# ---------- Autenticacion ----------

def test_autenticar_con_credenciales_correctas(sesion, admin):
    assert usuarios.autenticar(sesion, ADMIN_CORREO, ADMIN_CLAVE).id == admin.id


@pytest.mark.parametrize(
    "correo, clave",
    [
        (ADMIN_CORREO, "clave-equivocada"),
        ("nadie@quinor.local", ADMIN_CLAVE),
        ("nadie@quinor.local", "clave-equivocada"),
    ],
)
def test_el_mensaje_no_distingue_que_fallo(sesion, admin, correo, clave):
    """Decir 'ese correo no existe' regala al atacante la mitad del trabajo."""
    with pytest.raises(usuarios.CredencialesInvalidas) as exc:
        usuarios.autenticar(sesion, correo, clave)
    assert str(exc.value) == "Correo o contrasena incorrectos"


def test_una_cuenta_desactivada_no_entra(sesion, admin):
    usuario = usuarios.crear(sesion, "Ana", "ana@quinor.local", "consulta", "clave-de-ana-123")
    usuarios.cambiar_activacion(sesion, usuario.id, False, admin.id)
    with pytest.raises(usuarios.CredencialesInvalidas):
        usuarios.autenticar(sesion, "ana@quinor.local", "clave-de-ana-123")


# ---------- Criterio 4: token opaco en api_token ----------

def test_el_token_en_claro_no_se_guarda(sesion, admin):
    claro, token = usuarios.emitir_token(sesion, admin, "laptop", ttl_horas=12)
    guardado = sesion.execute(
        text("SELECT token_hash FROM api_token WHERE id = :i"), {"i": token.id}
    ).scalar_one()
    assert guardado == seguridad.hash_token(claro)
    assert claro not in guardado
    # Y no aparece en ninguna otra columna de la fila.
    fila = sesion.execute(text("SELECT * FROM api_token WHERE id = :i"), {"i": token.id}
                          ).mappings().one()
    assert claro not in str(dict(fila))


def test_el_token_resuelve_al_usuario(sesion, admin):
    claro, _ = usuarios.emitir_token(sesion, admin, "laptop", ttl_horas=12)
    assert usuarios.resolver_token(sesion, claro).id == admin.id


def test_usar_el_token_deja_marca_del_ultimo_uso(sesion, admin):
    claro, token = usuarios.emitir_token(sesion, admin, "laptop", ttl_horas=12)
    assert token.ultimo_uso_en is None
    usuarios.resolver_token(sesion, claro)
    sesion.refresh(token)
    assert token.ultimo_uso_en is not None


@pytest.mark.parametrize("claro", ["", "no-es-un-token", "x" * 43])
def test_un_token_desconocido_no_resuelve(sesion, admin, claro):
    assert usuarios.resolver_token(sesion, claro) is None


def test_un_token_revocado_deja_de_servir_de_inmediato(sesion, admin):
    """Cada peticion consulta la fila, asi que no hay ventana de gracia."""
    claro, token = usuarios.emitir_token(sesion, admin, "laptop", ttl_horas=12)
    usuarios.revocar_token(sesion, token.id, admin.id)
    assert usuarios.resolver_token(sesion, claro) is None


def test_revocar_dos_veces_no_cambia_quien_ni_cuando(sesion, admin):
    claro, token = usuarios.emitir_token(sesion, admin, "laptop", ttl_horas=12)
    primero = usuarios.revocar_token(sesion, token.id, admin.id)
    momento = primero.revocado_en
    segundo = usuarios.revocar_token(sesion, token.id, admin.id)
    assert segundo.revocado_en == momento
    assert len(sesion.scalars(
        select(Auditoria).where(Auditoria.accion == "revocar_token")).all()) == 1


def test_un_token_vencido_no_sirve(sesion, admin):
    """El esquema exige expira_en > creado_en, asi que se retrasan ambas fechas:
    un token vencido es uno emitido hace tiempo, no uno que caduca antes de nacer."""
    claro, token = usuarios.emitir_token(sesion, admin, "laptop", ttl_horas=12)
    ayer = dt.datetime.now() - dt.timedelta(days=1)
    sesion.execute(
        text("UPDATE api_token SET creado_en = :c, expira_en = :e WHERE id = :i"),
        {"c": ayer, "e": ayer + dt.timedelta(hours=12), "i": token.id},
    )
    sesion.commit()
    sesion.expunge_all()      # la peticion real llega con la sesion limpia
    assert usuarios.resolver_token(sesion, claro) is None


def test_revocar_un_token_inexistente(sesion, admin):
    with pytest.raises(usuarios.TokenNoEncontrado):
        usuarios.revocar_token(sesion, 9999, admin.id)


def test_el_vencimiento_sale_del_ttl(sesion, admin):
    _, token = usuarios.emitir_token(sesion, admin, "laptop", ttl_horas=3)
    horas = (token.expira_en - token.creado_en).total_seconds() / 3600
    assert 2.99 < horas < 3.01


def test_listar_tokens_es_por_usuario(sesion, admin):
    otra = usuarios.crear(sesion, "Ana", "ana@quinor.local", "consulta", "clave-de-ana-123")
    usuarios.emitir_token(sesion, admin, "del admin", ttl_horas=12)
    usuarios.emitir_token(sesion, otra, "de ana", ttl_horas=12)
    assert [t.nombre for t in usuarios.listar_tokens(sesion, otra.id)] == ["de ana"]


def test_la_emision_y_la_revocacion_quedan_en_auditoria(sesion, admin):
    _, token = usuarios.emitir_token(sesion, admin, "laptop de rampa", ttl_horas=12)
    usuarios.revocar_token(sesion, token.id, admin.id)
    acciones = [f.accion for f in sesion.scalars(
        select(Auditoria).where(Auditoria.entidad == "api_token")
        .order_by(Auditoria.id)).all()]
    assert acciones == ["emitir_token", "revocar_token"]


def test_un_token_sin_nombre_recibe_uno(sesion, admin):
    _, token = usuarios.emitir_token(sesion, admin, "   ", ttl_horas=12)
    assert token.nombre == "token"


def test_obtener_token(sesion, admin):
    _, token = usuarios.emitir_token(sesion, admin, "laptop", ttl_horas=12)
    assert usuarios.obtener_token(sesion, token.id).id == token.id
    with pytest.raises(usuarios.TokenNoEncontrado):
        usuarios.obtener_token(sesion, 9999)


def test_un_token_de_cuenta_borrada_no_resuelve(sesion, admin):
    """Defensa en profundidad: el esquema impide borrar usuarios, pero si la
    fila desapareciera por otra via, el token no debe seguir valiendo."""
    usuario = usuarios.crear(sesion, "Ana", "ana@quinor.local", "consulta", "clave-de-ana-123")
    claro, _ = usuarios.emitir_token(sesion, usuario, "laptop", ttl_horas=12)
    sesion.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    sesion.execute(text("DELETE FROM usuario WHERE id = :i"), {"i": usuario.id})
    sesion.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    sesion.commit()
    # La fila ya no esta, pero seguiria en el mapa de identidad de esta sesion.
    # Una peticion real llega con la sesion limpia, que es lo que se simula aqui.
    sesion.expunge_all()
    assert usuarios.resolver_token(sesion, claro) is None


# ---------- Administrador inicial ----------

def test_el_administrador_inicial_se_crea_una_sola_vez(sesion, ajustes):
    primero = usuarios.asegurar_administrador(sesion, ajustes)
    segundo = usuarios.asegurar_administrador(sesion, ajustes)
    assert primero.id == segundo.id
    assert primero.rol == "administrador"
    assert sesion.execute(text("SELECT COUNT(*) FROM usuario")).scalar_one() == 1


def test_no_se_pisa_la_clave_de_un_administrador_existente(sesion, ajustes):
    """Una variable de entorno filtrada no debe ser una llave permanente."""
    usuarios.asegurar_administrador(sesion, ajustes)
    usuario = usuarios.buscar_por_correo(sesion, ADMIN_CORREO)
    usuarios.cambiar_password(sesion, usuario.id, "la-que-puso-el-cliente-999")

    usuarios.asegurar_administrador(sesion, ajustes)

    assert usuarios.autenticar(sesion, ADMIN_CORREO, "la-que-puso-el-cliente-999")
    with pytest.raises(usuarios.CredencialesInvalidas):
        usuarios.autenticar(sesion, ADMIN_CORREO, ADMIN_CLAVE)


def test_sin_clave_configurada_no_se_crea_nada(sesion):
    sin_clave = Ajustes(database_url=URL_PRUEBAS, admin_password="")
    assert usuarios.asegurar_administrador(sesion, sin_clave) is None
    assert sesion.scalars(select(Usuario)).all() == []


# ---------- Roles en el modelo ----------

@pytest.mark.parametrize(
    "rol, escribe, es_admin",
    [
        ("administrador", True, True),
        ("supervisor", True, False),
        ("consulta", False, False),
    ],
)
def test_los_permisos_del_rol(sesion, admin, rol, escribe, es_admin):
    usuario = usuarios.crear(sesion, "X", f"{rol}@quinor.local", rol, "clave-cualquiera-123")
    assert usuario.puede_escribir() is escribe
    assert usuario.es_administrador() is es_admin


def test_una_cuenta_desactivada_no_escribe_aunque_sea_administradora(sesion, admin):
    usuarios.cambiar_activacion(sesion, admin.id, False, admin.id)
    sesion.refresh(admin)
    assert admin.puede_escribir() is False
    assert admin.es_administrador() is False


def test_un_token_vigente_lo_dice(sesion, admin):
    _, token = usuarios.emitir_token(sesion, admin, "laptop", ttl_horas=12)
    ahora = dt.datetime.now()
    assert token.vigente(ahora) is True
    assert token.vigente(token.expira_en + dt.timedelta(seconds=1)) is False
    assert isinstance(token, ApiToken)
