"""Pruebas de HU-13: clasificar un evento.

Criterios de aceptacion:
  1. El cambio de estado exige un comentario de al menos 10 caracteres.
  2. Se registra el usuario y la fecha del cambio.
  3. Un evento Confirmado no puede volver al estado Pendiente.

El criterio 3 se comprueba en los tres sitios donde esta puesto, y a proposito.
`test_un_evento_confirmado_no_vuelve_a_revision` prueba la regla de la
aplicacion; `test_el_contrato_no_acepta_pendiente_como_destino` prueba que la API
no ofrece siquiera la vuelta atras; y
`test_el_motor_rechaza_el_reabrir_aunque_la_aplicacion_lo_permitiera` escribe por
debajo de la aplicacion para comprobar que el trigger del esquema sigue ahi. Una
regla que solo vive en el formulario se salta con una llamada directa, y esta es
la que decide si un faltante queda cerrado o no.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from tests.conftest import ContadorDeConsultas
from tests.test_detalle import anotar, sembrar

from app import veredictos
from app.detalle import armar
from app.veredictos import (CONFIRMADO, EN_REVISION, FALSO_POSITIVO,
                            ComentarioInsuficiente, EstadoDesconocido,
                            EventoNoEncontrado, TransicionProhibida, clasificar)

COMENTARIO = "Se verifico en almacen: faltaban 3 sacos del lote 148."
OTRO = "Era un error de tara de la bascula, el camion estaba completo."


def supervisor(sesion, correo: str = "jefe@quinor.local",
               nombre: str = "Rosa Quispe") -> object:
    """Un usuario real en la base: la clave ajena de veredicto lo exige."""
    from app.models import Usuario

    usuario = Usuario(nombre=nombre, correo=correo, rol="supervisor",
                      hash_password="no-se-usa-en-esta-prueba", activo=True)
    sesion.add(usuario)
    sesion.commit()
    sesion.refresh(usuario)
    return usuario


def estado_de(sesion, evento_id: int) -> str:
    from app.models import Evento

    sesion.expire_all()
    return sesion.get(Evento, evento_id).estado


# ------------------------------------------------------------------ criterio 1
def test_un_comentario_corto_no_clasifica(sesion):
    """Nueve caracteres no son diez. El evento se queda donde estaba."""
    evento = sembrar(sesion)
    with pytest.raises(ComentarioInsuficiente, match="al menos 10"):
        clasificar(sesion, evento, CONFIRMADO, "faltaban.", supervisor(sesion))
    assert estado_de(sesion, evento) == "pendiente"


def test_un_comentario_de_solo_espacios_no_clasifica(sesion):
    """Diez espacios cumplen la letra del criterio y ninguna de sus razones."""
    evento = sembrar(sesion)
    with pytest.raises(ComentarioInsuficiente):
        clasificar(sesion, evento, CONFIRMADO, " " * 12, supervisor(sesion))


def test_un_comentario_vacio_no_clasifica(sesion):
    evento = sembrar(sesion)
    for vacio in ("", None):
        with pytest.raises(ComentarioInsuficiente):
            clasificar(sesion, evento, CONFIRMADO, vacio, supervisor(
                sesion, correo=f"u{vacio!r}@quinor.local"))


def test_diez_caracteres_justos_bastan(sesion):
    evento = sembrar(sesion)
    hecho = clasificar(sesion, evento, CONFIRMADO, "faltan 3sc", supervisor(sesion))
    assert hecho.comentario == "faltan 3sc"


def test_el_comentario_se_guarda_recortado(sesion):
    evento = sembrar(sesion)
    hecho = clasificar(sesion, evento, CONFIRMADO, f"  {COMENTARIO}  ",
                       supervisor(sesion))
    assert hecho.comentario == COMENTARIO


def test_un_comentario_que_no_cabe_se_rechaza_en_vez_de_truncarse(sesion):
    """Un comentario cortado a la mitad dice algo distinto del que se escribio."""
    evento = sembrar(sesion)
    with pytest.raises(ComentarioInsuficiente, match="maximo es 1000"):
        clasificar(sesion, evento, CONFIRMADO, "x" * 1001, supervisor(sesion))


def test_mil_caracteres_justos_caben(sesion):
    evento = sembrar(sesion)
    hecho = clasificar(sesion, evento, CONFIRMADO, "x" * 1000, supervisor(sesion))
    assert len(hecho.comentario) == 1000


# ------------------------------------------------------------------ criterio 2
def test_se_registra_quien_clasifico_y_cuando(sesion):
    """Criterio 2. El nombre viaja en la respuesta: un id no dice nada a nadie."""
    evento = sembrar(sesion)
    antes = dt.datetime.now().replace(microsecond=0)

    quien = supervisor(sesion)
    hecho = clasificar(sesion, evento, CONFIRMADO, COMENTARIO, quien)

    assert hecho.usuario_id == quien.id
    assert hecho.usuario_nombre == "Rosa Quispe"
    assert hecho.fecha >= antes
    assert hecho.veredicto_id > 0


def test_el_veredicto_queda_en_su_tabla(sesion):
    from app.models import Veredicto

    evento = sembrar(sesion)
    quien = supervisor(sesion)
    clasificar(sesion, evento, FALSO_POSITIVO, OTRO, quien)

    fila = sesion.query(Veredicto).filter_by(evento_id=evento).one()
    assert (fila.estado_nuevo, fila.usuario_id, fila.comentario) == (
        FALSO_POSITIVO, quien.id, OTRO)


def test_la_clasificacion_queda_en_auditoria_con_el_estado_anterior(sesion):
    """La auditoria de HU-16 tiene que poder responder 'de donde venia esto'."""
    from app.models import Auditoria

    evento = sembrar(sesion, estado="pendiente_analisis")
    quien = supervisor(sesion)
    clasificar(sesion, evento, CONFIRMADO, COMENTARIO, quien)

    fila = sesion.query(Auditoria).filter_by(
        entidad="evento", entidad_id=evento, accion="clasificar_evento").one()
    assert fila.usuario_id == quien.id
    assert fila.detalle["estado_anterior"] == "pendiente_analisis"
    assert fila.detalle["estado_nuevo"] == CONFIRMADO
    assert fila.detalle["comentario"] == COMENTARIO
    assert fila.detalle["correccion"] is False


# --------------------------------------------------------- transiciones
@pytest.mark.parametrize("desde", ["pendiente", "pendiente_analisis", "sin_clip"])
@pytest.mark.parametrize("hasta", [EN_REVISION, CONFIRMADO, FALSO_POSITIVO])
def test_desde_un_estado_abierto_se_puede_ir_a_los_tres(sesion, desde, hasta):
    """El paso por En revision es opcional: se puede cerrar directamente.

    Un evento en Sin clip se clasifica igual que los demas, y es el caso que mas
    importa cerrar: hay una discrepancia real y ningun video que mirar, asi que
    el supervisor va al almacen y decide. Si la pantalla se lo impidiera, esos
    eventos se quedarian abiertos para siempre.
    """
    evento = sembrar(sesion, estado=desde)
    hecho = clasificar(sesion, evento, hasta, COMENTARIO,
                       supervisor(sesion, correo=f"{desde}-{hasta}@quinor.local"))

    assert hecho.estado_anterior == desde
    assert estado_de(sesion, evento) == hasta
    assert hecho.cerrado is (hasta in (CONFIRMADO, FALSO_POSITIVO))
    assert hecho.fue_correccion is False


@pytest.mark.parametrize("hasta", [CONFIRMADO, FALSO_POSITIVO])
def test_desde_en_revision_se_cierra(sesion, hasta):
    evento = sembrar(sesion, estado=EN_REVISION)
    hecho = clasificar(sesion, evento, hasta, COMENTARIO,
                       supervisor(sesion, correo=f"rev-{hasta}@quinor.local"))
    assert hecho.cerrado is True


def test_lo_que_ya_esta_en_revision_no_vuelve_a_revision(sesion):
    """No es un cambio de estado, asi que no es un veredicto.

    Anotar algo sin cambiar la decision es la HU-16, no esta.
    """
    evento = sembrar(sesion, estado=EN_REVISION)
    with pytest.raises(TransicionProhibida, match="ya esta en En revision"):
        clasificar(sesion, evento, EN_REVISION, COMENTARIO, supervisor(sesion))


def test_un_estado_final_no_se_repite(sesion):
    evento = sembrar(sesion, estado=CONFIRMADO)
    with pytest.raises(TransicionProhibida, match="ya esta en Confirmado"):
        clasificar(sesion, evento, CONFIRMADO, COMENTARIO, supervisor(sesion))


def test_un_estado_que_no_es_un_veredicto_se_rechaza(sesion):
    evento = sembrar(sesion)
    with pytest.raises(EstadoDesconocido, match="no es una clasificacion valida"):
        clasificar(sesion, evento, "pendiente", COMENTARIO, supervisor(sesion))


def test_el_comentario_se_valida_antes_que_el_estado(sesion):
    """Con las dos cosas mal, lo que se contesta es lo que el usuario escribio.

    Un mensaje sobre el estado destino no le sirve a quien ademas tiene que
    reescribir el comentario; al revés, si.
    """
    evento = sembrar(sesion)
    with pytest.raises(ComentarioInsuficiente):
        clasificar(sesion, evento, "pendiente", "corto", supervisor(sesion))


def test_un_evento_que_no_existe_no_se_clasifica(sesion):
    with pytest.raises(EventoNoEncontrado, match="999999"):
        clasificar(sesion, 999_999, CONFIRMADO, COMENTARIO, supervisor(sesion))


# ----------------------------------------------------------- correcciones
def test_un_confirmado_se_puede_corregir_a_falso_positivo(sesion):
    """Ocurre: el clip se vuelve a mirar con mas calma y la conclusion cambia."""
    evento = sembrar(sesion)
    quien = supervisor(sesion)
    clasificar(sesion, evento, CONFIRMADO, COMENTARIO, quien)

    hecho = clasificar(sesion, evento, FALSO_POSITIVO, OTRO, quien)
    assert hecho.estado_anterior == CONFIRMADO
    assert hecho.fue_correccion is True
    assert estado_de(sesion, evento) == FALSO_POSITIVO


def test_un_falso_positivo_se_puede_corregir_a_confirmado(sesion):
    evento = sembrar(sesion, estado=FALSO_POSITIVO)
    hecho = clasificar(sesion, evento, CONFIRMADO, COMENTARIO, supervisor(sesion))
    assert hecho.fue_correccion is True


def test_la_correccion_no_borra_la_decision_anterior(sesion):
    """Es la razon de que haya una tabla y no solo una columna."""
    evento = sembrar(sesion)
    quien = supervisor(sesion)
    clasificar(sesion, evento, CONFIRMADO, COMENTARIO, quien)
    clasificar(sesion, evento, FALSO_POSITIVO, OTRO, quien)

    historial = veredictos.historial(sesion, evento)
    assert [v.estado_nuevo for v in historial] == [CONFIRMADO, FALSO_POSITIVO]
    assert [v.comentario for v in historial] == [COMENTARIO, OTRO]


def test_la_correccion_se_marca_en_auditoria(sesion):
    from app.models import Auditoria

    evento = sembrar(sesion)
    quien = supervisor(sesion)
    clasificar(sesion, evento, CONFIRMADO, COMENTARIO, quien)
    clasificar(sesion, evento, FALSO_POSITIVO, OTRO, quien)

    filas = sesion.query(Auditoria).filter_by(
        accion="clasificar_evento", entidad_id=evento).order_by(Auditoria.id).all()
    assert [f.detalle["correccion"] for f in filas] == [False, True]


# ------------------------------------------------------------------ criterio 3
@pytest.mark.parametrize("final", [CONFIRMADO, FALSO_POSITIVO])
def test_un_evento_cerrado_no_vuelve_a_revision(sesion, final):
    """RN-06. Reabrir devolveria el evento a la bandeja como si nadie lo hubiera
    mirado, perdiendo la decision y el nombre de quien la tomo."""
    evento = sembrar(sesion, estado=final)
    with pytest.raises(TransicionProhibida, match="RN-06"):
        clasificar(sesion, evento, EN_REVISION, COMENTARIO,
                   supervisor(sesion, correo=f"reabrir-{final}@quinor.local"))
    assert estado_de(sesion, evento) == final


def test_el_motor_rechaza_el_reabrir_aunque_la_aplicacion_lo_permitiera(sesion):
    """Prueba el trigger trg_evento_no_reabrir, que es la ultima defensa.

    Se sabotean a proposito las dos listas del servicio para llegar a la base con
    un cambio que hoy el servicio no deja pasar. No es una prueba de un camino
    normal: es la prueba de que si alguien relaja la regla de la aplicacion, el
    motor sigue diciendo no y la pantalla recibe un 409 con la frase de la RN-06
    en vez de un 500 con SQL dentro.
    """
    evento = sembrar(sesion, estado=CONFIRMADO)
    quien = supervisor(sesion)

    original_veredictos = veredictos.VEREDICTOS
    original_transiciones = veredictos.TRANSICIONES
    veredictos.VEREDICTOS = (*original_veredictos, "pendiente")
    veredictos.TRANSICIONES = dict(original_transiciones,
                                   confirmado=("pendiente",))
    try:
        with pytest.raises(TransicionProhibida, match="RN-06"):
            clasificar(sesion, evento, "pendiente", COMENTARIO, quien)
    finally:
        veredictos.VEREDICTOS = original_veredictos
        veredictos.TRANSICIONES = original_transiciones

    assert estado_de(sesion, evento) == CONFIRMADO


def test_un_fallo_del_motor_que_no_es_la_regla_no_se_disfraza(sesion, monkeypatch):
    """Un error de base que no sea el SIGNAL de la regla sube tal cual.

    Convertirlo en un 409 diria al supervisor que su decision no estaba
    permitida, cuando lo que pasa es que la base esta rota.
    """
    from sqlalchemy.exc import DatabaseError

    evento = sembrar(sesion)
    quien = supervisor(sesion)

    def commit_roto():
        raise DatabaseError("INSERT", {}, Exception("tabla llena"))

    monkeypatch.setattr(sesion, "commit", commit_roto)
    monkeypatch.setattr(sesion, "rollback", lambda: None)
    with pytest.raises(DatabaseError):
        clasificar(sesion, evento, CONFIRMADO, COMENTARIO, quien)


def test_el_mensaje_del_motor_cae_a_una_frase_cuando_no_lo_trae(sesion):
    """El SIGNAL siempre trae texto, pero el traductor no puede quedarse mudo."""
    from sqlalchemy.exc import DatabaseError

    sin_texto = DatabaseError("UPDATE", {}, Exception())
    assert veredictos._mensaje_del_motor(sin_texto).startswith("El motor")


# ------------------------------------------------------- lo que la pantalla usa
def test_los_destinos_posibles_dependen_del_estado(sesion):
    assert veredictos.destinos_desde("pendiente") == veredictos.VEREDICTOS
    assert veredictos.destinos_desde(EN_REVISION) == veredictos.FINALES
    assert veredictos.destinos_desde(CONFIRMADO) == (FALSO_POSITIVO,)
    assert veredictos.destinos_desde(FALSO_POSITIVO) == (CONFIRMADO,)
    assert veredictos.destinos_desde("estado_inventado") == ()
    assert veredictos.destinos_desde(None) == ()


def test_todo_estado_del_esquema_se_puede_clasificar(sesion):
    """Ningun evento puede quedarse sin salida: la bandeja de HU-11 dejaria de
    servir para saber que falta por revisar."""
    from app.models import ESTADOS_DE_EVENTO

    for estado in ESTADOS_DE_EVENTO:
        assert veredictos.se_puede_clasificar(estado), estado


def test_un_estado_que_la_tabla_no_conoce_da_una_frase_util():
    """El mensaje general, que es el que queda si el ENUM del esquema crece y la
    tabla de transiciones se queda atras.

    No es un caso de hoy: los seis estados estan en la tabla y hay una prueba que
    lo comprueba. Es lo que la pantalla diria el dia que no lo esten, en vez de
    quedarse sin texto.
    """
    frase = veredictos._por_que_no("estado_futuro", CONFIRMADO)
    assert "estado_futuro" in frase and "Confirmado" in frase


def test_los_estados_se_escriben_para_una_persona():
    assert veredictos.nombre_de(FALSO_POSITIVO) == "Falso positivo"
    assert veredictos.nombre_de("pendiente_analisis") == "Pendiente de analisis"
    # Un estado que no este en la tabla se devuelve tal cual antes que vacio.
    assert veredictos.nombre_de("otro") == "otro"
    assert veredictos.nombre_de(None) == ""


def test_el_historial_se_lee_en_el_orden_en_que_se_decidio(sesion):
    evento = sembrar(sesion)
    quien = supervisor(sesion)
    clasificar(sesion, evento, EN_REVISION, "Abro revision del lote 148.", quien)
    clasificar(sesion, evento, CONFIRMADO, COMENTARIO, quien)
    clasificar(sesion, evento, FALSO_POSITIVO, OTRO, quien)

    assert [v.estado_nuevo for v in veredictos.historial(sesion, evento)] == [
        EN_REVISION, CONFIRMADO, FALSO_POSITIVO]


def test_el_historial_de_un_evento_sin_veredictos_esta_vacio(sesion):
    assert veredictos.historial(sesion, sembrar(sesion)) == []


def test_el_historial_respeta_el_limite(sesion):
    evento = sembrar(sesion)
    quien = supervisor(sesion)
    clasificar(sesion, evento, CONFIRMADO, COMENTARIO, quien)
    clasificar(sesion, evento, FALSO_POSITIVO, OTRO, quien)
    assert len(veredictos.historial(sesion, evento, limite=1)) == 1


# ----------------------------------------------- el veredicto en el detalle
def test_el_detalle_trae_la_decision_vigente_y_el_historial(sesion):
    """HU-13 se lee desde el detalle de HU-12, que es donde se decide."""
    evento = sembrar(sesion)
    quien = supervisor(sesion)
    clasificar(sesion, evento, EN_REVISION, "Abro revision del lote 148.", quien)
    clasificar(sesion, evento, CONFIRMADO, COMENTARIO, quien)

    detalle = armar(sesion, evento)
    assert detalle.estado == CONFIRMADO
    assert detalle.cerrado is True
    assert detalle.veredicto.estado == CONFIRMADO
    assert detalle.veredicto.comentario == COMENTARIO
    assert detalle.veredicto.usuario_nombre == "Rosa Quispe"
    assert [d.estado for d in detalle.decisiones] == [EN_REVISION, CONFIRMADO]
    assert detalle.clasificaciones_posibles == (FALSO_POSITIVO,)


def test_el_detalle_encadena_el_estado_anterior_de_cada_decision(sesion):
    evento = sembrar(sesion)
    quien = supervisor(sesion)
    clasificar(sesion, evento, EN_REVISION, "Abro revision del lote 148.", quien)
    clasificar(sesion, evento, CONFIRMADO, COMENTARIO, quien)
    clasificar(sesion, evento, FALSO_POSITIVO, OTRO, quien)

    primera, segunda, tercera = armar(sesion, evento).decisiones
    # La primera no sabe de donde venia: el estado de partida pudo ser Pendiente,
    # Pendiente de analisis o Sin clip, y nadie lo registro.
    assert primera.estado_anterior is None
    assert primera.es_correccion is False
    assert segunda.estado_anterior == EN_REVISION
    assert segunda.es_correccion is False
    assert tercera.estado_anterior == CONFIRMADO
    assert tercera.es_correccion is True


def test_un_evento_sin_clasificar_lo_dice_sin_fingir_una_decision(sesion):
    detalle = armar(sesion, sembrar(sesion))
    assert detalle.veredicto is None
    assert detalle.decisiones == ()
    assert detalle.cerrado is False
    assert detalle.se_puede_clasificar is True


def test_el_detalle_sigue_en_cuatro_consultas_con_muchas_decisiones(sesion, motor):
    """La invariante de HU-12, con la cuarta consulta que trajo HU-13.

    Si alguien lee el nombre del supervisor por fila, aqui se ve.
    """
    evento = sembrar(sesion)
    anotar(sesion, evento, "crear_evento", {"tolerancia_aplicada_kg": "100.00"})
    quien = supervisor(sesion)
    for i in range(10):
        destino = CONFIRMADO if i % 2 == 0 else FALSO_POSITIVO
        clasificar(sesion, evento, destino, f"Revision numero {i} del lote.", quien)

    with ContadorDeConsultas(motor) as contador:
        detalle = armar(sesion, evento)
    assert len(contador) == 4, contador.sentencias
    assert len(detalle.decisiones) == 10


def test_los_nombres_salen_de_cada_usuario_y_no_del_ultimo(sesion):
    """Dos supervisores en el mismo evento: cada decision lleva su nombre."""
    evento = sembrar(sesion)
    rosa = supervisor(sesion)
    luis = supervisor(sesion, correo="luis@quinor.local", nombre="Luis Mamani")
    clasificar(sesion, evento, EN_REVISION, "Abro revision del lote 148.", rosa)
    clasificar(sesion, evento, CONFIRMADO, COMENTARIO, luis)

    assert [d.usuario_nombre for d in armar(sesion, evento).decisiones] == [
        "Rosa Quispe", "Luis Mamani"]


# ------------------------------------------------------------------- por HTTP
def clasificar_por_http(cliente, evento_id: int, estado: str,
                        comentario: str = COMENTARIO):
    return cliente.post(f"/eventos/{evento_id}/veredicto",
                        json={"estado_nuevo": estado, "comentario": comentario})


def test_el_endpoint_clasifica_y_devuelve_la_decision(client_supervisor, sesion):
    evento = sembrar(sesion)
    respuesta = clasificar_por_http(client_supervisor, evento, CONFIRMADO)

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["estado_anterior"] == "pendiente"
    assert cuerpo["estado"] == CONFIRMADO
    assert cuerpo["cerrado"] is True
    assert cuerpo["fue_correccion"] is False
    # Criterio 2: el usuario sale del token, no del cuerpo de la peticion.
    assert cuerpo["veredicto"]["usuario_nombre"] == "Usuario supervisor"
    assert cuerpo["veredicto"]["comentario"] == COMENTARIO
    assert cuerpo["veredicto"]["fecha"]


def test_el_endpoint_no_acepta_un_usuario_enviado_por_el_cliente(client_supervisor,
                                                                 client, sesion):
    """Firmar en nombre de otro vaciaria de sentido el criterio 2."""
    evento = sembrar(sesion)
    respuesta = client_supervisor.post(
        f"/eventos/{evento}/veredicto",
        json={"estado_nuevo": CONFIRMADO, "comentario": COMENTARIO,
              "usuario_id": 1, "usuario_nombre": "Otro"})
    assert respuesta.status_code == 201
    assert respuesta.json()["veredicto"]["usuario_nombre"] == "Usuario supervisor"


def test_el_contrato_no_acepta_pendiente_como_destino(client_supervisor, sesion):
    """Criterio 3 en el contrato: la vuelta atras no se ofrece."""
    evento = sembrar(sesion, estado=CONFIRMADO)
    respuesta = clasificar_por_http(client_supervisor, evento, "pendiente")
    assert respuesta.status_code == 422
    assert "estado_nuevo" in respuesta.text


def test_el_endpoint_contesta_422_al_comentario_corto(client_supervisor, sesion):
    evento = sembrar(sesion)
    respuesta = clasificar_por_http(client_supervisor, evento, CONFIRMADO, "corto")
    assert respuesta.status_code == 422
    assert "al menos 10" in respuesta.text


def test_el_endpoint_contesta_422_al_comentario_que_no_cabe(client_supervisor, sesion):
    evento = sembrar(sesion)
    respuesta = clasificar_por_http(client_supervisor, evento, CONFIRMADO, "x" * 1001)
    assert respuesta.status_code == 422


def test_el_endpoint_contesta_409_a_una_transicion_prohibida(client_supervisor,
                                                             sesion):
    evento = sembrar(sesion, estado=CONFIRMADO)
    respuesta = clasificar_por_http(client_supervisor, evento, EN_REVISION)
    assert respuesta.status_code == 409
    assert "RN-06" in respuesta.json()["detail"]


def test_el_endpoint_contesta_404_si_el_evento_no_existe(client_supervisor):
    respuesta = clasificar_por_http(client_supervisor, 999_999, CONFIRMADO)
    assert respuesta.status_code == 404


def test_el_rol_consulta_no_clasifica(client_consulta, sesion):
    """Clasificar es cerrar un caso, y quien solo consulta no cierra casos."""
    evento = sembrar(sesion)
    respuesta = clasificar_por_http(client_consulta, evento, CONFIRMADO)
    assert respuesta.status_code == 403
    assert estado_de(sesion, evento) == "pendiente"


def test_sin_token_no_se_clasifica(app, sesion):
    from fastapi.testclient import TestClient

    evento = sembrar(sesion)
    with TestClient(app) as anonimo:
        respuesta = clasificar_por_http(anonimo, evento, CONFIRMADO)
    assert respuesta.status_code == 401


def test_el_detalle_por_http_trae_el_veredicto(client_supervisor, sesion):
    evento = sembrar(sesion)
    clasificar_por_http(client_supervisor, evento, EN_REVISION,
                        "Abro revision del lote 148.")
    clasificar_por_http(client_supervisor, evento, CONFIRMADO)

    detalle = client_supervisor.get(f"/eventos/{evento}/detalle").json()
    assert detalle["estado"] == CONFIRMADO
    assert detalle["cerrado"] is True
    assert detalle["clasificaciones_posibles"] == [FALSO_POSITIVO]
    assert detalle["veredicto"]["comentario"] == COMENTARIO
    assert len(detalle["decisiones"]) == 2
    assert detalle["decisiones"][1]["estado_anterior"] == EN_REVISION


def test_el_evento_clasificado_se_ve_en_la_bandeja_con_su_estado(client_supervisor,
                                                                 sesion):
    """La bandeja de HU-11 filtra por `evento.estado`: por eso la clasificacion
    tambien mueve la columna del evento y no solo escribe el veredicto."""
    evento = sembrar(sesion)
    clasificar_por_http(client_supervisor, evento, FALSO_POSITIVO, OTRO)

    # `desde` explicito porque la bandeja mira por defecto los ultimos 7 dias y
    # el evento sembrado es del 3 de octubre.
    bandeja = client_supervisor.get(
        "/eventos/bandeja",
        params={"estado": FALSO_POSITIVO, "desde": "2026-10-01"}).json()
    assert [f["id"] for f in bandeja["filas"]] == [evento]


def test_clasificar_un_evento_sin_clip_ni_analisis(client_supervisor, sesion):
    """El caso que mas importa cerrar: discrepancia real y ningun video."""
    evento = sembrar(sesion, estado="sin_clip", diferencia_kg=Decimal("-320.00"),
                     diferencia_pct=Decimal("-1.60"))
    respuesta = clasificar_por_http(
        client_supervisor, evento, CONFIRMADO,
        "Sin video. Se conto en almacen y faltaban 6 sacos del lote.")
    assert respuesta.status_code == 201
    assert respuesta.json()["estado"] == CONFIRMADO
