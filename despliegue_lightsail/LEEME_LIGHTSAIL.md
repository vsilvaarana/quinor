# Base de datos de QUINOR en AWS Lightsail (MySQL 8)

Paquete para crear la base del sistema en una base administrada de Lightsail y
dejarla lista para la aplicación. Se ejecuta desde tu PC con Windows.

## Qué hay en esta carpeta

| Archivo | Qué hace | Modifica la base |
|---|---|---|
| `configurar_lightsail.ps1` | Activa el modo público y el parámetro que permite crear triggers | Configura AWS, no los datos |
| `desplegar_lightsail.ps1` | Corre los `.sql` en orden, con SSL y hora de Lima | Sí |
| `00_diagnostico.sql` | Versión, privilegios, SSL, zona horaria y si faltan pasos | No |
| `01_esquema.sql` | 13 tablas, 2 vistas y las 3 tolerancias | Sí |
| `02_triggers.sql` | Los 3 triggers: RN-06 y auditoría inmutable (HU-16) | Sí |
| `03_datos_demo.sql` | Usuarios, una orden y un evento de ejemplo | Sí, opcional |
| `99_verificacion.sql` | Cuenta lo creado y muestra la vista del dashboard | No |

Los `.sql` son los mismos del despliegue para MariaDB. Cambian los scripts de
PowerShell, que resuelven tres cosas propias de Lightsail:

1. **Triggers.** El usuario maestro de Lightsail no tiene el privilegio SUPER y
   el binlog está activo. Sin cambiar `log_bin_trust_function_creators` a 1, el
   paso 02 falla con `ERROR 1419`. Comprobado en MySQL 8 configurado igual.
2. **Zona horaria.** Lightsail trabaja en UTC y la aplicación escribe en hora de
   Lima. Sin corregirlo, las fechas que pone el script quedan 5 h adelantadas.
   El instalador fija la sesión en `-05:00`, y Perú no tiene horario de verano.
3. **SSL.** La base queda expuesta a internet, así que la conexión va cifrada y
   verificando el certificado de AWS (`global-bundle.pem`, se descarga solo).

---

## Paso 1. Crear la base en Lightsail

En https://lightsail.aws.amazon.com, ve a **Bases de datos > Crear base de datos**:

- **Ubicación:** la región más cercana a donde correrá la aplicación.
- **Motor:** MySQL, versión 8.0 (la más reciente de la lista).
- **Credenciales:** usuario `dbmasteruser`. Elige una contraseña fuerte y
  guárdala, porque Lightsail no la vuelve a mostrar.
- **Nombre de la base maestra:** `quinor`. Es la base donde irán las tablas.
- **Plan:** Estándar de 15 USD al mes. Si tu cuenta es nueva en Lightsail, los
  3 primeros meses son gratis.
- **Nombre del recurso:** por ejemplo `quinor-db`.

Cuando el estado pase a **Disponible** (unos 10–15 minutos), anota el
**punto de enlace** (endpoint). Tiene esta forma:
`ls-xxxxxxxx.yyyyyy.us-east-1.rds.amazonaws.com`.

## Paso 2. Modo público y parámetro de los triggers

### Opción A: con el script (requiere AWS CLI)

