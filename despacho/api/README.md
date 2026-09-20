# API de Despacho QUINOR - Alternativa 1

Orquestador de despacho del sistema de deteccion de sustraccion de quinua.
Ubicacion en el repositorio: `quinor/despacho/api`.

Sigue la misma estructura y arquitectura que `quinor/blockchain/api`: fabrica de
aplicacion, configuracion inyectada, autenticacion por `X-API-Key` y `pytest.ini`
con umbral de cobertura.

Referencia funcional: `Documento_Funcional_Tecnico_Alternativa1_QUINOR.docx` v1.2.

## Alcance de este sprint

| Historia | Descripcion | Estado |
|---|---|---|
| HU-01 | Lectura automatica de la bascula por Modbus | **DONE** |
| HU-02 | Consulta de la orden de despacho al ERP/WMS | **DONE** |
| HU-04 | Configuracion de tolerancias por producto | **DONE** |
| HU-15 | Usuarios, roles y autenticacion por token | **DONE** |
| HU-17 | Cola de tareas con reintentos | PENDING, depende de HU-03 (Sprint 2) |

Total computable: 11 puntos de los 14 planificados, los 11 entregados. Los 3
restantes son HU-17, excluida por depender de HU-03, del Sprint 2.

Adelantado del Sprint 2:

| Historia | Descripcion | Estado | Donde vive |
|---|---|---|---|
| HU-03 | Evento de discrepancia por diferencia de peso | **DONE** | esta API |
| HU-05 | Grabacion continua de camaras en buffer circular | **DONE** | `quinor/despacho/grabador` |
| HU-06 | Recorte del clip de la ventana de la carga | **DONE** | marca de carga aqui, recorte en el grabador |

HU-03 estaba bloqueada por HU-01, HU-02 y HU-04, las tres del Sprint 1. Al
cerrarse el sprint quedo desbloqueada y se entrego. Con ella el circulo se
cierra: el sistema ya pesa, sabe cuanto se esperaba y compara las dos cifras.

HU-05 no tenia dependencias y vive en su propio servicio, `quinor/despacho/grabador`,
porque grabar sin parar y atender peticiones HTTP son dos trabajos distintos. Su
README explica el detalle; aqui basta con saber que escribe en `salud_componente`
y que por eso las camaras aparecen en `GET /salud` junto a la bascula y el ERP.

HU-06 esta repartida a proposito: la marca de inicio de carga vive aqui, porque
es la API quien sabe cuando el camion entra a la rampa; el recorte vive en el
grabador, porque el buffer de video esta alli y la pesada no puede quedarse
esperando a ffmpeg.

## Requisitos previos

- Docker Desktop con WSL2 en Windows.
- Nada mas. Python, MySQL y el resto viven dentro de los contenedores.

## Puesta en marcha

```bash
cp .env.example .env
# Editar .env y cambiar TODAS las claves antes de continuar.

docker compose up --build
```

Servicios publicados:

| URL | Servicio |
|---|---|
| http://localhost:8000/ | Informacion del servicio, sin autenticacion |
| http://localhost:8000/salud | Estado de los componentes, con token |
| http://localhost:8000/docs | Documentacion OpenAPI del orquestador |
| http://localhost:8001/docs | Stub del ERP |
| http://localhost:8501 | Dashboard Streamlit |
| localhost:3306 | MariaDB 10.11, el mismo motor que el hosting |
| localhost:5020 | Simulador Modbus de la bascula |
| localhost:8554 | Servidor RTSP de las camaras simuladas (HU-05) |
| http://localhost:9001 | Consola de MinIO, almacen de clips (HU-06) |

## Verificacion del entorno

```bash
curl -s http://localhost:8000/                                    # publico
curl -s -H "X-API-Key: $TOKEN" http://localhost:8000/salud | python -m json.tool
```

Los tres componentes deben responder `ok`. Si `mysql` da error, esperar a que
termine el arranque inicial del contenedor: la primera vez tarda cerca de un minuto.

## Simuladores

No hay acceso a la bascula ni al ERP reales durante el Sprint 1, asi que ambos
se sustituyen por contenedores.

**Bascula** (`sim/scale_sim.py`). Servidor Modbus TCP que publica una pesada nueva
cada 15 segundos. Mapa de registros holding:

| Registro | Contenido |
|---|---|
| 0-1 | Peso en kg, float32 big-endian |
| 2 | Contador de pesadas |
| 3 | Estado: 0 en movimiento, 1 peso estable |

El 30 % de las pesadas simula un faltante de uno a tres sacos, para tener casos
reales cuando entre HU-03 en el Sprint 2. Ajustable con `SCALE_SIM_PROB_FALTANTE`.

