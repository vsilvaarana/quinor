"""Construye los bocetos a lapiz de todas las pantallas de QUINOR.

Un archivo HTML y un PNG por pantalla. El estilo vive en estilo.py, asi que
cambiar el trazo o el gris en un sitio los cambia en las nueve.

Cada numero del margen aparece tambien junto al bloque que explica: sin eso, el
lector tiene que adivinar a que parte del dibujo se refiere cada nota.

    python3 construir.py              # escribe los HTML y renderiza los PNG
    python3 construir.py --solo-html
"""
from __future__ import annotations

import pathlib
import sys

from estilo import (CSS, FILTRO, PLANTILLA, anotacion, barra, caja, campo,
                    casilla, marca, marco, media, metrica, pastilla,
                    separacion, tabla)

AQUI = pathlib.Path(__file__).resolve().parent
SALIDA = AQUI / "pantallas"

PIE_COMUN = ("Boceto a lapiz. Trazo irregular, sin color, cifras y textos "
             "sustituidos por marcas. Sirve para acordar <em>que va en la "
             "pantalla y en que orden</em> sin discutir tipografias ni colores. "
             "Los numeros del dibujo se leen en el margen.")

PANTALLAS: list[dict] = []


def pantalla(slug, encabezado, subtitulo, contenido, anotaciones,
             sello="BORRADOR v0", pie=PIE_COMUN):
    PANTALLAS.append(dict(slug=slug, encabezado=encabezado, subtitulo=subtitulo,
                          contenido=contenido, anotaciones="".join(anotaciones),
                          sello=sello, pie=pie))


# ---------------------------------------------------------------- 01 ingreso
pantalla(
    "01_ingreso",
    "Ingreso al sistema",
    "HU-15, criterio 4 · boceto de trabajo, no es la interfaz final",
    f"""
<div style="max-width:520px; margin:40px auto 0;">
  {marca(1, caja(f'''
    <div style="font-size:15px; letter-spacing:1px; margin-bottom:4px;">
      QUINOR S.A.C. · CONTROL DE DESPACHO</div>
    <div class="nota" style="margin-bottom:22px;">Identificate para continuar</div>
    {campo("Correo", "nombre@quinor.com.pe", hueco=True, estilo="margin-bottom:20px;")}
    {campo("Contrasena", "• • • • • • • •", estilo="margin-bottom:22px;")}
    <div>{pastilla("Entrar", activa=True)}</div>
  '''))}
  {marca(2, '<div class="nota" style="margin-top:14px;">mensaje de error · el mismo para correo o clave equivocados</div>')}
  {marca(3, caja('<div class="nota" style="margin:0;">La clave viaja una vez. Lo que se guarda en la sesion del navegador es un token opaco, y se tira al salir.</div>', "punteado"))}
</div>
{separacion(20)}
""",
    [anotacion(1, "Criterio 4", "No hay clave estatica en ninguna parte: el "
                                "ingreso cambia correo y clave por un token "
                                "opaco que luego se puede revocar."),
     anotacion(2, "Seguridad", "El error no distingue si fallo el correo o la "
                               "clave. Distinguirlo serviria para averiguar "
                               "que correos existen."),
     anotacion(3, "Apartado 8", "La contrasena se guarda con bcrypt y el token "
                                "solo como hash: ni el sistema puede leerlos.")],
)

# ---------------------------------------------------------------- 02 bandeja
FILAS_BANDEJA = [
    ["0", "0000-00-00 00:00", "ORD-0000-0000", "cliente", "-000,00", "-0,00",
     "000", "000", "+0", "0", "revisar", "alta", "pendiente", "si"],
    ["0", "0000-00-00 00:00", "ORD-0000-0000", "cliente", "-000,00", "-0,00",
     "000", "000", "-0", "0", "normal", "media", "pendiente", "si"],
    ["0", "0000-00-00 00:00", "ORD-0000-0000", "cliente", "+000,00", "+0,00",
     "-", "-", "-", "-", "-", "-", "pendiente_analisis", "en curso"],
    ["0", "0000-00-00 00:00", "ORD-0000-0000", "cliente", "-000,00", "-0,00",
     "-", "-", "-", "-", "-", "-", "sin_clip", "no hay video"],
]

