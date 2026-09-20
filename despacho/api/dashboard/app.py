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
    """Discrepancias detectadas. HU-03.

    Es la pantalla que da sentido al resto: aqui es donde el supervisor se
    entera del faltante el mismo dia. La version con filtros combinados y sus
    2 s de respuesta es HU-11; esta es la lista tal cual.
    """
    st.subheader("Eventos de discrepancia")
    st.caption("Se crea uno cuando la diferencia entre el peso real y el esperado "
               "supera la tolerancia del producto.")

    estados = ["todos", "pendiente", "pendiente_analisis", "en_revision",
               "confirmado", "falso_positivo", "sin_clip"]
    izquierda, derecha = st.columns([1, 2])
    estado = izquierda.selectbox("Estado", estados)
    orden = derecha.text_input("Numero de orden", placeholder="ORD-2026-0001")

    parametros = {}
    if estado != "todos":
        parametros["estado"] = estado
    if orden.strip():
        parametros["numero_orden"] = orden.strip()

    respuesta = pedir("GET", "/eventos", params=parametros)
    if respuesta.status_code != 200:
        st.error(detalle_del_error(respuesta))
        return
    eventos = respuesta.json()
    if not eventos:
        st.success("No hay eventos de discrepancia con ese filtro.")
        return

    pendientes = sum(1 for e in eventos if e["estado"] == "pendiente")
    if pendientes:
        st.warning(f"{pendientes} evento(s) pendientes de revisar.")

    st.dataframe(
        pd.DataFrame([{
            "ID": e["id"],
            "Fecha": e["creado_en"][:19].replace("T", " "),
            "Orden": e["numero_orden"],
            "Cliente": e["cliente"],
            "Esperado kg": e["peso_esperado_kg"],
            "Real kg": e["peso_real_kg"],
            "Diferencia kg": e["diferencia_kg"],
            "Diferencia %": e["diferencia_pct"],
            "Tolerancia kg": e["tolerancia_aplicada_kg"],
            # HU-07. Un guion no es un cero: mientras el clip no se ha
            # analizado no hay conteo, y confundir las dos cosas mandaria a
            # alguien a la rampa por una carga que nadie ha mirado todavia.
            "Sacos orden": e["sacos_esperados"],
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
                     else ("si" if e["clip_url"] else "en curso")),
        } for e in eventos]),
        use_container_width=True, hide_index=True)

    # HU-07, criterio 3: lo que el conteo aporta sobre el peso. Una carga con el
    # peso corto y los sacos completos no es lo mismo que una con sacos de menos:
    # la primera apunta a sustitucion de producto, la segunda a hurto de bultos.
    faltan_sacos = [e for e in eventos
                    if e["diferencia_sacos"] is not None and e["diferencia_sacos"] < 0]
    if faltan_sacos:
        st.warning(
            f"{len(faltan_sacos)} evento(s) con menos sacos en el video que en la "
            f"orden. Peso corto con los sacos completos apunta a producto "
            f"sustituido; sacos de menos, a bultos que no subieron.")

    sin_conteo = [e for e in eventos
                  if e["clip_url"] and e["sacos_contados"] is None]
    if sin_conteo:
        st.info(f"{len(sin_conteo)} evento(s) con clip pero sin conteo todavia. "
                f"Si no cambia, revisar que el servicio YOLO este en pie.")

    # HU-08 y RN-03. La presencia anomala es, junto con la diferencia de sacos,
    # lo que hara que HU-09 llame al modelo de vision-lenguaje.
    con_personal = [e for e in eventos if e["personal_anomalo"]]
    if con_personal:
        st.warning(
            f"{len(con_personal)} evento(s) con presencia de personal que llamo la "
            f"atencion: mas gente de la habitual a la vez, alguien mucho tiempo en "
            f"zona, o personas en rampa sin sacos cruzando. Es un motivo para "
            f"mirar el clip, no una conclusion sobre nadie.")

    # HU-09, criterio 3 y apartado 5.3. Un evento sin descripcion no es lo mismo
    # que uno que nadie intento describir, y el supervisor tiene que poder
    # distinguirlo sin abrir la auditoria.
    sin_analisis = [e for e in eventos if e["estado"] == "pendiente_analisis"]
    if sin_analisis:
        st.info(f"{len(sin_analisis)} evento(s) quedaron en Pendiente de analisis: "
                f"el modelo de vision-lenguaje fallo tras sus reintentos. La "
                f"severidad si esta, porque sale de la regla y no del modelo.")

    sin_clip = [e for e in eventos if e["estado"] == "sin_clip"]
    if sin_clip:
        st.info(f"{len(sin_clip)} evento(s) sin clip: no habia video de esa ventana "
                f"en el buffer. El detalle del motivo esta en la auditoria.")

    with st.expander("Ventana de video de un evento"):
        elegido = st.selectbox(
            "Evento", [e["id"] for e in eventos],
            format_func=lambda i: f"#{i}")
        evento = next(e for e in eventos if e["id"] == elegido)
        if evento["inicio_carga"]:
            st.write(f"Inicio de carga marcado: "
                     f"**{evento['inicio_carga'][:19].replace('T', ' ')}**")
        else:
            st.write("Nadie marco el inicio de carga: el clip cubre solo los "
                     "minutos previos al cierre.")
        if evento["clip_desde"]:
            st.write(f"Clip recortado de **{evento['clip_desde'][11:19]}** a "
                     f"**{evento['clip_hasta'][11:19]}**")
        if evento["sacos_contados"] is not None:
            st.write(f"Conteo del video: **{evento['sacos_contados']}** sacos "
                     f"frente a **{evento['sacos_esperados']}** de la orden "
                     f"(diferencia **{evento['diferencia_sacos']:+d}**)")
        elif evento["clip_url"]:
            st.write("El clip todavia no se ha analizado.")
        _analisis_del_evento(evento)
        _personas_del_evento(evento)
        _avisos_del_evento(evento)

        if evento["clip_url"]:
            st.caption("Ubicacion del clip en el almacen:")
            st.code(evento["clip_url"], language=None)