Para probar el criterio 2 de HU-01, que exige detectar que la bascula no responde
en 5 segundos:

```bash
docker compose stop scale-sim
curl -s http://localhost:8000/salud | python -m json.tool
```

**ERP** (`sim/erp_mock.py`). Tres ordenes fijas, todas con 50 kg por saco.
`ORD-2026-0001` (400 sacos), `ORD-2026-0002` (270) y `ORD-2026-0003` (180).
Cualquier otro numero devuelve 404, que es el caso del criterio 2 de HU-02.
Para probar el timeout del cliente, subir `ERP_MOCK_DELAY_MS` por encima de
`ERP_TIMEOUT_SECONDS`.

## Arquitectura

Sigue el patron de `quinor/blockchain/api`: fabrica de aplicacion, configuracion
inyectada y estado en `app.state`.

```python
app = create_app(database_url=..., admin_email=..., scale_host=..., scale_port=...)
```

`create_app` resuelve cada parametro con este orden: lo que se le pasa, luego la
variable de entorno, luego el valor por defecto. Ningun modulo lee el entorno por
su cuenta ni guarda estado global, de modo que una prueba levanta la API contra
otra base de datos y otra bascula sin tocar el proceso. Dos instancias conviven
sin pisarse: cada una tiene su motor.

En `app.state` viven `ajustes`, `motor`, `fabrica` de sesiones y `cerrar`, el
mismo papel que cumple `app.state.network` en el ejemplo.

`uvicorn` la arranca con `--factory`, no importando un objeto `app` de modulo.

### Autenticacion

Cabecera `X-API-Key`, que desde HU-15 lleva un token opaco emitido por
`POST /auth/login`. Ya no hay clave estatica: la variable `API_KEY` desaparecio.
`GET /` es la unica ruta publica y sirve de healthcheck; el resto exige token,
incluido `GET /salud`, que expone version de motor y detalle de fallos internos.

Tres dependencias marcan quien puede hacer que, y cada endpoint declara la suya:

| Dependencia | Quien pasa |
|---|---|
| `requiere_usuario` | cualquier token vigente de una cuenta activa |
| `requiere_escritura` | Administrador y Supervisor |
| `requiere_administrador` | solo Administrador |

El detalle del esquema de usuarios, roles y tokens esta en la seccion de HU-15.
Editar la configuracion exige Administrador; leerla, solo un token valido.

## HU-01: lectura de la bascula (DONE)

> Como operador de despacho, quiero que el sistema registre automaticamente el
> peso de la bascula al cerrar cada carga, para no depender de anotaciones
> manuales que pueden alterarse.

Cerrar una carga es una llamada al orquestador. El orquestador lee la bascula por
Modbus, no espera a que nadie le mande el numero:

```bash
curl -X POST localhost:8000/pesadas \
     -H 'Content-Type: application/json' \
     -d '{"numero_orden":"ORD-2026-0001"}'
```

| Criterio | Como se cumple | Donde se prueba |
|---|---|---|
| 1. Lee el peso por Modbus y lo guarda con fecha, hora, ID de carga e ID de bascula | `app/bascula.py` decodifica el float32 de los registros 0-1; `app/pesadas.py` persiste en la tabla `pesada` | `test_registra_la_pesada_con_fecha_hora_carga_y_bascula` |
| 2. Si no responde en 5 s, error en `salud_componente` visible en `GET /salud` | Presupuesto duro con `asyncio.wait_for`; el registro de salud se confirma en su propia transaccion | `test_crear_pesada_bascula_caida`, `test_salud_con_la_bascula_caida` |
| 3. El peso se almacena con dos decimales en kg | `Decimal` con redondeo HALF_UP y columna `DECIMAL(10,2)` | `test_crear_pesada_persiste_con_dos_decimales` |

### Decisiones que conviene conocer

**El orquestador lee la bascula, no al reves.** El apartado 6.4 describe un
servicio de bascula que publica en `POST /pesadas`. Se invirtio: hay una sola
implementacion de Modbus, y el presupuesto de 5 s vive en el mismo sitio donde se
registra el fallo. Volver al modelo del documento es cambiar quien llama a
`bascula.leer_peso`, nada mas.

**Los 5 segundos son un presupuesto total, no un timeout por operacion.** Conexion,
lectura y reintentos caben dentro del mismo limite. Al operador le da igual en
cual de las tres etapas se atasco.

**Un peso en movimiento no se registra.** Si el registro de estado de la bascula
dice que sigue oscilando, la respuesta es 409 y no se guarda nada: ese numero
todavia no es un dato.

**`salud_componente` solo guarda cambios de estado.** HU-18 sondeara cada 30 s;
registrar cada sondeo generaria miles de filas identicas al dia y enterraria justo
lo que interesa, que es el momento en que algo dejo de funcionar. La respuesta de
`GET /salud` si trae la marca de la verificacion en vivo.