pantalla(
    "02_bandeja",
    "Bandeja de eventos de discrepancia",
    "HU-11 · boceto de trabajo, no es la interfaz final",
    marco("Eventos", f"""
  <div class="etiqueta">Eventos de discrepancia</div>
  <div class="nota" style="margin-bottom:14px;">
    se crea uno cuando la diferencia entre el peso real y el esperado supera la
    tolerancia del producto</div>

  {marca(1, f'''
  <div class="fila">
    <div class="col">{campo("Estado", "por defecto", flecha=True)}</div>
    <div class="col">{campo("Severidad", "todas", flecha=True)}</div>
    <div class="col">{campo("Periodo", "ultimos 7 dias", flecha=True)}</div>
    <div class="col" style="flex:2;">{campo("Numero de orden", "0148, o la orden completa", hueco=True)}</div>
  </div>
  <div class="fila" style="align-items:center;">
    <div class="col" style="flex:2;">{casilla("Solo con faltante de sacos")}</div>
    <div class="col">{campo("Filas por pagina", "50", flecha=True)}</div>
    <div class="col">{campo("Pagina", "1")}</div>
  </div>''')}

  {marca(2, '<div class="nota" style="margin-bottom:12px;">Vista por defecto: solo los <strong>Pendientes</strong> de los <strong>ultimos 7 dias</strong>. Cambia Estado o Periodo para ver mas.</div>')}

  {caja('<div class="texto">! &nbsp;0 evento(s) pendientes de revisar</div>', "doble", "margin-bottom:10px;")}
  {caja('<div class="texto">! &nbsp;0 evento(s) con presencia de personal que llamo la atencion</div>' + barra("larga"), "fino", "margin-bottom:14px;")}

  {marca(3, caja(tabla(
      ["ID", "Fecha", "Orden", "Cliente", "Dif. kg", "Dif. %", "Sacos orden",
       "Sacos video", "Dif. sacos", "Personas", "Personal", "Severidad",
       "Estado", "Clip"],
      FILAS_BANDEJA, derecha=(4, 5, 6, 7, 8, 9), clase="apretada")))}

  {marca(4, '<div class="nota" style="margin-top:8px;">Mostrando 1 a 0 de 0 evento(s) · Pagina 1 de 0 · consulta resuelta en 00 ms</div>')}
  {separacion(8)}
  {marca(5, caja('<div class="etiqueta" style="margin:0;">Detalle del evento, con video y fotogramas &nbsp; &#9662;</div>', "fino"))}
"""),
    [anotacion(1, "Criterios 1 y 2", "Los cuatro filtros se combinan entre si. "
                                     "Cada uno se manda solo si el supervisor "
                                     "lo toco, para no desactivar sin querer "
                                     "los valores por defecto."),
     anotacion(2, "Criterio 3", "La vista por defecto se declara. Sin ese "
                                "aviso, quien entra y ve tres eventos puede "
                                "irse creyendo que son todos los que hay."),
     anotacion(3, "Criterio 1 · NULL no es cero", "ID, fecha, orden, "
               "diferencia, severidad y estado, mas las columnas de HU-07 a "
               "HU-09. Un guion donde no hubo analisis: un cero diria que no "
               "cruzo ningun saco, que es otra cosa."),
     anotacion(4, "Criterio 2", "El tiempo de la consulta se muestra siempre, "
                                "no solo cuando pasa de 2 s: una pantalla que "
                                "se degrada hay que verla antes de que sea "
                                "costumbre."),
     anotacion(5, "Enlace", "Desde aqui se abre el detalle de HU-12, para el "
                            "evento que el supervisor elija.")],
)