def _analisis_del_evento(evento: dict) -> None:
    """Lo que el modelo describio y por que el evento tiene esa severidad. HU-09.

    Las dos severidades se muestran juntas a proposito. La del evento sale de la
    RN-04 y es la que manda; la del modelo esta al lado para que el supervisor
    vea cuando discrepan, que es de donde sale la revision semanal del apartado
    9.2. Enseñar solo una escondería justo el dato que sirve para mejorar.
    """
    if evento["severidad"]:
        st.write(f"Severidad: **{evento['severidad'].capitalize()}** "
                 f"(regla RN-04)")

    analisis = evento.get("descripcion_ia")
    if not analisis:
        if evento["estado"] == "pendiente_analisis":
            st.info("El modelo de vision-lenguaje fallo tras sus reintentos. "
                    "La severidad de arriba sale de la regla, no del modelo.")
        return

    st.write(f"**Descripcion del modelo:** {analisis['descripcion']}")
    if analisis.get("evidencia"):
        st.write("Evidencia observada:")
        for punto in analisis["evidencia"]:
            st.write(f"- {punto}")

    severidad_ia = analisis.get("severidad_ia")
    if severidad_ia and severidad_ia != evento["severidad"]:
        st.warning(
            f"El modelo propuso severidad **{severidad_ia.capitalize()}** y la "
            f"regla dice **{evento['severidad'].capitalize()}**. Manda la regla. "
            f"Estas discrepancias son las que se revisan cada semana.")

    st.caption(
        f"Modelo {analisis.get('modelo', '?')} ({analisis.get('proveedor', '?')}), "
        f"confianza {analisis.get('confianza', 0):.0%}, "
        f"{analisis.get('intentos', 1)} intento(s). Es una ayuda para priorizar, "
        f"no una conclusion: la decision es del supervisor.")

    _fotogramas_del_evento(evento)


def _fotogramas_del_evento(evento: dict) -> None:
    """Los fotogramas que explican la carga, con su motivo y su segundo."""
    fotogramas = evento.get("fotogramas_clave") or []
    if not fotogramas:
        return

    st.caption("Fotogramas que el sistema eligio por lo que ocurrio en ellos:")
    for imagen in fotogramas:
        st.write(f"- segundo {imagen.get('segundo', 0):.0f}, "
                 f"{imagen.get('motivo', 'sin motivo')}: "
                 f"{imagen.get('detalle', '')}")
        st.code(imagen.get("url", ""), language=None)


def _personas_del_evento(evento: dict) -> None:
    """Quien estuvo en la zona de carga y cuanto. HU-08, criterio 2.

    El aviso sobre los identificadores no es un adorno legal: quien lee
    "persona 1" tiene que saber que ese 1 no es nadie en concreto y que no vale
    fuera de este clip. Sin eso, la tabla invita a sacar conclusiones sobre
    gente, que es justo lo que la RN-08 y el apartado 8 quieren evitar.
    """
    if evento["personas_detectadas"] is None:
        return

    respuesta = pedir("GET", f"/eventos/{evento['id']}/personas")
    if respuesta.status_code != 200:
        st.warning(detalle_del_error(respuesta))
        return
    presencia = respuesta.json()

    st.write(f"Personas en la zona de carga: **{presencia['cuantas']}**")
    if evento["personal_anomalo"]:
        st.warning("La presencia de personal llamo la atencion. Es un motivo "
                   "para mirar el clip, no una conclusion sobre nadie.")
    if not presencia["personas"]:
        st.caption("Nadie estuvo en la zona de carga durante el clip.")
        return

    st.dataframe(
        pd.DataFrame([{
            "Persona (id temporal)": p["id_temporal"],
            "Tiempo en zona (s)": float(p["segundos_en_zona"]),
            "Desde el fotograma": p["primer_fotograma"],
            "Hasta el fotograma": p["ultimo_fotograma"],
        } for p in presencia["personas"]]),
        use_container_width=True, hide_index=True)
    st.caption(presencia["nota"])


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