**La orden tiene que existir en la base local.** Traerla del ERP es HU-02. Hasta
entonces, una orden desconocida devuelve 404 diciendolo.

**El peso manual queda marcado.** `POST /pesadas` con `peso_real_kg` guarda
`origen = manual` y exige un motivo. La diferencia entre una lectura automatica y
una anotacion humana no se pierde en el historial, que es justo lo que la historia
pretende evitar.

### Codigos de respuesta

| Codigo | Situacion |
|---|---|
| 201 | Pesada registrada |
| 401 | Falta el token en X-API-Key, o esta revocado o vencido |
| 404 | La orden no esta en la base local |
| 409 | La bascula sigue en movimiento |
| 503 | La bascula no respondio. El fallo ya esta en `salud_componente` |

## HU-02: consulta de la orden al ERP (DONE)

> Como operador de despacho, quiero que el sistema obtenga del ERP/WMS el peso y
> cantidad de sacos esperados de la orden de despacho, para comparar lo cargado
> contra lo planificado.

```bash
curl -H "X-API-Key: $TOKEN" localhost:8000/ordenes/ORD-2026-0001
curl -H "X-API-Key: $TOKEN" "localhost:8000/ordenes/ORD-2026-0001?refrescar=true"
```

`POST /pesadas` ya no exige que la orden exista en la base: la resuelve contra el
ERP por su cuenta.

| Criterio | Como se cumple | Donde se prueba |
|---|---|---|
| 1. Consulta el ERP por API REST y obtiene peso esperado y numero de sacos | `app/erp.py` con httpx y validacion del contrato; `app/ordenes.py` persiste la copia local | `test_obtiene_peso_esperado_y_numero_de_sacos`, `test_una_orden_nueva_se_trae_del_erp_y_se_guarda` |
| 2. Si la orden no existe se muestra un mensaje y no se crea evento | El 404 del ERP se traduce en `OrdenNoDisponible` y la carga se detiene antes de escribir nada | `test_si_el_erp_no_reconoce_la_orden_no_se_guarda_nada`, `test_crear_pesada_orden_desconocida` |
| 3. La respuesta se guarda junto a la pesada | La copia local queda enlazada por clave foranea, y la auditoria de la pesada guarda peso, sacos y `orden_sincronizada_en` | `test_la_pesada_guarda_la_respuesta_del_erp` |

### Decisiones que conviene conocer

**Dos fallos distintos, no uno.** Que el ERP conteste "esa orden no existe" y que
el ERP no conteste son cosas diferentes, y el codigo las separa en
`OrdenNoExisteEnERP` y `ErpNoDisponible`. Confundirlas llevaria a parar el
despacho por un problema de red, o a dar por buena una orden que el ERP nunca
reconocio.

**Un corte de red no para la rampa si ya sabemos que dice la orden.** La RN-02
pide registrar una incidencia de integracion cuando no se puede validar contra el
ERP. Eso es lo que ocurre: se marca el componente `erp` en error, queda una
entrada `incidencia_integracion_erp` en auditoria, y si existe copia local se
sigue con ella. Sin copia local, la carga se detiene: no hay contra que comparar.

**La copia local es una cache con fecha, no un espejo.** `sincronizado_en` dice
cuando se leyo del ERP, y mientras la copia sea mas joven que
`ERP_CACHE_TTL_SECONDS` no se vuelve a preguntar. Con 900 s por defecto, una
rampa cargando veinte camiones hace una consulta por orden, no una por pesada.
`?refrescar=true` la fuerza cuando el supervisor sabe que el ERP acaba de
corregir algo.

**La orden se valida al entrar, no al guardar.** Un peso en cero o unos sacos
negativos chocarian despues contra las restricciones CHECK del esquema, con un
error que no dice de donde vino el dato. `OrdenERP` los rechaza en el cliente y
los clasifica como fallo de integracion.

**Un cambio en el ERP deja rastro.** Al refrescar una orden ya conocida, la
entrada `sincronizar_orden` guarda los valores anteriores. Si manana la orden
cambia, el historial conserva contra que valores se peso aquel dia.

### Codigos de respuesta de /ordenes

| Codigo | Situacion |
|---|---|
| 200 | Orden resuelta, del ERP o de la copia local vigente |
| 401 | Falta el token en X-API-Key, o esta revocado o vencido |
| 404 | El ERP no reconoce la orden, o no contesta y no hay copia local |

## HU-03: evento de discrepancia (DONE, adelantada del Sprint 2)

> Como supervisor de despacho, quiero que el sistema genere un evento de
> discrepancia cuando el peso real difiera del esperado mas alla de la
> tolerancia, para enterarme en el momento y no cuando reclama el cliente.