# ---------------------------------------------------------------- 03 detalle
pantalla(
    "03_detalle",
    "Detalle del evento",
    "HU-12 · boceto de trabajo, no es la interfaz final",
    marco("Eventos", f"""
  {caja('<div style="font-size:14px; letter-spacing:1px;">EVENTO #0 &nbsp;·&nbsp; ORD-0000-0000</div>' + barra("media") + '<div class="nota">cliente · producto · fecha de la pesada · estado</div>', "", "margin-bottom:14px;")}

  {marca(1, f'''
  <div class="fila">
    <div class="col">{metrica("Peso esperado", "00 000,00 <small>kg</small>")}</div>
    <div class="col">{metrica("Peso real", "00 000,00 <small>kg</small>")}</div>
    <div class="col">{metrica("Diferencia", "-000,00 <small>kg / -0,00 %</small>", trazo="doble")}</div>
  </div>
  <div class="nota" style="margin:-6px 0 14px;">tolerancia aplicada aquel dia · cuanto se paso</div>
  <div class="fila">
    <div class="col">{metrica("Sacos en la orden", "000")}</div>
    <div class="col">{metrica("Sacos en el video", "000")}</div>
    <div class="col">{metrica("Diferencia", "+0")}</div>
  </div>''')}

  {marca(2, caja('<div class="texto">! &nbsp;AVISO DE SUSTITUCION DE PRODUCTO</div>' + barra("larga") + barra("media"), "doble", "margin-bottom:16px;"))}

  {marca(3, f'''
  <div class="etiqueta">Video del evento</div>
  {media("REPRODUCTOR DEL CLIP · ABRE EN EL SEGUNDO DE LA ANOMALIA", 200)}
  {caja('<div class="fila" style="margin:0; align-items:center; gap:10px;">'
        '<span style="font-size:13px;">&#9658;</span>'
        '<span style="font-size:11px;">00:00 / 00:00</span>'
        '<span style="flex:1;">' + barra("larga") + '</span>'
        '<span style="font-size:11px; letter-spacing:1px;">PAUSA · AVANCE · PANTALLA COMPLETA</span>'
        '</div>', "fino", "margin:6px 0; padding:8px 12px;")}
  <div class="nota" style="margin-bottom:16px;">ventana recortada · camara · aviso de formato .mkv · el enlace caduca</div>''')}

  {marca(4, f'''
  <div class="etiqueta">Fotogramas del analisis</div>
  <div class="fila">
    <div class="col">
      {media("FOTOGRAMA 1<br>ANOMALIA", 110, trazo="doble")}
      <div class="nota" style="margin:6px 0;">s00 · saco saliente</div>
      {pastilla("Ver el clip desde el segundo 0", activa=True)}
    </div>
    <div class="col">
      {media("FOTOGRAMA 2", 110, trazo="fino")}
      <div class="nota" style="margin:6px 0;">s00 · primer saco</div>
      {pastilla("Ver el clip desde el segundo 0", activa=True)}
    </div>
    <div class="col" style="opacity:.4;">
      {media("HASTA 4<br>FOTOGRAMAS", 110, trazo="fino", con_aspa=False)}
    </div>
  </div>''')}

  {marca(5, caja('<div class="etiqueta">Analisis</div>'
        '<div class="texto" style="margin-bottom:6px;">SEVERIDAD: <strong>ALTA</strong> (regla) &nbsp;|&nbsp; el modelo propuso: MEDIA</div>'
        + barra("larga") + barra("larga") + barra("media") +
        '<div class="nota" style="margin-top:8px;">descripcion del modelo · evidencia · aviso cuando las dos severidades discrepan</div>', "", "margin-bottom:14px;"))}

  {marca(6, caja('<div class="etiqueta">Personas en la zona de carga</div>'
        + tabla(["Persona (id temporal)", "Tiempo en zona", "Desde el fotograma", "Hasta el fotograma"],
                [["0", "00,0 s", "000", "0 000"], ["0", "00,0 s", "000", "0 000"],
                 ["0", "00,0 s", "0 000", "0 000"]], derecha=(1, 2, 3))
        + '<div class="nota" style="margin-top:8px;">identificadores temporales del rastreador · sin identificacion facial ni datos biometricos (RN-08)</div>', "", "margin-bottom:14px;"))}

  {caja('<div class="etiqueta" style="margin:0;">Avisos enviados (HU-10)</div>' + barra("media"), "fino")}
"""),
    [anotacion(1, "Criterio 1", "Los pesos y el conteo primero: la "
                                "discrepancia es el hecho y existe desde que "
                                "cerro el camion; el video solo la verifica."),
     anotacion(2, "Conclusion", "Peso corto con los bultos cuadrados: la firma "
                                "de la sustitucion de producto, que es el "
                                "problema que motiva el sistema."),
     anotacion(3, "Criterio 2", "Reproductor del navegador: la pausa y el "
                                "avance vienen de serie. El enlace al almacen "
                                "caduca a los quince minutos."),
     anotacion(4, "Criterio 3", "El fotograma de la anomalia va primero y "
                                "remarcado, y su boton lleva el video a ese "
                                "segundo."),
     anotacion(5, "HU-09", "Las dos severidades juntas: manda la regla, y se "
                           "ve cuando el modelo discrepa."),
     anotacion(6, "RN-08", "Numero temporal y tiempo en zona. Ni foto, ni "
                           "nombre, ni codigo de empleado.")],
)

