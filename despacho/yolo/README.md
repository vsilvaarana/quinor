# Servicio YOLO QUINOR - Alternativa 1

Conteo de los sacos que cruzan la linea de carga (HU-07) y seguimiento de las
personas presentes en la zona de carga (HU-08), sobre el clip de un evento.
Ubicacion en el repositorio: `quinor/despacho/yolo`.

Sigue la misma arquitectura que `quinor/blockchain/api`, que el orquestador y que
el grabador: fabrica de aplicacion (`create_app`), configuracion inyectada por
parametro, `app/` con el codigo, `tests/` con una suite por modulo, `sim/` con el
simulador y `pytest.ini` con umbral de cobertura.

Referencia funcional: `Documento_Funcional_Tecnico_Alternativa1_QUINOR.docx` v1.2,
apartado 6.4.

## Por que un servicio aparte

PyTorch, CUDA y ultralytics son varios gigas que ni el orquestador ni el grabador
necesitan para nada, y en planta la GPU del RNF-06 se le asigna a un solo
contenedor. Ademas, analizar un clip tarda minutos: colgarlo del `POST /pesadas`
romperia los 2 s que exige el RNF-03.

El reparto queda asi:

- **este servicio** mira el video, y no toca la base de datos ni sabe que es un
  evento;
- **el grabador** elige el clip, pide el analisis y escribe el resultado, que es
  el criterio 3 de HU-07 y el criterio 2 de HU-08;
- **el orquestador** lo expone en `GET /eventos`, en
  `GET /eventos/{id}/personas` y en el dashboard.

Sacos y personas salen de la misma pasada por el video. El clip ya esta abierto y
ultralytics devuelve las dos cosas en la misma inferencia: separarlas en dos
recorridos doblaria el coste sin ganar nada, y el RNF-01 no tiene ese margen.

El clip viaja por ruta y no por el cuerpo de la peticion: son cientos de megas
por evento y los dos contenedores ya ven el mismo volumen del buffer.

## HU-07: conteo de sacos (DONE)

> Como supervisor de despacho, quiero que el sistema cuente los sacos cargados al
> camion a partir del video, para contrastar el conteo visual con el peso y la
> orden.

| Criterio | Como se cumple | Donde se prueba |
|---|---|---|
| 1. El servicio procesa el clip y devuelve los sacos que cruzan la linea | `app/analisis.py` detecta y sigue con YOLO11 + ByteTrack; `app/conteo.py` decide que cruces cuentan | `test_cuenta_los_sacos_que_cruzan`, `test_una_carga_conocida_se_cuenta_bien`, `tests/test_conteo.py` entero |
| 2. Precision del conteo >= 95 % en el set de validacion | `sim/validar.py` mide carga por carga; el resultado esta en `reporte_validacion.txt` | `tests/test_validacion.py`, y `python -m sim.validar` |
| 3. El conteo y la diferencia con la orden se guardan en el evento | Lo hace el grabador: `grabador/app/conteo.py` | `grabador/tests/test_conteo.py` |

## HU-08: seguimiento de personas (DONE)

> Como supervisor de despacho, quiero que el sistema haga seguimiento de las
> personas presentes en la zona de carga durante el evento, para identificar si
> hubo personal no autorizado o movimientos anomalos.

| Criterio | Como se cumple | Donde se prueba |
|---|---|---|
| 1. Se detecta y sigue a cada persona con un ID temporal durante el clip | ByteTrack pone el identificador; `app/personas.py` lleva la cuenta | `test_cada_persona_tiene_su_identificador_durante_el_clip`, `test_se_sigue_a_las_personas_del_clip` |
| 2. Se registra cuantas estuvieron en zona y el tiempo de permanencia | `Resumen` en la respuesta; el grabador lo escribe en `persona_en_evento` | `test_se_registra_el_tiempo_de_permanencia`, `test_quien_estuvo_en_zona_y_cuanto_queda_guardado` |
| 3. No se realiza identificacion facial ni se guardan datos biometricos | Por aqui no sale un rostro: de cada persona van un numero de seguimiento, dos fotogramas y unos segundos | `test_de_una_persona_solo_se_guardan_un_numero_y_unos_segundos`, `test_el_identificador_no_sobrevive_al_clip` |

### El criterio 3 no se cumple por omision

Es la forma del modulo. `app/personas.py` no recibe ni una imagen: recibe
posiciones con un numero, y devuelve ese numero, dos instantes y unos segundos.
No hay rostro, ni huella, ni descriptor, ni nada que permita reconocer a la misma
persona en otro clip. El identificador lo asigna ByteTrack, vale solo dentro de
ese video y se reinicia con el siguiente, como pide el apartado 8 y exige la Ley
29733.

Hay pruebas que lo vigilan, y no solo comentarios: si alguien anadiera un recorte
de imagen o un descriptor al contrato o a la tabla, `test_de_una_persona_solo_se_guardan_un_numero_y_unos_segundos`
fallaria antes de que eso saliera de la red interna.