No hay que llamar a nada: registrar una pesada dispara la evaluacion, y si la
carga se sale de la tolerancia el evento viaja en la misma respuesta.

```bash
curl -X POST localhost:8000/pesadas -H "X-API-Key: $TOKEN" \
     -H 'Content-Type: application/json' -d '{"numero_orden":"ORD-2026-0001"}'
# -> {"id":1, ..., "evaluada":true, "evento":{"id":1,"estado":"pendiente",
#     "diferencia_kg":"-150.00","diferencia_pct":"-0.75", ...}}

curl -H "X-API-Key: $TOKEN" "localhost:8000/eventos?estado=pendiente"
curl -H "X-API-Key: $TOKEN" localhost:8000/eventos/1
```

| Criterio | Como se cumple | Donde se prueba |
|---|---|---|
| 1. Si la diferencia supera la tolerancia se crea un evento Pendiente | `app/eventos.py` compara contra la tolerancia de HU-04 segun la RN-01; el estado por defecto de la tabla es `pendiente` | `test_una_carga_fuera_de_tolerancia_genera_evento_pendiente`, `test_solo_se_pasa_de_la_tolerancia_estrictamente` |
| 2. El evento incluye orden, pesos, diferencia en kg y porcentaje | `EventoLeido` junta el evento con su pesada y su orden | `test_la_pesada_fuera_de_tolerancia_devuelve_su_evento` |
| 3. El evento se crea en menos de 10 s desde la pesada | Evaluacion sincrona justo despues de confirmar la pesada; en la practica, milisegundos | `test_el_evento_se_crea_en_menos_de_10_segundos`, `test_la_evaluacion_no_retrasa_la_pesada` |

### Decisiones que conviene conocer

**La evaluacion va despues del commit de la pesada, no dentro.** La pesada es la
evidencia y tiene que sobrevivir aunque la comparacion falle. Meterlas en la
misma transaccion significaria perder el peso del camion por un error al
comparar. Si la evaluacion revienta, el fallo queda en `salud_componente` y la
pesada se puede reevaluar mas tarde.

**Sincrona, no en cola.** El criterio 3 da 10 segundos para una resta que tarda
milisegundos. Lo que HU-17 sacara a una cola es el analisis de video, que si
tarda; adelantar Celery para esto seria complejidad sin nada a cambio.

**Un evento por pesada, garantizado por la base.** La clave unica sobre
`pesada_id` existe para poder reprocesar sin duplicar. Reevaluar una pesada
devuelve el evento que ya tenia, y el supervisor recibe un aviso por carga y no
uno por reintento.

**El sobrepeso tambien genera evento.** El criterio habla de valor absoluto, y
con razon: un contenedor mas pesado de lo planificado apunta a una sustitucion
igual que uno mas ligero. La diferencia se guarda con signo para distinguirlos.

**Igual a la tolerancia no es discrepancia.** La comparacion es estrictamente
mayor. La tolerancia es lo que se acepta, no lo primero que se rechaza.

**El evento recuerda contra que umbral se juzgo.** La tolerancia aplicada queda
en la auditoria del momento de la creacion. Si manana alguien la sube, los
eventos ya creados siguen explicando por que se crearon.

**Una carga sin tolerancia configurada no pasa por limpia.** Si el producto no
tiene fila en `configuracion`, la pesada se registra pero `evaluada` viene en
`false` con su motivo, queda una incidencia en auditoria y el componente
`configuracion` aparece en error en `GET /salud`. Callarse dejaria creer que esa
carga se reviso y salio bien, que es exactamente el problema que el proyecto
intenta resolver. Una vez configurada la tolerancia,
`POST /pesadas/{id}/evaluar` recupera la pesada sin volver a pesar el camion.

### Codigos de respuesta de /eventos

| Codigo | Situacion |
|---|---|
| 200 | Evento leido, o pesada reevaluada |
| 401 | Falta el token en X-API-Key, o esta revocado o vencido |
| 403 | El rol Consulta ha intentado reevaluar |
| 404 | No existe el evento o la pesada |
| 409 | Se intento reevaluar un producto que sigue sin tolerancia configurada |

### Lo que el evento va recogiendo

El evento nace con `sacos_contados`, `personas_detectadas`, `severidad` y
`clip_url` en blanco. Los llenan HU-06, HU-07, HU-08 y HU-09 conforme el clip se
recorta y se analiza. La pantalla con filtros combinados y respuesta en 2 s es
HU-11; la de este sprint es la lista tal cual, en la pestana Eventos del
dashboard.

### HU-10: se aviso de esto, o no (DONE, la parte de consulta)