# ------------------------------------------------------------- 04 clasificar
pantalla(
    "04_clasificar",
    "Clasificar el evento",
    "HU-13 · diseno previo: la historia todavia no esta desarrollada",
    marco("Eventos", f"""
  {marca(1, caja('<div style="font-size:14px; letter-spacing:1px;">EVENTO #0 &nbsp;·&nbsp; ORD-0000-0000</div>'
        '<div class="nota" style="margin-bottom:10px;">el detalle de HU-12 queda arriba: el veredicto se da mirando el clip</div>'
        '<div class="nota" style="margin:0;">… pesos, conteo, video y fotogramas …</div>', "punteado", "margin-bottom:18px;"))}

  {marca(2, caja(f'''
    <div class="etiqueta">Veredicto del supervisor</div>
    <div class="fila" style="margin-bottom:14px;">
      <div class="col">{pastilla("( ) Confirmado", activa=True)}</div>
      <div class="col">{pastilla("( ) Falso positivo", activa=True)}</div>
      <div class="col"></div>
    </div>
    {campo("Comentario (minimo 10 caracteres)", "que se vio y que se decidio", hueco=True, estilo="min-height:78px;")}
    <div class="nota" style="margin:6px 0 14px;">0 / 10 caracteres · el boton no se habilita hasta llegar</div>
    <div>{pastilla("Guardar veredicto", activa=True)}{pastilla("Cancelar")}</div>
  '''))}

  {marca(3, caja('<div class="texto">! &nbsp;Un evento Confirmado no vuelve a Pendiente (RN-06)</div>'
        '<div class="nota">la regla la hace cumplir el motor con un trigger; la pantalla lo dice antes de que alguien lo intente</div>', "doble", "margin:14px 0;"))}

  {marca(4, caja('<div class="etiqueta">Historial de veredictos</div>'
        + tabla(["Fecha", "Usuario", "Veredicto", "Comentario"],
                [["0000-00-00 00:00", "nombre del supervisor", "en_revision", "texto del comentario"],
                 ["0000-00-00 00:00", "nombre del supervisor", "confirmado", "texto del comentario"]])
        + '<div class="nota" style="margin-top:8px;">sale de la tabla veredicto y de la auditoria, que no admite UPDATE ni DELETE</div>', ""))}
"""),
    [anotacion(1, "Por que aqui", "El veredicto se da mirando el clip. "
                                  "Sacarlo a otra pantalla obligaria a "
                                  "recordar lo que se acaba de ver."),
     anotacion(2, "Criterio 1", "El comentario es obligatorio y de diez "
                                "caracteres minimo (RN-05). El contador esta a "
                                "la vista para que nadie pulse a ciegas."),
     anotacion(3, "Criterio 3", "Confirmado no retrocede. El trigger que lo "
                                "impide ya existe; falta traducir su error a "
                                "una frase en la pantalla."),
     anotacion(4, "Criterio 2", "Queda registrado usuario y fecha. El usuario "
                                "sale del token, no de un campo que se pueda "
                                "escribir, y la auditoria no se puede alterar.")],
    sello="DISENO PREVIO",
    pie=("Boceto a lapiz de una pantalla <strong>que todavia no existe</strong>. "
         "HU-13 es la ultima historia del MVP, y la que desbloquea las dos "
         "mediciones del piloto: los falsos positivos y la concordancia de "
         "severidad. Esto es la propuesta, no un reflejo de lo construido."),
)


