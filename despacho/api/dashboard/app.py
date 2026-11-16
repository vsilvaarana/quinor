"""Dashboard del supervisor - Sprint 1.

Cubre la parte de HU-01 a HU-07 y HU-15 que vive fuera de la API: entrar con
correo y clave, registrar las pesadas al cerrar cada carga, consultar las ordenes
del ERP, ver las discrepancias detectadas, el estado de las camaras, los clips y
el conteo de sacos, ajustar las tolerancias por producto, administrar usuarios y
roles, y emitir o revocar tokens. El criterio 1 de HU-04 pide la pantalla de configuracion, y el
criterio 4 de HU-15 pide que la revocacion se pueda hacer desde aqui.

No guarda la clave en ningun sitio: la cambia por un token al entrar y trabaja
solo con ese token, que vive en la sesion del navegador y desaparece al salir.
"""
from __future__ import annotations

import datetime as dt
import os

import httpx
import pandas as pd
import streamlit as st

API_URL = os.getenv("API_INTERNAL_URL", "http://api:8000")
TIEMPO_LIMITE = 15

# Como se escriben los estados del evento en pantalla. Sin esto la interfaz
# muestra `falso_positivo` y el supervisor lee codigo. Solo traduce: que
# transiciones se permiten lo decide la API y llega en el detalle.
NOMBRE_DEL_ESTADO = {
    "pendiente": "Pendiente",
    "pendiente_analisis": "Pendiente de análisis",
    "en_revision": "En revisión",
    "confirmado": "Confirmado",
    "falso_positivo": "Falso positivo",
    "sin_clip": "Sin clip",
}
# Los roles que escriben. El rol Consulta ve la decision pero no la toma: la API
# lo rechaza con 403 y la pantalla no ofrece el formulario, para no invitar a un
# error que ya esta cerrado.
ROLES_QUE_CLASIFICAN = ("administrador", "supervisor")
# Donde el callback de clasificar deja lo que paso, para que lo pinte la pasada
# siguiente: dentro de un callback no se puede dibujar.
RESULTADO_CLASIFICACION = "resultado_clasificacion"
# Los ids de la ultima bandeja que se vio, en su orden. La pagina del evento los
# usa para Anterior y Siguiente sin volver a pedir la bandeja. Se queda con la
# lista de cuando se salio de la bandeja a proposito: un evento recien
# clasificado suele caerse del filtro, y aun asi hay que poder pasar al que sigue.
IDS_DE_LA_BANDEJA = "ids_de_la_bandeja"
# Las claves de los filtros de la bandeja. Streamlit olvida el valor de un
# control que no se dibuja en una pasada, y mientras se ve la pagina de un evento
# los filtros no se dibujan: sin conservarlos, volver a la bandeja la dejaria en
# la vista por defecto y el supervisor perderia lo que estaba filtrando.
# Donde los dialogos de confirmacion dejan su resultado para que lo pinte la
# pasada siguiente: al confirmar se redibuja todo y el dialogo ya no existe.
AVISO_DE_ADMINISTRACION = "aviso_de_administracion"
CLAVES_DE_FILTROS = ("filtro_estado", "filtro_severidad", "filtro_periodo",
                     "filtro_orden", "filtro_desde", "filtro_hasta",
                     "filtro_solo_faltante", "filtro_tamano", "filtro_pagina")

st.set_page_config(page_title="QUINOR - Control de despacho", page_icon="📦", layout="wide")

# El evento que el supervisor eligio en la bandeja. Mientras tenga valor, la
# pestana Eventos muestra la pagina de ese evento en lugar de la bandeja.
EVENTO_ELEGIDO = "evento_elegido"
# Nombres de las decisiones de HU-13 tal como los lee el supervisor. Los estados
# siguen siendo los de la API; esto solo cambia como se preguntan.
NOMBRE_DE_LA_DECISION = {
    "confirmado": "Confirmar discrepancia",
    "falso_positivo": "Marcar como falso positivo",
    "en_revision": "Mantener en revisión",
    "pendiente": "Devolver a pendiente",
}