Mandar el correo es trabajo del servicio de notificaciones
(`quinor/despacho/notificaciones`). Lo que vive aqui es la constancia:
`GET /eventos/{id}/avisos` responde a quien se aviso, a que hora, cuanto se
tardo desde el analisis y, si no salio, por que.

Es la pregunta que se hace cuando el cliente reclama meses despues, y la
respuesta no puede depender de que un supervisor conserve el correo. Un aviso
fallido cuenta como no avisado: nadie lo recibio.

Va en su propia ruta por lo mismo que las personas de HU-08. La lista de eventos
de HU-11 tiene 2 s para responder, y arrastrar los avisos en cada fila la haria
pesada para quien solo quiere ver las diferencias de peso.

En el dashboard aparece dentro del detalle del evento, y aparece aunque no haya
aviso. Esa es la parte util: un evento Alto sin correo enviado es un fallo que
de otro modo solo se veria en los logs del grabador, y quien tiene que enterarse
es el supervisor que esta delante de la pantalla preguntandose por que nadie le
dijo nada.

## HU-06: la marca de inicio de carga (DONE)

El criterio 1 de HU-06 mide el clip "desde 5 min antes del inicio de carga", y el
apartado 5.2 dice que el sistema marca ese inicio. Hasta aqui nadie lo hacia: el
modelo solo guardaba el instante de la pesada. Ahora:

```bash
# El camion entra a la rampa
curl -X POST -H "X-API-Key: $TOKEN" localhost:8000/cargas/ORD-2026-0001/inicio

# ...se carga...

# La pesada cierra la carga y se queda con el instante de inicio
curl -X POST -H "X-API-Key: $TOKEN" -H 'Content-Type: application/json' \
     -d '{"numero_orden":"ORD-2026-0001"}' localhost:8000/pesadas
```

El recorte del clip lo hace el grabador, que tiene el buffer: ver su README.

**La pesada nunca se rechaza por falta de marca.** Si nadie la abrio,
`inicio_carga` queda en NULL y el clip cubre solo los minutos previos al cierre.
El peso del camion no puede perderse porque falte una anotacion de video.

**Una orden no puede tener dos cargas abiertas.** Lo impide el servicio y lo
impide la base, con un indice unico parcial emulado con columna generada, igual
que en `modelo_version`. Dos marcas abiertas dejarian a la pesada sin saber cual
consumir.

**La ventana que se muestra en el evento es la que se recorto de verdad**, leida
de la auditoria del grabador, no una cuenta repetida aqui. Dos copias de "5 y 2
minutos" acabarian discrepando.

| Codigo | Situacion |
|---|---|
| 201 | Carga marcada |
| 403 | El rol Consulta no marca cargas |
| 404 | El ERP no reconoce la orden |
| 409 | Esa orden ya tiene una carga abierta |

## HU-04: tolerancias por producto (DONE)

> Como administrador del sistema, quiero configurar la tolerancia de peso
> permitida (kg y porcentaje) por tipo de producto, para ajustar la sensibilidad
> sin cambiar el codigo.

La pantalla esta en el dashboard, pestana **Tolerancias**. Por API:

```bash
curl -H "X-API-Key: $TOKEN" localhost:8000/configuracion
curl -X PATCH -H "X-API-Key: $TOKEN" -H 'Content-Type: application/json' \
     -d '{"tolerancia_kg":65,"tolerancia_pct":0.25}' \
     "localhost:8000/configuracion/Quinua%20blanca%20organica"
curl -H "X-API-Key: $TOKEN" \
     "localhost:8000/configuracion/Quinua%20blanca%20organica/aplicada?peso_esperado_kg=20000"
```

| Criterio | Como se cumple | Donde se prueba |
|---|---|---|
| 1. Pantalla con campos de tolerancia en kg y % | Pestana Tolerancias del dashboard sobre `GET/PATCH /configuracion` | `test_listar_las_tolerancias_configuradas`, `test_editar_la_tolerancia_como_administrador` |
| 2. Solo el rol Administrador puede editarla | `requiere_administrador` en el PATCH; leer solo exige token | `test_el_supervisor_lee_pero_no_edita_la_tolerancia`, `test_consulta_tampoco_edita_la_tolerancia` |
| 3. Cada cambio queda registrado con usuario y fecha | La fila guarda el ultimo cambio y `auditoria` el historial con los valores de antes y despues | `test_la_respuesta_dice_quien_hizo_el_ultimo_cambio`, `test_el_historial_trae_los_valores_de_antes_y_despues` |

### La RN-01 en la practica

La tolerancia se define dos veces, en kg y en porcentaje, y manda la mas
restrictiva. Con los valores sembrados, 50 kg y 0,5 %:

