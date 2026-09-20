# Grabador de video QUINOR - Alternativa 1

Grabacion continua de las camaras de la rampa en buffer circular (HU-05),
recorte del clip de cada evento de discrepancia (HU-06), conteo de los sacos de
ese clip (HU-07, criterio 3), registro de las personas que estuvieron en la zona
de carga (HU-08, criterio 2), escritura de la descripcion y la severidad del
evento (HU-09) y aviso al supervisor en cuanto queda clasificado (HU-10,
criterio 3).
Ubicacion en el repositorio: `quinor/despacho/grabador`.

Sigue la misma arquitectura que `quinor/blockchain/api` y que el orquestador:
fabrica de servicio (`crear_grabador`), configuracion inyectada por parametro,
`app/` con el codigo, `tests/` con una suite por modulo, `sim/` con el simulador
y `pytest.ini` con umbral de cobertura.

Referencia funcional: `Documento_Funcional_Tecnico_Alternativa1_QUINOR.docx` v1.2.

## Por que un servicio aparte

Grabar sin parar y atender peticiones HTTP son dos trabajos distintos. Un fallo
del grabador no puede llevarse por delante el registro de pesadas de HU-01, y
reiniciar la API no deberia dejar la rampa sin video. Ademas, la imagen del
grabador incluye ffmpeg, que son unos 200 MB de codecs que el orquestador no usa.

Los dos servicios comparten la base de datos. El grabador escribe en
`salud_componente`, que es lo que el `GET /salud` del orquestador ya lee, y en
`evento.clip_url` y `evento.estado`, que es lo que HU-06 pide vincular. Por eso
las camaras aparecen en la misma respuesta que la bascula y el ERP, y el clip
aparece en el evento, sin que el grabador exponga ningun endpoint.

Que HU-06 viva aqui no es una comodidad: el buffer esta en este volumen y ffmpeg
en esta imagen. Recortar desde la API obligaria a montarle el video y a meterle
los codecs, y ademas la pesada esperaria al recorte y a la subida, que es justo
lo que el RNF-03 prohibe.

## HU-05: grabacion continua (DONE)

> Como supervisor de despacho, quiero que las camaras de la rampa graben de forma
> continua en un buffer circular, para contar con el video de cualquier carga
> reciente.

| Criterio | Como se cumple | Donde se prueba |
|---|---|---|
| 1. Segmentos de 1 min con el muxer segment de ffmpeg, `-c copy` y `-strftime 1` | `app/ffmpeg.py` construye la orden; `app/grabador.py` supervisa un ffmpeg por camara | `test_usa_el_muxer_segment`, `test_graba_de_verdad_partiendo_en_segmentos`, `test_el_video_grabado_no_esta_reencodificado` |
| 2. Al menos 72 h de video en disco local | `app/retencion.py` purga por antiguedad y, si el disco aprieta, tambien por espacio | `test_se_borra_lo_que_pasa_de_las_72_horas`, `test_con_el_disco_lleno_se_borra_lo_mas_antiguo_y_se_avisa` |
| 3. La desconexion de una camara queda en `salud_componente` y se ve en `GET /salud` | `app/salud.py` escribe en la tabla del orquestador con el id de la camara como componente | `test_una_camara_caida_se_registra_en_salud`, `test_si_la_camara_se_apaga_se_detecta_y_se_registra` |

### La orden que se ejecuta

```
ffmpeg -hide_banner -loglevel warning -nostdin \
       -rtsp_transport tcp -timeout 15000000 -i rtsp://.../stream \
       -an -c copy -f segment -segment_time 60 -segment_format matroska \
       -reset_timestamps 1 -strftime 1 \
       /video/camara-01/camara-01_%Y%m%d-%H%M%S.mkv
```

El log de arranque la imprime entera, de modo que lo que se ejecuta es lo que se
puede copiar en una terminal para diagnosticar.

### Decisiones que conviene conocer

**Quien graba es ffmpeg; este servicio solo lo supervisa.** Arranca un proceso
por camara, mira si siguen vivos, los vuelve a levantar y deja constancia de la
caida. Esa separacion es la que permite que una camara caida no afecte a las
otras tres.

**`-c copy` no es un detalle de rendimiento.** Reencodificar consumiria la GPU
que el servicio YOLO necesita para HU-07 y degradaria la imagen que luego sirve
de evidencia. Con `-c copy` los paquetes pasan tal cual del RTSP al archivo.