# Rediseno UX/UI del 05/11/2026; desde el 13/11/2026 en tema claro. El tema vive
# en .streamlit/config.toml; aqui solo lo que el tema no cubre (tipografia de
# titulos, tarjetas, la barra de pasos). Si las fuentes no cargan (sin internet)
# se usa la del sistema y todo sigue legible.
ESTILO = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Grotesk:wght@400;500;600&display=swap');
html, body, [class*="css"], .stMarkdown, .stText, button, input, textarea {font-family: Inter, system-ui, sans-serif;}
h1, h2, h3, h4, [data-testid="stMetricValue"] {font-family: 'Space Grotesk', Inter, sans-serif !important; letter-spacing: -.01em;}
[data-testid="stMetricValue"] {font-weight: 500;}
[data-testid="stMetricLabel"] p {color: #5F6B64;}
.block-container {padding-top: 2.5rem; max-width: 1280px;}
#MainMenu, footer, [data-testid="stDecoration"] {visibility: hidden;}
.stTabs [data-baseweb="tab-list"] {gap: 4px; border-bottom: 1px solid #D9D4C7;}
.stTabs [data-baseweb="tab"] {height: 48px; padding: 0 16px; font-size: 15px;}
.stButton button, .stFormSubmitButton button, .stDownloadButton button {border-radius: 12px; min-height: 44px; font-weight: 500;}
[data-testid="stVerticalBlockBorderWrapper"] {border-radius: 16px;}
[data-testid="stExpander"] details {border-radius: 16px; border-color: #D9D4C7;}
.q-saludo {font: 500 40px/1.12 'Space Grotesk', Inter, sans-serif; letter-spacing: -.02em; margin: 6px 0 4px;}
.q-tenue {color: #5F6B64;}
.q-oro {color: #A8741A;}
.q-vivo {display: inline-flex; align-items: center; gap: 8px; font-size: 14px; color: #5F6B64;}
.q-vivo i {width: 8px; height: 8px; border-radius: 50%; background: #2E8B57; animation: q-pulso 2s infinite;}
.q-vivo.q-caido {color: #9B2C14; font-weight: 500;}
.q-vivo.q-caido i {background: #9B2C14; animation: none;}
.q-vivo.q-aviso {color: #7A4F00;}
.q-vivo.q-aviso i {background: #C98A00; animation: none;}
@keyframes q-pulso {0% {box-shadow: 0 0 0 0 rgba(46,139,87,.55);} 70% {box-shadow: 0 0 0 10px rgba(46,139,87,0);} 100% {box-shadow: 0 0 0 0 rgba(46,139,87,0);}}
.q-pasos {display: flex; gap: 6px; margin: 4px 0 2px;}
.q-paso {flex: 1; display: flex; flex-direction: column; gap: 5px; min-width: 0;}
.q-paso b {height: 5px; border-radius: 3px; display: block;}
.q-paso span {font-size: 12px; color: #5F6B64; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.q-ok b {background: #2E8B57;} .q-curso b {background: repeating-linear-gradient(90deg,#3B6FB6 0 6px,#C9D8EE 6px 12px); background-size: 24px 5px; animation: q-avanza 1s linear infinite;}
.q-fallo b {background: transparent; box-shadow: inset 0 0 0 2px #A8741A;} .q-no b {background: #D9D4C7;}
@keyframes q-avanza {from {background-position: 0 0;} to {background-position: 24px 0;}}
.q-pill {display: inline-block; font-size: 12px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; padding: 5px 10px; border-radius: 8px;}
.q-alta {background: #FBE3DC; color: #9B2C14;} .q-media {background: #FCEFD6; color: #8A5A00;}
.q-baja {background: #E3ECF7; color: #2F5487;} .q-sin {background: #ECEAE3; color: #5F6B64;}
.q-chips {display: flex; flex-wrap: wrap; gap: 8px; margin: 4px 0 12px;}
.q-chip {font-size: 14px; padding: 7px 12px; border-radius: 999px; border: 1px solid #CFC9BA; color: #3A4640;}
.q-chip strong {color: #1E2A23;}
.q-grande {font: 500 30px 'Space Grotesk', Inter, sans-serif; line-height: 1.1;}
.q-pasos-pesada {display: flex; gap: 10px; margin: 6px 0 18px;}
.q-pp {flex: 1; padding: 12px 14px; border-radius: 12px; border: 1px solid #D9D4C7; font-size: 14px; color: #5F6B64;}
.q-pp.hecho {border-color: #8CC5A5; color: #2E8B57;} .q-pp.actual {border-color: #A8741A; color: #1E2A23;}
.q-dif {font: 500 26px/1.1 'Space Grotesk', Inter, sans-serif; color: #9B2C14; font-variant-numeric: tabular-nums;}
.q-hall {display: inline-block; font-size: 13px; font-weight: 600; padding: 4px 10px; border-radius: 8px; border: 1px solid #CFC9BA; color: #3A4640; margin-bottom: 6px;}
.q-hall.q-sust {background: #1E2A23; border-color: #1E2A23; color: #FFFFFF;}
.q-marca {background: #1F5C3A; color: #FFFFFF; border-radius: 18px; padding: 44px 40px; min-height: 440px; display: flex; flex-direction: column; justify-content: space-between; gap: 32px;}
.q-marca .q-nombre {font: 600 30px/1.1 'Space Grotesk', Inter, sans-serif; letter-spacing: -.01em;}
.q-marca .q-sub {color: #D5E8DC; font-size: 15px; margin-top: 4px;}
.q-marca .q-lema {font: 500 28px/1.22 'Space Grotesk', Inter, sans-serif; letter-spacing: -.01em; max-width: 420px;}
.q-marca .q-pie {color: #D5E8DC; font-size: 14px;}
@media (max-width: 760px) {.q-marca {min-height: 0; padding: 28px 24px; gap: 18px;} .q-marca .q-lema {font-size: 21px;}}
.q-lectura {font: 500 48px/1.15 'Space Grotesk', Inter, sans-serif; letter-spacing: -.02em; font-variant-numeric: tabular-nums; margin: 2px 0 18px;}
.q-reloj {font: 400 30px/1 'Space Grotesk', Inter, sans-serif; letter-spacing: -.03em; font-variant-numeric: tabular-nums;}
</style>
"""
st.markdown(ESTILO, unsafe_allow_html=True)


def _barra_de_pasos(pasos: list[tuple[str, str]]) -> str:
    """HTML de la barra de avance: (nombre, estado) con estado ok|curso|fallo|no.

    Responde a lo que mas se preguntaba en las pruebas: "en que momento se
    actualiza". Cada evento dice que hizo el sistema y que le falta.
    """
    celdas = "".join(f'<div class="q-paso q-{estado}"><b></b><span>{nombre}</span></div>'
                     for nombre, estado in pasos)
    return f'<div class="q-pasos">{celdas}</div>'


# Estados en los que un supervisor ya tomo el caso: ningun proceso automatico lo
# vuelve a tocar, asi que lo que falte no esta "en curso", quedo sin hacer.
ESTADOS_CERRADOS = {"en_revision", "confirmado", "falso_positivo"}


def _sin_curso_si_cerrado(pasos: list[tuple[str, str]], estado: str) -> list[tuple[str, str]]:
    """Un evento clasificado no tiene nada en marcha: lo pendiente se ve apagado.

    Sin esto, los eventos viejos cerrados antes de que hubiera conteo parecian
    seguir procesando para siempre (visto el 06/11/2026).
    """
    if estado not in ESTADOS_CERRADOS:
        return pasos
    return [(nombre, "no" if paso == "curso" else paso) for nombre, paso in pasos]


def _pasos_de_la_fila(e: dict) -> list[tuple[str, str]]:
    """Los pasos de un evento a partir de su fila de la bandeja."""
    sin_clip = e["estado"] == "sin_clip"
    clip = "fallo" if sin_clip else ("ok" if e["tiene_clip"] else "curso")
    if sin_clip:
        conteo = "no"
    elif e["sacos_contados"] is not None:
        conteo = "ok"
    else:
        conteo = "curso" if e["tiene_clip"] else "no"
    if e["estado"] == "pendiente_analisis":
        analisis = "fallo"
    elif e["severidad"]:
        analisis = "ok"
    else:
        analisis = "curso" if conteo == "ok" else "no"
    return _sin_curso_si_cerrado(
        [("Pesada", "ok"), ("Video", clip), ("Conteo", conteo), ("Análisis", analisis)],
        e["estado"])


def _pill_de_severidad(severidad: str | None) -> str:
    if not severidad:
        return '<span class="q-pill q-sin">Sin severidad</span>'
    return f'<span class="q-pill q-{severidad}">Severidad {severidad}</span>'


# --------------------------------------------------------------- transporte
def pedir(metodo: str, ruta: str, **extra) -> httpx.Response:
    """Llama a la API con el token de la sesion en la cabecera X-API-Key."""
    cabeceras = {"X-API-Key": st.session_state.get("token", "")}
    return httpx.request(metodo, f"{API_URL}{ruta}", timeout=TIEMPO_LIMITE,
                         headers=cabeceras, **extra)


def detalle_del_error(respuesta: httpx.Response) -> str:
    try:
        return str(respuesta.json().get("detail", respuesta.text))
    except ValueError:
        return respuesta.text


def puede_escribir() -> bool:
    """Si el usuario de la sesion puede clasificar. HU-13 con HU-15."""
    return st.session_state.get("usuario", {}).get("rol") in ROLES_QUE_CLASIFICAN


def cerrar_sesion() -> None:
    for clave in ("token", "usuario"):
        st.session_state.pop(clave, None)


# ------------------------------------------------------------------- ingreso
def _intentar_ingreso(correo: str, clave: str) -> None:
    try:
        respuesta = httpx.post(f"{API_URL}/auth/login", timeout=TIEMPO_LIMITE,
                               json={"correo": correo, "clave": clave})
    except httpx.HTTPError:
        st.error("No hay conexión con el sistema. Intente de nuevo en unos "
                 "segundos; si continúa, avise al administrador.")
        return
    if respuesta.status_code != 200:
        # La API no distingue si fallo el correo o la clave, y aqui tampoco.
        st.error(detalle_del_error(respuesta))
        return
    datos = respuesta.json()
    st.session_state["token"] = datos["token"]
    st.session_state["usuario"] = datos["usuario"]
    st.rerun()


def pantalla_de_ingreso() -> None:
    """Ingreso en dos mitades: a la izquierda que sistema es, a la derecha el
    formulario. Es el diseno del prototipo de la critica de UX (15/11/2026).

    A todo el ancho los campos median mas de mil pixeles para un correo, y la
    pantalla no decia a que sistema se estaba entrando. La primera correccion
    (fase 6) solo centro el formulario; esta le anade el panel de marca. En una
    pantalla estrecha las dos mitades se apilan y el panel se encoge.
    """
    # Un respiro arriba: sin el, la barra superior de Streamlit tapaba el borde
    # redondeado del panel.
    st.markdown('<div style="height: 6vh"></div>', unsafe_allow_html=True)
    _, cuerpo, _ = st.columns([1, 10, 1])
    with cuerpo:
        marca, acceso = st.columns(2, gap="large", vertical_alignment="center")
        marca.markdown(
            '<div class="q-marca">'
            '<div><div class="q-nombre">QUINOR</div>'
            '<div class="q-sub">Control de despacho</div></div>'
            '<div class="q-lema">Cada carga, pesada y contada antes de que el '
            'contenedor salga de planta.</div>'
            '<div class="q-pie">Rampa de carga · QUINOR S.A.C.</div>'
            '</div>', unsafe_allow_html=True)
        with acceso:
            st.markdown("### Iniciar sesión")
            st.caption("Use el correo y la contraseña que le asignó el administrador.")
            with st.form("ingreso"):
                correo = st.text_input("Correo electrónico",
                                       placeholder="usuario@quinor.local")
                clave = st.text_input("Contraseña", type="password")
                # Sin return aqui: la leyenda de abajo debe dibujarse siempre,
                # tambien antes de pulsar y cuando el ingreso falla.
                if st.form_submit_button("Iniciar sesión", type="primary",
                                         use_container_width=True):
                    _intentar_ingreso(correo, clave)
            st.caption("La sesión se cierra al salir del navegador. Si no puede "
                       "ingresar, avise al administrador del sistema.")


# -------------------------------------------------------------------- salud
def panel_de_salud() -> None:
    st.subheader("Estado de los componentes")
    try:
        respuesta = pedir("GET", "/salud")
    except httpx.HTTPError:
        st.error("No hay conexión con el sistema. Intente de nuevo en unos "
                 "segundos; si continúa, avise al administrador.")
        return
    if respuesta.status_code == 401:
        st.warning("La sesión venció o el token fue revocado. Vuelva a iniciar sesión.")
        cerrar_sesion()
        st.rerun()
    if respuesta.status_code != 200:
        st.error(detalle_del_error(respuesta))
        return
    datos = respuesta.json()
    if datos["estado"] == "ok":
        st.success("Todos los componentes responden.")
    else:
        st.warning("Hay componentes con error. Revise el detalle.")
    st.dataframe(pd.DataFrame(datos["componentes"]),
                 use_container_width=True, hide_index=True)


# ------------------------------------------------------------ confirmaciones
@st.dialog("Confirmar acción")
def _confirmar(pregunta: str, consecuencia: str, etiqueta: str, metodo: str,
               ruta: str, cuerpo: dict | None, hecho: str) -> None:
    """Pide confirmacion antes de una accion de administracion y la ejecuta.

    Revocar un token, desactivar a alguien o cambiarle el rol se aplicaban al
    primer clic. Son acciones que dejan a una persona o a un equipo sin acceso
    (o le dan mas del que tenia), y un clic de mas en la fila equivocada no se
    notaba hasta que alguien llamaba. El dialogo dice que va a pasar antes de
    que pase (critica de UX del 15/11/2026, fase 3).

    El resultado se deja en la sesion y lo pinta la pasada siguiente: al
    confirmar se redibuja la pagina y este dialogo deja de existir.
    """
    st.write(pregunta)
    st.caption(consecuencia)
    confirmar, cancelar = st.columns(2)
    if confirmar.button(etiqueta, type="primary", use_container_width=True):
        resultado = pedir(metodo, ruta, json=cuerpo)
        if resultado.status_code == 200:
            st.session_state[AVISO_DE_ADMINISTRACION] = hecho
            st.rerun()
        st.error(detalle_del_error(resultado))
    if cancelar.button("Cancelar", use_container_width=True):
        st.rerun()


def _aviso_de_administracion() -> None:
    """Pinta, una sola vez, lo que dejo el ultimo dialogo confirmado."""
    hecho = st.session_state.pop(AVISO_DE_ADMINISTRACION, None)
    if hecho:
        st.success(hecho)


def _fecha_corta(valor: str | None) -> str:
    return (valor or "-")[:16].replace("T", " ")


# ------------------------------------------------------------------- tokens
def panel_de_tokens() -> None:
    st.subheader("Tokens de acceso")
    st.caption("El valor del token se muestra una sola vez, al emitirlo. Cópielo "
               "en ese momento: después no se puede recuperar.")
    _aviso_de_administracion()

    with st.expander("Emitir un token nuevo"):
        with st.form("emitir_token"):
            nombre = st.text_input("¿Para qué equipo?", placeholder="Laptop de rampa 1")
            horas = st.number_input("Vigencia en horas", min_value=1, max_value=8760, value=12)
            if st.form_submit_button("Emitir token"):
                respuesta = pedir("POST", "/auth/tokens",
                                  json={"nombre": nombre or "token", "ttl_horas": float(horas)})
                if respuesta.status_code == 201:
                    st.success(respuesta.json()["aviso"])
                    st.code(respuesta.json()["token"], language=None)
                else:
                    st.error(detalle_del_error(respuesta))

    respuesta = pedir("GET", "/auth/tokens")
    if respuesta.status_code != 200:
        st.error(detalle_del_error(respuesta))
        return
    tokens = respuesta.json()
    if not tokens:
        st.info("No hay tokens emitidos.")
        return

    anchos = [3, 3, 3, 2]
    for columna, titulo in zip(st.columns(anchos), ("Equipo", "Vence", "Último uso", "")):
        columna.caption(titulo)
    for token in tokens:
        revocado = token["revocado_en"] is not None
        columnas = st.columns(anchos, vertical_alignment="center")
        columnas[0].write(f"**{token['nombre']}**")
        columnas[1].write(_fecha_corta(token["expira_en"]))
        columnas[2].write("Revocado" if revocado else _fecha_corta(token["ultimo_uso_en"]))
        if not revocado and columnas[3].button("Revocar", key=f"revocar_{token['id']}",
                                               use_container_width=True):
            _confirmar(
                f"Va a revocar el token **{token['nombre']}**.",
                "Deja de servir de inmediato y no se puede deshacer. El equipo que "
                "lo use tendrá que pedir un token nuevo. Si es el token de esta "
                "sesión, tendrá que volver a iniciar sesión.",
                "Revocar token", "DELETE", f"/auth/tokens/{token['id']}", None,
                f"Token «{token['nombre']}» revocado. Ya no sirve.")


# ----------------------------------------------------------------- eventos
def panel_de_eventos() -> None:
    """Bandeja de eventos. HU-03 y HU-11.

      1. La tabla muestra ID, fecha, orden, diferencia, severidad y estado.
      2. Los filtros se combinan y la tabla se actualiza en menos de 2 s.
      3. Por defecto se muestran los eventos Pendientes de los ultimos 7 dias.

    Es la pantalla que da sentido al resto: aqui es donde el supervisor se
    entera del faltante el mismo dia.

    Los datos salen de `GET /eventos/bandeja`, que devuelve una sola pagina con
    una sola consulta. El listado anterior pedia `/eventos`, que arma cada fila
    con cuatro consultas: servia con veinte eventos y no habria servido con un
    ano de operacion.
    """
    elegido = st.session_state.get(EVENTO_ELEGIDO)
    if elegido is not None:
        # El evento se ve en su propia pagina y no debajo de la bandeja. Antes
        # se abria en un desplegable al final, despues de todas las tarjetas:
        # quien pulsaba "Ver detalle" no veia cambiar nada y tenia que bajar a
        # buscarlo (critica de UX del 15/11/2026).
        _pagina_del_evento(elegido)
        return

    # Los filtros van a la vista y no dentro de un desplegable cerrado: el que
    # mas se usa (el estado) se cambia con un clic, y lo que esta filtrado se
    # lee sin abrir nada (critica de UX del 15/11/2026, fase 2).
    filtros = _filtros_de_la_bandeja()

    respuesta = pedir("GET", "/eventos/bandeja", params=filtros)
    if respuesta.status_code != 200:
        st.error(detalle_del_error(respuesta))
        return
    bandeja = respuesta.json()
    eventos = bandeja["filas"]

    st.session_state[IDS_DE_LA_BANDEJA] = [e["id"] for e in eventos]

    _aviso_de_filtros_por_defecto(bandeja)
    _resultado_de_la_clasificacion()

    if not eventos:
        st.success("No hay eventos de discrepancia con el filtro seleccionado.")
        _pie_de_la_bandeja(bandeja)
        return

    _senales_de_la_bandeja(bandeja)
    _tarjetas_de_la_bandeja(eventos)

    with st.expander("Vista de tabla"):
        _tabla_de_la_bandeja(eventos)

    _pie_de_la_bandeja(bandeja)


def _conservar_filtros() -> None:
    """Mantiene los filtros de la bandeja mientras se ve la pagina de un evento
    o cualquier otra pantalla del menu. Se llama en cada pasada, desde el
    programa, y no desde la bandeja: mientras se esta en otra pantalla la
    bandeja no se ejecuta.

    Reasignar la clave a si misma es la forma que da Streamlit de decirle que el
    valor sigue en uso aunque su control no se haya dibujado en esta pasada.
    """
    for clave in CLAVES_DE_FILTROS:
        if clave in st.session_state:
            st.session_state[clave] = st.session_state[clave]


def _elegir_evento(evento_id: int) -> None:
    st.session_state[EVENTO_ELEGIDO] = evento_id


def _volver_a_la_bandeja() -> None:
    st.session_state.pop(EVENTO_ELEGIDO, None)


def _hallazgo_de_la_fila(e: dict) -> tuple[str, str]:
    """Que dice la fila, en dos o tres palabras: (clase CSS, texto).

    Es la distincion que da sentido al sistema y antes solo se veia dentro del
    detalle: no es lo mismo que falten sacos que que los sacos cuadren y falte
    peso. Sigue las mismas reglas que el resumen de la API (`bandeja.resumen`):
    faltante es diferencia de sacos negativa, y sustitucion es peso corto con
    diferencia de sacos igual a cero. Convencion 7: sin conteo no hay hallazgo,
    y se dice asi en lugar de suponer que cuadra.
    """
    if e["sacos_contados"] is None:
        return "", "Conteo de sacos pendiente"
    diferencia = e["diferencia_sacos"]
    if diferencia is None:
        return "", "Sin sacos esperados en la orden"
    if diferencia < 0:
        return "", f"Faltan {-diferencia} saco{'s' if diferencia != -1 else ''}"
    if diferencia > 0:
        return "", f"Sobran {diferencia} saco{'s' if diferencia != 1 else ''}"
    if float(e["diferencia_kg"]) < 0:
        return "q-sust", "Posible sustitución"
    return "", "Sobrepeso con sacos completos"


def _tarjetas_de_la_bandeja(eventos: list[dict]) -> None:
    """Un evento por tarjeta, con lo que importa a la vista: cuanto falta, que
    significa, en que va el analisis y un boton para revisarlo.

    La diferencia en kg va en grande porque es el hecho; antes iba en la letra
    mas pequena de la tarjeta, por debajo del numero de orden.
    """
    for e in eventos:
        with st.container(border=True):
            quien, cuanto, que, accion = st.columns([4, 3, 4, 2],
                                                    vertical_alignment="center")
            # Dia y mes bastan en la tarjeta (el ano esta en la tabla): con la
            # fecha completa el renglon no cabia y se partia en dos.
            fecha = f"{e['creado_en'][8:10]}/{e['creado_en'][5:7]} {e['creado_en'][11:16]}"
            quien.markdown(
                f"{_pill_de_severidad(e['severidad'])} &nbsp;"
                f"<span class='q-tenue'>#{e['id']} · {fecha}</span>",
                unsafe_allow_html=True)
            quien.markdown(f"**{e['numero_orden']}** · {e['cliente']}")

            cuanto.markdown(
                f"<div class='q-dif'>{float(e['diferencia_kg']):+,.0f} kg</div>",
                unsafe_allow_html=True)
            cuanto.caption(f"{float(e['diferencia_pct']):+.1f} % del peso esperado")

            clase, hallazgo = _hallazgo_de_la_fila(e)
            que.markdown(f"<span class='q-hall {clase}'>{hallazgo}</span>"
                         + _barra_de_pasos(_pasos_de_la_fila(e)),
                         unsafe_allow_html=True)
            if e["sacos_contados"] is None:
                sacos = ""
            elif e["sacos_esperados"] is None:
                sacos = f" · {e['sacos_contados']} sacos en el video"
            else:
                sacos = f" · {e['sacos_contados']} de {e['sacos_esperados']} sacos en el video"
            incompleto = e["estado"] in ESTADOS_CERRADOS and (
                e["sacos_contados"] is None or not e["severidad"])
            que.caption(NOMBRE_DEL_ESTADO.get(e["estado"], e["estado"]) + sacos
                        + (" · cerrado sin análisis completo" if incompleto else ""))
            accion.button("Ver detalle", key=f"revisar_{e['id']}", use_container_width=True,
                          type="primary" if e["estado"] == "pendiente" else "secondary",
                          on_click=_elegir_evento, args=(e["id"],))


def _tabla_de_la_bandeja(eventos: list[dict]) -> None:
    st.dataframe(
        pd.DataFrame([{
            "ID": e["id"],
            "Fecha": e["creado_en"][:19].replace("T", " "),
            "Orden": e["numero_orden"],
            "Cliente": e["cliente"],
            "Diferencia kg": e["diferencia_kg"],
            "Diferencia %": e["diferencia_pct"],
            # HU-07. Un guion no es un cero: mientras el clip no se ha
            # analizado no hay conteo, y confundir las dos cosas mandaria a
            # alguien a la rampa por una carga que nadie ha mirado todavia.
            "Sacos orden": ("-" if e["sacos_esperados"] is None
                            else e["sacos_esperados"]),
            "Sacos video": ("-" if e["sacos_contados"] is None
                            else e["sacos_contados"]),
            "Dif. sacos": ("-" if e["diferencia_sacos"] is None
                           else e["diferencia_sacos"]),
            # HU-08. Igual que arriba, un guion no es un cero: sin analizar no
            # hay dato, y una rampa vacia si lo es.
            "Personas": ("-" if e["personas_detectadas"] is None
                         else e["personas_detectadas"]),
            "Personal": ("-" if e["personal_anomalo"] is None
                         else ("Revisar" if e["personal_anomalo"] else "Normal")),
            # HU-09. Sale de la RN-04, no del modelo: por eso esta aunque el
            # proveedor haya fallado.
            "Severidad": (e["severidad"] or "-").capitalize(),
            # El nombre que lee el supervisor, no el codigo de la API.
            "Estado": NOMBRE_DEL_ESTADO.get(e["estado"], e["estado"]),
            # HU-06. "Sin clip" no es lo mismo que "todavia no": el recorte
            # espera a que se grabe el margen posterior al cierre.
            "Clip": ("No hay video" if e["estado"] == "sin_clip"
                     else ("Sí" if e["tiene_clip"] else "En curso")),
        } for e in eventos]),
        use_container_width=True, hide_index=True)


def _resultado_de_la_clasificacion() -> None:
    """Pinta lo que dejo el callback de HU-13, si dejo algo.

    Se pinta arriba de la pagina del evento, que es donde sigue el supervisor
    despues de clasificar, y tambien en la bandeja por si vuelve a ella antes de
    que se haya mostrado: el mensaje se consume al leerlo, asi que sale una vez.
    """
    nivel, mensaje = st.session_state.pop(RESULTADO_CLASIFICACION, (None, None))
    if nivel == "ok":
        st.success(mensaje)
    elif nivel == "aviso":
        st.warning(mensaje)
    elif nivel == "error":
        st.error(mensaje)


ESTADOS_DEL_FILTRO = ["por defecto", "pendiente_analisis", "en_revision",
                      "confirmado", "falso_positivo", "sin_clip", "todos"]
PERIODOS_DEL_FILTRO = {"ultimos 7 dias": "Últimos 7 días", "hoy": "Hoy",
                       "ultimos 30 dias": "Últimos 30 días", "todo": "Todo",
                       "personalizado": "Personalizado"}


def _a_la_primera_pagina() -> None:
    """Al cambiar un filtro se vuelve a la pagina 1: la 3 de otro filtro no
    significa nada, y puede no existir."""
    st.session_state["filtro_pagina"] = 1


def _aplicar_filtro(clave: str, valor) -> None:
    """Callback de los botones de resumen: fija un filtro como si se hubiera
    elegido a mano. Tiene que ser callback porque el control ya esta dibujado
    cuando se pulsa, y Streamlit no deja cambiar su valor despues."""
    st.session_state[clave] = valor
    _a_la_primera_pagina()


def _ir_a_la_pagina(pagina: int) -> None:
    st.session_state["filtro_pagina"] = pagina


def _filtros_de_la_bandeja() -> dict:
    """Los cuatro filtros del criterio 1, mas los que el uso pidio.

    Cada uno se manda solo si el supervisor lo toco. Mandarlos todos siempre
    desactivaria los valores por defecto del criterio 3 sin que nadie lo hubiera
    pedido: la API distingue "no dijo nada" de "dijo que todos".

    El estado, el periodo y la orden estan siempre a la vista. Lo que se usa
    poco (severidad, solo faltantes, filas por pagina) queda en "Más filtros",
    y su etiqueta dice cuantos hay puestos para que un filtro olvidado no pase
    por una bandeja vacia.
    """
    # Los valores iniciales se dejan en la sesion y no en el control: asi los
    # botones de resumen pueden fijarlos sin que Streamlit avise de que el
    # control tiene dos origenes para su valor.
    st.session_state.setdefault("filtro_estado", "por defecto")
    st.session_state.setdefault("filtro_solo_faltante", False)
    st.session_state.setdefault("filtro_pagina", 1)

    estado = st.pills(
        "Estado", ESTADOS_DEL_FILTRO, key="filtro_estado",
        label_visibility="collapsed", on_change=_a_la_primera_pagina,
        format_func=lambda e: {"por defecto": "Pendientes", "todos": "Todos"}.get(
            e, NOMBRE_DEL_ESTADO.get(e, e)))
    # Las etiquetas se pueden desmarcar: sin ninguna, la vista por defecto.
    estado = estado or "por defecto"

    puestos = (int(st.session_state.get("filtro_severidad", "todas") != "todas")
               + int(bool(st.session_state.get("filtro_solo_faltante"))))
    fila1 = st.columns([2, 3, 2], vertical_alignment="bottom")
    rango = fila1[0].selectbox(
        "Periodo", list(PERIODOS_DEL_FILTRO), key="filtro_periodo",
        on_change=_a_la_primera_pagina, format_func=PERIODOS_DEL_FILTRO.get)
    orden = fila1[1].text_input("Número de orden", key="filtro_orden",
                                on_change=_a_la_primera_pagina,
                                placeholder="Ej.: 0148 u ORD-2026-0148")
    with fila1[2].popover("Más filtros" + (f" ({puestos})" if puestos else ""),
                          use_container_width=True):
        severidad = st.selectbox("Severidad", ["todas", "alta", "media", "baja"],
                                 key="filtro_severidad", format_func=str.capitalize,
                                 on_change=_a_la_primera_pagina)
        solo_faltante = st.checkbox(
            "Solo con diferencia de sacos", key="filtro_solo_faltante",
            on_change=_a_la_primera_pagina,
            help="Excluye las cargas cuyo conteo de sacos coincide con la orden.")
        tamano = st.selectbox("Eventos por página", [25, 50, 100, 200], index=1,
                              key="filtro_tamano", on_change=_a_la_primera_pagina)

    desde = hasta = None
    if rango == "personalizado":
        fila2 = st.columns(2)
        desde = fila2[0].date_input("Desde", key="filtro_desde",
                                    on_change=_a_la_primera_pagina,
                                    value=dt.date.today() - dt.timedelta(days=7))
        hasta = fila2[1].date_input("Hasta", key="filtro_hasta",
                                    on_change=_a_la_primera_pagina,
                                    value=dt.date.today())

    # La pagina ya no es un control dentro de los filtros: se cambia con los
    # botones Anterior y Siguiente del pie, que es donde se lee en cual se esta.
    filtros: dict = {"tamano": tamano,
                     "pagina": int(st.session_state["filtro_pagina"])}
    if estado == "todos":
        filtros["sin_defectos"] = True
    elif estado != "por defecto":
        filtros["estado"] = estado
    if severidad != "todas":
        filtros["severidad"] = severidad
    if orden.strip():
        filtros["numero_orden"] = orden.strip()
    if solo_faltante:
        filtros["solo_con_faltante"] = True

    hoy = dt.date.today()
    if rango == "hoy":
        filtros["desde"] = filtros["hasta"] = hoy.isoformat()
    elif rango == "ultimos 30 dias":
        filtros["desde"] = (hoy - dt.timedelta(days=30)).isoformat()
    elif rango == "todo":
        filtros["sin_defectos"] = True
        if estado == "por defecto":
            # `sin_defectos` apaga los dos valores por defecto de la API a la
            # vez. Sin esto, "Pendientes" + "Todo" mostraba todos los estados
            # con la etiqueta Pendientes marcada.
            filtros["estado"] = "pendiente"
    elif rango == "personalizado" and desde and hasta:
        filtros["desde"], filtros["hasta"] = desde.isoformat(), hasta.isoformat()
    elif estado == "todos":
        # Lo mismo al reves: "Todos" + "Últimos 7 días" mostraba todo el
        # historico, porque la ventana de 7 dias tambien es un valor por
        # defecto. Se manda la fecha de forma explicita.
        filtros["desde"] = (hoy - dt.timedelta(days=7)).isoformat()

    return filtros


def _aviso_de_filtros_por_defecto(bandeja: dict) -> None:
    """Dice cuando lo que se ve no es todo lo que hay. Criterio 3.

    Sin esto, un supervisor que entra y ve tres eventos puede irse creyendo que
    esos son todos, cuando esta viendo los pendientes de la ultima semana. El
    aviso es la mitad util del valor por defecto.
    """
    puestos = bandeja["filtros"].get("por_defecto") or []
    if not puestos:
        return
    partes = []
    if "estado" in puestos:
        partes.append("solo los **Pendientes**")
    if "desde" in puestos:
        partes.append("de los **últimos 7 días**")
    st.caption("Vista por defecto: " + " ".join(partes) +
               ". Ajuste los filtros de Estado o Periodo para ampliar la vista.")


def _senales_de_la_bandeja(bandeja: dict) -> None:
    """Lo que conviene mirar antes que la lista, en una linea de etiquetas.

    Las cifras salen del resumen que calcula la API sobre la pagina que se esta
    viendo, no de recorrer las filas aqui: asi la pantalla y la API no pueden
    contar cosas distintas. La explicacion larga queda a un clic, para que la
    pantalla no abrume.
    """
    resumen = bandeja.get("resumen") or {}
    filas = bandeja["filas"]
    sin_analisis = sum(1 for e in filas if e["estado"] == "pendiente_analisis")
    sin_clip = sum(1 for e in filas if e["estado"] == "sin_clip")
    senales = [
        (resumen.get("abiertos"), "pendiente(s) de revisión"),
        (resumen.get("con_peso_corto_y_sacos_completos"), "con posible sustitución"),
        (resumen.get("con_faltante_de_sacos"), "con faltante de sacos"),
        (resumen.get("con_personal_anomalo"), "con presencia de personal atípica"),
        (sin_analisis, "sin descripción automática"),
        (sin_clip, "sin video"),
    ]
    chips = "".join(f'<span class="q-chip"><strong>{n}</strong> {texto}</span>'
                    for n, texto in senales if n)
    if not chips:
        return
    st.markdown(f'<div class="q-chips">{chips}</div>', unsafe_allow_html=True)

    # Las etiquetas de arriba informan; lo que se puede filtrar va en botones.
    # Antes las etiquetas tenian forma de filtro y no hacian nada al pulsarlas.
    # Solo se ofrece lo que la API sabe filtrar, y no lo que ya esta filtrado.
    atajos = []
    if (resumen.get("con_faltante_de_sacos")
            and not st.session_state.get("filtro_solo_faltante")):
        atajos.append(("Ver solo con diferencia de sacos", "filtro_solo_faltante", True))
    if sin_analisis and st.session_state.get("filtro_estado") != "pendiente_analisis":
        atajos.append(("Ver solo sin descripción automática", "filtro_estado",
                       "pendiente_analisis"))
    if sin_clip and st.session_state.get("filtro_estado") != "sin_clip":
        atajos.append(("Ver solo sin video", "filtro_estado", "sin_clip"))
    columnas = st.columns([3] * len(atajos) + [2] + [3] * (3 - len(atajos)))
    for columna, (etiqueta, clave, valor) in zip(columnas, atajos):
        columna.button(etiqueta, key=f"atajo_{clave}_{valor}", use_container_width=True,
                       on_click=_aplicar_filtro, args=(clave, valor))
    with columnas[len(atajos)].popover("Leyenda", use_container_width=True):
        st.markdown(
            "- **Posible sustitución:** falta peso y el conteo de sacos coincide "
            "con la orden.\n"
            "- **Faltante de sacos:** el video registró menos sacos que la orden. "
            "Un peso inferior con los sacos completos sugiere sustitución de "
            "producto; un faltante de sacos, bultos que no se cargaron.\n"
            "- **Presencia de personal atípica:** más personas de lo habitual, "
            "permanencias prolongadas o personal en la rampa sin movimiento de "
            "sacos. Indica revisar el video; no constituye una conclusión sobre "
            "ninguna persona.\n"
            "- **Sin descripción automática:** el modelo de visión-lenguaje no "
            "respondió. La severidad se mantiene, pues proviene de las reglas del negocio.\n"
            "- **Sin video:** no existe grabación de esa carga. El motivo consta en "
            "la auditoría.")


def _pie_de_la_bandeja(bandeja: dict) -> None:
    """Cuantos hay, cual se esta viendo y cuanto tardo. Criterio 2.

    El tiempo se muestra siempre y no solo cuando es malo. Una pantalla que solo
    avisa cuando ya va lenta no deja ver que se estaba degradando.
    """
    total = bandeja["total"]
    if total:
        donde = (f"Mostrando {bandeja['desde_fila']} a {bandeja['hasta_fila']} "
                 f"de {total} evento(s). Página {bandeja['pagina']} de "
                 f"{bandeja['paginas']}.")
    else:
        donde = "Ningún evento cumple el filtro."

    segundos = bandeja["segundos"]
    texto, anterior, siguiente = st.columns([6, 2, 2], vertical_alignment="center")
    if bandeja["dentro_del_criterio"]:
        texto.caption(donde)
    else:
        # El criterio 2 se mide con lo que pasa de verdad, y una pantalla que se
        # vuelve lenta hay que verla antes de que sea costumbre.
        texto.warning(f"{donde} La consulta tardó {segundos:.1f} s, más de lo habitual.")

    # La paginacion va aqui, junto al texto que dice en que pagina se esta, y no
    # dentro de los filtros. Con una sola pagina no se dibuja nada.
    pagina, paginas = bandeja.get("pagina") or 1, bandeja.get("paginas") or 1
    if paginas > 1:
        anterior.button("Anterior", use_container_width=True, disabled=pagina <= 1,
                        on_click=_ir_a_la_pagina, args=(max(pagina - 1, 1),))
        siguiente.button("Siguiente", use_container_width=True,
                         disabled=pagina >= paginas, key="pagina_siguiente",
                         on_click=_ir_a_la_pagina, args=(min(pagina + 1, paginas),))


def _pagina_del_evento(evento_id: int) -> None:
    """La pagina de un evento, con su video, su analisis y la decision. HU-12 y HU-13.

      1. El detalle muestra pesos, conteo de sacos, personas detectadas,
         descripcion y severidad.
      2. El clip se reproduce en el navegador con controles de pausa y avance.
      3. Se muestra el fotograma donde se detecto la anomalia.

    Una sola llamada a `GET /eventos/{id}/detalle`. La version anterior pedia el
    evento, las personas y los avisos por separado, y cada peticion volvia a
    buscar el evento para comprobar que existia.

    Los campos que la fila de la bandeja no trae (la tolerancia de aquel dia, la
    ventana recortada, el enlace firmado) se piden aqui y no alli a proposito:
    cuestan una consulta cada uno y el criterio 2 de HU-11 da 2 segundos para
    toda la tabla. Aqui se pagan una vez, para el evento que el supervisor
    eligio.

    La decision va al lado del video y no debajo de todo. Sigue siendo la
    conclusion (se clasifica despues de mirar), pero con el formulario a tres
    pantallas del reproductor el supervisor tenia que subir y bajar para
    contrastar lo que escribia con lo que veia.
    """
    ids = st.session_state.get(IDS_DE_LA_BANDEJA) or []
    posicion = ids.index(evento_id) if evento_id in ids else None

    volver, donde, anterior, siguiente = st.columns([3, 4, 2, 2],
                                                    vertical_alignment="center")
    volver.button("← Volver a Eventos", on_click=_volver_a_la_bandeja)
    if posicion is not None:
        donde.caption(f"Evento {posicion + 1} de {len(ids)} de la bandeja")
    hay_anterior = posicion is not None and posicion > 0
    hay_siguiente = posicion is not None and posicion < len(ids) - 1
    anterior.button("Anterior", use_container_width=True, disabled=not hay_anterior,
                    on_click=_elegir_evento,
                    args=(ids[posicion - 1] if hay_anterior else evento_id,))
    siguiente.button("Siguiente", use_container_width=True, disabled=not hay_siguiente,
                     on_click=_elegir_evento,
                     args=(ids[posicion + 1] if hay_siguiente else evento_id,))

    _resultado_de_la_clasificacion()

    respuesta = pedir("GET", f"/eventos/{evento_id}/detalle")
    if respuesta.status_code != 200:
        st.warning(detalle_del_error(respuesta))
        return
    detalle = respuesta.json()

    st.markdown(
        f"### {detalle['numero_orden']} &nbsp;"
        f"{_pill_de_severidad(detalle['analisis']['severidad'])}",
        unsafe_allow_html=True)
    st.caption(f"Evento #{detalle['id']} · {detalle['cliente']} · {detalle['producto']} · "
               f"{NOMBRE_DEL_ESTADO.get(detalle['estado'], detalle['estado'])}")
    st.markdown(_barra_de_pasos(_pasos_del_detalle(detalle)), unsafe_allow_html=True)
    _cifras_del_detalle(detalle)

    evidencia, decision = st.columns([3, 2], gap="large")
    with evidencia:
        _reproductor_del_clip(detalle)
        _fotogramas_del_detalle(detalle)
        _analisis_del_detalle(detalle)
        _personas_del_detalle(detalle)
    with decision:
        _clasificacion_del_evento(detalle)
        _avisos_del_evento({"id": detalle["id"],
                            "severidad": detalle["analisis"]["severidad"]})


def _pasos_del_detalle(detalle: dict) -> list[tuple[str, str]]:
    """La misma barra de la bandeja, con lo que trae el detalle."""
    sin_clip = detalle["estado"] == "sin_clip"
    clip = "fallo" if sin_clip else ("ok" if detalle["clip"]["reproducible"] else "curso")
    contado = detalle["sacos"]["analizado"]
    conteo = "ok" if contado else ("no" if sin_clip else "curso")
    analisis = detalle["analisis"]
    if detalle["estado"] == "pendiente_analisis":
        paso = "fallo"
    elif analisis["severidad"]:
        paso = "ok"
    else:
        paso = "curso" if contado else "no"
    return _sin_curso_si_cerrado(
        [("Pesada", "ok"), ("Video", clip), ("Conteo", conteo), ("Análisis", paso)],
        detalle["estado"])


def _cifras_del_detalle(detalle: dict) -> None:
    """Criterio 1: los pesos y el conteo, antes que el video.

    El orden no es casual. El video es la verificacion; la discrepancia es el
    hecho, y existe desde que el camion cerro. Un supervisor que abre esto
    tiene que ver primero cuanto falta.
    """
    pesos, sacos = detalle["pesos"], detalle["sacos"]

    if detalle["peso_corto_con_sacos_completos"]:
        # HU-07, criterio 3. Es la conclusion que justifica el proyecto entero:
        # no se llevaron sacos, cambiaron lo que hay dentro. Va antes que las
        # cifras porque es lo que el supervisor tiene que saber primero; antes
        # quedaba debajo de seis numeros.
        st.error("Falta peso y los bultos cuadran: apunta a producto sustituido, "
                 "no a sacos que no subieron.")

    diferencia_kg = float(pesos["diferencia_kg"])
    izquierda, centro, derecha = st.columns(3)
    izquierda.metric("Peso esperado", f"{float(pesos['esperado_kg']):,.2f} kg")
    centro.metric("Peso real", f"{float(pesos['real_kg']):,.2f} kg")
    # Un evento existe porque la diferencia paso la tolerancia, asi que siempre
    # es mala noticia, falte o sobre. "normal" pinta en rojo lo negativo e
    # "inverse" lo positivo: se elige el que deja la cifra en rojo. Con
    # "inverse" fijo, un faltante de 350 kg salia en verde.
    derecha.metric("Diferencia de peso", f"{diferencia_kg:+,.2f} kg",
                   delta=f"{float(pesos['diferencia_pct']):+.2f} %",
                   delta_color="normal" if diferencia_kg < 0 else "inverse")

    if pesos["tolerancia_aplicada_kg"] is not None:
        # La de aquel dia, no la de hoy: si alguien la cambio despues, el evento
        # sigue diciendo contra que umbral se juzgo aquella carga.
        texto = (f"Se toleraban {float(pesos['tolerancia_aplicada_kg']):,.2f} kg "
                 f"para este producto cuando se creó el evento")
        if pesos["exceso_sobre_la_tolerancia_kg"] is not None:
            texto += (f", así que se pasó en "
                      f"{float(pesos['exceso_sobre_la_tolerancia_kg']):,.2f} kg")
        st.caption(texto + ".")

    if not sacos["analizado"]:
        # Un guion no es un cero: sin analizar no hay conteo, y confundirlo
        # mandaria a alguien a la rampa por una carga que nadie ha mirado.
        st.info("El conteo de sacos todavía no está: el clip no se ha analizado.")
    else:
        uno, dos, tres = st.columns(3)
        uno.metric("Sacos en la orden", sacos["esperados"])
        dos.metric("Sacos en el video", sacos["contados"])
        tres.metric("Diferencia de sacos", f"{sacos['diferencia']:+d}")


def _reproductor_del_clip(detalle: dict) -> None:
    """Criterio 2: el clip en el navegador, con pausa y avance.

    Los controles no se programan: son los del reproductor del navegador, que
    los trae de serie y sabe pedir el video por trozos cuando el supervisor
    adelanta. El enlace apunta a MinIO y caduca; la API solo lo firma.

    Cuando no hay video, el hueco dice por que. Un reproductor vacio dejaria al
    supervisor sin saber si el clip se perdio o si falla su navegador.
    """
    clip = detalle["clip"]
    st.markdown("**Video del evento**")

    if clip["desde"] and clip["hasta"]:
        ventana = (f"Ventana recortada de {clip['desde'][11:19]} a "
                   f"{clip['hasta'][11:19]}")
        if clip["camara"]:
            ventana += f", cámara {clip['camara']}"
        st.caption(ventana + ".")
    elif detalle["inicio_carga"] is None:
        st.caption("Nadie marcó el inicio de carga: el clip cubre solo los "
                   "minutos previos al cierre.")

    if not clip["reproducible"]:
        st.info(clip["enlace"]["explicacion"]
                or "El clip no se puede reproducir ahora mismo.")
        if clip["motivo_sin_clip"]:
            # No es lo mismo la camara caida que el video ya purgado del buffer.
            st.caption(f"Lo que anotó el grabador: {clip['motivo_sin_clip']}.")
        if clip["enlace"]["direccion"]:
            st.caption("Ubicación del clip en el almacén:")
            st.code(clip["enlace"]["direccion"], language=None)
        return

    st.video(clip["enlace"]["url"], start_time=int(_segundo_de_arranque(detalle)))

    if clip["formato"] == "mkv":
        # El grabador escribe Matroska porque un corte de luz no se lleva el
        # fichero entero. El precio lo paga esta pantalla: Chrome y Edge lo
        # reproducen, Firefox y Safari no, y un recuadro negro sin explicacion
        # haria pensar que el clip se perdio.
        st.caption("Si el video no se reproduce en este navegador, ábralo en "
                   "Chrome o Edge, o descárguelo desde el menú del reproductor.")

    if clip["completo"] is False:
        # Se reproduce, pero no cubre toda la ventana. Quien lo mira tiene que
        # saberlo antes de concluir que no pasa nada en los minutos que faltan.
        st.warning(f"El clip cubre el {clip['cobertura_pct']:.0f} % de la "
                   f"ventana: faltaban tramos de la grabación.")
    st.caption(f"Por seguridad, el enlace al video caduca en "
               f"{clip['enlace']['minutos']} minuto(s). Si deja de reproducirse, "
               f"actualice la página.")


def _segundo_de_arranque(detalle: dict) -> float:
    """Donde abre el reproductor: la anomalia, o lo que el supervisor pidio."""
    return float(st.session_state.get(_clave_del_segundo(detalle["id"]),
                                      detalle["segundo_de_entrada"]))


def _clave_del_segundo(evento_id: int) -> str:
    """Por evento: dos eventos abiertos no comparten donde estaba cada uno."""
    return f"segundo_del_evento_{evento_id}"


def _ir_al_segundo(evento_id: int, segundo: float) -> None:
    """Callback del boton de salto.

    Tiene que ser un callback y no el valor que devuelve el boton: Streamlit
    ejecuta los callbacks antes de volver a dibujar la pagina, y el reproductor
    se dibuja arriba. Comprobando el boton despues, el salto se veria una
    interaccion mas tarde.
    """
    st.session_state[_clave_del_segundo(evento_id)] = segundo


MOTIVOS = {
    "saco_saliente": "un saco sale de la zona de carga",
    "pico_de_personas": "el momento con más gente en la zona",
    "primer_saco": "el primer saco de la carga",
    "ultimo_saco": "el último saco de la carga",
    "centro_del_clip": "el centro del clip",
}


def _fotogramas_del_detalle(detalle: dict) -> None:
    """Criterio 3: el fotograma de la anomalia, y los demas al lado.

    Cada uno trae un boton que abre el video en su segundo. Es la diferencia
    entre "aqui pasa algo" y "mira esto": sin el salto, el supervisor tiene que
    buscar a mano el instante dentro de siete minutos de video.
    """
    fotogramas = detalle.get("fotogramas") or []
    if not fotogramas:
        if detalle["clip"]["reproducible"]:
            st.caption("No hay fotogramas guardados de este evento.")
        return

    anomalia = detalle.get("anomalia") or {}
    st.markdown("**Fotogramas del análisis**")
    if anomalia.get("es_anomalia"):
        st.caption(f"El primero es el de la anomalía: "
                   f"{MOTIVOS.get(anomalia['motivo'], anomalia['motivo'])}, "
                   f"en el segundo {anomalia['segundo']:.0f}.")
    else:
        st.caption("Ninguno es una anomalía por sí mismo: son los momentos que "
                   "el sistema guardó para situarse en el video.")

    # De dos en dos: la evidencia comparte el ancho con la decision, y cuatro
    # en fila dejaban cada fotograma demasiado pequeno para distinguir nada.
    columnas = st.columns(2)
    for indice, imagen in enumerate(fotogramas):
        with columnas[indice % 2]:
            motivo = MOTIVOS.get(imagen["motivo"], imagen["motivo"] or "sin motivo")
            if imagen["enlace"]["reproducible"]:
                st.image(imagen["enlace"]["url"],
                         caption=f"Segundo {imagen['segundo']:.0f}: {motivo}",
                         use_container_width=True)
            else:
                st.info(f"{motivo}: {imagen['enlace']['explicacion']}")
            if imagen["detalle"]:
                st.caption(imagen["detalle"])
            if detalle["clip"]["reproducible"]:
                st.button(
                    f"Ver desde el segundo {imagen['segundo']:.0f}",
                    use_container_width=True,
                    key=f"salto_{detalle['id']}_{imagen['fotograma']}_{imagen['motivo']}",
                    on_click=_ir_al_segundo,
                    args=(detalle["id"], imagen["segundo"]))


def _analisis_del_detalle(detalle: dict) -> None:
    """Criterio 1: la descripcion y la severidad. HU-09.

    Las dos severidades se muestran juntas a proposito. La del evento sale de la
    RN-04 y es la que manda; la del modelo esta al lado para que el supervisor
    vea cuando discrepan, que es de donde sale la revision semanal del apartado
    9.2. Ensenar solo una esconderia justo el dato que sirve para mejorar.
    """
    analisis = detalle["analisis"]

    if analisis["severidad"]:
        st.write(f"Severidad: **{analisis['severidad'].capitalize()}**")

    if not analisis["hay_descripcion"]:
        if detalle["estado"] == "pendiente_analisis":
            st.info("La descripción automática no está disponible: el servicio de "
                    "análisis no respondió. La severidad se calculó igualmente.")
        elif detalle["clip"]["reproducible"]:
            st.caption("La descripción automática del video aún no está disponible.")
        return

    st.write(f"**Descripción del modelo:** {analisis['descripcion']}")
    if analisis["evidencia"]:
        st.write("Evidencia observada:")
        for punto in analisis["evidencia"]:
            st.write(f"- {punto}")

    if analisis["discrepan"]:
        st.warning(
            f"El modelo propuso severidad **{analisis['severidad_ia'].capitalize()}** "
            f"y la regla dice **{analisis['severidad'].capitalize()}**. Manda la "
            f"regla. Estas discrepancias son las que se revisan cada semana.")



def _personas_del_detalle(detalle: dict) -> None:
    """Criterio 1: las personas detectadas. HU-08, criterio 2.

    El aviso sobre los identificadores no es un adorno legal: quien lee
    "persona 1" tiene que saber que ese 1 no es nadie en concreto y que no vale
    fuera de este clip. Sin eso, la tabla invita a sacar conclusiones sobre
    gente, que es justo lo que la RN-08 y el apartado 8 quieren evitar.
    """
    personas = detalle["personas"]
    if not personas["analizado"]:
        return

    st.write(f"Personas en la zona de carga: **{personas['detectadas']}**")
    if personas["personal_anomalo"]:
        st.warning("La presencia de personal llamó la atención. Es un motivo "
                   "para mirar el clip, no una conclusión sobre nadie.")
    if not personas["presencias"]:
        st.caption("Nadie estuvo en la zona de carga durante el clip.")
        return

    st.dataframe(
        pd.DataFrame([{
            "Persona (id temporal)": p["id_temporal"],
            "Tiempo en zona (s)": float(p["segundos_en_zona"]),
            "Desde el fotograma": p["primer_fotograma"],
            "Hasta el fotograma": p["ultimo_fotograma"],
        } for p in personas["presencias"]]),
        use_container_width=True, hide_index=True)
    st.caption(f"{personas['nota']} Permanencia máxima "
               f"{float(personas['permanencia_maxima_s']):.0f} s, "
               f"{float(personas['segundos_totales']):.0f} s en total.")


def _avisos_del_evento(evento: dict) -> None:
    """Si se aviso al supervisor, a quien y cuanto se tardo. HU-10.

    Aparece aunque no haya aviso, y esa es la parte util. Un evento Alto sin
    correo enviado es un fallo que hoy solo se veria mirando los logs del
    grabador, y quien tiene que enterarse es el supervisor que esta delante de
    esta pantalla preguntandose por que nadie le dijo nada.
    """
    if not evento["severidad"]:
        return

    respuesta = pedir("GET", f"/eventos/{evento['id']}/avisos")
    if respuesta.status_code != 200:
        st.warning(detalle_del_error(respuesta))
        return
    avisos = respuesta.json()

    if not avisos["notificaciones"]:
        st.info("Todavía no ha salido ningún aviso de este evento.")
        return

    for aviso in avisos["notificaciones"]:
        cuando = (aviso["enviada_en"] or aviso["creado_en"])[11:19]
        if aviso["estado"] == "enviada":
            st.write(f"Aviso por {aviso['canal']} a las **{cuando}**, a "
                     f"**{len(aviso['destinatarios'])}** destinatario(s): "
                     f"{', '.join(aviso['destinatarios'])}")
            if aviso["segundos_desde_analisis"] is not None:
                segundos = float(aviso["segundos_desde_analisis"])
                if aviso["dentro_del_criterio"]:
                    st.caption(f"Enviado {segundos:.1f} s después del análisis.")
                else:
                    # No se esconde: el criterio 3 se mide con lo que pasa de
                    # verdad, y un aviso tardio hay que verlo antes de que sea
                    # costumbre.
                    st.warning(f"El aviso salió {segundos:.0f} s después del "
                               f"análisis, por encima de los 60 s previstos.")
        else:
            st.error(f"El aviso no salió ({aviso['intentos']} intento(s)): "
                     f"{aviso['error'] or 'sin detalle'}. Nadie ha recibido "
                     f"este evento por correo.")


def _clasificacion_del_evento(detalle: dict) -> None:
    """La decision del supervisor sobre el evento. HU-13.

      1. El cambio de estado exige un comentario de al menos 10 caracteres.
      2. Se registra el usuario y la fecha del cambio.
      3. Un evento Confirmado no puede volver al estado Pendiente.

    Va en la columna de al lado del video, debajo de las cifras: sigue siendo
    la conclusion, pero se escribe con la evidencia a la vista.

    Las opciones que se ofrecen salen de `clasificaciones_posibles`, que calcula
    la API. Repetir aqui la tabla de transiciones acabaria ofreciendo un boton
    que la API rechaza, y quien lo pulsa no tiene forma de saber cual de las dos
    pantallas esta equivocada.
    """
    st.markdown("#### Clasificación del evento")

    vigente = detalle["veredicto"]
    if vigente:
        quien = vigente["usuario_nombre"] or f"id {vigente['usuario_id']}"
        cuando = vigente["fecha"][:19].replace("T", " ")
        marca = " (corrección)" if vigente["es_correccion"] else ""
        st.success(f"**{NOMBRE_DEL_ESTADO.get(vigente['estado'], vigente['estado'])}**"
                   f"{marca}, por {quien} el {cuando}")
        st.caption(f"\"{vigente['comentario']}\"")
    else:
        st.info("Este evento aún no ha sido clasificado.")

    if len(detalle["decisiones"]) > 1:
        st.caption("Historial de decisiones")
        st.dataframe(
            pd.DataFrame([{
                "Fecha": d["fecha"][:19].replace("T", " "),
                "Decisión": NOMBRE_DEL_ESTADO.get(d["estado"], d["estado"]),
                "Venía de": NOMBRE_DEL_ESTADO.get(d["estado_anterior"], "Sin registrar"),
                "Usuario": d["usuario_nombre"] or f"id {d['usuario_id']}",
                "Comentario": d["comentario"],
            } for d in detalle["decisiones"]]),
            use_container_width=True, hide_index=True)

    posibles = detalle["clasificaciones_posibles"]
    if not puede_escribir():
        st.caption("El rol Consulta no clasifica eventos.")
        return
    if not posibles:
        st.caption("Este evento no admite más cambios de estado.")
        return

    # Las claves llevan el id del evento: dos eventos abiertos uno tras otro no
    # comparten ni la opcion marcada ni el comentario a medio escribir.
    clave_estado = f"estado_del_veredicto_{detalle['id']}"
    clave_comentario = f"comentario_del_veredicto_{detalle['id']}"
    with st.form(f"clasificar_{detalle['id']}"):
        st.radio(
            "Resultado de la revisión", posibles, key=clave_estado,
            format_func=lambda e: NOMBRE_DE_LA_DECISION.get(e, NOMBRE_DEL_ESTADO.get(e, e)))
        if "confirmado" in posibles:
            # Criterio 3 de HU-13. La regla ya existia en la API; lo que faltaba
            # era decirla antes de pulsar, no despues en un mensaje de error.
            st.caption("Confirmar la discrepancia cierra el caso: después no podrá "
                       "devolverlo a Pendiente.")
        # El minimo va en la etiqueta porque dentro de un formulario Streamlit no
        # redibuja mientras se escribe: un contador de "faltan N" no avanzaria.
        # El maximo si lo cuenta el propio cuadro de texto.
        st.text_area(
            "Justificación (mínimo 10 caracteres)", max_chars=1000, height=110,
            key=clave_comentario,
            placeholder="Describa qué comprobó y dónde.",
            help="Es lo que se leerá cuando se audite este evento dentro de "
                 "unos meses.")
        # El envio es un callback y no el valor que devuelve el boton, por lo
        # mismo que el salto de HU-12: Streamlit ejecuta los callbacks antes de
        # volver a dibujar, asi que la peticion sale antes de que esta pantalla
        # pida el detalle y lo que se ve debajo ya es el estado nuevo.
        # Comprobandolo despues, la decision se veria una interaccion mas tarde.
        st.form_submit_button(
            "Registrar clasificación", type="primary",
            on_click=_guardar_clasificacion,
            args=(detalle["id"], clave_estado, clave_comentario))


def _guardar_clasificacion(evento_id: int, clave_estado: str,
                           clave_comentario: str) -> None:
    """Envia la decision y deja el resultado para que lo pinte la pasada nueva."""
    estado = st.session_state.get(clave_estado)
    comentario = st.session_state.get(clave_comentario) or ""

    # El minimo se comprueba antes de salir a la red: el aviso llega al instante
    # y la API lo vuelve a comprobar igual, que es donde manda.
    if len(comentario.strip()) < 10:
        st.session_state[RESULTADO_CLASIFICACION] = (
            "aviso", "La justificación necesita al menos 10 caracteres. "
                     "Explique en qué se basa la decisión.")
        return

    resultado = pedir("POST", f"/eventos/{evento_id}/veredicto",
                      json={"estado_nuevo": estado, "comentario": comentario})
    if resultado.status_code == 201:
        hecho = resultado.json()
        nombre = NOMBRE_DEL_ESTADO.get(hecho["estado"], hecho["estado"])
        st.session_state[RESULTADO_CLASIFICACION] = (
            "ok", f"Evento #{hecho['evento_id']} clasificado como {nombre}.")
        # El comentario ya esta guardado: dejarlo en el cuadro invitaria a
        # enviarlo otra vez como si fuera una decision nueva.
        st.session_state[clave_comentario] = ""
    else:
        st.session_state[RESULTADO_CLASIFICACION] = (
            "error", detalle_del_error(resultado))


# ----------------------------------------------------------------- pesadas
# Lo que el panel recuerda entre redibujados: la orden consultada y el
# resultado de la ultima pesada. Streamlit vuelve a correr el script en cada
# clic, y sin esto el resultado desapareceria en cuanto el operador toca algo.
ORDEN_CONSULTADA = "pesadas_orden"
ULTIMA_PESADA = "pesadas_ultima"
ERROR_DE_PESADA = "pesadas_error"
# La ultima lectura previa de la bascula: {"numero_orden", "datos"}. Se guarda
# con la orden para no ensenar el peso de un camion al consultar el siguiente.
LECTURA_PREVIA = "pesadas_lectura_previa"
# Ordenes que se van a pesar sin marcar el inicio de la carga. La API lo admite
# ("sin marca la pesada se registra igual"), asi que la pantalla no lo bloquea,
# pero pide decirlo en vez de dejarlo pasar por descuido.
SIN_MARCA_DE_INICIO = "pesadas_sin_marca"
# Lo minimo que se le pide a quien escribe un peso a mano. Un motivo de dos
# letras no le sirve a nadie que revise el caso meses despues.
MINIMO_MOTIVO_MANUAL = 10


def panel_de_pesadas() -> None:
    """Registro de pesadas al cerrar una carga. HU-01, con HU-02 y HU-03.

    Hasta ahora la pesada solo entraba por la API: el criterio 1 de HU-01 se
    cumplia, pero en la rampa no habia donde pulsar. Esta pantalla sigue el
    orden real del despacho: consultar la orden, marcar el inicio de la carga,
    y al cerrarla leer la bascula. El registro manual existe para cuando la
    bascula falla, y exige un motivo porque queda en la auditoria con el nombre
    de quien lo escribio.

    Desde la fase 5 de la critica de UX (15/11/2026) los tres pasos se abren de
    uno en uno. Antes estaban los tres a la vista a la vez y la barra de pasos
    solo informaba: se podia pulsar "Registrar pesada" con la carga sin marcar
    sin que nada lo hiciera notar.
    """
    st.markdown("### Registro de pesada")

    if puede_escribir():
        # Los pasos van arriba pero se pintan despues de la consulta, para que
        # reflejen la orden recien consultada en esta misma pasada.
        lugar_de_los_pasos = st.empty()
        orden = st.session_state.get(ORDEN_CONSULTADA)
        if orden:
            _orden_en_curso(orden)
        else:
            _consulta_de_la_orden()
            orden = st.session_state.get(ORDEN_CONSULTADA)
            if orden:
                # Recien consultada: se redibuja para pasar al paso siguiente.
                st.rerun()
        abierta = _carga_abierta_de(orden["numero_orden"]) if orden else None
        pesada = st.session_state.get(ULTIMA_PESADA)
        hecha = bool(pesada and orden and pesada["numero_orden"] == orden["numero_orden"])
        sin_marca = bool(orden) and orden["numero_orden"] in st.session_state.get(
            SIN_MARCA_DE_INICIO, ())
        with lugar_de_los_pasos.container():
            _pasos_de_la_pesada(orden, abierta or sin_marca, pesada)
        if hecha:
            # La carga ya se cerro: el resultado ocupa el lugar de los pasos,
            # para que nadie vuelva a pulsar "Marcar inicio" creyendo que la
            # pesada no se guardo.
            _resultado_de_la_pesada(pesada)
            if st.button("Registrar otra pesada", type="primary"):
                _olvidar_la_orden()
                st.rerun()
        elif orden and not (abierta or sin_marca):
            _inicio_de_la_carga(orden)
        elif orden:
            if abierta:
                _reloj_de_la_carga(dt.datetime.fromisoformat(abierta["inicio"]),
                                   abierta["bascula_id"])
            else:
                st.caption("Pesada sin marca de inicio: el video del evento cubrirá "
                           "solo los 5 minutos previos al cierre.")
            _cierre_de_la_carga(orden)
            if error := st.session_state.get(ERROR_DE_PESADA):
                st.error(error)
    else:
        st.info("El rol Consulta ve el historial de pesadas, pero no las registra.")

    st.divider()
    _historial_de_pesadas()


def _olvidar_la_orden() -> None:
    """Vuelve al paso 1. Se lleva la lectura previa: es de esa orden."""
    for clave in (ORDEN_CONSULTADA, ULTIMA_PESADA, ERROR_DE_PESADA, LECTURA_PREVIA):
        st.session_state.pop(clave, None)


def _orden_en_curso(orden: dict) -> None:
    """El paso 1 ya hecho, en una linea, con la salida para corregirlo."""
    with st.container(border=True):
        datos, cambiar = st.columns([8, 2], vertical_alignment="center")
        datos.markdown(
            f"**{orden['numero_orden']}** · {orden['cliente']} · {orden['producto']}  \n"
            f"Peso esperado **{float(orden['peso_esperado_kg']):,.0f} kg** en "
            f"**{orden['sacos_esperados']}** sacos · orden del {orden['fecha']}")
        datos.caption("Datos del ERP, actualizados el "
                      f"{orden['sincronizado_en'][:19].replace('T', ' ')}.")
        cambiar.button("Cambiar orden", use_container_width=True,
                       on_click=_olvidar_la_orden)


def _pasos_de_la_pesada(orden: dict | None, abierta: dict | None,
                        pesada: dict | None) -> None:
    """Orden, carga y peso: donde esta el operador y que le falta."""
    hecha = bool(pesada and orden and pesada["numero_orden"] == orden["numero_orden"])
    estados = ["hecho" if orden else "actual",
               "hecho" if (abierta or hecha) else ("actual" if orden else ""),
               "hecho" if hecha else ("actual" if abierta else "")]
    nombres = ["1 · Orden", "2 · Carga", "3 · Pesaje"]
    celdas = "".join(f'<div class="q-pp {e}">{"✓ " if e == "hecho" else ""}{n}</div>'
                     for n, e in zip(nombres, estados))
    st.markdown(f'<div class="q-pasos-pesada">{celdas}</div>', unsafe_allow_html=True)


def _consulta_de_la_orden() -> None:
    with st.form("consultar_orden"):
        columnas = st.columns([3, 1])
        numero = columnas[0].text_input(
            "Número de orden de despacho", placeholder="ORD-2026-0001",
            value=(st.session_state.get(ORDEN_CONSULTADA) or {}).get("numero_orden", ""))
        columnas[1].write("")      # alinea el boton con la caja de texto
        consultar = columnas[1].form_submit_button("Consultar orden", type="primary",
                                                   use_container_width=True)
    if not consultar:
        return
    numero = numero.strip()
    st.session_state.pop(ULTIMA_PESADA, None)
    st.session_state.pop(ERROR_DE_PESADA, None)
    if not numero:
        st.warning("Ingrese el número de orden.")
        return
    respuesta = pedir("GET", f"/ordenes/{numero}")
    if respuesta.status_code == 200:
        st.session_state[ORDEN_CONSULTADA] = respuesta.json()
    else:
        # Criterio 2 de HU-02: la orden que el ERP no reconoce no se pesa.
        st.session_state.pop(ORDEN_CONSULTADA, None)
        st.error(detalle_del_error(respuesta))


def _carga_abierta_de(numero_orden: str) -> dict | None:
    respuesta = pedir("GET", "/cargas", params={"solo_abiertas": True, "limite": 500})
    if respuesta.status_code != 200:
        return None
    for carga in respuesta.json():
        if carga["numero_orden"] == numero_orden:
            return carga
    return None


def _marcar_sin_inicio(numero_orden: str) -> None:
    st.session_state[SIN_MARCA_DE_INICIO] = (
        set(st.session_state.get(SIN_MARCA_DE_INICIO, ())) | {numero_orden})


def _inicio_de_la_carga(orden: dict) -> None:
    """Paso 2: la marca de inicio. Sin ella el clip de HU-06 solo cubre los 5
    minutos previos al cierre.

    Se puede saltar, porque la API registra la pesada igual, pero hay que
    decirlo: el boton secundario deja claro lo que se pierde.
    """
    st.markdown("##### Carga")
    st.caption("Inicie la carga al subir el primer saco. El video del evento "
               "cubrirá desde 5 minutos antes de este momento.")
    iniciar, saltar, _ = st.columns([2, 3, 3])
    if iniciar.button("Iniciar carga", type="primary", use_container_width=True):
        respuesta = pedir("POST", f"/cargas/{orden['numero_orden']}/inicio", json={})
        if respuesta.status_code == 201:
            st.rerun()
        else:
            st.error(detalle_del_error(respuesta))
    saltar.button("La carga ya terminó: pesar sin marcar el inicio",
                  use_container_width=True, on_click=_marcar_sin_inicio,
                  args=(orden["numero_orden"],))


@st.fragment(run_every=1)
def _reloj_de_la_carga(inicio: dt.datetime, bascula: str) -> None:
    """El tiempo de carga avanza solo, sin pulsar Actualizar.

    Es un fragmento: Streamlit lo vuelve a dibujar cada segundo sin repetir el
    resto de la pagina (ni sus llamadas a la API).
    """
    segundos = max(0, int((dt.datetime.now() - inicio).total_seconds()))
    with st.container(border=True):
        # El reloj acompana, no manda: a 64 px era lo mas grande de la pantalla
        # y el tiempo de carga no es el dato con el que se decide nada.
        izquierda, derecha = st.columns([5, 1], vertical_alignment="center")
        izquierda.markdown(
            f'<span class="q-vivo"><i></i>Carga en curso desde las {inicio:%H:%M} '
            f'· báscula {bascula}</span>', unsafe_allow_html=True)
        izquierda.caption("Al terminar de cargar, lea la báscula.")
        derecha.markdown(f'<div class="q-reloj">{segundos // 60:02d}:{segundos % 60:02d}</div>',
                         unsafe_allow_html=True)


def _aviso_previo(orden: dict, peso: float | None) -> None:
    """Antes de guardar, dice si esa pesada va a abrir un caso. RN-01."""
    if peso is None:
        # Sin peso no hay nada que comparar. Decir "dentro de la tolerancia"
        # sobre un valor que nadie escribio seria dar por buena una carga que
        # no se ha pesado.
        st.caption("Escriba el peso leído para saber si generará un evento.")
        return
    esperado = float(orden["peso_esperado_kg"])
    respuesta = pedir("GET", f"/configuracion/{orden['producto']}/aplicada",
                      params={"peso_esperado_kg": esperado})
    if respuesta.status_code != 200:
        return
    tolerancia = float(respuesta.json()["tolerancia_efectiva_kg"])
    diferencia = peso - esperado
    if abs(diferencia) > tolerancia:
        st.error(f"Diferencia de {diferencia:+,.0f} kg: supera la tolerancia de "
                 f"{tolerancia:,.0f} kg. Al registrar la pesada se generará un evento de "
                 "discrepancia y se iniciará el análisis del video.")
    else:
        st.success(f"Diferencia de {diferencia:+,.0f} kg: dentro de la tolerancia de "
                   f"{tolerancia:,.0f} kg. No se generará ningún evento.")


def _leer_la_bascula(numero_orden: str) -> None:
    """Pide la lectura previa. Es un callback para que el resultado ya este en
    la sesion cuando se redibuja la pantalla."""
    st.session_state.pop(ERROR_DE_PESADA, None)
    st.session_state.pop(LECTURA_PREVIA, None)
    try:
        respuesta = pedir("POST", "/pesadas/lectura-previa",
                          json={"numero_orden": numero_orden})
    except httpx.HTTPError:
        st.session_state[ERROR_DE_PESADA] = (
            "No hay conexión con el sistema. Intente leer la báscula de nuevo.")
        return
    if respuesta.status_code == 200:
        st.session_state[LECTURA_PREVIA] = {"numero_orden": numero_orden,
                                            "datos": respuesta.json()}
    elif respuesta.status_code == 503:
        st.session_state[ERROR_DE_PESADA] = (
            "La báscula no respondió. La falla quedó registrada en Estado del sistema. "
            "Puede leerla de nuevo o registrar el peso mediante «Ingreso manual». "
            f"Detalle: {detalle_del_error(respuesta)}")
    else:
        st.session_state[ERROR_DE_PESADA] = detalle_del_error(respuesta)


def _registrar_la_pesada(cuerpo: dict) -> None:
    st.session_state.pop(ULTIMA_PESADA, None)
    st.session_state.pop(ERROR_DE_PESADA, None)
    with st.spinner("Registrando la pesada..."):
        respuesta = pedir("POST", "/pesadas", json=cuerpo)
    if respuesta.status_code == 201:
        st.session_state[ULTIMA_PESADA] = respuesta.json()
        st.session_state.pop(LECTURA_PREVIA, None)
    elif respuesta.status_code == 503:
        st.session_state[ERROR_DE_PESADA] = (
            "La báscula no respondió. La falla quedó registrada en Estado del sistema. "
            "Puede reintentar o registrar el peso mediante «Ingreso manual». "
            f"Detalle: {detalle_del_error(respuesta)}")
    else:
        st.session_state[ERROR_DE_PESADA] = detalle_del_error(respuesta)
    st.rerun()


def _pesaje_con_bascula(orden: dict) -> None:
    """Leer primero, registrar despues.

    La lectura previa (POST /pesadas/lectura-previa) deja ver si la pesada va a
    abrir un evento antes de confirmarla, que es lo que el ingreso manual ya
    ofrecia. A cambio, cada lectura queda en la auditoria con el usuario, y la
    pantalla lo dice: quien mira el peso y no registra deja rastro.

    Al registrar, la API vuelve a leer la bascula. El peso de esta pantalla es
    orientativo y nunca se envia.
    """
    previa = st.session_state.get(LECTURA_PREVIA)
    if not previa or previa["numero_orden"] != orden["numero_orden"]:
        st.caption("Lea la báscula para ver el peso y saber si la pesada generará un "
                   "evento. Cada lectura queda registrada con su usuario.")
        st.button("Leer báscula", type="primary", on_click=_leer_la_bascula,
                  args=(orden["numero_orden"],))
        return

    datos = previa["datos"]
    hora = datos["leido_en"][11:19]
    with st.container(border=True):
        peso, comparacion = st.columns([3, 4], vertical_alignment="center")
        peso.caption(f"Lectura de la báscula {datos['bascula_id']} a las {hora}")
        peso.markdown(f"<div class='q-lectura'>{float(datos['peso_kg']):,.0f} kg</div>",
                      unsafe_allow_html=True)
        if not datos["estable"]:
            # Convencion 7: con la bascula en movimiento el numero no es un dato.
            st.warning("La báscula sigue en movimiento: este peso todavía no es "
                       "válido. Espere a que se estabilice y léala de nuevo.")
        else:
            esperado, real = comparacion.columns(2)
            esperado.metric("Esperado según la orden",
                            f"{float(datos['peso_esperado_kg']):,.0f} kg")
            diferencia = float(datos["diferencia_kg"])
            real.metric("Diferencia", f"{diferencia:+,.0f} kg",
                        delta=f"{float(datos['diferencia_pct']):+.2f} %",
                        delta_color="off")
            if datos["generaria_evento"] is None:
                st.warning("Este producto no tiene tolerancia configurada: no se puede "
                           "saber si la pesada generará un evento. Avise al administrador.")
            elif datos["generaria_evento"]:
                st.error(f"**Supera la tolerancia de {float(datos['tolerancia_kg']):,.0f} kg.** "
                         "Al registrar la pesada se generará un evento de discrepancia "
                         "y se analizará el video de la carga.")
            else:
                st.success(f"Dentro de la tolerancia de {float(datos['tolerancia_kg']):,.0f} "
                           "kg. No se generará ningún evento.")

    registrar, releer, _ = st.columns([3, 2, 3])
    pulsado = registrar.button("Registrar pesada y cerrar carga", type="primary",
                               use_container_width=True, disabled=not datos["estable"])
    releer.button("Leer de nuevo", use_container_width=True,
                  on_click=_leer_la_bascula, args=(orden["numero_orden"],))
    st.caption("Al registrar, el sistema vuelve a leer la báscula: el peso guardado es "
               "el de ese momento. Esta lectura quedó registrada con su usuario.")
    if pulsado:
        _registrar_la_pesada({"numero_orden": orden["numero_orden"]})


def _pesaje_manual(orden: dict) -> None:
    st.caption("Utilice el ingreso manual solo si la báscula no responde. El "
               "registro queda identificado como manual, con su usuario y el motivo.")
    # El campo empieza vacio. Antes venia con el peso esperado de la orden,
    # y el aviso de abajo salia en verde sin que nadie hubiera escrito nada:
    # en un control contra la sustraccion, el valor por defecto no puede ser
    # justo el que esconde el faltante.
    peso = st.number_input(
        "Peso real (kg)", min_value=0.0, max_value=999999.99, step=10.0,
        value=None, format="%.2f",
        placeholder="Escriba el peso leído en la balanza auxiliar")
    motivo = st.text_area(
        "Motivo del ingreso manual", height=80,
        placeholder="Ej.: báscula sin respuesta; pesaje en balanza auxiliar")
    faltan = MINIMO_MOTIVO_MANUAL - len((motivo or "").strip())
    st.caption(f"Mínimo {MINIMO_MOTIVO_MANUAL} caracteres (faltan {faltan})."
               if faltan > 0 else "Motivo válido.")
    _aviso_previo(orden, peso)
    if not st.button("Registrar pesada", type="primary"):
        return
    if peso is None:
        st.warning("Escriba el peso real antes de registrar la pesada.")
        return
    if len((motivo or "").strip()) < MINIMO_MOTIVO_MANUAL:
        st.warning(f"Indique el motivo del ingreso manual "
                   f"(mínimo {MINIMO_MOTIVO_MANUAL} caracteres).")
        return
    _registrar_la_pesada({"numero_orden": orden["numero_orden"],
                          "peso_real_kg": round(peso, 2),
                          "motivo_manual": motivo.strip()})


def _cierre_de_la_carga(orden: dict) -> None:
    """Paso 3: el pesaje, con bascula o a mano."""
    st.markdown("##### Pesaje")
    origen = st.segmented_control(
        "Origen del peso", ["Báscula", "Ingreso manual"],
        default="Báscula",
        help="El ingreso manual es para cuando la báscula no responde. Queda "
             "identificado como manual, con su usuario, en la auditoría.")
    if origen == "Ingreso manual":
        _pesaje_manual(orden)
    else:
        _pesaje_con_bascula(orden)


def _resultado_de_la_pesada(pesada: dict) -> None:
    st.markdown("##### Resultado de la pesada")
    real, esperado = float(pesada["peso_real_kg"]), float(pesada["peso_esperado_kg"])
    cifras = st.columns(4)
    cifras[0].metric("Peso real", f"{real:,.2f} kg")
    cifras[1].metric("Peso esperado", f"{esperado:,.2f} kg")
    cifras[2].metric("Diferencia", f"{real - esperado:+,.2f} kg")
    cifras[3].metric("Origen", "Báscula" if pesada["origen"] == "bascula" else "Manual")
    st.caption(f"Pesada #{pesada['id']} - {pesada['fecha_hora'][:19].replace('T', ' ')} - "
               f"báscula {pesada['bascula_id']} - orden {pesada['numero_orden']}")

    evento = pesada.get("evento")
    if evento:
        # HU-03: el aviso viaja en la misma respuesta de la pesada. El criterio 3
        # pide crearlo en menos de 10 s; se muestra cuanto tardo de verdad.
        segundos = (dt.datetime.fromisoformat(evento["creado_en"])
                    - dt.datetime.fromisoformat(evento["pesada_fecha_hora"])).total_seconds()
        tolerancia = evento.get("tolerancia_aplicada_kg")
        umbral = (f"por encima de la tolerancia de {float(tolerancia):,.2f} kg"
                  if tolerancia is not None else "fuera de la tolerancia del producto")
        st.error(
            f"**Evento de discrepancia #{evento['id']} creado** en {max(segundos, 0):.2f} s. "
            f"Diferencia de {float(evento['diferencia_kg']):+,.2f} kg "
            f"({float(evento['diferencia_pct']):+.2f} %), {umbral}. "
            "El sistema recorta el video y lo analiza; el caso aparece en Eventos.")
    elif not pesada.get("evaluada", True):
        st.warning(f"Pesada registrada, pero sin evaluar: {pesada.get('motivo_sin_evaluar')}")
    else:
        st.success("Pesada registrada. La diferencia está dentro de la tolerancia del "
                   "producto: no se crea evento.")


def _eventos_por_pesada() -> dict[int, int] | None:
    """Que pesada abrio que evento, o None si no se pudo saber.

    Una sola llamada para toda la tabla (convencion 9): `GET /pesadas` no trae
    el evento, y pedirlo fila a fila serian veinte peticiones.
    """
    try:
        respuesta = pedir("GET", "/eventos", params={"limite": 100})
    except httpx.HTTPError:
        return None
    if respuesta.status_code != 200:
        return None
    return {e["pesada_id"]: e["id"] for e in respuesta.json()}


def _historial_de_pesadas() -> None:
    st.markdown("##### Últimas pesadas")
    respuesta = pedir("GET", "/pesadas", params={"limite": 20})
    if respuesta.status_code != 200:
        st.error(detalle_del_error(respuesta))
        return
    pesadas = respuesta.json()
    if not pesadas:
        st.info("Todavía no hay pesadas registradas.")
        return
    eventos = _eventos_por_pesada()

    def resultado(pesada: dict) -> str:
        # Convencion 7: si no se pudo consultar, no se afirma "sin evento".
        if eventos is None:
            return "No disponible"
        return f"Evento #{eventos[pesada['id']]}" if pesada["id"] in eventos else "Sin evento"

    # El resultado va el primero: es lo que se busca en esta tabla. Antes habia
    # que restar dos columnas de cabeza para saber que pesada abrio un caso.
    st.dataframe(
        pd.DataFrame([{
            "Resultado": resultado(p),
            "Fecha y hora": p["fecha_hora"][:19].replace("T", " "),
            "Orden": p["numero_orden"],
            "Cliente": p["cliente"],
            "Diferencia (kg)": round(float(p["peso_real_kg"]) - float(p["peso_esperado_kg"]), 2),
            "Peso real (kg)": float(p["peso_real_kg"]),
            "Esperado (kg)": float(p["peso_esperado_kg"]),
            "Origen": "Báscula" if p["origen"] == "bascula" else "Manual",
            "Báscula": p["bascula_id"],
            "ID": p["id"],
        } for p in pesadas]),
        use_container_width=True, hide_index=True,
        column_config={c: st.column_config.NumberColumn(format="%.2f")
                       for c in ("Peso real (kg)", "Esperado (kg)", "Diferencia (kg)")})
    if eventos is None:
        st.caption("No se pudo consultar qué pesadas abrieron un evento.")


# ----------------------------------------------------------------- ordenes
def panel_de_ordenes() -> None:
    """Ordenes de despacho del ERP. HU-02.

    La pestana Pesadas ya consulta la orden antes de pesar; esta deja ver lo que
    hay detras: la copia local que el sistema guarda de cada orden, cuando se
    sincronizo, y las pesadas que se hicieron contra ella. El criterio 3 pide que
    la respuesta del ERP quede junto a la pesada: aqui se ve con que peso y con
    cuantos sacos esperados se juzgo cada una.
    """
    st.subheader("Órdenes de despacho")
    st.caption("Órdenes obtenidas del ERP. Se conserva una copia local por si el ERP "
               "no está disponible.")

    with st.form("consultar_erp"):
        columnas = st.columns([3, 2, 1])
        numero = columnas[0].text_input("Número de orden", placeholder="ORD-2026-0001")
        refrescar = columnas[1].checkbox(
            "Consultar al ERP aunque haya copia local", value=True,
            help="Sin marcar, se usa la copia local mientras siga vigente.")
        columnas[2].write("")
        consultar = columnas[2].form_submit_button("Consultar", type="primary",
                                                   use_container_width=True)
    if consultar and numero.strip():
        respuesta = pedir("GET", f"/ordenes/{numero.strip()}",
                          params={"refrescar": refrescar})
        if respuesta.status_code == 200:
            orden = respuesta.json()
            st.success(f"El ERP devolvió la orden {orden['numero_orden']}: "
                       f"{orden['cliente']} - {orden['producto']}.")
            cifras = st.columns(3)
            cifras[0].metric("Peso esperado", f"{float(orden['peso_esperado_kg']):,.2f} kg")
            cifras[1].metric("Sacos esperados", orden["sacos_esperados"])
            cifras[2].metric("Fecha de la orden", orden["fecha"])
            st.caption("Copia local sincronizada el "
                       f"{orden['sincronizado_en'][:19].replace('T', ' ')}.")
            _pesadas_de_la_orden(orden["numero_orden"])
        else:
            # Criterio 2: la orden que el ERP no reconoce no se pesa, asi que
            # tampoco puede dar lugar a un evento.
            st.error(f"{detalle_del_error(respuesta)}. Sin orden válida no se registra "
                     "la pesada ni se crea evento.")

    st.markdown("##### Copia local de órdenes")
    respuesta = pedir("GET", "/ordenes", params={"limite": 100})
    if respuesta.status_code != 200:
        st.error(detalle_del_error(respuesta))
        return
    ordenes = respuesta.json()
    if not ordenes:
        st.info("Todavía no se ha consultado ninguna orden al ERP.")
        return
    st.dataframe(
        pd.DataFrame([{
            "Orden": o["numero_orden"],
            "Cliente": o["cliente"],
            "Producto": o["producto"],
            "Peso esperado (kg)": float(o["peso_esperado_kg"]),
            "Sacos esperados": o["sacos_esperados"],
            "Fecha": o["fecha"],
            "Sincronizada": o["sincronizado_en"][:19].replace("T", " "),
        } for o in ordenes]),
        use_container_width=True, hide_index=True,
        column_config={"Peso esperado (kg)": st.column_config.NumberColumn(format="%.2f")})


def _pesadas_de_la_orden(numero_orden: str) -> None:
    respuesta = pedir("GET", "/pesadas", params={"numero_orden": numero_orden, "limite": 50})
    if respuesta.status_code != 200 or not respuesta.json():
        st.caption("Esta orden todavía no tiene pesadas.")
        return
    st.markdown(f"Pesadas de {numero_orden}, con lo que el ERP esperaba en ese momento:")
    st.dataframe(
        pd.DataFrame([{
            "Pesada": p["id"],
            "Fecha y hora": p["fecha_hora"][:19].replace("T", " "),
            "Peso real (kg)": float(p["peso_real_kg"]),
            "Esperado según ERP (kg)": float(p["peso_esperado_kg"]),
            "Origen": "Báscula" if p["origen"] == "bascula" else "Manual",
        } for p in respuesta.json()]),
        use_container_width=True, hide_index=True,
        column_config={c: st.column_config.NumberColumn(format="%.2f")
                       for c in ("Peso real (kg)", "Esperado según ERP (kg)")})


# ------------------------------------------------------------------- video
# Como se nombran en GET /salud los componentes que escribe el grabador.
PREFIJO_CAMARA = "camara"
COMPONENTE_DISCO = "disco-video"


def panel_de_video() -> None:
    """Grabacion, clips y conteo de sacos. HU-05, HU-06 y HU-07.

    Las tres historias viven en el grabador, que no tiene pantalla: escribe su
    estado en salud_componente y sus resultados en el evento. Esta pestana lo
    junta en un solo sitio, para responder de un vistazo a las tres preguntas
    del supervisor: si las camaras estan grabando, si cada evento tiene su clip
    y cuantos sacos se vieron cruzar.
    """
    _grabacion_continua()
    st.divider()
    _clips_y_conteo()


def _grabacion_continua() -> None:
    st.subheader("Grabación continua")
    st.caption("Las cámaras graban de forma continua y se conservan al menos las "
               "últimas 72 horas. Las interrupciones se registran aquí.")
    respuesta = pedir("GET", "/salud")
    if respuesta.status_code != 200:
        st.error(detalle_del_error(respuesta))
        return
    componentes = respuesta.json()["componentes"]
    camaras = [c for c in componentes if c["componente"].startswith(PREFIJO_CAMARA)]
    disco = next((c for c in componentes if c["componente"] == COMPONENTE_DISCO), None)

    if not camaras:
        st.warning("El grabador todavía no ha informado de ninguna cámara. "
                   "Compruebe que el servicio grabador esté en marcha.")
    columnas = st.columns(max(len(camaras), 1) + (1 if disco else 0))
    for columna, camara in zip(columnas, camaras):
        with columna.container(border=True):
            estado = "Grabando" if camara["estado"] == "ok" else "Sin señal"
            icono = ":green[●]" if camara["estado"] == "ok" else ":red[●]"
            st.markdown(f"{icono} **{camara['componente']}** - {estado}")
            st.caption(camara["mensaje"])
    if disco:
        with columnas[-1].container(border=True):
            icono = ":green[●]" if disco["estado"] == "ok" else ":red[●]"
            st.markdown(f"{icono} **Almacén de grabación**")
            st.caption(disco["mensaje"])

    # Historial de las camaras: solo se guardan los cambios de estado, asi que
    # cada fila es una caida o una recuperacion, no un latido.
    filas = []
    for camara in camaras:
        r = pedir("GET", "/salud/historial", params={"componente": camara["componente"],
                                                     "limite": 20})
        if r.status_code == 200:
            filas += r.json()
    if filas:
        filas.sort(key=lambda f: f["verificado_en"], reverse=True)
        with st.expander("Historial de caídas y recuperaciones de las cámaras"):
            st.dataframe(
                pd.DataFrame([{
                    "Fecha y hora": str(f["verificado_en"])[:19].replace("T", " "),
                    "Cámara": f["componente"],
                    "Estado": "Grabando" if f["estado"] == "ok" else "Sin señal",
                    "Detalle": f["mensaje"],
                } for f in filas[:30]]),
                use_container_width=True, hide_index=True)


def _situacion_del_clip(evento: dict) -> str:
    if evento["estado"] == "sin_clip":
        return "Sin clip"
    if evento.get("clip_url"):
        return "Vinculado"
    return "Pendiente de recorte"


def _situacion_del_conteo(evento: dict, clip: str) -> str:
    # NULL no es cero: un conteo vacio significa que no se miro, no que el
    # camion saliera sin sacos.
    if evento.get("sacos_contados") is not None:
        return "Contado"
    if clip == "Vinculado":
        return "Pendiente de conteo"
    return "-"


def _o_guion(valor, signo: bool = False) -> str:
    if valor is None:
        return "-"
    return f"{valor:+d}" if signo else str(valor)


def _clips_y_conteo() -> None:
    st.subheader("Clips y conteo de sacos")
    st.caption("Por cada evento se guarda el video desde 5 minutos antes del inicio de "
               "la carga hasta 2 minutos después del cierre, y se cuentan los sacos que "
               "cruzan la línea de carga.")
    respuesta = pedir("GET", "/eventos", params={"limite": 50})
    if respuesta.status_code != 200:
        st.error(detalle_del_error(respuesta))
        return
    eventos = respuesta.json()
    if not eventos:
        st.info("Todavía no hay eventos de discrepancia.")
        return

    filas = []
    for e in eventos:
        clip = _situacion_del_clip(e)
        desde, hasta = e.get("clip_desde"), e.get("clip_hasta")
        minutos = None
        if desde and hasta:
            minutos = round((dt.datetime.fromisoformat(hasta)
                             - dt.datetime.fromisoformat(desde)).total_seconds() / 60, 1)
        filas.append({
            "Evento": e["id"],
            "Fecha": e["creado_en"][:16].replace("T", " "),
            "Orden": e["numero_orden"],
            "Clip": clip,
            "Ventana": (f"{desde[11:16]} a {hasta[11:16]}" if desde and hasta else "-"),
            "Duración (min)": f"{minutos:.1f}" if minutos is not None else "-",
            "Conteo": _situacion_del_conteo(e, clip),
            # Como texto, para que lo que no se midio salga como "-" y no como
            # un cero o un "None": NULL no es cero.
            "Sacos orden": _o_guion(e.get("sacos_esperados")),
            "Sacos video": _o_guion(e.get("sacos_contados")),
            "Dif. sacos": _o_guion(e.get("diferencia_sacos"), signo=True),
        })
    tabla = pd.DataFrame(filas)

    cifras = st.columns(4)
    cifras[0].metric("Eventos", len(tabla))
    cifras[1].metric("Con clip", int((tabla["Clip"] == "Vinculado").sum()))
    cifras[2].metric("Sin clip", int((tabla["Clip"] == "Sin clip").sum()),
                     help="Faltó video de más de la mitad de la carga: no había "
                          "grabación de ese periodo o la cámara estaba fuera de servicio.")
    cifras[3].metric("Con conteo", int((tabla["Conteo"] == "Contado").sum()))

    st.dataframe(tabla, use_container_width=True, hide_index=True)
    st.caption("El video de cada evento se reproduce en Eventos, al abrir el evento.")


# -------------------------------------------------------------- tolerancias
NOMBRE_DEL_CANAL = {"sms": "SMS", "slack": "Slack", "correo": "Correo"}


def _canales_en_texto(canales: dict | None) -> str:
    """El mapa de la RN-04 en una linea legible, en lugar del JSON crudo."""
    if not canales:
        return "Sin canales configurados"
    partes = []
    for severidad in ("alta", "media", "baja"):
        nombres = [NOMBRE_DEL_CANAL.get(c, c) for c in canales.get(severidad) or []]
        partes.append(f"{severidad.capitalize()}: {', '.join(nombres) or 'sin aviso'}")
    return " · ".join(partes)


def panel_de_tolerancias(editable: bool) -> None:
    """Pantalla del criterio 1 de HU-04: tolerancia en kg y en porcentaje.

    El supervisor la ve pero no la edita. Saber contra que umbral se esta
    midiendo su rampa no es lo mismo que poder moverlo, y ocultarselo solo
    conseguiria que preguntara por chat cada vez.

    Desde la fase 6 de la critica de UX (15/11/2026) los productos van en una
    tabla, para poder compararlos, y se edita uno cada vez. Antes cada producto
    era un bloque desplegado con su formulario, su simulador, su JSON de canales
    y su historial: tres productos eran tres pantallas de alto.
    """
    st.subheader("Tolerancias por producto")
    st.caption("Se aplica el límite más restrictivo entre el de kg y el porcentual. "
               "Los cambios solo afectan a las pesadas futuras y quedan registrados "
               "con usuario y fecha.")
    _aviso_de_administracion()

    respuesta = pedir("GET", "/configuracion")
    if respuesta.status_code != 200:
        st.error(detalle_del_error(respuesta))
        return
    productos = respuesta.json()
    if not productos:
        st.info("No hay productos configurados.")
        return

    # Traduce la configuracion a kg concretos. Nadie calcula de cabeza si el
    # 0,5 % de 20 000 kg queda por encima o por debajo del tope en kg. El calculo
    # lo hace la API (RN-01): repetirlo aqui acabaria discrepando.
    peso = st.columns([1, 3])[0].number_input(
        "Orden de ejemplo (kg)", min_value=1.0, step=1000.0, value=20000.0,
        help="La columna «Se admiten» muestra la tolerancia en kilos para una "
             "orden de este tamaño.")
    filas = []
    for fila in productos:
        aplicada = pedir("GET", f"/configuracion/{fila['producto']}/aplicada",
                         params={"peso_esperado_kg": peso})
        if aplicada.status_code == 200:
            datos = aplicada.json()
            # En una sola columna: con dos, "Último cambio" no cabia en pantalla.
            admite = (f"{float(datos['tolerancia_efectiva_kg']):,.0f} kg "
                      f"(límite en {datos['manda']})")
        else:
            admite = "No disponible"
        filas.append({
            "Producto": fila["producto"],
            "Límite en kg": float(fila["tolerancia_kg"]),
            "Límite en %": float(fila["tolerancia_pct"]),
            "Se admiten": admite,
            "Avisos por severidad": _canales_en_texto(fila["canales_por_severidad"]),
            "Último cambio": (f"{fila['fecha'][:10]} · {fila['actualizado_por_nombre']}"
                              if fila["actualizado_por_nombre"]
                              else "Sin cambios desde la instalación"),
        })
    st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True,
                 column_config={
                     "Límite en kg": st.column_config.NumberColumn(format="%.2f"),
                     "Límite en %": st.column_config.NumberColumn(format="%.2f")})
    st.caption("Los canales de aviso se muestran, pero todavía no se editan desde "
               "esta pantalla.")

    nombres = [fila["producto"] for fila in productos]
    elegido = st.selectbox(
        "Producto a editar" if editable else "Ver el historial de", nombres,
        key="tolerancia_producto")
    fila = productos[nombres.index(elegido)]

    edicion, historial = st.columns(2, gap="large")
    with edicion:
        if editable:
            _edicion_de_la_tolerancia(fila)
        else:
            # Una vista de lectura, no un formulario con todo deshabilitado: los
            # campos grises y el boton apagado invitaban a probar a pulsarlos.
            st.markdown(f"**{fila['producto']}**")
            st.write(f"Límite en kg: **{float(fila['tolerancia_kg']):,.2f}**  \n"
                     f"Límite en %: **{float(fila['tolerancia_pct']):.2f}**")
            st.caption("Solo el rol Administrador puede modificar estos valores.")
    with historial:
        _historial_de_la_tolerancia(fila["producto"])


def _edicion_de_la_tolerancia(fila: dict) -> None:
    with st.form(f"tolerancia_{fila['id']}"):
        st.markdown(f"**{fila['producto']}**")
        izquierda, derecha = st.columns(2)
        kg = izquierda.number_input(
            "Límite en kg", min_value=0.0, max_value=999999.99, step=1.0,
            value=float(fila["tolerancia_kg"]), format="%.2f",
            help="Diferencia absoluta admitida entre el peso real y el esperado.")
        pct = derecha.number_input(
            "Límite en %", min_value=0.0, max_value=100.0, step=0.05,
            value=float(fila["tolerancia_pct"]), format="%.2f",
            help="Porcentaje del peso esperado de la orden.")
        guardar = st.form_submit_button("Guardar cambios", type="primary")
    if not guardar:
        return
    antes = (float(fila["tolerancia_kg"]), float(fila["tolerancia_pct"]))
    if (kg, pct) == antes:
        st.info("No hay cambios que guardar.")
        return
    # Mover una tolerancia decide que cargas abren un evento y cuales no. Se
    # confirma viendo el antes y el despues, como el resto de acciones de
    # administracion (fase 3).
    _confirmar(
        f"Va a cambiar la tolerancia de **{fila['producto']}** de "
        f"{antes[0]:,.2f} kg y {antes[1]:.2f} % a **{kg:,.2f} kg y {pct:.2f} %**.",
        "Se aplica a las pesadas que se registren a partir de ahora. Los eventos ya "
        "creados conservan la tolerancia de su día. Queda en la auditoría con su usuario.",
        "Cambiar tolerancia", "PATCH", f"/configuracion/{fila['producto']}",
        {"tolerancia_kg": kg, "tolerancia_pct": pct},
        f"Tolerancia de {fila['producto']} actualizada a {kg:,.2f} kg y {pct:.2f} %.")


def _historial_de_la_tolerancia(producto: str) -> None:
    st.markdown("**Historial de cambios**")
    cambios = pedir("GET", f"/configuracion/{producto}/historial")
    if cambios.status_code != 200:
        st.caption("No se pudo consultar el historial.")
        return
    if not cambios.json():
        st.caption("Sin cambios desde la instalación.")
        return
    st.dataframe(
        pd.DataFrame([{
            "Fecha": c["fecha"][:16].replace("T", " "),
            "Usuario": c["usuario_nombre"] or f"id {c['usuario_id']}",
            "kg": f"{c['detalle']['antes']['kg']} a {c['detalle']['despues']['kg']}",
            "%": f"{c['detalle']['antes']['pct']} a {c['detalle']['despues']['pct']}",
        } for c in cambios.json()]),
        use_container_width=True, hide_index=True)


# ----------------------------------------------------------------- usuarios
def panel_de_usuarios() -> None:
    st.subheader("Usuarios y roles")
    st.caption("Los usuarios no se eliminan, se desactivan: la auditoría debe "
               "seguir apuntando a una persona identificable.")
    _aviso_de_administracion()

    roles = ["administrador", "supervisor", "consulta"]
    with st.expander("Crear usuario"):
        with st.form("crear_usuario"):
            nombre = st.text_input("Nombre")
            correo = st.text_input("Correo electrónico")
            rol = st.selectbox("Rol", roles, index=2, format_func=str.capitalize)
            clave = st.text_input("Contraseña inicial", type="password",
                                  help="Mínimo 8 caracteres.")
            if st.form_submit_button("Crear usuario"):
                respuesta = pedir("POST", "/usuarios", json={
                    "nombre": nombre, "correo": correo, "rol": rol, "clave": clave})
                if respuesta.status_code == 201:
                    st.session_state[AVISO_DE_ADMINISTRACION] = (
                        f"Usuario {correo} creado con el rol {rol.capitalize()}.")
                    st.rerun()
                else:
                    st.error(detalle_del_error(respuesta))

    respuesta = pedir("GET", "/usuarios")
    if respuesta.status_code != 200:
        st.error(detalle_del_error(respuesta))
        return

    anchos = [4, 2, 3, 2, 2]
    for columna, titulo in zip(st.columns(anchos), ("Usuario", "Estado", "Rol", "", "")):
        columna.caption(titulo)
    for usuario in respuesta.json():
        columnas = st.columns(anchos, vertical_alignment="center")
        columnas[0].write(f"**{usuario['nombre']}**  \n{usuario['correo']}")
        columnas[1].write("Activo" if usuario["activo"] else "Inactivo")
        nuevo_rol = columnas[2].selectbox(
            "Rol", roles, index=roles.index(usuario["rol"]), format_func=str.capitalize,
            key=f"rol_{usuario['id']}", label_visibility="collapsed")
        # Elegir otro rol en la lista ya no lo cambia: lo propone. Antes bastaba
        # con rozar el desplegable para dar o quitar permisos de administrador.
        if nuevo_rol != usuario["rol"] and columnas[3].button(
                "Aplicar rol", key=f"aplicar_rol_{usuario['id']}", type="primary",
                use_container_width=True):
            _confirmar(
                f"Va a cambiar el rol de **{usuario['nombre']}** de "
                f"{usuario['rol'].capitalize()} a **{nuevo_rol.capitalize()}**.",
                "El cambio se aplica de inmediato y queda registrado en la auditoría "
                "con su usuario.",
                "Cambiar rol", "PATCH", f"/usuarios/{usuario['id']}/rol",
                {"rol": nuevo_rol},
                f"{usuario['nombre']} ahora tiene el rol {nuevo_rol.capitalize()}.")
        etiqueta = "Desactivar" if usuario["activo"] else "Reactivar"
        if columnas[4].button(etiqueta, key=f"activacion_{usuario['id']}",
                              use_container_width=True):
            if usuario["activo"]:
                _confirmar(
                    f"Va a desactivar a **{usuario['nombre']}** ({usuario['correo']}).",
                    "No podrá iniciar sesión hasta que se le reactive. Su historial "
                    "en la auditoría se conserva.",
                    "Desactivar usuario", "PATCH", f"/usuarios/{usuario['id']}/activacion",
                    {"activo": False}, f"{usuario['nombre']} quedó desactivado.")
            else:
                _confirmar(
                    f"Va a reactivar a **{usuario['nombre']}** ({usuario['correo']}).",
                    f"Podrá volver a iniciar sesión con el rol "
                    f"{usuario['rol'].capitalize()}.",
                    "Reactivar usuario", "PATCH", f"/usuarios/{usuario['id']}/activacion",
                    {"activo": True}, f"{usuario['nombre']} quedó reactivado.")


# ------------------------------------------------------------------ programa
if "token" not in st.session_state:
    pantalla_de_ingreso()
    st.stop()

usuario_actual = st.session_state["usuario"]

@st.cache_data(ttl=20, show_spinner=False)
def _salud_reciente(token: str) -> tuple[int, dict | None]:
    """GET /salud, guardado 20 segundos.

    `GET /salud` no lee una tabla: sondea de verdad la bascula por Modbus y el
    ERP por HTTP. La cabecera se dibuja en cada pasada, asi que sin esto cada
    clic interrogaba a la bascula, y con la bascula apagada cada pantalla tardaba
    los 5 segundos de su tiempo limite. Veinte segundos bastan para una linea de
    estado; la pantalla Estado del sistema sigue preguntando en directo.

    El token es parte de la clave para que una sesion no vea la respuesta (o el
    401) de otra. Si la peticion falla, la excepcion sale y no se guarda nada.
    """
    respuesta = httpx.request("GET", f"{API_URL}/salud", timeout=TIEMPO_LIMITE,
                              headers={"X-API-Key": token})
    return respuesta.status_code, (respuesta.json() if respuesta.status_code == 200
                                   else None)


def _estado_de_la_planta() -> str:
    """La linea de estado de la cabecera, leida de GET /salud.

    Antes decia "Rampa 1 · En línea" siempre, con un punto verde latiendo, sin
    preguntarle a nadie. Con una camara caida la cabecera seguia en verde, y un
    indicador que no puede ponerse en rojo es peor que no tener indicador: el
    supervisor aprende a fiarse de el. Convencion 8: un fallo se ve.

    Tres niveles, los mismos que usa la API. "error" va en rojo: algo no
    responde. "advertencia" va en ambar y no se llama falla: el caso tipico es
    la bascula en movimiento, que es lo normal mientras se carga un camion. La
    primera version pintaba las dos cosas en rojo como "componente con falla", y
    la cabecera daba la alarma cada vez que el peso oscilaba.
    """
    ahora = f"{dt.datetime.now():%d/%m/%Y %H:%M}"
    try:
        codigo, salud = _salud_reciente(st.session_state.get("token", ""))
    except httpx.HTTPError:
        return (f'<span class="q-vivo q-caido"><i></i>Sin conexión con el sistema · '
                f'{ahora}</span>')
    if codigo == 401:
        # La cabecera es lo primero que se dibuja: si el token ya no vale, se
        # sale aqui en vez de pintar todas las pantallas con el mismo error.
        _salud_reciente.clear()
        cerrar_sesion()
        st.rerun()
    if codigo != 200:
        return (f'<span class="q-vivo q-caido"><i></i>No se pudo leer el estado del '
                f'sistema · {ahora}</span>')

    componentes = salud["componentes"]
    caidos = [c["componente"] for c in componentes if c["estado"] == "error"]
    avisos = [c["componente"] for c in componentes
              if c["estado"] not in ("ok", "error")]
    if caidos:
        cuantos = (f"{len(caidos)} componentes con falla" if len(caidos) > 1
                   else "1 componente con falla")
        return (f'<span class="q-vivo q-caido"><i></i>{cuantos}: {", ".join(caidos)} · '
                f'consulte Estado del sistema · {ahora}</span>')
    if avisos:
        cuantos = (f"{len(avisos)} componentes con advertencia" if len(avisos) > 1
                   else "1 componente con advertencia")
        return (f'<span class="q-vivo q-aviso"><i></i>Sistema en línea · {cuantos}: '
                f'{", ".join(avisos)} · consulte Estado del sistema · {ahora}</span>')
    camaras = sum(1 for c in componentes if c["componente"].startswith(PREFIJO_CAMARA))
    grabando = (f' · {camaras} cámara{"s" if camaras != 1 else ""} grabando'
                if camaras else "")
    return (f'<span class="q-vivo"><i></i>Sistema en línea{grabando} · {ahora}</span>')


def _eventos_abiertos() -> int | None:
    """Cuantos eventos esperan revision, para el menu y la cabecera.

    None si no se pudo saber: no es lo mismo "cero pendientes" que "no lo se"
    (convencion 7), y el menu no debe decir que no hay nada cuando la API no
    contesto.
    """
    try:
        respuesta = pedir("GET", "/eventos/bandeja")
    except httpx.HTTPError:
        return None
    if respuesta.status_code != 200:
        return None
    return (respuesta.json().get("resumen") or {}).get("abiertos")


def _cabecera_de_eventos(abiertos: int | None) -> None:
    """Titulo y lo unico que importa al entrar: cuantos eventos esperan revision.

    Solo en Eventos. En las demas pantallas basta la linea de estado: el titulo
    de 40 px repetido en cada una empujaba el contenido hacia abajo, y la cifra
    de pendientes ya esta en el menu.
    """
    if abiertos:
        estado = (f'<span class="q-oro">{abiertos} evento{"s" if abiertos != 1 else ""}</span>'
                  f'<span class="q-tenue"> pendiente{"s" if abiertos != 1 else ""} de revisión</span>')
    elif abiertos == 0:
        estado = '<span class="q-tenue">Sin eventos pendientes de revisión</span>'
    else:
        estado = ""
    st.markdown(f'<div class="q-saludo">Control de despacho<br>{estado}</div>',
                unsafe_allow_html=True)


def _pantalla(panel, *argumentos, con_saludo: bool = False):
    """Envuelve un panel como pantalla del menu: linea de estado y contenido.

    La linea de estado va en todas: una camara caida tiene que verse se este
    donde se este.
    """
    def dibujar() -> None:
        st.markdown(_estado_de_la_planta(), unsafe_allow_html=True)
        # Con un evento abierto el titulo sobra: empujaba el video hacia abajo
        # y repetia una cifra que ya esta en el menu.
        if con_saludo and st.session_state.get(EVENTO_ELEGIDO) is None:
            _cabecera_de_eventos(abiertos)
        panel(*argumentos)
    return dibujar


# El rol Consulta no administra nada: la API lo rechaza con 403 y la pantalla
# ni siquiera ofrece la accion, para no invitar a un error que ya esta cerrado.
es_admin = usuario_actual["rol"] == "administrador"
abiertos = _eventos_abiertos()
_conservar_filtros()

# Menu lateral en tres grupos, en lugar de ocho pestanas al mismo nivel (critica
# de UX del 15/11/2026, fase 4). Dos razones:
#   - Las pestanas mezclaban lo que el supervisor usa cada hora (eventos,
#     pesadas) con lo que un administrador toca una vez al mes (tokens).
#   - `st.tabs` ejecuta el contenido de todas en cada pasada: cada clic volvia a
#     pedir a la API las pesadas, las ordenes, la salud, las tolerancias, los
#     tokens y los usuarios aunque se estuviera mirando un evento. Con
#     `st.navigation` solo se ejecuta la pantalla abierta.
# Los eventos van primero: son la razon de ser del sistema. Despues, el orden
# del despacho: la pesada donde nace cada evento (HU-01, HU-03) y la orden
# contra la que se juzga (HU-02). El contador de pendientes va en el nombre de
# la pantalla para que se vea desde cualquier otra.
# Las direcciones (`url_path`) son fijas para que un enlace guardado siga
# sirviendo aunque cambie el contador del titulo.
MENU = {
    "Operación": [
        st.Page(_pantalla(panel_de_eventos, con_saludo=True), url_path="eventos",
                title=f"Eventos ({abiertos})" if abiertos else "Eventos", default=True),
        st.Page(_pantalla(panel_de_pesadas), title="Registro de pesada",
                url_path="pesadas"),
        st.Page(_pantalla(panel_de_ordenes), title="Órdenes", url_path="ordenes"),
    ],
    "Monitoreo": [
        st.Page(_pantalla(panel_de_video), title="Cámaras", url_path="camaras"),
        st.Page(_pantalla(panel_de_salud), title="Estado del sistema",
                url_path="estado"),
    ],
    "Administración": [
        st.Page(_pantalla(panel_de_tolerancias, es_admin), title="Tolerancias",
                url_path="tolerancias"),
        st.Page(_pantalla(panel_de_tokens), title="Tokens de acceso",
                url_path="tokens"),
    ],
}
if es_admin:
    MENU["Administración"].append(
        st.Page(_pantalla(panel_de_usuarios), title="Usuarios", url_path="usuarios"))

pantalla_actual = st.navigation(MENU)

# Debajo del menu: quien esta dentro y como salir. "Actualizar" deja de ser el
# boton principal de la barra: no es la accion mas importante de la pantalla.
with st.sidebar:
    st.write(f"**{usuario_actual['nombre']}**")
    st.caption(f"{usuario_actual['correo']} · {usuario_actual['rol'].capitalize()}")
    if st.button("Actualizar datos", use_container_width=True):
        st.rerun()
    if st.button("Cerrar sesión", use_container_width=True):
        cerrar_sesion()
        st.rerun()

pantalla_actual.run()