| Orden | 0,5 % equivale a | Manda | Se admite |
|---|---|---|---|
| 20 000 kg | 100,00 kg | los kg | 50,00 kg |
| 10 000 kg | 50,00 kg | empatan | 50,00 kg |
| 5 000 kg | 25,00 kg | el porcentaje | 25,00 kg |

`GET /configuracion/{producto}/aplicada?peso_esperado_kg=...` devuelve esa
cuenta hecha, y la pantalla la muestra debajo de los dos campos.

### Decisiones que conviene conocer

**La pantalla edita, no da de alta.** Las filas las siembra el esquema y los
productos vienen del catalogo del ERP. Permitir crearlas desde aqui abriria la
puerta a tolerancias con nombres que no coinciden con ningun producto real, que
es la clase de fila que nadie descubre hasta que HU-03 no encuentra tolerancia.

**El supervisor lee la configuracion aunque no pueda cambiarla.** Necesita saber
contra que umbral se esta midiendo su rampa; ocultarselo solo consigue que
pregunte por chat cada vez. Editar sigue siendo cosa del administrador.

**El criterio 3 se cumple en dos sitios a la vez.** La fila guarda quien hizo el
ultimo cambio y cuando, que es lo que la pantalla muestra de un vistazo; la
tabla `auditoria` guarda el historial completo con los valores anteriores y los
nuevos. Solo lo primero dejaria sin rastro el cambio penultimo, que es justo el
que se busca cuando una tolerancia aparece mas laxa de lo que deberia.

**Un cambio que no cambia nada no se registra.** La auditoria sirve para saber
que se movio; llenarla de filas identicas la vuelve inutil justo cuando hace
falta leerla.

**Los limites viven en un solo sitio.** El esquema de entrada no repite los
rangos: los valida `configuracion.validar`, que devuelve un mensaje que dice que
corregir en lugar de un error de motor. Dos copias de la misma regla terminan
dejando de coincidir.

**Los canales por severidad se muestran pero no se editan.** Son el mapa de la
RN-04 y pertenecen a HU-10. Tras el cambio de alcance del 18/09/2026 los tres
niveles salen por correo y lo que cambia con la severidad son los destinatarios
y la urgencia, asi que la columna hoy dice lo mismo en las tres filas. Se
conserva porque Teams o el SMS entraran con su propia historia, y entonces
volvera a tener algo que decir.

### Codigos de respuesta de /configuracion

| Codigo | Situacion |
|---|---|
| 200 | Tolerancia leida o actualizada |
| 401 | Falta el token en X-API-Key, o esta revocado o vencido |
| 403 | El rol no es Administrador y ha intentado editar |
| 404 | No hay tolerancia configurada para ese producto |
| 422 | Cuerpo vacio, valor no numerico o fuera de rango |

## HU-15: usuarios, roles y tokens (DONE)

> Como administrador del sistema, quiero gestionar usuarios y roles
> (Administrador, Supervisor, Consulta), para que cada persona solo acceda a lo
> que le corresponde.

Entrar es cambiar una contrasena por un token. A partir de ahi la contrasena no
vuelve a viajar:

```bash
TOKEN=$(curl -s -X POST localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"correo":"admin@quinor.local","clave":"...."}' | python -c 'import sys,json;print(json.load(sys.stdin)["token"])')

curl -H "X-API-Key: $TOKEN" localhost:8000/auth/yo
curl -H "X-API-Key: $TOKEN" localhost:8000/usuarios
```

| Criterio | Como se cumple | Donde se prueba |
|---|---|---|
| 1. Se pueden crear, desactivar y asignar roles a usuarios | `app/usuarios.py` y los endpoints `/usuarios`; desactivar nunca borra | `test_crear_usuario_con_su_rol`, `test_asignar_otro_rol`, `test_desactivar_y_reactivar` |
| 2. El rol Consulta no cambia estados ni configuraciones | `requiere_escritura` y `requiere_administrador` en cada endpoint que escribe | `test_consulta_no_escribe`, `test_los_permisos_del_rol` |
| 3. Las contrasenas se almacenan con hash bcrypt | `seguridad.hash_password`, sal por fila, limite de 72 bytes explicito | `test_el_hash_es_bcrypt`, `test_una_clave_de_mas_de_72_bytes_se_rechaza` |
| 4. Token opaco en la tabla `api_token`, revocable desde el dashboard | SHA-256 del token en base, `resolver_token` en cada peticion, pestana "Mis tokens" del dashboard | `test_lo_que_se_guarda_es_el_sha256_del_token`, `test_un_token_revocado_deja_de_servir_de_inmediato` |

### Los tres roles

| Rol | Lee | Escribe pesadas y configuracion | Administra usuarios y roles |
|---|---|---|---|
| Administrador | si | si | si |
| Supervisor | si | si | no |
| Consulta | si | no | no |