**Matroska y no MP4.** Un MP4 solo queda reproducible cuando se cierra bien: si
se corta la luz en mitad de un segmento se pierde entero. Un MKV se lee hasta
donde llego, que es justo lo que hara falta.

**TCP y no UDP.** En una planta con ruido electrico, UDP pierde paquetes y el
video queda con saltos justo en el momento que habra que revisar.

**El nombre del archivo lleva la marca de tiempo, no un contador.** `-strftime 1`
escribe `camara-01_20260914-043000.mkv`, asi que HU-06 podra localizar la ventana
de una carga por nombre, sin abrir un solo archivo.

**Con el disco lleno se sigue grabando y se avisa.** Si el espacio no alcanza
para las 72 h, se borra lo mas antiguo aunque no las cumpla y el componente
`disco-video` queda en error en `GET /salud`. Dejar de grabar protegeria el video
viejo a costa de perder las cargas de hoy, que son las que todavia se pueden
investigar porque el camion sigue en planta.

**Un fallo de MySQL no para la grabacion.** Si la base no responde, el video
sigue cayendo al disco y lo que se pierde es la anotacion. Al reves seria
absurdo.

**La purga solo borra lo suyo.** Un archivo que no siga el patron de nombre del
grabador no se toca, por si alguien deja algo en esa carpeta.

## HU-06: recorte del clip (DONE)

> Como supervisor de despacho, quiero que el sistema recorte automaticamente el
> clip correspondiente a la ventana de tiempo de una carga con discrepancia, para
> revisar solo el tramo relevante y no horas de video.

| Criterio | Como se cumple | Donde se prueba |
|---|---|---|
| 1. Clip desde 5 min antes del inicio de carga hasta 2 min despues del cierre | `recorte.ventana_de` a partir de `pesada.inicio_carga` y `pesada.fecha_hora` | `test_la_ventana_empieza_5_min_antes_del_inicio_de_carga`, `test_recorta_video_de_verdad` |
| 2. El clip se guarda en MinIO y se vincula al evento | `app/almacen.py` sube y `clips._vincular` escribe `evento.clip_url` | `test_un_evento_recibe_su_clip`, `test_lo_que_se_baja_es_lo_que_se_subio` |
| 3. Si falta video del rango, el evento pasa a Sin clip | `clips.procesar_evento` captura `SinVideoEnLaVentana` y escribe el estado del apartado 5.3 | `test_sin_video_el_evento_pasa_a_sin_clip`, `test_con_muy_poco_video_tambien_es_sin_clip` |

### Como se recorta

El buffer son segmentos de un minuto con la marca de inicio en el nombre, asi que
recortar una ventana son tres pasos: elegir los segmentos que la tocan, pegarlos
con el demuxer `concat` y quedarse con el tramo pedido. Todo con `-c copy`, de
modo que un clip de siete minutos sale en segundos.

### Decisiones que conviene conocer

**El inicio de carga es un dato, no una estimacion.** El apartado 5.2 dice que el
sistema marca el inicio de la ventana de carga y hasta ahora nadie lo hacia. El
orquestador expone `POST /cargas/{orden}/inicio`, la pesada consume esa marca y
se queda con el instante. Sin la marca el clip sigue saliendo, pero cubre solo
los 5 minutos previos al cierre: una carga de veinte minutos se quedaria sin
principio.

**El recorte espera a que exista el margen posterior.** Los 2 minutos de despues
del cierre tardan 2 minutos en grabarse. Recortar en cuanto nace el evento daba
un clip cortado justo donde hay que mirar; se descubrio al probar el flujo
completo. Ahora el evento espera su turno y se recoge en una vuelta posterior.

**Con muy poco video tambien es Sin clip.** Un trozo suelto de una ventana larga
no sirve para revisar nada y, peor, haria creer al supervisor que tiene la carga
entera. Por debajo de `CLIP_MIN_COVERAGE_PCT` el evento se marca Sin clip con el
porcentaje que si habia.

**Sin credenciales de MinIO no se marca nada Sin clip.** Un fallo de
configuracion no puede convertirse en una conclusion sobre la evidencia: el
video sigue en el buffer y el grabador lo dice en el arranque.

**Lo que se guarda en el evento es `s3://bucket/objeto`, no una URL firmada.** El
evento se conserva 12 meses y una firma caduca en una hora; guardar algo que
dentro de una semana ya no abre seria peor que no guardar nada. La URL firmada la
pide el dashboard en el momento de reproducir.

