# Servicio de vision-lenguaje QUINOR - Alternativa 1

Describe lo ocurrido en el clip de un evento y asigna una severidad (HU-09).
Ubicacion en el repositorio: `quinor/despacho/vlm`.

Sigue la misma arquitectura que los otros tres servicios: fabrica de aplicacion
(`create_app`), configuracion inyectada por parametro, `app/` con el codigo,
`tests/` con una suite por modulo, `sim/` con el stub y `pytest.ini` con umbral
de cobertura.

Referencia funcional: `Documento_Funcional_Tecnico_Alternativa1_QUINOR.docx` v1.2,
apartados 6.4, 6.6 y 9.2.

## Por que un servicio aparte

No por tamano, como el de YOLO: esta imagen es la mas pequena de las cuatro,
porque aqui no hay modelo, hay una llamada HTTP. Va aparte porque **es el unico
servicio del sistema que sale a internet**. Tenerlo en un contenedor propio deja
esa salida en un solo sitio que se puede cortar, vigilar y ponerle una cuota, y
mantiene la red interna del apartado 8 como lo que dice ser.

El reparto:

- **este servicio** decide si hay que llamar al modelo, arma el prompt, llama,
  reintenta y valida lo que vuelve. No toca la base de datos;
- **el grabador** le pasa los datos y los fotogramas, y escribe el resultado en
  el evento o lo marca en Pendiente de analisis;
- **el orquestador** lo expone en `GET /eventos` y en el dashboard.

## HU-09: descripcion y severidad (DONE)

> Como supervisor de despacho, quiero que un modelo de vision-lenguaje describa
> lo ocurrido en el clip y asigne un nivel de severidad, para priorizar que
> eventos revisar primero.

| Criterio | Como se cumple | Donde se prueba |
|---|---|---|
| 1. Solo se invoca cuando YOLO confirma diferencia de sacos o personal anomalo | `app/invocacion.py` aplica la RN-03 antes de cualquier llamada | `tests/test_invocacion.py`, `test_una_carga_que_cuadra_no_llama_al_modelo` |
| 2. La respuesta es un JSON con descripcion, severidad y evidencia | `app/vlm.py` valida y normaliza lo que devuelve el modelo | `test_la_respuesta_trae_descripcion_severidad_y_evidencia` y las de validacion |
| 3. Si la API falla se reintenta 3 veces y luego se marca Pendiente de analisis | Los reintentos son de aqui; marcar el evento es del grabador | `test_tras_los_tres_intentos_se_informa_el_fallo`, `grabador/tests/test_interpretacion.py` |

### La severidad la decide la regla, no el modelo

El criterio 2 pide que el modelo devuelva severidad, y se le pide y se guarda.
Pero **la severidad del evento sale de la RN-04**, que la define con umbrales
exactos. Tres razones:

- una alerta de madrugada (HU-10) y el orden de la cola de revision (HU-11) no
  pueden depender de la temperatura de un modelo;
- es reproducible: el mismo clip da la misma severidad hoy y dentro de seis
  meses, que es lo que hace falta cuando un caso se discute;
- se puede explicar. "Alta porque la diferencia fue de 3 sacos" es algo que un
  supervisor puede comprobar; "Alta porque el modelo lo dijo" no lo es.

La del modelo se guarda aparte como `severidad_ia`, y de comparar las dos sale
la concordancia semanal que pide el apartado 9.2. Si el modelo acierta mejor que
la regla, se vera en esa medicion y entonces se decide, con datos delante.

### Cuando NO se llama al modelo

La RN-03 lo justifica por costo, y es verdad: la mayoria de los eventos de peso
son ajustes de bascula o humedad, no hurtos. Pero hay un segundo motivo, menos
obvio: **un analisis que aparece en todos los eventos deja de leerse.** Si el
supervisor ve una descripcion de IA en cada fila, incluidas las cuarenta cargas
correctas de la semana, deja de mirarlas, y entonces tampoco mira la que
importaba.

Cuando no se invoca, la respuesta dice por que. Un evento sin analisis y sin
explicacion parece un fallo del sistema, y alguien acabara reintentandolo a mano.

### El contrato

```
POST /analisis/vlm
{
  "evento_id": 42, "numero_orden": "ORD-2026-0101",
  "peso_esperado_kg": 20000.0, "peso_real_kg": 19850.0, "diferencia_kg": -150.0,
  "sacos_esperados": 400, "sacos_contados": 397, "diferencia_sacos": -3,
  "sacos_salientes": 1, "personas_detectadas": 4, "personal_anomalo": true,
  "fotogramas": [{"jpeg_base64": "...", "motivo": "saco_saliente",
                  "detalle": "Un saco cruza hacia fuera.", "segundo": 12.0}]
}

200 OK
{
  "invocado": true, "motivo_de_invocacion": "sacos_salientes",
  "explicacion": "YOLO confirmo que 1 saco(s) salieron de la zona de carga.",
  "severidad": "alta",
  "motivo_de_severidad": "1 saco(s) salieron de la zona de carga hacia fuera del camion.",
  "concuerdan": true,
  "analisis": {
    "descripcion": "Se observa a un operario retirando un saco...",
    "severidad_ia": "alta",
    "evidencia": ["Un saco cruza la linea hacia fuera de la zona de carga."],
    "confianza": 0.82, "modelo": "claude-sonnet-4-5", "proveedor": "anthropic",
    "intentos": 1, "segundos": 4.1
  },
  "fallo": false, "intentos": 1
}
```