# --------------------------------------------------- 05 y 06 tolerancias
def tolerancias(editable: bool) -> str:
    rol = "administrador" if editable else "supervisor"
    guardar = pastilla("Guardar", activa=True) if editable else pastilla("Guardar")
    aviso = "" if editable else marca(4, caja(
        '<div class="texto" style="margin:0;">Solo el rol Administrador puede '
        'editar estos valores</div>', "fino", "margin-bottom:14px;"))

    campos = marca(1, (
        '<div class="fila">'
        f'<div class="col">{campo("Tolerancia en kg", "000,00", apagado=not editable)}</div>'
        f'<div class="col">{campo("Tolerancia en %", "0,00", apagado=not editable)}</div>'
        '</div>'
        f'<div style="margin-bottom:16px;">{guardar}</div>'))

    simulador = marca(2, (
        '<div class="fila" style="align-items:center;">'
        f'<div class="col">{campo("Simular con una orden de (kg)", "00 000,00")}</div>'
        '<div class="col" style="flex:2;">'
        '<div class="texto">manda <strong>el porcentaje</strong>: se admiten '
        '<strong>000,00 kg</strong> de diferencia</div>'
        '<div class="nota">(el porcentaje equivale a 000,00 kg)</div>'
        '</div></div>'))

    historial = marca(3, (
        '<div class="nota" style="margin:14px 0 4px;">historial de cambios</div>'
        + tabla(["Fecha", "Usuario", "kg", "%"],
                [["0000-00-00 00:00", "nombre", "000,00 → 000,00", "0,00 → 0,00"],
                 ["0000-00-00 00:00", "nombre", "000,00 → 000,00", "0,00 → 0,00"]],
                derecha=(2, 3))))

    canales = caja('<div class="nota" style="margin:0;">alta → correo &nbsp;·&nbsp; '
                   'media → correo &nbsp;·&nbsp; baja → correo</div>', "punteado")

    producto = caja(
        '<div class="texto" style="margin-bottom:4px;"><strong>Quinua blanca '
        'organica</strong> &nbsp; &#9662;</div>'
        '<div class="nota" style="margin-bottom:18px;">ultimo cambio: '
        '0000-00-00 00:00 · nombre de quien lo hizo</div>'
        + campos + simulador +
        '<div class="nota" style="margin:10px 0 4px;">canales de alerta por '
        'severidad (los edita HU-10) &nbsp; &#9662;</div>' + canales + historial)

    otro = caja('<div class="texto" style="margin:0;">Quinua roja organica '
                '&nbsp; &#9656;</div>', "fino", "margin-top:12px;")
    cuarta = marca(4, otro) if editable else otro

    return marco("Tolerancias", f"""
  <div class="etiqueta">Tolerancias por producto</div>
  <div class="nota" style="margin-bottom:14px;">
    se aplica la mas restrictiva entre los kg y el porcentaje (RN-01) · cada
    cambio queda registrado con usuario y fecha</div>
  {aviso}
  {producto}
  {cuarta}
  {caja('<div class="texto" style="margin:0;">Quinua negra convencional &nbsp; &#9656;</div>', "fino", "margin-top:10px;")}
""", rol=rol)


pantalla(
    "05_tolerancias_administrador",
    "Tolerancias por producto · rol Administrador",
    "HU-04 · boceto de trabajo, no es la interfaz final",
    tolerancias(editable=True),
    [anotacion(1, "Criterios 1 y 2", "Tolerancia en kg y en porcentaje por "
                                     "producto, editables solo para el rol "
                                     "Administrador."),
     anotacion(2, "RN-01", "Manda la mas restrictiva de las dos. El simulador "
                           "lo traduce a kg concretos: nadie calcula de cabeza "
                           "si el 0,5 % de 20 000 kg pasa del tope en kg."),
     anotacion(3, "Criterio 3", "Cada cambio queda con usuario y fecha, y el "
                                "historial se lee aqui mismo."),
     anotacion(4, "Un producto por bloque", "Se abren de uno en uno. Tres "
                                            "productos configurados hoy; el "
                                            "catalogo lo marca el ERP.")],
)

pantalla(
    "06_tolerancias_supervisor",
    "Tolerancias por producto · rol Supervisor",
    "HU-04 y HU-15 · boceto de trabajo, no es la interfaz final",
    tolerancias(editable=False),
    [anotacion(1, "Criterio 2", "Los campos salen apagados y el boton Guardar "
                                "no responde. La API ademas lo rechaza con "
                                "403: las dos cosas, no una."),
     anotacion(2, "RN-01", "El simulador si funciona. Saber contra que umbral "
                           "se mide su rampa es justo lo que el supervisor "
                           "necesita."),
     anotacion(3, "Criterio 3", "Tambien ve quien cambio que y cuando, sin "
                                "poder cambiarlo."),
     anotacion(4, "Por que se le muestra", "Ocultarselo solo conseguiria que "
                                           "preguntara por chat cada vez. "
                                           "Ademas, su barra lateral no tiene "
                                           "la pestana Usuarios.")],
)