**Sin clip no se reintenta.** Es una conclusion, no un pendiente. Reintentarlo en
bucle solo gastaria disco; si el video apareciera, HU-13 permitira reabrir el caso.

**Un evento que falla no frena a los demas.** El que reviente sigue sin
`clip_url` y vuelve a salir en la siguiente vuelta.

### Lo que HU-17 cambiara

Los eventos se buscan sondeando la tabla cada pocos segundos. Cuando llegue la
cola con reintentos, lo unico que cambia es quien llama a `clips.procesar_evento`.

## HU-07: el conteo en el evento (DONE, criterio 3)

> 3. El conteo y la diferencia con la orden se guardan en el evento.

Contar es trabajo del servicio YOLO, que vive en `quinor/despacho/yolo` con su
GPU y sus varios gigas de PyTorch. Lo que pasa aqui es lo otro: elegir el clip,
pedirle el conteo a ese servicio, comparar con la orden y escribir el resultado.

| Criterio | Como se cumple | Donde se prueba |
|---|---|---|
| 3. El conteo y la diferencia se guardan en el evento | `app/conteo.py` llama a `POST /analisis/yolo` y escribe `sacos_contados`, `diferencia_sacos` y `personas_detectadas` | `test_el_conteo_y_la_diferencia_quedan_en_el_evento`, `test_el_clip_recien_recortado_se_cuenta_sin_bajarlo` |

**Por que aqui y no en el orquestador.** El clip acaba de salir de `app/clips.py`
y todavia esta en disco local: analizarlo en ese mismo paso ahorra bajarlo de
MinIO. Y sobre todo, el analisis tarda minutos y el RNF-03 exige que
`POST /pesadas` responda en menos de 2 s, asi que no puede colgar de esa peticion.

**El clip viaja por ruta, no por HTTP.** Son cientos de megas por evento y los dos
contenedores comparten el volumen del buffer. Subirlo para que el otro lo escriba
otra vez en disco seria copiar gigas al dia sin motivo.

**La diferencia se guarda, no se recalcula al mirarla.** La orden se resincroniza
desde el ERP: si manana cambia `sacos_esperados`, un evento ya investigado no
puede cambiar de cifra a posteriori. Va con signo, igual que `diferencia_kg`, para
que quien lea el evento no tenga que aprender dos convenciones: negativa es
faltante.

**Cuando el servicio no responde no se pierde nada.** El clip ya esta guardado y
vinculado, que es lo que no se puede perder. El fallo queda en auditoria como
`conteo_fallido` y el reintento lo recoge en una vuelta posterior, bajando el clip
de MinIO en lugar de volver a recortarlo: el buffer solo guarda 72 h y el clip del
almacen es exactamente el que se vinculo al evento.

**Los reintentos se acaban.** `COUNT_MAX_ATTEMPTS` los limita contando las filas de
`conteo_fallido`. Un YOLO caido un dia entero tendria al grabador bajando los
mismos clips cada quince segundos hasta que alguien mirase el log.

**Sin `YOLO_URL` el conteo esta apagado** y el grabador sigue haciendo lo suyo de
HU-05 y HU-06. En una instalacion sin GPU eso es lo correcto, no un fallo.

## HU-08: las personas del clip (DONE, criterio 2)

> 2. Se registra cuantas personas estuvieron en zona y el tiempo de permanencia.

El seguimiento lo hace el servicio YOLO en la misma pasada del video que el
conteo de sacos. Este servicio recibe la lista y la escribe.

| Criterio | Como se cumple | Donde se prueba |
|---|---|---|
| 2. Se registra cuantas estuvieron en zona y el tiempo de permanencia | `app/conteo.py` escribe una fila por presencia en `persona_en_evento` y el total en `evento.personas_detectadas` | `test_quien_estuvo_en_zona_y_cuanto_queda_guardado` |

**De cada persona se guardan cuatro numeros y ninguno la identifica.** Un
identificador de seguimiento que vale solo dentro de ese clip, los segundos que
estuvo en zona y los dos fotogramas entre los que se la vio. Ni foto, ni recorte,
ni descriptor, ni nombre, ni codigo de empleado: la RN-08 prohibe la
identificacion facial y los datos biometricos, y la forma de cumplirla es no
tener nada que identificar. `test_de_una_persona_solo_se_guardan_un_numero_y_unos_segundos`
comprueba las columnas de la tabla para que eso siga siendo cierto.