Cuando el proveedor agota los tres intentos, la respuesta es **200 y no 500**:
el servicio funciono, lo que fallo fue el proveedor. Viene con `fallo: true` y su
motivo, y **la severidad igual**, porque sale de la regla. Es lo que permite que
HU-10 notifique aunque el modelo este caido, que es justo el riesgo que senala el
apartado 12.

## Decisiones que conviene conocer

**Agnostico de proveedor.** El documento no fija ninguno, y esta es una pieza que
se cambia: por precio, por disponibilidad, o porque el modelo de dentro de un ano
sea otro. Hay un adaptador por proveedor en `app/proveedores.py` y cambiar de uno
a otro es cambiar `VLM_PROVIDER`. No se usa el SDK de nadie: los SDK cambian mas
rapido que las APIs, y atarse a uno convertiria ese cambio en una reescritura.

**El prompt vive en un solo archivo.** El apartado 9.2 manda revisarlo cuando la
concordancia con el supervisor baje del 85 %. Si estuviera repartido por el
codigo, revisarlo seria arqueologia. `app/prompt.py` se lee entero de una vez,
que es la unica forma de saber que se le esta pidiendo a un modelo.

**Al modelo se le prohibe describir personas.** La RN-08 y la Ley 29733 prohiben
la identificacion facial y los datos biometricos. El modelo recibe imagenes con
personas, asi que hay que decirselo explicitamente: habla de "un operario", nunca
de rasgos, ropa o rostro. Hay pruebas que lo vigilan.

**Y se le pide que llame normal a lo normal.** Un modelo que siempre encuentra
algo sospechoso manda a alguien a la rampa cada dia hasta que dejan de hacerle
caso. Esta escrito en el prompt y probado.

**Lo que vuelve se valida, no se guarda tal cual.** Un modelo puede devolver el
JSON dentro de un bloque de codigo, una severidad en ingles, una severidad
inventada o texto donde iba una lista. Lo que tiene arreglo evidente se
normaliza; lo que no, se rechaza y se reintenta. Una severidad inventada en la
tabla es peor que un evento en Pendiente de analisis: el segundo se ve, el
primero no.

**No todos los errores se reintentan.** Un 429 o un 503 se arreglan esperando, y
la espera se duplica en cada intento. Un 400 o un 401 no: insistir con una clave
mala tres veces solo retrasa el momento de leer el error, y en un proveedor de
pago cada intento se cobra.

## El stub de desarrollo

`sim/vlm_stub.py` **no es un mock**: es un servicio HTTP que habla el mismo
dialecto que el proveedor real, con sus cabeceras, sus codigos de error y su
forma de respuesta. Contra un mock del cliente no se puede comprobar lo que de
verdad falla en planta: que la clave no viaja, que un 429 se reintenta y un 401
no, que el JSON llega envuelto en un bloque de codigo.

Lo que si es de mentira es el contenido: ahi no hay ningun modelo mirando
imagenes. Por eso `GET /salud` avisa en voz alta cuando el proveedor es el stub,
para que nadie confunda una respuesta de desarrollo con un analisis.

```bash
python -m sim.vlm_stub --puerto 8404
python -m sim.vlm_stub --fallar 429 --veces 2    # se recupera al tercer intento
python -m sim.vlm_stub --fallar 503              # agota los tres
python -m sim.vlm_stub --basura                  # responde algo que no es JSON
```

## Variables de entorno

Ninguna clave vive en el codigo (apartado 8).

| Variable | Por defecto | Para que |
|---|---|---|
| `VLM_PROVIDER` | `stub` | `anthropic`, `openai` o `stub` |
| `VLM_API_KEY` | vacia | Clave del proveedor. Sin ella, `/salud` lo dice y el analisis responde 503 |
| `VLM_MODEL` | `claude-sonnet-4-5` | Modelo concreto |
| `VLM_BASE_URL` | vacia | Para el stub o una pasarela interna |
| `VLM_MAX_ATTEMPTS` | `3` | Los del criterio 3 |
| `VLM_BACKOFF_SECONDS` | `2` | Espera inicial, se duplica en cada intento |
| `VLM_TIMEOUT_SECONDS` | `120` | Por llamada |
| `VLM_TEMPERATURE` | `0.2` | Baja: el mismo clip debe describir lo mismo dos veces |
| `VLM_SERVICE_API_KEY` | vacia | Clave que este servicio exige a quien le llama |
| `PLANTA_SACOS_POR_CAMION` | `400` | Contexto de planta del apartado 9.2 |
| `PLANTA_DURACION_CARGA_MIN` | `45` | |
| `PERSONAS_HABITUALES` | `3` | |

El valor por defecto de `VLM_PROVIDER` es `stub` a proposito: un valor que
saliera a internet convertiria un despliegue mal configurado en una factura.

## Pruebas

```
python -m pytest
```

Todo corre contra el stub por HTTP de verdad, incluidos los reintentos, los
codigos de error y las respuestas mal formadas. Las esperas entre intentos se
inyectan para que la suite no tarde seis segundos en verificar un backoff: una
prueba lenta acaba desactivada.

## Lo que queda fuera

- **La clave real del proveedor.** Todo esta probado contra el stub; la primera
  llamada a un proveedor real queda pendiente de que QUINOR decida cual y
  provea la clave.
- **El banco de ejemplos verificados** (few-shot) del apartado 9.2, que se
  alimenta de los veredictos de HU-13.
- **La medicion semanal de concordancia.** El dato ya se guarda en cada evento
  (`severidad` frente a `severidad_ia`); el informe es HU-14.
- **HU-10**, las notificaciones segun severidad.