### Decisiones que conviene conocer

**Dos secretos, dos tratamientos.** La contrasena la elige una persona, asi que
va con bcrypt, lento a proposito para que un diccionario no sirva de nada. El
token lo genera el sistema con 256 bits de entropia, donde no hay diccionario que
alcance, y en cambio se verifica en cada peticion: ahi bcrypt seria un lastre, de
modo que se guarda su SHA-256 y se busca por indice unico.

**El token en claro se muestra una sola vez.** En base solo vive su hash. Quien
consiga leer la tabla `api_token` no puede usar ningun token, que es justo lo que
se le pide a esa tabla.

**La revocacion es inmediata, no diferida.** Cada peticion resuelve el token
contra la base. No hay cache ni sesion en memoria que sobreviva a un `DELETE
/auth/tokens/{id}`, y la siguiente peticion con ese token ya responde 401.

**Los usuarios no se borran, se desactivan.** La auditoria tiene que seguir
apuntando a una persona identificable, y el esquema lo impone con `ON DELETE
RESTRICT`. Al desactivar se revocan sus tokens en la misma transaccion: dejar
vivo el token de una cuenta cerrada seria cerrarla solo de nombre.

**El mensaje de credenciales no distingue que fallo.** Correo desconocido y
contrasena incorrecta devuelven lo mismo, y el caso del correo inexistente
verifica igualmente contra un hash de descarte para que el tiempo de respuesta
tampoco lo delate.

**El administrador inicial se crea, pero no se repisa.** Al arrancar, si
`ADMIN_EMAIL` no existe todavia se crea con `ADMIN_PASSWORD`. Si ya existe, no se
toca: una variable de entorno filtrada no debe convertirse en una llave
permanente. Con `ADMIN_PASSWORD` vacia no se crea nada y queda advertido en el log.

### Codigos de respuesta de /auth y /usuarios

| Codigo | Situacion |
|---|---|
| 200, 201 | Operacion realizada |
| 401 | Credenciales incorrectas, o token ausente, revocado o vencido |
| 403 | El rol no alcanza para esa operacion |
| 404 | El usuario o el token no existen |
| 409 | El correo ya esta registrado |
| 422 | Rol desconocido, clave de menos de 8 caracteres o de mas de 72 bytes |

## Base de datos

El modelo de la seccion 6.5 esta en `db/01_esquema.sql`: 10 tablas, 2 vistas,
3 triggers, 8 claves foraneas y 8 restricciones CHECK.

El compose monta `db/01_esquema.sql` en `docker-entrypoint-initdb.d`, asi que
MySQL lo aplica solo en el primer arranque. Para reaplicarlo a mano:

```bash
docker compose exec -T mysql mysql -u root -p"$MYSQL_ROOT_PASSWORD" quinor < db/01_esquema.sql
```

El script es idempotente y esta dividido en partes. La parte 1 crea lo que el
Sprint 1 necesita (usuario, api_token, orden_despacho, pesada, configuracion,
auditoria, salud_componente) y la parte 2 las tablas de sprints posteriores
(evento, veredicto, modelo_version), que se crean vacias.

Reglas de negocio que el motor hace cumplir, no solo la aplicacion:

| Regla | Como se garantiza |
|---|---|
| RN-06, un evento confirmado no vuelve a pendiente | Trigger `trg_evento_no_reabrir` |
| HU-16, la auditoria no se modifica ni se borra | Triggers `trg_auditoria_no_update` y `trg_auditoria_no_delete`, mas el REVOKE de la parte 6 |
| HU-13, comentario de al menos 10 caracteres | CHECK `ck_veredicto_comentario` |
| HU-15, un token revocado registra quien lo revoco | CHECK `ck_api_token_revocacion` |
| HU-19, solo un modelo YOLO activo a la vez | Columna generada `unico_activo` con indice unico |
| HU-11, listado en menos de 2 s | Indice `ix_evento_estado_creado` |

Los ENUM guardan codigos tecnicos en minuscula y sin tildes (`pendiente_analisis`,
`en_revision`). La etiqueta que ve el usuario vive en la aplicacion. La tabla de
equivalencia con la seccion 5.3 esta al inicio del script.

`db/99_pruebas.sql` recorre el camino feliz completo y sirve para comprobar que
el esquema quedo bien instalado. No forma parte del despliegue.

## Migraciones

Alembic aun no esta inicializado. Al empezar el modelo de datos:

```bash
docker compose exec api alembic init -t async alembic
docker compose exec api alembic revision --autogenerate -m "esquema inicial"
docker compose exec api alembic upgrade head
```

Configurar `utf8mb4` y `DATETIME(6)` en las migraciones, segun la seccion 6.5.

