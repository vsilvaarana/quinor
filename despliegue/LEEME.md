# Despliegue de la base QUINOR en vallesol.pe (MariaDB)

## Por que este paquete existe

Desde la sesión de Claude no hay ruta hacia `vallesol.pe`. Se comprobó por los
dos caminos posibles:

| Desde | Prueba | Resultado |
|---|---|---|
| Contenedor en la nube | `vallesol.pe:3306` | timeout, error MySQL 2003 (110) |
| Contenedor en la nube | `https://vallesol.pe` | 403 del proxy de salida |
| VM de Cowork en tu PC | resolución DNS | falla, no hay DNS |
| VM de Cowork en tu PC | `https://www.google.com` | 403, salida cerrada |

Tu VS Code sí conecta porque corre en Windows, con tu red y tu IP, que es la que
el hosting tiene permitida en Remote MySQL. Las credenciales están bien; lo que
falta es el camino. Por eso los scripts se ejecutan desde donde ya funciona.

## Qué hay aquí

| Archivo | Qué hace | Modifica la base |
|---|---|---|
| `00_diagnostico.sql` | Motor, versión, privilegios y qué hay ya dentro | No |
| `01_esquema.sql` | 13 tablas, 2 vistas y las 3 tolerancias por producto | Sí |
| `02_triggers.sql` | Los 3 triggers: RN-06 y auditoría inmutable (HU-16) | Sí |
| `03_datos_demo.sql` | Usuarios, una orden, un evento analizado y su aviso | Sí, opcional |
| `99_verificacion.sql` | Cuenta objetos y muestra la vista del dashboard | No |
| `desplegar.ps1` | Corre todo lo anterior en orden | Sí |

Los scripts se generan desde `despacho/api/db/01_esquema.sql`, que es la fuente
de verdad, con dos diferencias propias de un hosting compartido:

1. **Sin `CREATE DATABASE` ni `USE`.** La base `vallesol_yolo` ya existe y el
   usuario de un hosting no puede crear bases.
2. **Triggers en archivo aparte,** porque necesitan `DELIMITER`, que es una
   instrucción del cliente y no todos los editores la entienden.

## El servidor corre MariaDB 11.4.13

Lo verificado a mano fue contra **MariaDB 10.11.14** y **MySQL 8.0.46**. La
serie 11.4 no se pudo instalar en el entorno de pruebas porque los repositorios
de MariaDB no son alcanzables desde ahí, así que los dos puntos donde 11.4 se
aparta de 10.x se revisaron en la documentación oficial y se cubrieron en los
scripts:

**1. La colación por defecto cambió.** Desde 11.4.2, `utf8mb4` usa
`utf8mb4_uca1400_ai_ci` en lugar de `utf8mb4_general_ci`. Como el esquema ya no
fija ninguna colación, hereda la de la base y cualquiera de las dos le sirve:
ambas ignoran mayúsculas y tildes, que es lo único que necesita para comparar
números de orden y correos. Se añadieron dos comprobaciones: `00_diagnostico.sql`
muestra con qué colación nacerán las tablas, y `99_verificacion.sql` avisa si
quedó más de una entre ellas, porque una mezcla hace fallar el primer JOIN que
compare textos con `Illegal mix of collations`.

**2. `VALUES()` sigue siendo válida** dentro de `INSERT ... ON DUPLICATE KEY
UPDATE` en 11.4. Es la forma que se usa, y a propósito: la alternativa de MySQL
8.0.20 (alias `AS nuevo ... = nuevo.col`) y la que MariaDB prefiere (`VALUE()`)
funcionan cada una en un solo motor, así que ninguna serviría para un script
único.

El primer paso del despliegue es justamente el diagnóstico, que confirma la
versión y la colación reales antes de tocar nada.

## Qué se verificó contra MariaDB de verdad

Se instaló MariaDB 10.11.14 y se probó todo contra ella, en lugar de suponerlo:

| Prueba | Resultado |
|---|---|
| Carga del esquema, triggers y datos de demo | limpia, 13 tablas, 2 vistas, 3 triggers |
| Las 7 reglas que el motor debe hacer cumplir | las bloquea todas (ver abajo) |
| Suite del orquestador | 390 pruebas, 100 % de cobertura |
| Suite del grabador | 279 pruebas, 100 % de cobertura |
| Suite de notificaciones | 144 pruebas, 100 % de cobertura |
| Las tres suites de nuevo en MySQL 8.0.46 | 813 pruebas, sin regresiones |

Las reglas comprobadas una por una, con un intento real de violarlas:

