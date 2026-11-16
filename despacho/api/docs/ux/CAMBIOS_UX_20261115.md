# Dashboard: cambios de UX del 15/11/2026

Registro de lo que cambio en `dashboard/app.py` a raiz de la critica de diseno
del 15/11/2026. Hasta la fase 4 solo cambia la pantalla. La fase 5 anade un
endpoint a la API (`POST /pesadas/lectura-previa`); el esquema y las reglas de
negocio quedan igual. El prototipo con el antes y el despues de cada pantalla
esta en el artefacto "QUINOR - Critica UX/UI: antes y despues" del proyecto PI1.

## Estado

| Bloque | Que cubre | Estado |
|---|---|---|
| Puntos criticos | 5 fallos que afectaban la decision o el control | Hecho |
| Fase 1 | Textos: tildes, trato de usted, jerga | Hecho |
| Fase 2 | Bandeja: filtros a la vista, hallazgo en la tarjeta, paginacion | Hecho |
| Fase 3 | Confirmaciones antes de acciones de administracion | Hecho |
| Fase 4 | Menu lateral en lugar de ocho pestanas | Hecho |
| Fase 5 | Pesada guiada y lectura previa de la bascula (endpoint nuevo) | Hecho |
| Fase 6 | Tolerancias en tabla, ingreso centrado | Hecho |
| Fase 7 | Manual de usuario, capturas, prueba con un supervisor | Manual y capturas hechos; la prueba, pendiente (hay guion) |

## Puntos criticos

| # | Antes | Ahora | Donde |
|---|---|---|---|
| 1 | El peso manual venia con el peso esperado de la orden y el aviso salia en verde sin escribir nada | El campo empieza vacio, no hay aviso hasta escribir y no se registra sin peso | `_cierre_de_la_carga`, `_aviso_previo` |
| 2 | Un faltante de peso salia en verde (`delta_color="inverse"` fijo) | La diferencia sale en rojo, falte o sobre | `_cifras_del_detalle` |
| 3 | El detalle se abria en un desplegable al final de la bandeja | El evento tiene su pagina, con Volver, Anterior y Siguiente. Los filtros se conservan al volver | `panel_de_eventos`, `_pagina_del_evento`, `_conservar_filtros` |
| 4 | La clasificacion quedaba debajo de todo, lejos del video | Va en una columna al lado del video. La conclusion de sustitucion va antes que las cifras | `_pagina_del_evento`, `_cifras_del_detalle` |
| 5 | La cabecera decia "Rampa 1 - En linea" siempre | Lee `GET /salud`: en verde dice cuantas camaras graban, en rojo nombra el componente caido. Si la sesion vencio, cierra sesion ahi | `_estado_de_la_planta` |

## Fase 1: textos

- Tildes y ortografia en todos los textos visibles (64 lineas). Los comentarios
  y docstrings siguen sin tildes, como en el resto del proyecto.
- Trato de usted en todos los mensajes ("Vuelva a iniciar sesion", "Revise el
  detalle", "Compruebe que...").
- El error de conexion ya no muestra la direccion interna de la API ni la
  excepcion: "No hay conexion con el sistema. Intente de nuevo en unos
  segundos; si continua, avise al administrador." (`pantalla_de_ingreso`,
  `panel_de_salud`).