**Reanalizar reemplaza, no acumula.** HU-19 va a cambiar el modelo y volver a
analizar clips. El registro tiene que quedar como ese analisis y no como la suma
de todos los que se hicieron, asi que las filas de la presencia anterior se
borran antes de escribir las nuevas.

**`personal_anomalo` en el evento es una senal, no una conclusion.** NULL mientras
el clip no se analiza, que no es lo mismo que False: HU-09 no puede confundir "no
se miro" con "se miro y estaba bien". El detalle de por que se marco (cuantos a
la vez, cuanto duro la permanencia mas larga, con que zona se midio) va a
auditoria, junto con los umbrales contra los que se comparo.

## HU-09: la descripcion y la severidad en el evento (DONE)

Interpretar es trabajo del servicio de vision-lenguaje, que vive en
`quinor/despacho/vlm` porque es el unico que sale a internet. Lo que pasa aqui es
lo otro: juntar lo que el evento sabe, subir los fotogramas, pedir la
interpretacion y escribir el resultado o marcar el fallo.

| Criterio | Como se cumple | Donde se prueba |
|---|---|---|
| 2. Descripcion, severidad y evidencia | `app/interpretacion.py` escribe `severidad`, `descripcion_ia` y `fotogramas_clave` | `test_la_severidad_y_la_descripcion_quedan_en_el_evento` |
| 3. Tras los reintentos, Pendiente de analisis | `marcar_pendiente_de_analisis`, con el estado del apartado 5.3 | `test_cuando_el_modelo_agota_sus_intentos_el_evento_queda_marcado` |

**Los fotogramas se guardan en MinIO junto al clip.** No solo para mandarlos al
modelo: sirven para el reintento, que asi no obliga a reanalizar el video, y para
el criterio 3 de HU-12, que pedira mostrar el fotograma de la anomalia. Quedan en
la misma carpeta que el clip, de modo que la evidencia de un caso este en un solo
sitio.

**La severidad se guarda aunque el modelo falle.** Sale de la RN-04, que es una
regla con umbrales exactos y no necesita al modelo. Es lo que permite que HU-10
notifique igual cuando el proveedor esta caido, que es justo el riesgo del
apartado 12.

**Un caso que un supervisor ya abrio no se toca.** El paso a Pendiente de
analisis y la vuelta a Pendiente solo ocurren desde y hacia esos dos estados: un
analisis que falla tarde no puede devolver a la cola un caso en revision, y la
RN-06 prohibe que un Confirmado retroceda.

**Los reintentos se acaban.** `VLM_MAX_ATTEMPTS` los limita contando las filas de
`interpretacion_fallida` en auditoria. Un proveedor caido un dia entero tendria
al grabador bajando los mismos fotogramas y pagando llamadas cada treinta
segundos.

## HU-10: el aviso en cuanto el evento queda clasificado (DONE, criterio 3)

Mandar el correo es trabajo del servicio de notificaciones, que vive en
`quinor/despacho/notificaciones` y decide a quien avisa y que dice el mensaje. Lo
que pasa aqui es lo otro: darse cuenta de que un evento acaba de quedar
clasificado y pedir el aviso en el acto.

| Criterio | Como se cumple | Donde se prueba |
|---|---|---|
| 3. Menos de 60 s tras el analisis | `app/aviso.py` manda la marca tomada al escribir la severidad | `test_se_pide_el_aviso_con_lo_que_tardo_desde_el_analisis` |

**El reloj se mide aqui y no alli.** El servicio de notificaciones no sabe cuando
termino el analisis; sabe cuando le pidieron el correo. El unico sitio donde
consta el instante en que la severidad quedo escrita es este, que es quien la
escribio, asi que de aqui sale el `segundos_desde_analisis` que el criterio 3
necesita para poder medirse en lugar de suponerse.

**El aviso sale en la misma pasada que la interpretacion.** Con un sondeo cada
treinta segundos, esperar a la vuelta siguiente gastaria media ventana del
criterio sin hacer nada. La pasada de reintento (`revisar_avisos`) existe igual,
pero es para lo que fallo, no para el camino normal. Ahi no se manda la marca: el
analisis pudo ser hace horas, y decir "cero segundos" daria el criterio por
cumplido sin haberlo comprobado.

**Un fallo avisando no tumba la interpretacion.** El analisis ya esta guardado y
el evento ya es visible en el dashboard. Quedarse sin correo es malo; perder el
analisis por eso seria mucho peor.