Instala AWS CLI (https://aws.amazon.com/cli/) y corre `aws configure` con una
clave de acceso de tu cuenta. Luego:

```powershell
cd C:\ruta\a\despliegue_lightsail
powershell -ExecutionPolicy Bypass -File .\configurar_lightsail.ps1 -NombreRecurso quinor-db -Region us-east-1 -HacerPublica
```

Debe terminar con `Listo: log_bin_trust_function_creators = 1`. El modo público
tarda unos minutos más en aplicarse.

### Opción B: sin instalar nada (AWS CloudShell)

En la consola de AWS, abre **CloudShell** (ícono `>_` arriba a la derecha),
en la misma región de la base, y pega:

```bash
aws lightsail update-relational-database --relational-database-name quinor-db --publicly-accessible
aws lightsail update-relational-database-parameters --relational-database-name quinor-db \
  --parameters "parameterName=log_bin_trust_function_creators,parameterValue=1,applyMethod=immediate"
```

El modo público también se puede activar en la consola: entra a la base y,
en la pestaña **Redes**, activa **Modo público**.

## Paso 3. Cliente mysql en tu PC

El instalador necesita `mysql.exe`. Lo trae **MySQL Workbench**
(https://dev.mysql.com/downloads/workbench/), y el script lo encuentra solo.

## Paso 4. Crear las tablas

Primero solo el diagnóstico, que no toca nada:

```powershell
powershell -ExecutionPolicy Bypass -File .\desplegar_lightsail.ps1 -Servidor ls-xxxxxxxx.yyyyyy.us-east-1.rds.amazonaws.com -Base quinor -SoloDiagnostico
```

En la tabla `diagnostico_triggers` debe decir `ok`, en `zona_de_esta_sesion`
debe salir `-05:00`, y `Ssl_cipher` debe mostrar un algoritmo, lo que confirma
que la conexión va cifrada.

Después, el despliegue completo con los datos de ejemplo y el usuario propio de
la aplicación:

```powershell
powershell -ExecutionPolicy Bypass -File .\desplegar_lightsail.ps1 -Servidor ls-xxxxxxxx.yyyyyy.us-east-1.rds.amazonaws.com -Base quinor -ConDemo -CrearUsuarioApp
```

Te pedirá la contraseña de `dbmasteruser` y luego una contraseña nueva para
`quinor_app`, de al menos 12 caracteres y sin comillas simples ni barras
invertidas. Al final debe salir:

```
objeto        cuantos  esperado
tablas        13       13
vistas        2        2
triggers      3        3
tolerancias   3        3
```

Toda la salida queda en `salida_despliegue.txt`. Se puede volver a ejecutar sin
duplicar ni dañar datos.

**Si el script se detiene con "ALTO: log_bin_trust_function_creators está en 0",**
vuelve al Paso 2. Se detiene antes de crear nada para no dejar el esquema a medias.

## Paso 5. Conectar la aplicación

La aplicación usa el usuario `quinor_app`, no `dbmasteruser`. Ese usuario puede
leer y escribir datos, pero no borrar ni alterar tablas, así que si su clave se
filtra, el esquema sigue a salvo.

En `despacho/api/.env` (lo leen la API, el grabador y notificaciones):

```
DATABASE_URL=mysql+pymysql://quinor_app:LA_CLAVE@ls-xxxxxxxx.yyyyyy.us-east-1.rds.amazonaws.com:3306/quinor?charset=utf8mb4&ssl_ca=RUTA_AL_CERTIFICADO
```

- Fuera de Docker, en Windows, `RUTA_AL_CERTIFICADO` es la ruta del
  `global-bundle.pem` que descargó el script, con barras normales:
  `C:/ruta/a/despliegue_lightsail/global-bundle.pem`.
- Con Docker, el certificado tiene que estar dentro de cada contenedor que usa
  la base (`api`, `grabador`, `notificaciones`, `dashboard`). Por ejemplo, monta
  `./certs/global-bundle.pem:/certs/global-bundle.pem:ro` en cada uno y usa
  `ssl_ca=/certs/global-bundle.pem`.
- Si la clave tiene caracteres reservados en una URL (`@ : / ? # [ ] %`),
  escríbelos codificados: `@` es `%40`, `#` es `%23`, `[` es `%5B`.

El servicio `mysql` del docker-compose ya no hace falta para la aplicación. Puedes
dejarlo corriendo para las pruebas automáticas.

## Alternativa sin PowerShell: MySQL Workbench

1. Crea una conexión con el endpoint, el puerto 3306 y `dbmasteruser`. En la
   pestaña SSL elige `Require and Verify Identity` y como **SSL CA File** el
   archivo `global-bundle.pem` (descárgalo de
   https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem).
2. Abre una pestaña de consultas y ejecuta primero `USE quinor;` y
   `SET time_zone = '-05:00';`.
3. En **esa misma pestaña**, abre y ejecuta en orden `00`, `01`, `02`, `03`
   (opcional) y `99`. Workbench entiende el `DELIMITER` de `02_triggers.sql`.

## Lo que NO hay que hacer

- **No apuntes las pruebas (`pytest`) a esta base.** Su `conftest.py` hace
  `DROP DATABASE` y `TRUNCATE` en cada prueba, y borrarían todo. Las pruebas van
  contra un MySQL o MariaDB local.
- **Cambia la contraseña de los usuarios de ejemplo** (`Quinor2026!`) desde el
  dashboard después de entrar.
- **No guardes contraseñas en archivos del repositorio.** Ni en este LEEME ni en
  `.env` versionados.

## Costos a vigilar

- La base cuesta 15 USD al mes después de los meses gratis, y **se cobra aunque
  esté detenida**. Solo deja de cobrar si la eliminas (toma antes una
  instantánea si quieres conservar los datos).
- Configura una alerta de facturación en AWS (Billing > Budgets) para que te
  avise antes de que empiece el cobro.

## Qué se probó antes de entregarte esto

Contra MySQL 8.0.46 configurado como Lightsail (binlog activo, servidor en UTC,
SSL con verificación de nombre y un usuario maestro con los mismos permisos que
`dbmasteruser`, sin SUPER):

- Con el parámetro en 0, `02_triggers.sql` falla con `ERROR 1419`, y el
  instalador se detiene antes de crear nada.
- `configurar_lightsail.ps1`, probado con un AWS CLI simulado que responde como
  Lightsail (incluida la paginación de parámetros), activa el parámetro y el
  modo público.
- Con el parámetro en 1: 13 tablas, 2 vistas, 3 triggers y 3 tolerancias. Una
  segunda ejecución no duplica datos.
- El usuario `quinor_app` queda con SELECT, INSERT, UPDATE y DELETE; no puede
  borrar tablas, y los triggers lo frenan igual (RN-06 y auditoría).
- La API real, conectada con `quinor_app` y `ssl_ca`: el login del usuario de
  ejemplo, la pesada que crea un evento y la clasificación funcionan, y la
  conexión va cifrada (TLS 1.3).
- Las fechas que pone el script coinciden con las que escribe la aplicación (hora
  de Lima), aunque el servidor esté en UTC.

Lo único que no se pudo probar aquí es la cuenta real de AWS: los comandos de
`aws lightsail` siguen la documentación oficial, pero se probaron contra un
simulador.