## Pruebas

```bash
docker compose exec api pytest --cov=app --cov-report=term-missing
```

362 pruebas y 100 % de cobertura en los diecisiete modulos. El umbral esta fijado en
`pytest.ini` con `--cov-fail-under=90`: la suite falla si baja de ahi. El reporte
vigente esta en `reporte_coverage.txt`.

| Archivo | Que cubre |
|---|---|
| `test_api.py` | Cada endpoint, la autenticacion y los codigos de error |
| `test_bascula.py` | Decodificacion, presupuesto de tiempo y modos de fallo del Modbus |
| `test_pesadas.py` | Caso de uso, registro de salud y auditoria contra MySQL |
| `test_erp.py` | Cliente del ERP: contrato, 404, timeouts y respuestas corruptas |
| `test_ordenes.py` | Cache, refresco e incidencias de integracion contra MySQL |
| `test_configuracion.py` | Tolerancias por producto, la RN-01 y la auditoria del cambio |
| `test_eventos.py` | Frontera de la tolerancia, faltante y sobrepeso, idempotencia por pesada |
| `test_cargas.py` | Marca de inicio de carga, su consumo por la pesada y la unicidad |
| `test_seguridad.py` | Hash bcrypt de contrasenas y generacion de tokens opacos |
| `test_usuarios.py` | Altas, roles, desactivacion, login, emision y revocacion de tokens |
| `test_config.py` | `cargar_ajustes` y `create_app` con entorno y con parametros |

Las pruebas corren contra MySQL de verdad, no contra SQLite: el valor del esquema
esta en sus triggers, sus restricciones CHECK y el tipo DECIMAL, y ninguno de los
tres sobrevive a una base sustituta. La bascula la sustituye un servidor Modbus en
proceso con registros fijos, de modo que `pytest` no depende del contenedor
`scale-sim` ni de en que fase de su ciclo se encuentre.

## Redis

Declarado en el compose pero apagado. HU-17 esta en PENDING porque depende de
HU-03, del Sprint 2. Para levantarlo cuando llegue ese momento:

```bash
docker compose --profile sprint2 up
```

Asi no hay que rehacer la infraestructura mas adelante.

## Notas sobre las dependencias

- `cryptography` se conserva aunque MariaDB use `mysql_native_password`: MySQL 8 autentica con `caching_sha2_password`
  y PyMySQL falla en el primer connect sin ese paquete.
- `bcrypt` esta fijado en 4.0.1. En 4.1 se elimino `bcrypt.__about__`, que
  passlib 1.7.4 todavia lee.
- `pandas` es lo que permite a `st.dataframe` renderizar tablas. Tambien lo
  necesitaran HU-11, HU-14 y HU-20.
- La sincronizacion NTP del servidor, la bascula y las camaras es un requisito
  de infraestructura, no un paquete. El modelo de datos usa `DATETIME(6)` para
  correlacionar pesada y video, y esa precision no sirve con relojes desalineados.

## Estructura

```
quinor/
  blockchain/api/       ejemplo de referencia
  despacho/api/         esta API
    app/                codigo de la aplicacion
      main.py         create_app y todos los endpoints
      bascula.py      cliente Modbus de la bascula (HU-01)
      pesadas.py      caso de uso de registro de pesadas (HU-01)
      erp.py          cliente REST del ERP/WMS (HU-02)
      ordenes.py      caso de uso de ordenes con cache (HU-02)
      configuracion.py tolerancias por producto y RN-01 (HU-04)
      eventos.py      evento de discrepancia (HU-03)
      cargas.py       marca de inicio de carga (HU-06)
      seguridad.py    hash de contrasenas y tokens opacos (HU-15)
      usuarios.py     caso de uso de usuarios, roles y tokens (HU-15)
      salud.py        sondeo y registro de salud_componente
      auditoria.py    escritura en la tabla inmutable de auditoria
      models.py       modelos mapeados al esquema de db/01_esquema.sql
      schemas.py      contratos de entrada y salida
      config.py       Ajustes inmutables y cargar_ajustes
      db.py           constructores de motor y de sesiones
    tests/            conftest y una suite por modulo
    db/               esquema MySQL, diagrama entidad-relacion y pruebas
    sim/              simuladores de bascula y ERP
    dashboard/        interfaz Streamlit
    pytest.ini        umbral de cobertura
    requirements.txt  dependencias de ejecucion
    reporte_coverage.txt
```

La disposicion repite la del ejemplo: `app/` con el codigo, `tests/` con una
suite por modulo, y en la raiz `pytest.ini`, `requirements.txt` y el reporte de
cobertura. Las carpetas `db/`, `sim/` y `dashboard/` son propias de esta API, del
mismo modo que `data/` lo es de la del blockchain.
