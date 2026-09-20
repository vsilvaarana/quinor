# Servicio de notificaciones QUINOR - Alternativa 1

Aviso al supervisor por correo segun la severidad del evento (HU-10).
Ubicacion en el repositorio: `quinor/despacho/notificaciones`.

Sigue la misma arquitectura que `quinor/blockchain/api` y que los otros cuatro
servicios: fabrica de aplicacion (`create_app`), configuracion inyectada por
parametro, `app/` con el codigo, `tests/` con una suite por modulo y
`pytest.ini` con umbral de cobertura.

Referencia funcional: `Documento_Funcional_Tecnico_Alternativa1_QUINOR.docx` v1.2.

## El cambio de alcance del 18/09/2026

El criterio 1 original repartia por canal: la Alta a SMS y Slack, la Media a
Slack y correo, la Baja a correo. Slack salio del alcance porque se esta
evaluando Teams en su lugar, y el SMS salio con el. Esa decision entra en su
propia historia de un sprint posterior.

Al quedar un solo canal, el criterio 1 se habria quedado sin contenido: las tres
severidades serian el mismo correo, que es la forma mas rapida de que un
supervisor deje de abrirlos. Asi que la severidad pasa a decidir otras dos
cosas, y eso es lo que dice ahora el criterio:

| Severidad | Quien lo recibe | Asunto | Prioridad |
|---|---|---|---|
| Alta | Supervisores y administradores | `[ALERTA ALTA]` | alta |
| Media | Supervisores | `[Alerta media]` | normal |
| Baja | Supervisores | `[Aviso]` | normal |

El rol Consulta no recibe alertas de ningun nivel: es de solo lectura del
dashboard (apartado 4) y no le corresponde actuar sobre una carga.

La columna `canal` de la tabla `notificacion` se conserva aunque hoy solo valga
`correo`. Cuando entre Teams o el SMS, cada canal tendra su fila y la clave
unica `(evento_id, canal)` seguira impidiendo el aviso repetido de cada uno.

## Por que un servicio aparte

El apartado 6.4 lo lista como componente propio y fija la libreria: aiosmtplib.
Va en su contenedor por la misma razon que el de vision-lenguaje: es uno de los
dos servicios que hablan con un servidor de fuera, y tenerlo aparte deja esa
salida en un sitio que se puede cortar, vigilar y limitar.

El servicio no decide cuando avisar. Eso lo decide quien llama, que es el
grabador en cuanto la severidad queda escrita, y por eso puede medir el criterio
3. Aqui solo se decide a quien, con que urgencia y que dice el correo.

## Los tres criterios, y donde vive cada uno

**1. Correo en los tres niveles, con destinatarios y urgencia por severidad.**
`app/destinatarios.py`. Los correos salen de la tabla `usuario` de HU-15 y no de
una lista en el entorno: dar de alta a alguien en el dashboard basta para que
empiece a recibir alertas, y darlo de baja lo corta el mismo dia. La prioridad
viaja en tres cabeceras porque ningun cliente de correo las entiende todas.

**2. Orden, diferencia y enlace al evento.** `app/plantilla.py`. Los tres datos
van en el asunto y en el cuerpo, y hay pruebas que los buscan en el texto del
mensaje y no en la estructura que lo genero. La diferencia se da con el signo
puesto: "faltan 8 sacos" y "sobran 8 sacos" son dos situaciones distintas. Con
los sacos cuadrados y el peso corto, el asunto informa los kilos, que es
justamente el caso de producto sustituido que motiva el proyecto.

**3. Menos de 60 s tras el analisis.** Se mide entre los dos servicios: el
grabador toma la marca cuando escribe la severidad y la manda en
`segundos_desde_analisis`; aqui se suma lo que costo el envio, se guarda en la
tabla y se dice en la respuesta si entro dentro del limite. Un aviso tardio no
se esconde: sale en el log, en la tabla y en el dashboard.

## Lo que el correo no lleva