**El enganche es un parametro y no una llamada directa.** `interpretar` recibe
`al_clasificar`, de modo que HU-09 no depende de que exista HU-10. Quien enchufa
las dos cosas es el grabador, que es quien conoce las dos.

**Los reintentos se acaban**, como en HU-07 y HU-09: `NOTIFY_MAX_ATTEMPTS` los
limita contando las filas de `notificacion_fallida` en auditoria. Un servicio de
correo caido un dia entero tendria al grabador llamando en bucle sin que el
resultado cambiara.

## Configuracion

Todo por entorno, sin secretos en el codigo (seccion 8 del documento).

| Variable | Por defecto | Que hace |
|---|---|---|
| `DATABASE_URL` | obligatoria | Donde registrar la salud de las camaras |
| `CAMERAS` | vacio | Catalogo `id=url`, separado por comas. Maximo 4 (RNF-04) |
| `VIDEO_DIR` | `/video` | Raiz del buffer. Una subcarpeta por camara |
| `SEGMENT_SECONDS` | `60` | Duracion de cada segmento (criterio 1) |
| `RETENTION_HOURS` | `72` | Horas conservadas. Menos de 72 no arranca (criterio 2) |
| `MIN_FREE_PCT` | `10` | Por debajo se libera espacio y se avisa |
| `PURGE_INTERVAL_SECONDS` | `300` | Cada cuanto se revisa la retencion |
| `RTSP_TIMEOUT_SECONDS` | `15` | Sin respuesta en ese plazo, la camara se da por caida |
| `RETRY_SECONDS` | `10` | Espera entre reintentos de reconexion |
| `CLIP_PRE_SECONDS` | `300` | Margen antes del inicio de carga (HU-06, criterio 1) |
| `CLIP_POST_SECONDS` | `120` | Margen despues del cierre |
| `CLIP_CAMERA` | `camara-01` | De que camara se recorta el clip |
| `CLIP_MIN_COVERAGE_PCT` | `50` | Por debajo, el evento pasa a Sin clip |
| `CLIP_POLL_SECONDS` | `5` | Cada cuanto se buscan eventos sin clip |
| `MINIO_ENDPOINT` | `minio:9000` | Almacen de clips |
| `MINIO_ACCESS_KEY` | vacia | Sin credenciales no se recortan clips, y se avisa |
| `MINIO_SECRET_KEY` | vacia | |
| `MINIO_BUCKET` | `clips` | Se crea solo si no existe |
| `YOLO_URL` | vacia | Servicio de conteo. Vacia deja HU-07 apagada |
| `YOLO_API_KEY` | vacia | Clave compartida con ese servicio |
| `YOLO_TIMEOUT_SECONDS` | `600` | Sin esto, un YOLO colgado para la vuelta |
| `COUNT_MAX_ATTEMPTS` | `3` | Intentos de conteo por evento |
| `COUNT_POLL_SECONDS` | `15` | Cada cuanto se buscan eventos sin conteo |
| `VLM_URL` | vacia | Servicio de vision-lenguaje. Vacia deja HU-09 apagada |
| `VLM_SERVICE_API_KEY` | vacia | Clave compartida con ese servicio |
| `VLM_MAX_ATTEMPTS` | `3` | Intentos de interpretacion por evento |
| `VLM_POLL_SECONDS` | `30` | Cada cuanto se buscan eventos sin severidad |
| `NOTIFY_URL` | vacia | Servicio de notificaciones. Vacia deja HU-10 apagada |
| `NOTIFY_SERVICE_API_KEY` | vacia | Clave compartida con ese servicio |
| `NOTIFY_MAX_ATTEMPTS` | `3` | Intentos de aviso por evento |
| `NOTIFY_TIMEOUT_SECONDS` | `30` | Mas que esto ya no cabe en los 60 s del criterio 3 |
| `NOTIFY_POLL_SECONDS` | `10` | Cada cuanto se buscan eventos clasificados sin correo |

Ejemplo con camaras reales:

```bash
CAMERAS=camara-01=rtsp://admin:clave@10.0.0.11:554/Streaming/Channels/101,camara-02=rtsp://admin:clave@10.0.0.12:554/Streaming/Channels/101
```

## Puesta en marcha

El grabador forma parte del mismo compose que el orquestador:

```bash
cd ../api
docker compose up --build grabador rtsp-server camara-sim-01 camara-sim-02
```

Para comprobar que graba:

