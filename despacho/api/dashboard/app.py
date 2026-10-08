"""Dashboard del supervisor - Sprint 1.

Cubre la parte de HU-03, HU-04, HU-06 y HU-15 que vive fuera de la API: entrar con
correo y clave, ver las discrepancias detectadas y el estado de los componentes,
ajustar las tolerancias por producto, administrar usuarios y roles, y emitir o
revocar tokens. El criterio 1 de HU-04 pide la pantalla de configuracion, y el
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

st.set_page_config(page_title="QUINOR - Control de despacho", page_icon="📦", layout="wide")


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


def cerrar_sesion() -> None:
    for clave in ("token", "usuario"):
        st.session_state.pop(clave, None)


# ------------------------------------------------------------------- ingreso
def pantalla_de_ingreso() -> None:
    st.title("QUINOR S.A.C. - Control de despacho")
    st.caption("Identificate para continuar. HU-15, criterio 4.")
    with st.form("ingreso"):
        correo = st.text_input("Correo", placeholder="admin@quinor.local")
        clave = st.text_input("Contrasena", type="password")
        if not st.form_submit_button("Entrar", type="primary"):
            return
        try:
            respuesta = httpx.post(f"{API_URL}/auth/login", timeout=TIEMPO_LIMITE,
                                   json={"correo": correo, "clave": clave})
        except httpx.HTTPError as exc:
            st.error(f"No se pudo consultar el orquestador en {API_URL}: {exc}")
            return
        if respuesta.status_code != 200:
            # La API no distingue si fallo el correo o la clave, y aqui tampoco.
            st.error(detalle_del_error(respuesta))
            return
        datos = respuesta.json()
        st.session_state["token"] = datos["token"]
        st.session_state["usuario"] = datos["usuario"]
        st.rerun()


# -------------------------------------------------------------------- salud
def panel_de_salud() -> None:
    st.subheader("Estado de los componentes")
    try:
        respuesta = pedir("GET", "/salud")
    except httpx.HTTPError as exc:
        st.error(f"No se pudo consultar el orquestador en {API_URL}: {exc}")
        return
    if respuesta.status_code == 401:
        st.warning("La sesion vencio o el token fue revocado. Vuelve a entrar.")
        cerrar_sesion()
        st.rerun()
    if respuesta.status_code != 200:
        st.error(detalle_del_error(respuesta))
        return
    datos = respuesta.json()
    if datos["estado"] == "ok":
        st.success("Todos los componentes responden.")
    else:
        st.warning("Hay componentes con error. Revisa el detalle.")
    st.dataframe(pd.DataFrame(datos["componentes"]),
                 use_container_width=True, hide_index=True)


# ------------------------------------------------------------------- tokens
def panel_de_tokens() -> None:
    st.subheader("Mis tokens de API")
    st.caption("El valor en claro se muestra una sola vez. Despues solo queda su hash.")

    with st.expander("Emitir un token nuevo"):
        with st.form("emitir_token"):
            nombre = st.text_input("Para que equipo", placeholder="Laptop de rampa 1")
            horas = st.number_input("Vigencia en horas", min_value=1, max_value=8760, value=12)
            if st.form_submit_button("Emitir"):
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

    for token in tokens:
        revocado = token["revocado_en"] is not None
        columnas = st.columns([3, 3, 3, 2])
        columnas[0].write(f"**{token['nombre']}**")
        columnas[1].write(f"Vence: {token['expira_en'][:19].replace('T', ' ')}")
        columnas[2].write("Revocado" if revocado else
                          f"Ultimo uso: {(token['ultimo_uso_en'] or '-')[:19].replace('T', ' ')}")
        if revocado:
            columnas[3].write("-")
        elif columnas[3].button("Revocar", key=f"revocar_{token['id']}"):
            resultado = pedir("DELETE", f"/auth/tokens/{token['id']}")
            if resultado.status_code == 200:
                st.success(f"Token '{token['nombre']}' revocado. Deja de servir de inmediato.")
                if resultado.json()["id"] == st.session_state.get("token_id"):
                    cerrar_sesion()
                st.rerun()
            else:
                st.error(detalle_del_error(resultado))


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
    st.subheader("Eventos de discrepancia")
    st.caption("Se crea uno cuando la diferencia entre el peso real y el esperado "
               "supera la tolerancia del producto.")

    filtros = _filtros_de_la_bandeja()

    respuesta = pedir("GET", "/eventos/bandeja", params=filtros)
    if respuesta.status_code != 200:
        st.error(detalle_del_error(respuesta))
        return
    bandeja = respuesta.json()
    eventos = bandeja["filas"]

    _aviso_de_filtros_por_defecto(bandeja)

    if not eventos:
        st.success("No hay eventos de discrepancia con ese filtro.")
        _pie_de_la_bandeja(bandeja)
        return

    _senales_de_la_bandeja(bandeja)

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
                         else ("revisar" if e["personal_anomalo"] else "normal")),
            # HU-09. Sale de la RN-04, no del modelo: por eso esta aunque el
            # proveedor haya fallado.
            "Severidad": e["severidad"] or "-",
            "Estado": e["estado"],
            # HU-06. "Sin clip" no es lo mismo que "todavia no": el recorte
            # espera a que se grabe el margen posterior al cierre.
            "Clip": ("no hay video" if e["estado"] == "sin_clip"
                     else ("si" if e["tiene_clip"] else "en curso")),
        } for e in eventos]),
        use_container_width=True, hide_index=True)

    _pie_de_la_bandeja(bandeja)
    _detalle_del_evento(eventos)


def _filtros_de_la_bandeja() -> dict:
    """Los cuatro filtros del criterio 1, mas los que el uso pidio.

    Cada uno se manda solo si el supervisor lo toco. Mandarlos todos siempre
    desactivaria los valores por defecto del criterio 3 sin que nadie lo hubiera
    pedido: la API distingue "no dijo nada" de "dijo que todos".
    """
    fila1 = st.columns([1, 1, 1, 2])
    estado = fila1[0].selectbox(
        "Estado", ["por defecto", "todos", "pendiente", "pendiente_analisis",
                   "en_revision", "confirmado", "falso_positivo", "sin_clip"],
        help="Por defecto son los Pendientes, segun el criterio 3 de HU-11.")
    severidad = fila1[1].selectbox("Severidad",
                                   ["todas", "alta", "media", "baja"])
    rango = fila1[2].selectbox(
        "Periodo", ["ultimos 7 dias", "hoy", "ultimos 30 dias", "todo",
                    "personalizado"])
    orden = fila1[3].text_input("Numero de orden",
                                placeholder="0148, o la orden completa")

    desde = hasta = None
    if rango == "personalizado":
        fila2 = st.columns(2)
        desde = fila2[0].date_input("Desde",
                                    value=dt.date.today() - dt.timedelta(days=7))
        hasta = fila2[1].date_input("Hasta", value=dt.date.today())

    fila3 = st.columns([2, 1, 1])
    solo_faltante = fila3[0].checkbox(
        "Solo con faltante de sacos",
        help="Deja fuera las cargas donde el conteo cuadra. Peso corto con los "
             "sacos completos apunta a sustitucion y se ve quitando esto.")
    tamano = fila3[1].selectbox("Filas por pagina", [25, 50, 100, 200], index=1)
    pagina = fila3[2].number_input("Pagina", min_value=1, value=1, step=1)

    filtros: dict = {"tamano": tamano, "pagina": int(pagina)}
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

    if rango == "hoy":
        filtros["desde"] = filtros["hasta"] = dt.date.today().isoformat()
    elif rango == "ultimos 30 dias":
        filtros["desde"] = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    elif rango == "todo":
        filtros["sin_defectos"] = True
    elif rango == "personalizado" and desde and hasta:
        filtros["desde"], filtros["hasta"] = desde.isoformat(), hasta.isoformat()

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
        partes.append("de los **ultimos 7 dias**")
    st.caption("Vista por defecto: " + " ".join(partes) +
               ". Cambia Estado o Periodo para ver mas.")


def _senales_de_la_bandeja(bandeja: dict) -> None:
    """Lo que conviene mirar antes que la tabla.

    Las cifras salen del resumen que calcula la API sobre la pagina que se esta
    viendo, no de recorrer las filas aqui: asi la pantalla y la API no pueden
    contar cosas distintas.
    """
    resumen = bandeja.get("resumen") or {}

    if resumen.get("abiertos"):
        st.warning(f"{resumen['abiertos']} evento(s) pendientes de revisar.")

    # HU-07, criterio 3. Una carga con el peso corto y los sacos completos no es
    # lo mismo que una con sacos de menos: la primera apunta a sustitucion de
    # producto, la segunda a hurto de bultos.
    if resumen.get("con_faltante_de_sacos"):
        st.warning(
            f"{resumen['con_faltante_de_sacos']} evento(s) con menos sacos en el "
            f"video que en la orden. Peso corto con los sacos completos apunta a "
            f"producto sustituido; sacos de menos, a bultos que no subieron.")

    # HU-08 y RN-03. La presencia anomala es, junto con la diferencia de sacos,
    # lo que hace que HU-09 llame al modelo de vision-lenguaje.
    if resumen.get("con_personal_anomalo"):
        st.warning(
            f"{resumen['con_personal_anomalo']} evento(s) con presencia de personal "
            f"que llamo la atencion: mas gente de la habitual a la vez, alguien "
            f"mucho tiempo en zona, o personas en rampa sin sacos cruzando. Es un "
            f"motivo para mirar el clip, no una conclusion sobre nadie.")

    # HU-09, criterio 3 y apartado 5.3. Un evento sin descripcion no es lo mismo
    # que uno que nadie intento describir.
    sin_analisis = [e for e in bandeja["filas"]
                    if e["estado"] == "pendiente_analisis"]
    if sin_analisis:
        st.info(f"{len(sin_analisis)} evento(s) quedaron en Pendiente de analisis: "
                f"el modelo de vision-lenguaje fallo tras sus reintentos. La "
                f"severidad si esta, porque sale de la regla y no del modelo.")

    sin_clip = [e for e in bandeja["filas"] if e["estado"] == "sin_clip"]
    if sin_clip:
        st.info(f"{len(sin_clip)} evento(s) sin clip: no habia video de esa ventana "
                f"en el buffer. El detalle del motivo esta en la auditoria.")


def _pie_de_la_bandeja(bandeja: dict) -> None:
    """Cuantos hay, cual se esta viendo y cuanto tardo. Criterio 2.

    El tiempo se muestra siempre y no solo cuando es malo. Una pantalla que solo
    avisa cuando ya va lenta no deja ver que se estaba degradando.
    """
    total = bandeja["total"]
    if total:
        donde = (f"Mostrando {bandeja['desde_fila']} a {bandeja['hasta_fila']} "
                 f"de {total} evento(s). Pagina {bandeja['pagina']} de "
                 f"{bandeja['paginas']}.")
    else:
        donde = "Ningun evento cumple ese filtro."

    segundos = bandeja["segundos"]
    if bandeja["dentro_del_criterio"]:
        st.caption(f"{donde} Consulta resuelta en {segundos * 1000:.0f} ms.")
    else:
        # El criterio 2 se mide con lo que pasa de verdad, y una pantalla que se
        # vuelve lenta hay que verla antes de que sea costumbre.
        st.warning(f"{donde} La consulta tardo {segundos:.1f} s, por encima de "
                   f"los 2 s que exige el criterio 2 de HU-11.")


def _detalle_del_evento(eventos: list[dict]) -> None:
    """El detalle del evento elegido, con su video y su analisis. HU-12.

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
    """
    with st.expander("Detalle del evento, con video y fotogramas"):
        elegido = st.selectbox(
            "Evento", [e["id"] for e in eventos],
            format_func=lambda i: f"#{i}")

        respuesta = pedir("GET", f"/eventos/{elegido}/detalle")
        if respuesta.status_code != 200:
            st.warning(detalle_del_error(respuesta))
            return
        detalle = respuesta.json()

        _cifras_del_detalle(detalle)
        _reproductor_del_clip(detalle)
        _fotogramas_del_detalle(detalle)
        _analisis_del_detalle(detalle)
        _personas_del_detalle(detalle)
        _avisos_del_evento({"id": detalle["id"],
                            "severidad": detalle["analisis"]["severidad"]})


def _cifras_del_detalle(detalle: dict) -> None:
    """Criterio 1: los pesos y el conteo, antes que el video.

    El orden no es casual. El video es la verificacion; la discrepancia es el
    hecho, y existe desde que el camion cerro. Un supervisor que abre esto
    tiene que ver primero cuanto falta.
    """
    pesos, sacos = detalle["pesos"], detalle["sacos"]

    izquierda, centro, derecha = st.columns(3)
    izquierda.metric("Peso esperado", f"{float(pesos['esperado_kg']):,.2f} kg")
    centro.metric("Peso real", f"{float(pesos['real_kg']):,.2f} kg")
    derecha.metric("Diferencia", f"{float(pesos['diferencia_kg']):+,.2f} kg",
                   delta=f"{float(pesos['diferencia_pct']):+.2f} %",
                   delta_color="inverse")

    if pesos["tolerancia_aplicada_kg"] is not None:
        # La de aquel dia, no la de hoy: si alguien la cambio despues, el evento
        # sigue diciendo contra que umbral se juzgo aquella carga.
        texto = (f"Se toleraban {float(pesos['tolerancia_aplicada_kg']):,.2f} kg "
                 f"para este producto cuando se creo el evento")
        if pesos["exceso_sobre_la_tolerancia_kg"] is not None:
            texto += (f", asi que se paso en "
                      f"{float(pesos['exceso_sobre_la_tolerancia_kg']):,.2f} kg")
        st.caption(texto + ".")

    if not sacos["analizado"]:
        # Un guion no es un cero: sin analizar no hay conteo, y confundirlo
        # mandaria a alguien a la rampa por una carga que nadie ha mirado.
        st.info("El conteo de sacos todavia no esta: el clip no se ha analizado.")
    else:
        uno, dos, tres = st.columns(3)
        uno.metric("Sacos en la orden", sacos["esperados"])
        dos.metric("Sacos en el video", sacos["contados"])
        tres.metric("Diferencia", f"{sacos['diferencia']:+d}")

    if detalle["peso_corto_con_sacos_completos"]:
        # HU-07, criterio 3. Es la conclusion que justifica el proyecto entero:
        # no se llevaron sacos, cambiaron lo que hay dentro.
        st.error("Falta peso y los bultos cuadran: apunta a producto sustituido, "
                 "no a sacos que no subieron.")


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
            ventana += f", camara {clip['camara']}"
        st.caption(ventana + ".")
    elif detalle["inicio_carga"] is None:
        st.caption("Nadie marco el inicio de carga: el clip cubre solo los "
                   "minutos previos al cierre.")

    if not clip["reproducible"]:
        st.info(clip["enlace"]["explicacion"]
                or "El clip no se puede reproducir ahora mismo.")
        if clip["motivo_sin_clip"]:
            # No es lo mismo la camara caida que el video ya purgado del buffer.
            st.caption(f"Lo que anoto el grabador: {clip['motivo_sin_clip']}.")
        if clip["enlace"]["direccion"]:
            st.caption("Ubicacion del clip en el almacen:")
            st.code(clip["enlace"]["direccion"], language=None)
        return

    st.video(clip["enlace"]["url"], start_time=int(_segundo_de_arranque(detalle)))

    if clip["formato"] == "mkv":
        # El grabador escribe Matroska porque un corte de luz no se lleva el
        # fichero entero. El precio lo paga esta pantalla: Chrome y Edge lo
        # reproducen, Firefox y Safari no, y un recuadro negro sin explicacion
        # haria pensar que el clip se perdio.
        st.caption("El clip esta en Matroska (.mkv), el formato con el que se "
                   "graba para que un corte de luz no se lleve el fichero "
                   "entero. Se reproduce en Chrome y en Edge; en Firefox o "
                   "Safari hay que descargarlo con el enlace del reproductor.")

    if clip["completo"] is False:
        # Se reproduce, pero no cubre toda la ventana. Quien lo mira tiene que
        # saberlo antes de concluir que no pasa nada en los minutos que faltan.
        st.warning(f"El clip cubre el {clip['cobertura_pct']:.0f} % de la "
                   f"ventana: faltaban segmentos en el buffer.")
    st.caption(f"Enlace valido {clip['enlace']['minutos']} minuto(s). Caduca a "
               f"proposito: sirve para revisar el caso, no para repartirlo.")


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
    "pico_de_personas": "el momento con mas gente en la zona",
    "primer_saco": "el primer saco de la carga",
    "ultimo_saco": "el ultimo saco de la carga",
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
    st.markdown("**Fotogramas del analisis**")
    if anomalia.get("es_anomalia"):
        st.caption(f"El primero es el de la anomalia: "
                   f"{MOTIVOS.get(anomalia['motivo'], anomalia['motivo'])}, "
                   f"en el segundo {anomalia['segundo']:.0f}.")
    else:
        st.caption("Ninguno es una anomalia por si mismo: son los momentos que "
                   "el sistema guardo para situarse en el video.")

    columnas = st.columns(min(len(fotogramas), 4))
    for columna, imagen in zip(columnas, fotogramas):
        with columna:
            motivo = MOTIVOS.get(imagen["motivo"], imagen["motivo"] or "sin motivo")
            if imagen["enlace"]["reproducible"]:
                st.image(imagen["enlace"]["url"],
                         caption=f"s{imagen['segundo']:.0f} - {motivo}",
                         use_container_width=True)
            else:
                st.info(f"{motivo}: {imagen['enlace']['explicacion']}")
            if imagen["detalle"]:
                st.caption(imagen["detalle"])
            if detalle["clip"]["reproducible"]:
                st.button(
                    f"Ver el clip desde el segundo {imagen['segundo']:.0f}",
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
        st.write(f"Severidad: **{analisis['severidad'].capitalize()}** (regla RN-04)")

    if not analisis["hay_descripcion"]:
        if detalle["estado"] == "pendiente_analisis":
            st.info("El modelo de vision-lenguaje fallo tras sus reintentos. "
                    "La severidad de arriba sale de la regla, no del modelo.")
        elif detalle["clip"]["reproducible"]:
            st.caption("El clip todavia no tiene descripcion del modelo.")
        return

    st.write(f"**Descripcion del modelo:** {analisis['descripcion']}")
    if analisis["evidencia"]:
        st.write("Evidencia observada:")
        for punto in analisis["evidencia"]:
            st.write(f"- {punto}")

    if analisis["discrepan"]:
        st.warning(
            f"El modelo propuso severidad **{analisis['severidad_ia'].capitalize()}** "
            f"y la regla dice **{analisis['severidad'].capitalize()}**. Manda la "
            f"regla. Estas discrepancias son las que se revisan cada semana.")

    st.caption(
        f"Modelo {analisis['modelo'] or '?'} ({analisis['proveedor'] or '?'}), "
        f"confianza {(analisis['confianza'] or 0):.0%}, "
        f"{analisis['intentos'] or 1} intento(s). Es una ayuda para priorizar, "
        f"no una conclusion: la decision es del supervisor.")


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
        st.warning("La presencia de personal llamo la atencion. Es un motivo "
                   "para mirar el clip, no una conclusion sobre nadie.")
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
    st.caption(f"{personas['nota']} Permanencia maxima "
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
        st.info("Todavia no ha salido ningun aviso de este evento.")
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
                    st.caption(f"Salio {segundos:.1f} s despues del analisis.")
                else:
                    # No se esconde: el criterio 3 se mide con lo que pasa de
                    # verdad, y un aviso tardio hay que verlo antes de que sea
                    # costumbre.
                    st.warning(f"El aviso salio {segundos:.0f} s despues del "
                               f"analisis, por encima de los 60 s previstos.")
        else:
            st.error(f"El aviso no salio ({aviso['intentos']} intento(s)): "
                     f"{aviso['error'] or 'sin detalle'}. Nadie ha recibido "
                     f"este evento por correo.")


# -------------------------------------------------------------- tolerancias
def panel_de_tolerancias(editable: bool) -> None:
    """Pantalla del criterio 1 de HU-04: tolerancia en kg y en porcentaje.

    El supervisor la ve pero no la edita. Saber contra que umbral se esta
    midiendo su rampa no es lo mismo que poder moverlo, y ocultarselo solo
    conseguiria que preguntara por chat cada vez.
    """
    st.subheader("Tolerancias por producto")
    st.caption("Se aplica la mas restrictiva entre los kg y el porcentaje (RN-01). "
               "Cada cambio queda registrado con usuario y fecha.")

    respuesta = pedir("GET", "/configuracion")
    if respuesta.status_code != 200:
        st.error(detalle_del_error(respuesta))
        return
    productos = respuesta.json()
    if not productos:
        st.info("No hay productos configurados.")
        return

    if not editable:
        st.info("Solo el rol Administrador puede editar estos valores.")

    for fila in productos:
        with st.expander(fila["producto"], expanded=editable):
            autor = fila["actualizado_por_nombre"] or "sin cambios desde la instalacion"
            st.caption(f"Ultimo cambio: {fila['fecha'][:19].replace('T', ' ')} - {autor}")

            with st.form(f"tolerancia_{fila['id']}"):
                izquierda, derecha = st.columns(2)
                kg = izquierda.number_input(
                    "Tolerancia en kg", min_value=0.0, max_value=999999.99, step=1.0,
                    value=float(fila["tolerancia_kg"]), format="%.2f",
                    disabled=not editable,
                    help="Diferencia absoluta admitida entre el peso real y el esperado.")
                pct = derecha.number_input(
                    "Tolerancia en %", min_value=0.0, max_value=100.0, step=0.05,
                    value=float(fila["tolerancia_pct"]), format="%.2f",
                    disabled=not editable,
                    help="Porcentaje del peso esperado de la orden.")
                guardar = st.form_submit_button("Guardar", type="primary",
                                                disabled=not editable)
            if guardar:
                resultado = pedir("PATCH", f"/configuracion/{fila['producto']}",
                                  json={"tolerancia_kg": kg, "tolerancia_pct": pct})
                if resultado.status_code == 200:
                    st.success(f"Tolerancia de {fila['producto']} actualizada.")
                    st.rerun()
                else:
                    st.error(detalle_del_error(resultado))

            # Traduce la configuracion a kg concretos. Nadie calcula de cabeza si
            # el 0,5 % de 20 000 kg queda por encima o por debajo del tope en kg.
            peso = st.number_input(
                "Simular con una orden de (kg)", min_value=1.0, step=100.0,
                value=20000.0, key=f"simular_{fila['id']}")
            aplicada = pedir("GET", f"/configuracion/{fila['producto']}/aplicada",
                             params={"peso_esperado_kg": peso})
            if aplicada.status_code == 200:
                datos = aplicada.json()
                st.write(
                    f"Manda **{datos['manda']}**: se admiten "
                    f"**{datos['tolerancia_efectiva_kg']} kg** de diferencia "
                    f"(el porcentaje equivale a {datos['equivalente_del_pct_kg']} kg).")

            st.caption("Canales de alerta por severidad (los edita HU-10):")
            st.json(fila["canales_por_severidad"], expanded=False)

            cambios = pedir("GET", f"/configuracion/{fila['producto']}/historial")
            if cambios.status_code == 200 and cambios.json():
                st.caption("Historial de cambios")
                st.dataframe(
                    pd.DataFrame([{
                        "Fecha": c["fecha"][:19].replace("T", " "),
                        "Usuario": c["usuario_nombre"] or f"id {c['usuario_id']}",
                        "kg": f"{c['detalle']['antes']['kg']} -> {c['detalle']['despues']['kg']}",
                        "%": f"{c['detalle']['antes']['pct']} -> {c['detalle']['despues']['pct']}",
                    } for c in cambios.json()]),
                    use_container_width=True, hide_index=True)


# ----------------------------------------------------------------- usuarios
def panel_de_usuarios() -> None:
    st.subheader("Usuarios y roles")
    st.caption("Los usuarios no se borran, se desactivan: la auditoria tiene que "
               "seguir apuntando a una persona identificable.")

    with st.expander("Crear usuario"):
        with st.form("crear_usuario"):
            nombre = st.text_input("Nombre")
            correo = st.text_input("Correo")
            rol = st.selectbox("Rol", ["administrador", "supervisor", "consulta"], index=2)
            clave = st.text_input("Contrasena inicial", type="password",
                                  help="Minimo 8 caracteres, maximo 72 bytes.")
            if st.form_submit_button("Crear"):
                respuesta = pedir("POST", "/usuarios", json={
                    "nombre": nombre, "correo": correo, "rol": rol, "clave": clave})
                if respuesta.status_code == 201:
                    st.success(f"Usuario {correo} creado con rol {rol}.")
                    st.rerun()
                else:
                    st.error(detalle_del_error(respuesta))

    respuesta = pedir("GET", "/usuarios")
    if respuesta.status_code != 200:
        st.error(detalle_del_error(respuesta))
        return

    roles = ["administrador", "supervisor", "consulta"]
    for usuario in respuesta.json():
        columnas = st.columns([3, 3, 2, 2])
        estado = "activo" if usuario["activo"] else "inactivo"
        columnas[0].write(f"**{usuario['nombre']}**  \n{usuario['correo']}")
        columnas[1].write(f"Estado: {estado}")
        nuevo_rol = columnas[2].selectbox(
            "Rol", roles, index=roles.index(usuario["rol"]),
            key=f"rol_{usuario['id']}", label_visibility="collapsed")
        if nuevo_rol != usuario["rol"]:
            resultado = pedir("PATCH", f"/usuarios/{usuario['id']}/rol",
                              json={"rol": nuevo_rol})
            if resultado.status_code == 200:
                st.rerun()
            else:
                st.error(detalle_del_error(resultado))
        etiqueta = "Desactivar" if usuario["activo"] else "Reactivar"
        if columnas[3].button(etiqueta, key=f"activacion_{usuario['id']}"):
            resultado = pedir("PATCH", f"/usuarios/{usuario['id']}/activacion",
                              json={"activo": not usuario["activo"]})
            if resultado.status_code == 200:
                st.rerun()
            else:
                st.error(detalle_del_error(resultado))


# ------------------------------------------------------------------ programa
if "token" not in st.session_state:
    pantalla_de_ingreso()
    st.stop()

usuario_actual = st.session_state["usuario"]

with st.sidebar:
    st.write(f"**{usuario_actual['nombre']}**")
    st.caption(f"{usuario_actual['correo']} - rol {usuario_actual['rol']}")
    if st.button("Salir"):
        cerrar_sesion()
        st.rerun()
    if st.button("Actualizar", type="primary"):
        st.rerun()

st.title("QUINOR S.A.C. - Control de despacho")
st.caption("Alternativa 1, Sprint 1.")

# El rol Consulta no administra nada: la API lo rechaza con 403 y la pantalla
# ni siquiera ofrece la accion, para no invitar a un error que ya esta cerrado.
es_admin = usuario_actual["rol"] == "administrador"
# Los eventos van primero: son la razon de ser del sistema y lo que el
# supervisor abre el dashboard para mirar.
if es_admin:
    discrepancias, salud, tolerancias, tokens, gente = st.tabs(
        ["Eventos", "Salud", "Tolerancias", "Mis tokens", "Usuarios"])
    with gente:
        panel_de_usuarios()
else:
    discrepancias, salud, tolerancias, tokens = st.tabs(
        ["Eventos", "Salud", "Tolerancias", "Mis tokens"])

with discrepancias:
    panel_de_eventos()
with salud:
    panel_de_salud()
with tolerancias:
    panel_de_tolerancias(editable=es_admin)
with tokens:
    panel_de_tokens()