Eso tiene una consecuencia que conviene decir en voz alta: **si un operario sale
del cuadro y vuelve, el rastreador le da otro numero y se cuenta como dos
presencias.** Es el precio de no identificar a nadie, y es el lado correcto en el
que equivocarse.

### La zona de carga

La permanencia se mide dentro de un rectangulo en coordenadas relativas, no en
todo el cuadro. Con el cuadro entero, quien pasa por el fondo cuenta como
presente en la rampa, y ese ruido aparece justo cuando hay que decidir si bajar a
mirar. Por defecto es el cuadro completo, porque elegir una zona mas estrecha a
ciegas dejaria fuera a gente que si estuvo: se calibra en el piloto mirando un
clip real, igual que la linea (apartado 9.1). La respuesta trae `zona_completa`
para que quien lea el dato sepa con cual de las dos situaciones esta.

### "Personal no autorizado", sin identificar a nadie

La RN-03 manda invocar el modelo de vision-lenguaje solo cuando YOLO confirma
diferencia de sacos "o presencia anomala de personal", y la RN-04 pone "personal
no habitual" en severidad Media. Hacen falta entonces una senal y que esa senal
no venga de saber quien es nadie.

"No autorizado" no se puede decidir sin una lista de personas, y una lista de
personas es justo lo que la RN-08 prohibe. Lo que si se puede medir es el
comportamiento del grupo y del tiempo, que es lo que hacen las tres reglas de
`app/anomalias.py`:

| Codigo | Cuando salta | Umbral |
|---|---|---|
| `demasiadas_personas_a_la_vez` | Mas gente simultanea de la que cabe en una rampa normal | `PERSONAS_HABITUALES` |
| `permanencia_excesiva` | Alguien se queda mucho mas de lo que dura una carga | `PERMANENCIA_MAX_SEGUNDOS` |
| `personas_sin_movimiento_de_sacos` | Hubo gente en zona y ningun saco cruzo la linea | fijo |

Se mira **cuantas a la vez** y no cuantas en total: cuatro personas que se turnan
durante la carga son un turno, cuatro a la vez son otra cosa. Los umbrales son
configurables porque lo habitual en una rampa lo sabe QUINOR y no este codigo;
los valores por defecto son un punto de partida para el piloto.

Esto no es una acusacion ni una conclusion: es un motivo para que un supervisor
mire el clip, y el disparo que la RN-03 necesita para no llamar al modelo de
vision-lenguaje en cada carga. La decision sobre una persona la toma una persona,
con la politica de RR. HH. delante.

### El contrato

```
POST /analisis/yolo
{
  "clip": "/video/clips/evento-42.mkv",
  "sacos_esperados": 400,
  "linea": [0.5, 0.0, 0.5, 1.0],       # opcional, la de la camara que llama
  "zona":  [0.4, 0.0, 1.0, 1.0],       # opcional, la zona de carga de esa camara
  "invertir_sentido": false            # opcional
}

200 OK
{
  "sacos_contados": 398, "sacos_entrantes": 400, "sacos_salientes": 2,
  "sacos_esperados": 400, "diferencia_sacos": -2,
  "personas_detectadas": 3,
  "presencia": {
    "cuantas": 3, "maximo_simultaneo": 2, "segundos_totales": 540.0,
    "permanencia_maxima_s": 320.5, "permanencia_media_s": 180.0,
    "zona_completa": false,
    "personas": [
      {"id_temporal": 1, "segundos_en_zona": 320.5,
       "primer_fotograma": 10, "ultimo_fotograma": 3200}
    ]
  },
  "anomalia_de_personal": false, "motivos_de_anomalia": [],
  "fotogramas_procesados": 6300, "duracion_del_clip_s": 420.0,
  "segundos_de_proceso": 95.4, "modelo": "sacos.pt", "aviso": null
}
```

`GET /` es publico y sirve de healthcheck. `GET /salud` y `POST /analisis/yolo`
piden `X-API-Key` cuando `YOLO_API_KEY` esta configurada.

## Decisiones que conviene conocer

**Contar no es detectar.** Un saco aparece en decenas de fotogramas seguidos, y
sumar detecciones daria cientos por carga. Lo que se cuenta es cuantos objetos,
cada uno con su identificador de seguimiento, pasaron de un lado de la linea al
otro. Ese planteamiento es tambien lo que aguanta las oclusiones que el apartado
11 senala como riesgo: si un operario tapa un saco tres fotogramas, el
identificador sobrevive y el cruce se cuenta una sola vez.

**La linea va en coordenadas relativas.** De 0 a 1, no en pixeles, para que
cambiar la camara por otra de mas resolucion no obligue a recalibrar. Quien llama
puede pasar la suya: con dos camaras enfocando rampas distintas, la linea no es
la misma, y sin eso haria falta un servicio por camara.

**Los sacos que vuelven se informan aparte.** El conteo neto es lo que entro menos
lo que salio, pero `sacos_salientes` viaja en la respuesta porque la RN-04 trata
un saco que sale de la zona de carga como senal de severidad Alta: no es un error
de conteo.