```bash
docker compose exec grabador ls -la /video/camara-01 | tail -5
```

Para comprobar el criterio 3, se apaga una camara y se consulta la salud:

```bash
docker compose stop camara-sim-01
curl -s -H "X-API-Key: $TOKEN" localhost:8000/salud | python -m json.tool
```

## Simulador de camaras

No hay camaras reales durante el desarrollo, igual que no hay bascula ni ERP.
Una camara IP es un servidor RTSP, asi que el simulador son dos piezas:

- `rtsp-server`: mediamtx, que hace de servidor RTSP.
- `camara-sim-01` y `camara-sim-02`: `sim/camara_sim.py`, que publican una senal
  sintetica con el identificador de camara y el reloj quemados en la imagen, de
  modo que al abrir un segmento se ve de que camara es y de que minuto.

El grabador se conecta contra el servidor RTSP igual que lo hara contra la camara
real: al cambiar `CAMERAS` por las URL de planta, no cambia una linea de codigo.

## Pruebas

```bash
pytest --cov=app --cov-report=term-missing
```

152 pruebas y 100 % de cobertura en los once modulos. El umbral esta fijado en
`pytest.ini` con `--cov-fail-under=90`. El reporte vigente esta en
`reporte_coverage.txt`.

| Archivo | Que cubre |
|---|---|
| `test_config.py` | Catalogo de camaras, limites del criterio 2 y precedencia de parametros |
| `test_ffmpeg.py` | Cada bandera del criterio 1 y el patron de nombre de los segmentos |
| `test_retencion.py` | Las 72 h, la frontera exacta y el disco al limite |
| `test_salud.py` | Registro de la desconexion contra MySQL real |
| `test_grabador.py` | Supervision, reintentos, ciclo de vida y grabacion real por RTSP |
| `test_recorte.py` | Ventana del clip, eleccion de segmentos y recorte real con ffmpeg |
| `test_clips.py` | Subida a un S3 real, vinculo con el evento y el estado Sin clip |

Siete pruebas graban y recortan de verdad: levantan un servidor RTSP, una camara emitiendo
y ffmpeg escribiendo en disco, y luego comprueban con `ffprobe` que los segmentos
duran lo configurado y que el codec de salida es el de entrada. Comprobar con un
mock que se llama a `subprocess` no diria nada sobre si el video acaba partido en
segmentos, que es lo que pide el criterio.

Esas pruebas necesitan ffmpeg, ffprobe y un servidor RTSP. En el compose lo
aporta `rtsp-server`; en local, la variable `MEDIAMTX_BIN`. Sin el, se saltan y
lo dicen en lugar de fingir que pasaron.

Las de HU-06 usan ademas un servidor S3 en proceso (`moto`). MinIO habla S3, asi
que el cliente oficial de MinIO funciona igual contra el: lo que se comprueba es
que el objeto quedo donde el evento apunta, no que se llamo a una funcion.

## Estructura

```
quinor/
  blockchain/api/       ejemplo de referencia
  despacho/
    api/                orquestador (HU-01, HU-02, HU-03, HU-04, HU-15)
    grabador/           este servicio (HU-05 a HU-10)
      app/
        grabador.py     supervisor de los ffmpeg y bucle principal
        ffmpeg.py       construccion y arranque de la orden de ffmpeg
        retencion.py    buffer circular de 72 h
        recorte.py      ventana y recorte del clip (HU-06)
        clips.py        caso de uso del clip de un evento (HU-06)
        conteo.py       analisis del clip y escritura en el evento (HU-07, HU-08)
        interpretacion.py descripcion y severidad del evento (HU-09)
        aviso.py        peticion del correo al quedar clasificado (HU-10)
        almacen.py      subida y descarga en MinIO (HU-06, HU-07)
        tablas.py       tablas del orquestador que este servicio usa
        salud.py        escritura en salud_componente
        config.py       Ajustes inmutables y catalogo de camaras
        db.py           motor de SQLAlchemy
      tests/            conftest y una suite por modulo
      sim/              camara simulada
      pytest.ini        umbral de cobertura
      requirements.txt  dependencias de ejecucion
      reporte_coverage.txt
```

## Lo que viene despues

HU-17 sustituira el sondeo de eventos por una cola con reintentos: cuando llegue,
lo unico que cambia es quien llama a `clips.procesar_evento`, `conteo.contar`,
`interpretacion.interpretar` y `aviso.avisar`.