- RN-06: reabrir un evento Confirmado queda bloqueado por `trg_evento_no_reabrir`
- HU-16: modificar o borrar una fila de auditoría, bloqueado por sus dos triggers
- `CHECK`: un aviso marcado como enviada sin fecha de envío, rechazado
- `CHECK`: una tolerancia negativa, rechazada
- `UNIQUE`: un segundo aviso del mismo evento y canal, rechazado
- `ENUM`: una severidad inventada, rechazada

### Lo que esa verificación encontró

El esquema fijaba la colación `utf8mb4_0900_ai_ci`, que **solo existe en MySQL
8**. En MariaDB fallaba en la línea 60 con `ERROR 1273 (HY000): Unknown
collation`, es decir, el despliegue no habría arrancado. Lo mismo pasaba en el
`conftest.py` de las tres suites que usan base de datos.

Ya está corregido en la fuente, no solo en esta copia: ahora no se fija ninguna
colación y se usa la del servidor. MySQL 8 pone `utf8mb4_0900_ai_ci` y MariaDB
pone `utf8mb4_general_ci`, y las dos ignoran mayúsculas y tildes, que es lo
único que el esquema necesita para comparar números de orden y correos.

## Cómo ejecutarlo

### Opción A: PowerShell (lo más rápido)

```powershell
cd C:\proyectos\PI1\quinor\despliegue
.\desplegar.ps1 -ConDemo
```

Pide la contraseña, corre los cinco scripts en orden y deja todo en
`salida_despliegue.txt`. Si prefieres mirar antes de tocar nada:

```powershell
.\desplegar.ps1 -SoloDiagnostico
```

### Opción B: cliente mysql a mano

```bash
mysql -h vallesol.pe -u vallesol_user_yolo -p vallesol_yolo < 00_diagnostico.sql
mysql -h vallesol.pe -u vallesol_user_yolo -p vallesol_yolo < 01_esquema.sql
mysql -h vallesol.pe -u vallesol_user_yolo -p vallesol_yolo < 02_triggers.sql
mysql -h vallesol.pe -u vallesol_user_yolo -p vallesol_yolo < 03_datos_demo.sql
mysql -h vallesol.pe -u vallesol_user_yolo -p vallesol_yolo < 99_verificacion.sql
```

### Opción C: phpMyAdmin del hosting

Entrar a la base `vallesol_yolo`, pestaña **Importar**, y subir los archivos en
ese mismo orden. phpMyAdmin entiende `DELIMITER`, así que `02_triggers.sql`
funciona tal cual.

## Qué tiene que salir

Al final, `99_verificacion.sql` debe mostrar:

```
objeto        cuantos  esperado
tablas        13       13
vistas        2        2
triggers      3        3
tolerancias   3        3
```

Si los triggers salen en 0, el usuario del hosting no tiene el privilegio
`TRIGGER` sobre la base. Hay que pedírselo al proveedor. Sin ellos el sistema
funciona, pero dos reglas dejan de estar protegidas por el motor: que un evento
Confirmado no retroceda (RN-06) y que la auditoría no se pueda alterar (HU-16).

## Lo que NO conviene ejecutar contra este servidor

Las suites de pruebas de Python (`pytest` en `api`, `grabador`, `yolo`, `vlm` y
`notificaciones`) **no deben apuntar a `vallesol_yolo`**. Su `conftest.py` hace
`DROP DATABASE` y `TRUNCATE` en cada prueba, por diseño: están pensadas para una
base desechable. Contra el servidor real borrarían todo lo que acabamos de
cargar.

Si quieres correrlas contra MySQL de verdad, que sea contra otra base, por
ejemplo `vallesol_yolo_test`, y con `TEST_DATABASE_URL` apuntando ahí. Aun así,
necesitan privilegio para crear y borrar bases, que un hosting compartido no
suele dar.

## Después del despliegue

La aplicación se conecta con esta cadena, que va en el `.env` y nunca en el
código (apartado 8):

```
DATABASE_URL=mysql+pymysql://vallesol_user_yolo:LA_CLAVE@vallesol.pe:3306/vallesol_yolo?charset=utf8mb4
```

Si la clave lleva caracteres reservados en una URL, como `[` o `]`, hay que
escribirlos codificados (`%5B` y `%5D`). Con `Yolo900_900` no hace falta.

Si cargaste los datos de demo, los cuatro usuarios entran con la contraseña
`Quinor2026!`. Cámbiala desde el dashboard en cuanto entres: una contraseña que
viaja en un script deja de ser secreta.