**El salto de fotogramas es 1, y no por comodidad.** Saltando uno de cada dos, el
conteo daba cero. No era el detector, que veia los sacos igual de bien: era
ByteTrack, que asocia por solapamiento. Un saco que avanza mas que su propio ancho
entre dos fotogramas mirados no solapa con su prediccion, nunca recibe
identificador y ningun cruce se cuenta. Subir `YOLO_FRAME_STRIDE` obliga a repetir
la validacion del criterio 2 con la velocidad real de la rampa.

**Ese fallo no puede ser silencioso.** Cuando el detector ve objetos y el
rastreador no sigue ninguno, la respuesta trae un `aviso` y el log una linea de
error. Sin eso, un stride mal puesto devuelve cero y parece un camion sin cargar,
que es justo la conclusion que mandaria a alguien a la rampa por nada.

**El modelo se carga al arrancar.** Un servicio que carga PyTorch en la primera
peticion se lo cobra al primer camion del dia, que es cuando esta esperando. Si
los pesos no estan o no cargan, el servicio arranca igual, `GET /salud` lo dice y
`POST /analisis/yolo` responde 503: reiniciarse en bucle solo esconderia el motivo.

**Los pesos llegan por volumen, no en la imagen.** Cambiar de modelo no reconstruye
nada, que es lo que HU-19 necesitara al reentrenar con el dataset real. El nombre
del modelo viaja en cada respuesta y queda en la auditoria del evento, para saber
con cual se conto una carga que se discuta seis meses despues.

## El set de validacion

**Es sintetico, y eso hay que leerlo entero.** QUINOR todavia no ha entregado
fotogramas de la rampa; el dataset propio etiquetado es HU-19. `sim/rampa_sim.py`
genera dos cosas: imagenes etiquetadas en formato YOLO para entrenar, y clips en
los que un numero conocido de sacos cruza la linea, con operarios que tapan y
sacos que vuelven atras.

Lo que la cifra mide es el contador completo: deteccion, seguimiento, oclusiones,
cruces y retornos. Lo que no mide es como se comportara el modelo con sacos de
yute reales, polvo y contraluz. Esa cifra sale del piloto de 4 semanas, y su
criterio de salida es el mismo 95 %.

El dataset es formato YOLO, el mismo que HU-19 espera del etiquetado en CVAT, de
modo que cambiar este set por el real sera cambiar la carpeta.

```
python -m sim.entrenar --imagenes 200 --epocas 20 --tamano 416   # entrena
python -m sim.validar                                            # mide y reporta
```

El reporte que produjo el modelo actual esta en `reporte_validacion.txt`, con su
advertencia en la cabecera.

## Variables de entorno

Ninguna clave vive en el codigo (apartado 8).

| Variable | Por defecto | Para que |
|---|---|---|
| `YOLO_WEIGHTS` | `modelos/sacos.pt` | Pesos del modelo activo |
| `YOLO_DEVICE` | `cpu` | `0` o `cuda:0` en planta (RNF-06) |
| `LINEA_CARGA` | `0.5,0.0,0.5,1.0` | Linea de carga en coordenadas relativas |
| `LINEA_INVERTIDA` | `false` | Si la camara mira la rampa del otro costado |
| `YOLO_CONF` | `0.35` | Umbral de confianza |
| `YOLO_FRAME_STRIDE` | `1` | Fotogramas que se saltan. Ver arriba |
| `YOLO_MEMORIA` | `30` | Fotogramas que un identificador puede desaparecer |
| `ZONA_CARGA` | `0,0,1,1` | Zona de carga de HU-08, en coordenadas relativas |
| `PERSONAS_HABITUALES` | `3` | Personas simultaneas que no llaman la atencion |
| `PERMANENCIA_MAX_SEGUNDOS` | `600` | Por encima, la permanencia es anomala |
| `PERMANENCIA_MIN_SEGUNDOS` | `1` | Por debajo, es un parpadeo del detector |
| `YOLO_API_KEY` | vacio | Clave compartida con el grabador |

## Pruebas

```
python -m pytest                    # suite completa con cobertura
python -m pytest tests/test_modelo.py   # solo con los pesos entrenados
```

`tests/test_modelo.py` carga el modelo de verdad y analiza video de verdad; se
salta cuando `modelos/sacos.pt` no existe, porque entrenarlo lleva minutos y no
puede ser un requisito para correr la suite. El resto usa un modelo inyectado:
lo que prueban es el contrato de la API y la regla de conteo, no la inferencia de
ultralytics, que ya tiene las suyas.

## Lo que queda fuera

- **HU-09**, severidad y descripcion con modelo de vision-lenguaje. Este servicio
  ya le entrega lo que la RN-03 necesita para decidir si invocarlo.
- **HU-19**, dataset real etiquetado y versionado del modelo en `modelo_version`.
  Mientras tanto, el nombre del archivo de pesos hace de version.