Fotogramas adjuntos. Son imagenes de la zona de carga con personas dentro, y el
apartado 8 las quiere en la red interna: un adjunto sale de ese control en
cuanto alguien reenvia el correo. El enlace del criterio 2 lleva al dashboard,
que pide sesion.

Tampoco lleva nada que identifique a nadie. De las personas del clip solo dice
cuantas hubo, que es lo que HU-08 guarda (RN-08).

## Rutas

| Metodo y ruta | Para que |
|---|---|
| `GET /` | Healthcheck del compose. Es la unica ruta publica. |
| `GET /salud` | Si el servicio puede avisar: servidor de correo, base de datos y cuantos destinatarios recibirian una Alta. |
| `POST /notificaciones` | Avisa de un evento. Recibe `evento_id` y, si quien llama la tiene, la medida del criterio 3. |

El contenido del correo se lee de la base y no de lo que mande quien llama: el
correo tiene que decir lo mismo que el dashboard.

## No avisar dos veces

El grabador sondea, y sondear significa que el mismo evento pasa por aqui en
cada vuelta. La defensa es la clave unica `(evento_id, canal)` de la tabla: la
comprobacion previa evita el trabajo, pero es la clave la que evita el segundo
correo si dos procesos coinciden.

Un aviso fallido no cuenta como avisado y su fila se reemplaza en el siguiente
intento. Si contara, un relay caido durante un minuto dejaria un evento Alto sin
aviso para siempre, que es peor que el correo duplicado que se queria evitar.

## Configuracion

Ninguna clave en el codigo (apartado 8). Todo por entorno o secreto de Docker:

| Variable | Para que |
|---|---|
| `DATABASE_URL` | Donde estan `usuario`, `evento` y `notificacion`. |
| `SMTP_HOST`, `SMTP_PORT` | El servidor de correo. Por defecto el buzon de desarrollo. |
| `SMTP_SECURITY` | `starttls` (587), `ssl` (465) o `ninguno` (desarrollo). |
| `SMTP_USER`, `SMTP_PASSWORD` | Credenciales del buzon de salida. La contrasena no aparece ni al imprimir los ajustes. |
| `SMTP_FROM`, `SMTP_FROM_NAME` | De quien sale. Conviene un buzon del sistema y no el de una persona. |
| `DASHBOARD_BASE_URL` | El enlace del criterio 2. |
| `NOTIFY_SERVICE_API_KEY` | La clave que este servicio exige a quien le llama. |
| `NOTIFY_MAX_ATTEMPTS`, `NOTIFY_BACKOFF_SECONDS` | Reintentos del envio. Caben en los 60 s del criterio 3. |

## Los reintentos distinguen lo que tiene arreglo

Un 421 o un 451 son "ahora no puedo, vuelve luego" y merecen otro intento; un
550 es "esa direccion no existe" y repetirlo tres veces solo retrasa el registro
del fallo. El criterio 3 da 60 segundos, y gastarlos insistiendo en un error
permanente es incumplirlo sin motivo.

## Pruebas

```bash
DATABASE_URL=... pytest
```

El correo se prueba contra un servidor SMTP de verdad levantado dentro de las
pruebas con aiosmtpd, no contra un mock de aiosmtplib: lo que hay que demostrar
es que sale un correo con su asunto codificado, sus dos partes y su cabecera de
prioridad, y eso solo se ve del lado del servidor. Los destinatarios y el
contenido se leen de MySQL de verdad, porque de eso van los criterios 1 y 2.

Cobertura y resultado en `reporte_coverage.txt`.

## En desarrollo

`docker compose up` levanta el servicio junto a **mailpit**, un buzon que acepta
cualquier correo y no lo entrega a nadie. Los correos se leen en
`http://localhost:8025`. Es lo que permite recorrer HU-10 de punta a punta sin
un relay corporativo y sin riesgo de escribirle a un supervisor de verdad
durante una prueba.