- El aviso de Matroska pasa a decir que hacer ("abralo en Chrome o Edge, o
  descarguelo") y el del enlace firmado, que caduca por seguridad. La razon
  tecnica sigue en los comentarios y en el README.
- "Manda kg" pasa a "Se aplica el limite en kg" (`panel_de_tolerancias`).
- El pie de los fotogramas pasa de "s412 - motivo" a "Segundo 412: motivo".
- La vista de tabla muestra el nombre del estado ("Falso positivo") y no el
  codigo de la API (`falso_positivo`). El rol del usuario se escribe con
  mayuscula inicial.

Sin tocar a proposito: los textos que llegan de la API (mensajes de `/salud`,
`clip.enlace.explicacion`, `personas.nota`, los `detail` de los errores) y el
nombre de los componentes (`camara-rampa-01`). Si vienen sin tildes, se
corrigen en el servicio que los escribe. Tampoco "buffer", que queda para la
fase 6.

## Fase 2: bandeja de eventos

- **Filtros a la vista.** El estado se elige con etiquetas (`st.pills`); el
  periodo y el numero de orden estan siempre visibles. Severidad, "Solo con
  diferencia de sacos" y eventos por pagina van en "Mas filtros", cuya etiqueta
  dice cuantos hay puestos.
- **Paginacion en el pie.** Botones Anterior y Siguiente junto al texto
  "Pagina X de Y". Cambiar cualquier filtro vuelve a la pagina 1.
- **Hallazgo en la tarjeta.** Cada tarjeta dice "Posible sustitucion", "Faltan
  N sacos", "Sobran N sacos", "Sobrepeso con sacos completos" o "Conteo de
  sacos pendiente". Usa las mismas reglas que `bandeja.resumen` de la API
  (`_hallazgo_de_la_fila`).
- **Diferencia en kg destacada.** Va en grande y en rojo; antes iba en la letra
  mas pequena.
- **Resumen.** Se anade la etiqueta "con posible sustitucion"
  (`con_peso_corto_y_sacos_completos`, que la API ya calculaba y la pantalla no
  mostraba). Lo que la API sabe filtrar se ofrece en botones ("Ver solo...");
  las etiquetas quedan como informacion.

### Dos correcciones de comportamiento en los filtros

`sin_defectos` apaga a la vez los dos valores por defecto de la API (estado
Pendiente y ventana de 7 dias). La pantalla lo usaba para dos cosas distintas y
el resultado no coincidia con lo que se leia:

| Filtro en pantalla | Antes mostraba | Ahora muestra |
|---|---|---|
| Pendientes + periodo "Todo" | Todos los estados de todo el historico | Solo pendientes de todo el historico (se manda `estado=pendiente`) |
| Todos + "Ultimos 7 dias" | Todo el historico | Todos los estados de los ultimos 7 dias (se manda `desde`) |

La opcion "Pendiente" explicita del desplegable anterior desaparece: era
equivalente a "Pendientes" salvo por ese efecto.

## Fase 3: confirmaciones

- **Revocar token, desactivar o reactivar usuario, cambiar rol** pasan por un
  dialogo (`_confirmar`, con `st.dialog`) que dice que va a ocurrir. El
  resultado se muestra al cerrarse (`_aviso_de_administracion`).
- **Cambio de rol.** Elegir otro rol en la lista ya no lo aplica: aparece el
  boton "Aplicar rol", que abre el dialogo.
- **Clasificacion.** Antes del cuadro de texto se avisa de que confirmar la
  discrepancia no se puede devolver a Pendiente (criterio 3 de HU-13). El
  minimo de 10 caracteres va en la etiqueta del campo.
- Las listas de tokens y usuarios tienen cabecera de columnas.

Limites conocidos:

- No hay contador en vivo de "faltan N caracteres" en la justificacion: dentro
  de un formulario Streamlit no redibuja mientras se escribe. El maximo (1000)
  si lo cuenta el propio campo.
- Se quito un bloque que comparaba con `st.session_state["token_id"]`, clave
  que nunca se guardaba. Revocar el token de la propia sesion se resuelve en la
  siguiente pasada: la API responde 401 y la cabecera cierra sesion.

## Fase 4: menu lateral

Las ocho pestanas (`st.tabs`) pasan a ser un menu en la barra lateral
(`st.navigation`), en tres grupos:

| Grupo | Pantallas | Direccion |
|---|---|---|
| Operacion | Eventos (con el numero de pendientes), Registro de pesada, Ordenes | `/`, `/pesadas`, `/ordenes` |
| Monitoreo | Camaras, Estado del sistema | `/camaras`, `/estado` |
| Administracion | Tolerancias, Tokens de acceso y, solo para el administrador, Usuarios | `/tolerancias`, `/tokens`, `/usuarios` |

- **Solo se ejecuta la pantalla abierta.** `st.tabs` ejecutaba el contenido de
  las ocho en cada clic. Medido con la API simulada: abrir Eventos hace ahora
  llamadas a 2 rutas (`/eventos/bandeja` y `/salud`) y Registro de pesada a 3;
  antes cada pasada pedia tambien pesadas, ordenes, cargas, tolerancias, tokens
  y usuarios.
- **El contador de pendientes va en el menu** ("Eventos (3)"), visible desde
  cualquier pantalla. Si la API no contesta, el menu dice "Eventos" a secas y no
  "0" (`_eventos_abiertos`).
- **La linea de estado va en todas las pantallas; el titulo grande, solo en
  Eventos** (`_pantalla`, `_cabecera_de_eventos`).
- **Los filtros de la bandeja se conservan** al visitar otra pantalla
  (`_conservar_filtros` se llama ahora desde el programa).
- **Barra lateral:** el menu arriba y, debajo, el usuario, "Actualizar datos"
  (ya no es el boton principal) y "Cerrar sesion".
- Los textos que decian "la pestana Eventos" dicen ahora "Eventos".

Cosas a tener en cuenta:

- Cada pantalla tiene direccion propia, asi que se puede guardar un enlace a
  `http://localhost:8501/pesadas`. La sesion sigue viviendo en la memoria del
  navegador: abrir el enlace en una pestana nueva pide iniciar sesion.
- El formulario a medio llenar de una pantalla se pierde al cambiar a otra
  (Streamlit descarta los controles que no se dibujan). Se conservan los
  filtros de la bandeja, la orden consultada y el resultado de la ultima pesada.
- Si se queda abierta la pagina de un evento y se va a otra pantalla, al volver
  a Eventos se sigue viendo ese evento. "Volver a Eventos" lleva a la bandeja.

## Fase 5: pesada guiada y lectura previa

### En la API: `POST /pesadas/lectura-previa`

Lee la bascula y dice que pasaria al registrar, sin registrar nada.

| | |
|---|---|
| Cuerpo | `numero_orden` (obligatorio), `bascula_id` (opcional) |
| Rol | El mismo que registrar una pesada (`requiere_escritura`); Consulta recibe 403 |
| 200 | `peso_kg`, `estable`, `leido_en`, `peso_esperado_kg`, `diferencia_kg`, `diferencia_pct`, `tolerancia_kg`, `generaria_evento` |
| 404 | La orden no existe en el ERP ni en la copia local |
| 503 | La bascula no responde; el fallo queda en `salud_componente` |
| 422 | Falta `numero_orden` |

Decisiones, tomadas con el responsable del proyecto el 15/11/2026:

- **Cada lectura previa deja una fila en `auditoria`** (`accion =
  'lectura_previa'`, `entidad = 'orden_despacho'`, con el usuario y, en el
  detalle, bascula, peso, si era estable, diferencia, tolerancia y si generaria
  evento). Motivo: hasta ahora la pesada con bascula era atomica, se leia y se
  guardaba en la misma peticion. Con la lectura previa alguien puede ver el
  faltante antes de que exista un registro y no registrar. El rastro convierte
  eso en algo que se puede consultar:

  ```sql
  -- Lecturas previas fuera de tolerancia sin pesada posterior de esa orden
  SELECT a.fecha, a.usuario_id, a.detalle
    FROM auditoria a
   WHERE a.accion = 'lectura_previa'
     AND JSON_EXTRACT(a.detalle, '$.generaria_evento') = true
     AND NOT EXISTS (SELECT 1 FROM pesada p
                      WHERE p.orden_id = a.entidad_id AND p.fecha_hora >= a.fecha);
  ```

- **Al registrar, la API vuelve a leer la bascula.** El peso de la lectura
  previa nunca viaja desde el navegador.
- **Null no es "no".** Con la bascula en movimiento se responde 200 con
  `estable: false` y sin diferencia; sin tolerancia configurada,
  `generaria_evento` va en null.
- No crea pesada ni evento y no consume la marca de inicio de carga (HU-06).
- No se anadio al Excel del backlog; queda documentado aqui y en el README.

Codigo: `pesadas.lectura_previa` y `pesadas._leer_anotando_la_salud` (la
lectura con anotacion de salud, que ahora comparten la pesada y la previa),
`schemas.PedirLecturaPrevia`, `schemas.LecturaPrevia`, y la ruta en `main.py`.
13 pruebas nuevas en `tests/test_api.py` (bloque "POST /pesadas/lectura-previa").

**Pendiente que conviene decidir:** el rastro existe, pero ninguna pantalla lo
muestra. Hoy solo se ve con la consulta SQL de arriba. Un listado de "lecturas
previas sin pesada" en Estado del sistema o en Eventos cerraria el circulo.

### En la pantalla: Registro de pesada

- **Los pasos se abren de uno en uno.** Paso 1, consultar la orden; al
  consultarla queda resumida en una linea con "Cambiar orden". Paso 2, iniciar
  la carga. Paso 3, el pesaje. Antes los tres estaban a la vista a la vez.
- **Se puede pesar sin marcar el inicio**, porque la API lo admite, pero hay
  que pulsarlo ("La carga ya termino: pesar sin marcar el inicio") y la
  pantalla dice lo que se pierde: el video cubrira solo los 5 minutos previos.
- **Pesaje con bascula en dos tiempos:** "Leer bascula" muestra el peso, la
  diferencia contra la orden y si generara un evento; despues, "Registrar
  pesada y cerrar carga". La pantalla avisa de que cada lectura queda
  registrada con el usuario. Con la bascula en movimiento no deja registrar.
- **El reloj de la carga** baja de 64 a 30 px.
- **El historial** tiene una columna "Resultado" ("Evento #214" o "Sin
  evento"), la primera. Sale de una sola llamada a `GET /eventos`; si falla,
  dice "No disponible" en lugar de "Sin evento".
- El ingreso manual no cambia.

Funciones: `panel_de_pesadas`, `_orden_en_curso`, `_inicio_de_la_carga`,
`_pesaje_con_bascula`, `_pesaje_manual`, `_leer_la_bascula`,
`_registrar_la_pesada`, `_eventos_por_pesada`, `_historial_de_pesadas`.
Desaparece `_ficha_de_la_orden`.

## Fase 6: tolerancias e ingreso

- **Tolerancias en una tabla** con todos los productos: limite en kg, limite en
  %, cuantos kilos se admiten para una orden de ejemplo (un solo campo para
  toda la tabla), que regla se aplica, los avisos y el ultimo cambio. Se edita
  un producto cada vez, elegido en una lista. El calculo de la tolerancia
  efectiva lo sigue haciendo la API (`/configuracion/{producto}/aplicada`).
- **Los canales de aviso se leen en texto** ("Alta: SMS, Slack - Media: ...")
  y no en JSON. **Siguen sin poder editarse**: la API no lo ofrece (lo deja para
  HU-10), y la pantalla lo dice. El prototipo los mostraba como casillas; eso
  no se hizo porque no habia donde guardarlas.
- **Guardar pide confirmacion** con el antes y el despues (`_confirmar`), y no
  llama a la API si no cambio nada.
- **El supervisor tiene una vista de lectura**, sin campos ni botones
  deshabilitados.
- **Solo se pide el historial del producto elegido** (antes, el de todos).
- **Ingreso en dos mitades**, como en el prototipo: a la izquierda un panel
  verde con el nombre del sistema y para que sirve, a la derecha el formulario.
  En pantallas estrechas se apilan. La primera version (hecha por un subagente
  y revisada) solo centraba el formulario; el responsable pidio el diseno del
  prototipo y se rehizo el mismo 15/11/2026 (`pantalla_de_ingreso`, clase
  `.q-marca`). Comprobado en el navegador contra el dashboard local. No se anadio un boton para ver la
  contrasena porque el campo de Streamlit ya lo trae: ese punto de la critica
  inicial era incorrecto.
- "Buffer de video" pasa a "Almacen de grabacion".

Funciones: `panel_de_tolerancias`, `_canales_en_texto`,
`_edicion_de_la_tolerancia`, `_historial_de_la_tolerancia`,
`pantalla_de_ingreso`, `_intentar_ingreso`.

## Fase 7: manual, capturas y prueba

- **Manual de usuario:** `docs/MANUAL_DE_USUARIO.md`, escrito de nuevo sobre las
  pantallas actuales. No se encontro el manual anterior en el repositorio; si
  existe en otro sitio, este lo reemplaza o hay que fusionarlos.
- **Capturas:** 13 en `docs/ux/capturas/`, generadas con `docs/ux/capturar.py`.
  Son del codigo real del dashboard en un navegador (Chrome sin ventana), con
  datos inventados servidos por `docs/ux/api_simulada.py`. **No son evidencia de
  ninguna historia**: las capturas `hu*.png` de `docs/` no se tocaron y siguen
  mostrando las pantallas anteriores.
- **Prueba con un supervisor:** no se hizo; no se puede hacer desde el codigo.
  El guion esta en `docs/ux/PRUEBA_CON_SUPERVISOR.md`.

### Lo que encontro la primera revision visual

Hasta la fase 6 nadie habia visto las pantallas dibujadas. Al sacar las
capturas aparecieron cinco defectos que `AppTest` no puede ver, ya corregidos:

| Defecto | Correccion |
|---|---|
| El peso de la lectura previa (48 px) pisaba el aviso de debajo | Margen inferior en `.q-lectura` y alineacion al centro |
| La fecha de la tarjeta se partia en dos lineas | Fecha corta, `15/11 09:12`; el ano esta en la tabla |
| El titulo grande "Control de despacho" salia tambien con un evento abierto | Solo se dibuja en la bandeja |
| En Tolerancias, "Ultimo cambio" quedaba fuera de pantalla | "Se admiten" y la regla van en una columna; el campo de ejemplo, mas corto |
| Dos lineas separadoras seguidas en la barra lateral | Se quito la propia; el menu ya trae la suya |

Tambien confirmo dos cosas: el menu lateral, los dialogos y las etiquetas de
estado funcionan en un navegador real (era lo que las pruebas no podian
pulsar), y el campo de contrasena trae su boton para verla.

Queda sin corregir, por menor: los correos se dibujan como enlaces.

## Bandeja de eventos, segunda pasada (15/11/2026, tras verla en uso)

El responsable abrio la pantalla de Eventos y no vio la mejora: lo entregado en
la fase 2 se parecia poco a la propuesta del prototipo. Se rehizo:

- **Titulo compacto.** "Eventos" y, debajo, "3 pendientes de revision". Antes,
  "Control de despacho" a 40 px con la cifra en dorado, en dos renglones.
- **Lista en filas con cabecera** (Severidad, Orden, Diferencia de peso,
  Hallazgo, Proceso) en lugar de una tarjeta alta por evento. Cada fila mide
  unos 100 px; antes, unos 150, y cabian tres en pantalla.
- **Proceso en una frase** ("Analisis completo", "Conteo en curso (3 de 4)",
  "Sin video de la carga"), con la barra de pasos pequena y sin rotulos.
- La severidad se escribe corta ("Alta"), el boton se llama "Revisar" y la
  diferencia usa el signo menos tipografico.
- **La lista va sobre fondo blanco**, como la tarjeta del prototipo; el
  responsable noto que faltaba al comparar la captura. La regla CSS apunta al
  contenedor con borde que envuelve a `st-key-lista_de_eventos`.

Funciones: `_tarjetas_de_la_bandeja` (reescrita), `_proceso_de_la_fila`,
`_cabecera_de_eventos`, `_pill_de_severidad(corta=True)`. El espacio entre
filas se aprieta con la clase `st-key-lista_de_eventos`, que Streamlit da al
contenedor por su `key`.

**Lo que esta pasada dejo claro:** el dashboard corre en Python 3.11 y las
comprobaciones se estaban ejecutando con 3.13. Una f-string con comillas
anidadas, valida en 3.12 o posterior, paso las pruebas y habria dejado el
dashboard sin arrancar en el contenedor. La detecto `capturar.py`, que usa el
entorno del proyecto. **Los scripts de `docs/ux/` hay que ejecutarlos con el
Python del proyecto (3.11).**

## Tarjetas, tablas y campos en blanco (15/11/2026)

El prototipo pone todo el contenido sobre tarjetas blancas y el dashboard lo
dejaba en el crema del fondo. A pedido del responsable se igualo en todas las
pantallas:

| Elemento | Como se consigue |
|---|---|
| Tarjetas (orden, carga, lectura de bascula, cifras, video, analisis, personas, decision, usuarios, tokens) | `_tarjeta(clave)`: contenedor con borde y clave `tarjeta_<clave>`; el CSS pinta de blanco todo contenedor con esa clase |
| Lista de eventos, formularios y desplegables | Reglas CSS en `ESTILO` |
| Tablas (`st.dataframe`) | `_tabla(...)`: da el color celda a celda con el estilo de pandas, porque la tabla se dibuja en un lienzo que no hereda el CSS. Tambien fija dos decimales |
| Campos de texto, numero y listas | `secondaryBackgroundColor = "#FFFFFF"` en `.streamlit/config.toml`, mas un borde por CSS |
| Barra lateral | Conserva el crema (`#F1EDE2`) por CSS, porque el tema ya no se lo da |

La pagina del evento paso de bloques sueltos a cinco tarjetas (cifras, video,
analisis, personas y decision), y el formulario de clasificacion ya no tiene
borde propio porque va dentro de la tarjeta de la decision.

Hay que usar `_tabla` y `_tarjeta` en cualquier pantalla nueva, y no
`st.dataframe` ni `st.container(border=True)` directamente.

El cambio de `config.toml` solo se toma al arrancar Streamlit: hay que
reiniciar el servicio `dashboard`.

## Correccion de la linea de estado (15/11/2026, tras verla en uso)

El responsable vio "1 componente con falla: bascula" en la pantalla de Eventos.
Al revisarlo aparecieron dos defectos del punto critico 5:

- **La cabecera llamaba falla a una advertencia.** `GET /salud` devuelve tres
  niveles: `ok`, `advertencia` (la bascula en movimiento, que es lo normal
  mientras se carga y lo que hace el simulador en cada ciclo) y `error` (no
  responde). La cabecera pintaba en rojo todo lo que no fuera `ok`. Ahora
  `error` va en rojo como "componente con falla" y `advertencia` en ambar como
  "Sistema en linea - 1 componente con advertencia".
- **La cabecera sondeaba la bascula en cada clic.** `GET /salud` no lee una
  tabla: interroga a la bascula por Modbus y al ERP por HTTP. Con la bascula
  apagada, cada pantalla tardaba los 5 segundos de su tiempo limite. Ahora la
  cabecera guarda la respuesta 20 segundos (`_salud_reciente`, con
  `st.cache_data`). La pantalla Estado del sistema sigue preguntando en directo.

Si tras esto la linea sigue en rojo con "bascula", la bascula no responde de
verdad: en local, comprobar que el servicio `scale-sim` esta en marcha
(`docker compose ps scale-sim`) y leer el mensaje en Estado del sistema.

## Por que el dashboard local mostraba la version anterior

El 15/11/2026 el responsable veia el ingreso antiguo aunque `dashboard/app.py`
ya tenia el nuevo. Causa: en Windows, Docker no propaga al contenedor los
avisos de cambio de un archivo montado, asi que Streamlit no se enteraba y
seguia sirviendo el codigo que cargo al arrancar. Lo mismo pudo pasar con cada
entrega anterior de esta mejora.

Correccion: el servicio `dashboard` de `docker-compose.yml` arranca ahora con
`--server.fileWatcherType=poll` y `--server.runOnSave=true`. Hace falta recrear
el contenedor una vez para que tome el comando nuevo:

```powershell
docker compose up -d --force-recreate api dashboard
```

Se incluye `api` porque `uvicorn --reload` depende del mismo aviso: sin
reiniciarla, el endpoint `POST /pesadas/lectura-previa` puede no existir todavia
en el contenedor y "Leer bascula" fallaria.

## Como se comprobo

Con `streamlit.testing.v1.AppTest` y una API simulada, sin levantar el entorno:

```bash
cd despacho/api
python docs/ux/verificar_puntos_criticos.py
python docs/ux/verificar_fases_1_a_4.py
python docs/ux/verificar_fases_5_y_6.py
```

Los tres terminan en "TODO OK" (26, 44 y 42 comprobaciones). No estan en `tests/`
porque la convencion 4 pide pruebas contra cosas reales y estas usan respuestas
de mentira.

### Suite pytest de `despacho/api` (15/11/2026)

```
Despues de la fase 4:  607 passed, 2008 sentencias, 100.00 %
Despues de la fase 5:  620 passed, 2066 sentencias, 100.00 %  (13 pruebas nuevas)
```

Minimo exigido: 90 %. `ruff check` sin avisos en los cuatro archivos tocados.

Ejecutada fuera del entorno habitual, en una copia del servicio: Python 3.11.18,
las versiones de `requirements-dev.txt` y MariaDB 10.11 local por socket, con
`TEST_DATABASE_URL` apuntando a `127.0.0.1` (base `quinor_test`) y
`PYTHONPATH` con `despacho/pruebas_comunes`. No se toco ninguna base real ni el
`.env`. No es la ejecucion oficial (`docker compose exec api pytest`, contra
MySQL 8), asi que `reporte_coverage.txt` no se modifico.

Que demuestra y que no: la suite mide `app/` (la API). En la fase 5 cubre el
endpoint nuevo y confirma que el resto sigue intacto, incluida la pesada, cuya
lectura de bascula se movio a una funcion compartida. **No cubre
`dashboard/app.py`**: `pytest.ini` usa `--cov=app` y no hay pruebas del dashboard en
`tests/`. Lo unico que ejercita el dashboard son los tres scripts de arriba, que
en ese mismo entorno (Streamlit 1.41.1, pandas 2.2.3) tambien terminan en
"TODO OK".

Lo que **no** se comprobo:

- No se vio contra el entorno real. Las 13 capturas son de un navegador real
  con datos simulados; las pantallas de Ordenes, Camaras y Estado del sistema
  no se capturaron.
- El dialogo de confirmacion de las tolerancias se comprobo hasta que se abre con
  el antes y el despues; el clic final que envia el cambio no.
- `AppTest` 1.41 no simula el redibujado parcial de `st.dialog`, el reenvio de
  `st.pills` ni el clic en el menu de `st.navigation`; los scripts lo imitan, y
  lo dicen en sus comentarios. El menu real, por tanto, no se ha pulsado nunca.

## Pendiente de actualizar

- Capturas de evidencia de `docs/` (`hu03_bandeja_eventos.png`,
  `hu06_07_detalle_clip_y_conteo.png` y las de pesadas): muestran las pantallas
  anteriores. Rehacerlas exige el entorno real.
- En AKS el codigo va dentro de la imagen: hay que reconstruir y publicar la
  imagen de la API (el dashboard usa la misma) para ver los cambios alli.