# --------------------------------------------------------------- 07 usuarios
BLOQUE_ROL = marca(2, (
    '<div class="fila">'
    f'<div class="col">{campo("Rol", "consulta", flecha=True)}</div>'
    f'<div class="col">{campo("Contrasena inicial", "• • • • • • • •")}</div>'
    '</div>'
    '<div class="nota" style="margin-bottom:12px;">minimo 8 caracteres, '
    'maximo 72 bytes</div>'))

pantalla(
    "07_usuarios",
    "Usuarios y roles",
    "HU-15 · boceto de trabajo, no es la interfaz final",
    marco("Usuarios", f"""
  <div class="etiqueta">Usuarios y roles</div>
  <div class="nota" style="margin-bottom:14px;">
    los usuarios no se borran, se desactivan: la auditoria tiene que seguir
    apuntando a una persona identificable</div>

  {marca(1, caja(f'''
    <div class="texto" style="margin-bottom:14px;">Crear usuario &nbsp; &#9662;</div>
    <div class="fila">
      <div class="col">{campo("Nombre", "nombre y apellido", hueco=True)}</div>
      <div class="col">{campo("Correo", "nombre@quinor.com.pe", hueco=True)}</div>
    </div>
    {BLOQUE_ROL}
    <div>{pastilla("Crear", activa=True)}</div>
  ''', "", "margin-bottom:16px;"))}

  {marca(3, caja(tabla(["Nombre y correo", "Estado", "Rol", ""],
              [["<strong>nombre</strong><br><span class='nota'>correo@quinor.com.pe</span>", "activo", "administrador &#9662;", pastilla("Desactivar", activa=True)],
               ["<strong>nombre</strong><br><span class='nota'>correo@quinor.com.pe</span>", "activo", "supervisor &#9662;", pastilla("Desactivar", activa=True)],
               ["<strong>nombre</strong><br><span class='nota'>correo@quinor.com.pe</span>", "inactivo", "consulta &#9662;", pastilla("Reactivar", activa=True)]])))}
"""),
    [anotacion(1, "Criterio 1", "Crear, desactivar y asignar rol, que son las "
                                "tres cosas que pide la historia."),
     anotacion(2, "Criterio 3", "Tres roles: Administrador, Supervisor y "
                                "Consulta. La contrasena se guarda con bcrypt "
                                "y no se vuelve a leer."),
     anotacion(3, "No se borra", "Desactivar, nunca borrar: la auditoria tiene "
                                 "que seguir apuntando a alguien. Esta pestana "
                                 "no existe para los otros dos roles.")],
)

# ----------------------------------------------------------------- 08 tokens
pantalla(
    "08_tokens",
    "Mis tokens de API",
    "HU-15, criterio 4 · boceto de trabajo, no es la interfaz final",
    marco("Mis tokens", f"""
  <div class="etiqueta">Mis tokens de API</div>
  <div class="nota" style="margin-bottom:14px;">
    el valor en claro se muestra una sola vez; despues solo queda su hash</div>

  {marca(1, caja(f'''
    <div class="texto" style="margin-bottom:14px;">Emitir un token nuevo &nbsp; &#9662;</div>
    <div class="fila">
      <div class="col">{campo("Para que equipo", "Laptop de rampa 1", hueco=True)}</div>
      <div class="col">{campo("Vigencia en horas", "12")}</div>
      <div class="col" style="display:flex; align-items:center;">{pastilla("Emitir", activa=True)}</div>
    </div>
    {marca(2, caja('<div class="nota" style="margin:0 0 6px;">copia este valor ahora: no se vuelve a mostrar</div>' + barra("larga"), "punteado"))}
  ''', "", "margin-bottom:16px;"))}

  {marca(3, caja(tabla(["Nombre", "Vence", "Ultimo uso", ""],
              [["<strong>equipo</strong>", "0000-00-00 00:00", "0000-00-00 00:00", pastilla("Revocar", activa=True)],
               ["<strong>equipo</strong>", "0000-00-00 00:00", "sin usar", pastilla("Revocar", activa=True)],
               ["<strong>equipo</strong>", "0000-00-00 00:00", "Revocado", "-"]])))}
"""),
    [anotacion(1, "Criterio 4", "El token se emite con nombre y vencimiento. "
                                "Cada equipo lleva el suyo, para poder "
                                "revocarlo sin tocar a los demas."),
     anotacion(2, "Una sola vez", "El valor en claro se ensena al emitirlo y "
                                  "no se guarda: en la base solo queda su "
                                  "hash."),
     anotacion(3, "Revocar", "Deja de servir en la siguiente peticion. El "
                             "ultimo uso dice que equipos siguen vivos antes "
                             "de cortar algo que alguien esta usando.")],
)

# ------------------------------------------------------------------ 09 salud
pantalla(
    "09_salud",
    "Estado de los componentes",
    "Consulta de salud · el panel completo es HU-18, fuera del MVP",
    marco("Salud", f"""
  <div class="etiqueta">Estado de los componentes</div>
  {marca(1, caja('<div class="texto" style="margin:0;">Todos los componentes responden</div>', "fino", "margin:6px 0 14px;"))}
  {marca(2, caja(tabla(["Componente", "Estado", "Mensaje", "Verificado"],
              [["mysql", "ok", "responde", "0000-00-00 00:00"],
               ["erp", "ok", "responde", "0000-00-00 00:00"],
               ["bascula", "ok", "lectura estable", "0000-00-00 00:00"],
               ["camara-rampa-01", "ok", "grabando", "0000-00-00 00:00"],
               ["disco-video", "advertencia", "queda poco espacio del buffer", "0000-00-00 00:00"],
               ["configuracion", "error", "un producto sin tolerancia configurada", "0000-00-00 00:00"]])))}
  {marca(3, '<div class="nota" style="margin-top:10px;">el ultimo estado conocido de cada componente · no se sondea al abrir la pantalla, se lee lo que ya se registro</div>')}
"""),
    [anotacion(1, "Lo que se ve de un vistazo", "Una linea que resume, porque "
               "quien abre esta pestana quiere saber si hay algo roto, no leer "
               "una tabla."),
     anotacion(2, "Quien escribe cada fila", "El orquestador anota base de "
               "datos, ERP y bascula; el grabador anota camaras y disco. Una "
               "carga que no se pudo evaluar por falta de tolerancia tambien "
               "aparece aqui, en lugar de quedarse en un log."),
     anotacion(3, "HU-18", "Solo se guarda fila cuando el estado cambia: "
               "sondear cada 30 s llenaria la tabla de filas iguales. El panel "
               "con semaforos y sondeo periodico es HU-18, postergada fuera "
               "del MVP.")],
)


# ----------------------------------------------------------------- escritura
def main() -> None:
    SALIDA.mkdir(exist_ok=True)
    rutas = []
    for p in PANTALLAS:
        html = PLANTILLA.format(
            titulo=f"{p['encabezado']} · boceto QUINOR",
            css=CSS, filtro=FILTRO, sello=p["sello"],
            encabezado=p["encabezado"], subtitulo=p["subtitulo"],
            contenido=p["contenido"], anotaciones=p["anotaciones"], pie=p["pie"])
        ruta = SALIDA / f"{p['slug']}.html"
        ruta.write_text(html, encoding="utf-8")
        rutas.append(ruta)
        print("escrito", ruta.name)

    if "--solo-html" in sys.argv:
        return

    import asyncio

    from playwright.async_api import async_playwright

    async def renderizar():
        async with async_playwright() as pw:
            nav = await pw.chromium.launch(
                executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
            # La ventana se deja baja a proposito: con full_page la captura
            # crece hasta el contenido, y una ventana alta solo anadiria papel
            # en blanco debajo de las pantallas cortas.
            pag = await nav.new_page(viewport={"width": 1480, "height": 400},
                                     device_scale_factor=2)
            for ruta in rutas:
                await pag.goto(ruta.as_uri(), wait_until="networkidle")
                await pag.wait_for_timeout(500)
                destino = ruta.with_suffix(".png")
                await pag.screenshot(path=str(destino), full_page=True)
                print("renderizado", destino.name,
                      destino.stat().st_size // 1024, "KB")
            await nav.close()

    asyncio.run(renderizar())


if __name__ == "__main__":
    main()
