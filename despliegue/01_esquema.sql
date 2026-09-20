-- =============================================================================
-- QUINOR S.A.C. - Alternativa 1 - Despliegue en vallesol.pe
-- Generado el 2026-09-19 desde despacho/api/db/01_esquema.sql
--
-- Servidor de destino: MariaDB 11.4.13. El esquema se probo contra MariaDB
-- 10.11.14 y MySQL 8.0.46 reales; la serie 11.4 no se pudo instalar aqui, asi
-- que los dos puntos donde 11.4 se aparta de 10.x se revisaron en la
-- documentacion y se cubrieron:
--
--   1. Colacion por defecto. Desde 11.4.2, utf8mb4 usa utf8mb4_uca1400_ai_ci
--      en lugar de utf8mb4_general_ci. Este script no fija ninguna colacion, de
--      modo que hereda la de la base y le sirve cualquiera de las dos: las dos
--      ignoran mayusculas y tildes, que es lo unico que el esquema necesita.
--      00_diagnostico.sql y 99_verificacion.sql muestran cual quedo y avisan si
--      hay mas de una entre las tablas.
--   2. VALUES() dentro de ON DUPLICATE KEY UPDATE sigue siendo valida en 11.4.
--      Las alternativas (alias de MySQL 8.0.20, o VALUE() de MariaDB) funcionan
--      en un solo motor cada una.
--
-- Sin CREATE DATABASE ni USE: la base vallesol_yolo ya existe y el usuario del
-- hosting no puede crear bases. Los triggers van en 02_triggers.sql porque
-- necesitan DELIMITER.
--
-- Es idempotente: usa IF NOT EXISTS y se puede volver a ejecutar sin danar
-- datos existentes.
-- =============================================================================

-- =============================================================================
-- QUINOR S.A.C. - Alternativa 1
-- Modelo de datos, seccion 6.5 del Documento Funcional y Tecnico v1.1
--
-- Motor      : MySQL 8.0+ o MariaDB 10.4+ (InnoDB)
-- Juego      : utf8mb4, con la colacion por defecto del servidor
--
-- No se fija la colacion a proposito. utf8mb4_0900_ai_ci solo existe en MySQL 8
-- y dejaba el esquema sin poder cargarse en MariaDB, que es el motor del
-- hosting de QUINOR. Con la del servidor, MySQL 8 pone utf8mb4_0900_ai_ci y
-- MariaDB utf8mb4_general_ci: las dos ignoran mayusculas y tildes, que es lo
-- unico que este esquema necesita para comparar numeros de orden y correos.
-- Precision  : DATETIME(6). Los milisegundos son necesarios para correlacionar
--              la pesada con el fotograma del video (seccion 6.5). Esa precision
--              depende de que servidor, bascula y camaras esten sincronizados
--              por NTP; sin eso el campo no sirve.
--
-- Ejecucion:
--   docker compose exec -T mysql mysql -u root -p"$MYSQL_ROOT_PASSWORD" quinor < db/01_esquema.sql
--
-- El script es idempotente: usa IF NOT EXISTS y puede reejecutarse sin danar
-- datos existentes.
--
-- ORGANIZACION
--   Parte 1  Tablas del Sprint 1   (HU-01, HU-02, HU-04, HU-15)
--   Parte 2  Tablas de sprints posteriores
--   Parte 3  Vistas de apoyo
--   Parte 4  Triggers de reglas de negocio
--   Parte 5  Datos iniciales
--   Parte 6  Privilegios (ejecutar como root, opcional)
--
-- Para levantar unicamente lo que el Sprint 1 necesita, ejecutar las partes
-- 1, 3, 4, 5 y 6 y omitir la parte 2. Las vistas de la parte 3 que dependen de
-- la tabla evento tambien quedarian fuera; estan marcadas.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- CONVENCION DE VALORES DE ENUM
--
-- La base guarda codigos tecnicos en minuscula, sin tildes ni espacios. La
-- etiqueta que ve el usuario vive en la aplicacion. Se decidio asi porque un
-- ENUM con tildes solo se puede escribir desde una conexion en utf8mb4: un
-- cliente en latin1 trunca el valor en silencio. Ademas, cambiar la redaccion
-- del documento dejaria de ser un ALTER TABLE.
--
--   evento.estado            seccion 5.3
--     pendiente              Pendiente
--     pendiente_analisis     Pendiente de analisis
--     en_revision            En revision
--     confirmado             Confirmado
--     falso_positivo         Falso positivo
--     sin_clip               Sin clip
--
--   evento.severidad         RN-04
--     baja / media / alta    Baja / Media / Alta
--
--   usuario.rol              seccion 4
--     administrador / supervisor / consulta
--
--   salud_componente.estado  HU-18
--     ok / advertencia / error
--
-- Pendiente reflejar esta equivalencia en la seccion 5.3 del documento.
-- -----------------------------------------------------------------------------

SET NAMES utf8mb4;
SET SESSION sql_mode = 'STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION';


-- #############################################################################
-- PARTE 1 - TABLAS DEL SPRINT 1
-- #############################################################################

-- -----------------------------------------------------------------------------
-- usuario  (HU-15)
-- Los usuarios no se eliminan, se desactivan: la evidencia de auditoria debe
-- seguir apuntando a una persona identificable. De ahi el campo activo y el
-- ON DELETE RESTRICT en todas las claves foraneas que lo referencian.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usuario (
  id            INT UNSIGNED    NOT NULL AUTO_INCREMENT,
  nombre        VARCHAR(120)    NOT NULL,
  correo        VARCHAR(180)    NOT NULL,
  rol           ENUM('administrador','supervisor','consulta') NOT NULL,
  hash_password VARCHAR(255)    NOT NULL
                COMMENT 'Hash bcrypt. Ocupa 60 caracteres; el margen permite cambiar de algoritmo sin migrar la columna.',
  activo        BOOLEAN         NOT NULL DEFAULT TRUE,
  PRIMARY KEY (id),
  UNIQUE KEY uq_usuario_correo (correo),
  KEY ix_usuario_rol_activo (rol, activo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Usuarios del dashboard. Roles segun la seccion 4.';


-- -----------------------------------------------------------------------------
-- api_token  (HU-15)
-- Autenticacion por token opaco. El token en claro se muestra una sola vez al
-- crearlo y nunca se persiste: en base de datos solo vive su SHA-256. Asi, quien
-- obtenga acceso de lectura a esta tabla no puede usar ningun token.
-- La revocacion es inmediata y queda registrada con quien la ejecuto.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_token (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  usuario_id    INT UNSIGNED    NOT NULL,
  token_hash    CHAR(64)        NOT NULL
                COMMENT 'SHA-256 hexadecimal del token generado con secrets.token_urlsafe(32).',
  nombre        VARCHAR(120)    NOT NULL
                COMMENT 'Etiqueta legible para el usuario, por ejemplo "Laptop de rampa 1".',
  creado_en     DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  expira_en     DATETIME(6)     NOT NULL,
  ultimo_uso_en DATETIME(6)     NULL,
  revocado_en   DATETIME(6)     NULL,
  revocado_por  INT UNSIGNED    NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_api_token_hash (token_hash),
  KEY ix_api_token_usuario (usuario_id, revocado_en),
  KEY ix_api_token_expira (expira_en),
  CONSTRAINT fk_api_token_usuario
    FOREIGN KEY (usuario_id)   REFERENCES usuario (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_api_token_revocador
    FOREIGN KEY (revocado_por) REFERENCES usuario (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_api_token_revocacion CHECK (
    (revocado_en IS NULL     AND revocado_por IS NULL) OR
    (revocado_en IS NOT NULL AND revocado_por IS NOT NULL)
  ),
  CONSTRAINT ck_api_token_vigencia CHECK (expira_en > creado_en)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Tokens de acceso a la API. Solo se almacena el hash, nunca el token.';


-- -----------------------------------------------------------------------------
-- orden_despacho  (HU-02)
-- Copia local de la orden obtenida del ERP. sincronizado_en permite saber si la
-- copia sigue vigente antes de reconsultar al ERP.
--
-- NOTA: sincronizado_en no figura en la lista de campos de la seccion 6.5. Se
-- agrega porque HU-02 exige cachear la orden y sin marca de tiempo la cache no
-- tiene criterio de expiracion. Pendiente reflejarlo en el documento.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orden_despacho (
  id               INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  numero_orden     VARCHAR(40)   NOT NULL,
  cliente          VARCHAR(180)  NOT NULL,
  producto         VARCHAR(120)  NOT NULL,
  peso_esperado_kg DECIMAL(10,2) NOT NULL,
  sacos_esperados  INT UNSIGNED  NOT NULL,
  fecha            DATE          NOT NULL,
  sincronizado_en  DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                   ON UPDATE CURRENT_TIMESTAMP(6)
                   COMMENT 'Momento de la ultima lectura desde el ERP.',
  PRIMARY KEY (id),
  UNIQUE KEY uq_orden_numero (numero_orden),
  KEY ix_orden_fecha (fecha),
  KEY ix_orden_producto (producto),
  CONSTRAINT ck_orden_peso  CHECK (peso_esperado_kg > 0),
  CONSTRAINT ck_orden_sacos CHECK (sacos_esperados  > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Copia local de la orden de despacho del ERP/WMS.';


-- -----------------------------------------------------------------------------
-- pesada  (HU-01)
-- peso_real_kg con dos decimales, tal como exige el criterio 3 de HU-01.
-- fecha_hora en DATETIME(6): es el campo que se cruza con el video.
--
-- bascula_id es una cadena y no una clave foranea porque la seccion 6.5 no
-- define una tabla de basculas. Al incorporar la segunda bascula prevista en el
-- RNF-04, conviene evaluar convertirlo en catalogo.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pesada (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  orden_id     INT UNSIGNED    NOT NULL,
  bascula_id   VARCHAR(20)     NOT NULL,
  peso_real_kg DECIMAL(10,2)   NOT NULL,
  fecha_hora   DATETIME(6)     NOT NULL
               COMMENT 'Instante del peso estable. Se correlaciona con el buffer de video.',
  -- HU-06: el criterio 1 mide la ventana del clip desde el inicio de la carga,
  -- no desde la pesada. Queda en NULL cuando nadie marco el inicio; en ese caso
  -- el recorte usa solo los 5 minutos previos al cierre.
  inicio_carga DATETIME(6)     NULL
               COMMENT 'Momento en que el camion entro a la rampa. Origen de la ventana del clip.',
  origen       ENUM('bascula','manual') NOT NULL DEFAULT 'bascula',
  PRIMARY KEY (id),
  KEY ix_pesada_orden (orden_id),
  KEY ix_pesada_fecha (fecha_hora),
  KEY ix_pesada_bascula (bascula_id, fecha_hora),
  CONSTRAINT fk_pesada_orden
    FOREIGN KEY (orden_id) REFERENCES orden_despacho (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_pesada_peso CHECK (peso_real_kg >= 0),
  CONSTRAINT ck_pesada_ventana CHECK (inicio_carga IS NULL OR inicio_carga <= fecha_hora)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Registro de cada pesada capturada de la bascula.';


-- -----------------------------------------------------------------------------
-- carga  (HU-06)
-- Marca de inicio de carga. El apartado 5.2 dice que "el sistema marca el inicio
-- de la ventana de carga", y hasta HU-06 nadie lo hacia: la ventana del clip
-- empezaba donde se pudiera. Aqui queda registrada cuando el camion entra a la
-- rampa y la consume la pesada que cierra esa carga.
--
-- Una orden no puede tener dos cargas abiertas a la vez, y eso lo garantiza el
-- indice unico parcial emulado con la columna generada, igual que en
-- modelo_version.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS carga (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  orden_id     INT UNSIGNED    NOT NULL,
  bascula_id   VARCHAR(20)     NOT NULL,
  inicio       DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  consumida_en DATETIME(6)     NULL
               COMMENT 'Momento en que una pesada cerro esta carga. NULL mientras sigue abierta.',
  pesada_id    BIGINT UNSIGNED NULL,
  usuario_id   INT UNSIGNED    NULL,
  -- Vale el id de la orden mientras la carga sigue abierta y NULL cuando se
  -- cierra. Como MySQL ignora los NULL en un indice unico, esto obliga a que
  -- haya a lo sumo una carga abierta por orden.
  orden_abierta INT UNSIGNED
                GENERATED ALWAYS AS (IF(consumida_en IS NULL, orden_id, NULL)) STORED,
  PRIMARY KEY (id),
  UNIQUE KEY uq_carga_abierta (orden_abierta),
  KEY ix_carga_orden (orden_id, inicio),
  CONSTRAINT fk_carga_orden
    FOREIGN KEY (orden_id)   REFERENCES orden_despacho (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_carga_pesada
    FOREIGN KEY (pesada_id)  REFERENCES pesada (id)         ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_carga_usuario
    FOREIGN KEY (usuario_id) REFERENCES usuario (id)        ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_carga_cierre CHECK (
    (consumida_en IS NULL     AND pesada_id IS NULL) OR
    (consumida_en IS NOT NULL AND pesada_id IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Marca de inicio de carga. Da origen a la ventana del clip de HU-06.';


-- -----------------------------------------------------------------------------
-- configuracion  (HU-04)
-- Tolerancia por tipo de producto. La RN-01 indica que se aplica la mas
-- restrictiva entre los kg y el porcentaje, decision que resuelve la aplicacion.
-- canales_por_severidad guarda el mapa de la RN-04 y HU-10.
--
-- Cambio de alcance del 18/09/2026: HU-10 quedo solo con correo. Slack sale
-- porque se esta evaluando Teams, y el SMS sale con el. La columna se conserva
-- porque esos canales volveran en su propia historia y el mapa por producto es
-- exactamente el sitio donde se declararan; hoy los tres niveles dicen
-- ["correo"], y lo que distingue a una severidad de otra son los destinatarios
-- y la urgencia, no el canal.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS configuracion (
  id                    INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  producto              VARCHAR(120)  NOT NULL,
  tolerancia_kg         DECIMAL(8,2)  NOT NULL,
  tolerancia_pct        DECIMAL(5,2)  NOT NULL,
  canales_por_severidad JSON          NOT NULL
                        COMMENT 'Canales por severidad. Hoy solo correo: {"alta":["correo"],"media":["correo"],"baja":["correo"]}. Slack, Teams y SMS entran con la historia que defina ese canal.',
  actualizado_por       INT UNSIGNED  NULL,
  fecha                 DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                        ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_configuracion_producto (producto),
  KEY ix_configuracion_usuario (actualizado_por),
  CONSTRAINT fk_configuracion_usuario
    FOREIGN KEY (actualizado_por) REFERENCES usuario (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_configuracion_kg  CHECK (tolerancia_kg  >= 0),
  CONSTRAINT ck_configuracion_pct CHECK (tolerancia_pct >= 0 AND tolerancia_pct <= 100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Parametros ajustables por producto. Solo el rol Administrador la edita.';


-- -----------------------------------------------------------------------------
-- auditoria  (HU-16)
-- Tabla de solo insercion. Los triggers de la parte 4 bloquean UPDATE y DELETE
-- a nivel de motor, y la parte 6 retira esos privilegios al usuario de la
-- aplicacion. Las dos capas se refuerzan: el trigger protege incluso frente a
-- una conexion con privilegios de mas.
--
-- usuario_id admite NULL para las acciones ejecutadas por el sistema, por
-- ejemplo la creacion automatica de un evento.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS auditoria (
  id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entidad    VARCHAR(60)     NOT NULL COMMENT 'Nombre de la tabla afectada.',
  entidad_id BIGINT UNSIGNED NULL,
  accion     VARCHAR(60)     NOT NULL COMMENT 'Por ejemplo: cambio_estado, revocar_token, editar_tolerancia.',
  usuario_id INT UNSIGNED    NULL     COMMENT 'NULL cuando la accion es del sistema.',
  detalle    JSON            NULL,
  fecha      DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY ix_auditoria_entidad (entidad, entidad_id, fecha),
  KEY ix_auditoria_usuario (usuario_id, fecha),
  KEY ix_auditoria_fecha (fecha),
  CONSTRAINT fk_auditoria_usuario
    FOREIGN KEY (usuario_id) REFERENCES usuario (id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Registro inmutable de acciones. Solo insercion.';


-- -----------------------------------------------------------------------------
-- salud_componente  (HU-01, HU-05, HU-18)
-- Historico de verificaciones, no estado actual. La vista v_salud_actual de la
-- parte 3 devuelve la ultima lectura de cada componente, que es lo que HU-18
-- necesita mostrar.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS salud_componente (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  componente    VARCHAR(60)     NOT NULL COMMENT 'bascula, camara-01, erp, cola, yolo, vlm.',
  estado        ENUM('ok','advertencia','error') NOT NULL,
  mensaje       VARCHAR(500)    NULL,
  verificado_en DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY ix_salud_componente (componente, verificado_en),
  KEY ix_salud_estado (estado, verificado_en)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Historico de verificaciones de bascula, camaras, cola y servicios de IA.';


-- #############################################################################
-- PARTE 2 - TABLAS DE SPRINTS POSTERIORES
-- Se crean vacias. Omitir esta parte no afecta al Sprint 1.
-- #############################################################################

-- -----------------------------------------------------------------------------
-- evento  (HU-03 en adelante)
-- Una pesada genera como maximo un evento, de ahi la clave unica sobre
-- pesada_id: evita duplicados si el orquestador reprocesa la misma pesada.
--
-- Las columnas que llegan en sprints posteriores nacen NULL:
--   sacos_contados      HU-07, Sprint 3
--   diferencia_sacos    HU-07, Sprint 3
--   personas_detectadas HU-08, Sprint 4
--   personal_anomalo    HU-08, Sprint 4
--   severidad           HU-09, Sprint 4
--   descripcion_ia      HU-09, Sprint 4
--   fotogramas_clave    HU-09, Sprint 4
--   clip_url            HU-06, Sprint 2
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evento (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  pesada_id           BIGINT UNSIGNED NOT NULL,
  diferencia_kg       DECIMAL(10,2)   NOT NULL COMMENT 'peso_real - peso_esperado. Negativa indica faltante.',
  diferencia_pct      DECIMAL(6,2)    NOT NULL,
  sacos_contados      INT UNSIGNED    NULL COMMENT 'Sacos que cruzaron la linea de carga en el clip (HU-07).',
  -- Criterio 3 de HU-07: la diferencia se guarda, no se recalcula al mirarla.
  -- Con signo, igual que diferencia_kg: negativa indica faltante. Se guarda
  -- aunque sea derivable de la orden porque la orden se resincroniza desde el
  -- ERP y un cambio posterior de sacos_esperados no debe reescribir la historia
  -- de un evento ya investigado. Es ademas lo que sostiene el filtro por
  -- diferencia de HU-11 sin unir con orden_despacho.
  diferencia_sacos    INT             NULL COMMENT 'sacos_contados - orden.sacos_esperados. Negativa indica faltante.',
  personas_detectadas INT UNSIGNED    NULL COMMENT 'Personas que estuvieron en la zona de carga durante el clip (HU-08).',
  -- HU-08 y RN-03. NULL mientras el clip no se ha analizado, que no es lo mismo
  -- que 0. Es la condicion que HU-09 consultara para decidir si invoca al modelo
  -- de vision-lenguaje, junto con la diferencia de sacos. El detalle de por que
  -- se marco (cuantos, cuanto tiempo, si hubo carga) vive en auditoria: aqui
  -- solo hace falta lo que se filtra.
  personal_anomalo    TINYINT(1)      NULL,
  -- HU-09. La severidad del evento sale de la RN-04, que es una regla escrita
  -- con umbrales exactos: una alerta de madrugada (HU-10) y el orden de la cola
  -- de revision (HU-11) no pueden depender de la temperatura de un modelo. La
  -- del modelo se guarda dentro de descripcion_ia como severidad_ia, y de
  -- comparar las dos sale la concordancia semanal del apartado 9.2.
  severidad           ENUM('baja','media','alta') NULL,
  descripcion_ia      JSON            NULL COMMENT 'Respuesta del modelo de vision-lenguaje: descripcion, severidad_ia, evidencia y con que modelo se obtuvo.',
  -- HU-09 y criterio 3 de HU-12: los fotogramas que explican la carga, ya en
  -- MinIO. Lista de {url, motivo, segundo, fotograma}. Van aqui y no en una
  -- tabla propia porque son como mucho cuatro por evento y siempre se leen
  -- juntos: una tabla para eso seria una union en cada detalle sin ganar nada.
  fotogramas_clave    JSON            NULL,
  estado              ENUM('pendiente','pendiente_analisis','en_revision','confirmado','falso_positivo','sin_clip')
                      NOT NULL DEFAULT 'pendiente',
  clip_url            VARCHAR(500)    NULL COMMENT 'Ruta del clip en MinIO.',
  creado_en           DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_evento_pesada (pesada_id),
  -- Indice que sostiene el filtro por defecto de HU-11 (Pendientes de los
  -- ultimos 7 dias) dentro de los 2 s que exige su criterio 2.
  KEY ix_evento_estado_creado (estado, creado_en),
  KEY ix_evento_severidad (severidad, creado_en),
  KEY ix_evento_creado (creado_en),
  -- Una diferencia sin conteo no significa nada: de donde habria salido.
  CONSTRAINT ck_evento_conteo CHECK (
    diferencia_sacos IS NULL OR sacos_contados IS NOT NULL),
  CONSTRAINT fk_evento_pesada
    FOREIGN KEY (pesada_id) REFERENCES pesada (id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Evento de discrepancia y resultado del analisis de IA.';


-- -----------------------------------------------------------------------------
-- persona_en_evento  (HU-08)
-- "Se detecta y sigue a cada persona con un ID temporal durante el clip" y "se
-- registra cuantas personas estuvieron en zona y el tiempo de permanencia".
--
-- Una fila por persona vista en la zona de carga durante el clip del evento.
--
-- Lo que esta tabla NO tiene es tan importante como lo que tiene. No hay
-- fotografia, ni recorte de imagen, ni descriptor facial, ni nombre, ni codigo
-- de empleado, ni nada que permita reconocer a la misma persona en otro clip:
-- la RN-08 y el apartado 8 prohiben la identificacion facial y los datos
-- biometricos, y la forma de cumplirlo es no tener nada que identificar.
--
-- id_temporal es el numero que asigno el rastreador dentro de ese video y solo
-- dentro de ese video. El 1 de un evento no tiene ninguna relacion con el 1 de
-- otro. Por eso la clave unica es (evento_id, id_temporal) y no id_temporal
-- solo: no es una persona, es una presencia en un clip.
--
-- Consecuencia asumida: si un operario sale del cuadro y vuelve, el rastreador
-- le da otro numero y aqui aparecen dos filas. Es el precio de no identificar a
-- nadie.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS persona_en_evento (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  evento_id        BIGINT UNSIGNED NOT NULL,
  id_temporal      INT UNSIGNED    NOT NULL
                   COMMENT 'Identificador del rastreador. Solo vale dentro de este clip.',
  segundos_en_zona DECIMAL(8,2)    NOT NULL
                   COMMENT 'Tiempo de permanencia en la zona de carga.',
  primer_fotograma INT UNSIGNED    NOT NULL,
  ultimo_fotograma INT UNSIGNED    NOT NULL,
  creado_en        DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  -- Reanalizar el mismo clip (HU-19 cambiara el modelo) no debe duplicar filas.
  UNIQUE KEY uq_persona_evento (evento_id, id_temporal),
  KEY ix_persona_permanencia (evento_id, segundos_en_zona),
  CONSTRAINT fk_persona_evento
    FOREIGN KEY (evento_id) REFERENCES evento (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_persona_segundos CHECK (segundos_en_zona >= 0),
  CONSTRAINT ck_persona_fotogramas CHECK (ultimo_fotograma >= primer_fotograma)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Presencia de personas en la zona de carga durante el clip (HU-08). Sin datos biometricos: RN-08.';


-- -----------------------------------------------------------------------------
-- notificacion  (HU-10)
-- "La notificacion se envia por correo en los tres niveles" y "se envia en
-- menos de 60 s tras el analisis".
--
-- Una fila por aviso. Existe por tres razones concretas:
--
--   1. No avisar dos veces del mismo evento. El grabador sondea, y sin una
--      marca de que ya se envio, cada vuelta seria otro correo. La clave unica
--      sobre (evento_id, canal) lo impide en la base y no solo en el codigo.
--   2. Medir el criterio 3. segundos_desde_analisis guarda cuanto paso desde
--      que la severidad quedo escrita hasta que el correo salio; sin esa cifra,
--      "menos de 60 s" no se puede comprobar en planta, solo suponer.
--   3. Que un aviso que no salio se vea. Un evento grave cuyo correo fallo es
--      peor que uno sin analizar: nadie lo esta esperando.
--
-- destinatarios guarda las direcciones a las que se envio, no los usuarios:
-- un correo que salio salio a esas direcciones, y si manana alguien cambia su
-- correo o se da de baja, el registro tiene que seguir diciendo la verdad.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notificacion (
  id                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  evento_id               BIGINT UNSIGNED NOT NULL,
  canal                   ENUM('correo') NOT NULL DEFAULT 'correo'
                          COMMENT 'Solo correo desde el cambio de alcance del 18/09/2026. Slack, Teams y SMS entran con su historia.',
  severidad               ENUM('baja','media','alta') NOT NULL,
  destinatarios           JSON            NOT NULL
                          COMMENT 'Direcciones a las que se envio, tal como estaban en ese momento.',
  asunto                  VARCHAR(300)    NOT NULL,
  estado                  ENUM('enviada','fallida') NOT NULL,
  intentos                TINYINT UNSIGNED NOT NULL DEFAULT 1,
  error                   VARCHAR(500)    NULL,
  segundos_desde_analisis DECIMAL(8,2)    NULL
                          COMMENT 'Criterio 3: menos de 60 s. NULL si no se pudo medir.',
  enviada_en              DATETIME(6)     NULL,
  creado_en               DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  -- Un aviso por evento y canal. Es lo que impide que el sondeo del grabador
  -- mande el mismo correo en cada vuelta.
  UNIQUE KEY uq_notificacion_evento_canal (evento_id, canal),
  KEY ix_notificacion_estado (estado, creado_en),
  KEY ix_notificacion_severidad (severidad, creado_en),
  CONSTRAINT fk_notificacion_evento
    FOREIGN KEY (evento_id) REFERENCES evento (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_notificacion_envio CHECK (
    (estado = 'enviada' AND enviada_en IS NOT NULL) OR
    (estado = 'fallida' AND enviada_en IS NULL)),
  CONSTRAINT ck_notificacion_intentos CHECK (intentos >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Avisos enviados por cada evento (HU-10). Solo correo; los demas canales entran con su historia.';


-- -----------------------------------------------------------------------------
-- veredicto  (HU-13)
-- El criterio 1 de HU-13 exige un comentario de al menos 10 caracteres. La
-- restriccion CHECK lo garantiza aunque el formulario falle.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS veredicto (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  evento_id    BIGINT UNSIGNED NOT NULL,
  usuario_id   INT UNSIGNED    NOT NULL,
  estado_nuevo ENUM('en_revision','confirmado','falso_positivo') NOT NULL,
  comentario   VARCHAR(1000)   NOT NULL,
  fecha        DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY ix_veredicto_evento (evento_id, fecha),
  KEY ix_veredicto_usuario (usuario_id, fecha),
  CONSTRAINT fk_veredicto_evento
    FOREIGN KEY (evento_id)  REFERENCES evento  (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT fk_veredicto_usuario
    FOREIGN KEY (usuario_id) REFERENCES usuario (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_veredicto_comentario CHECK (CHAR_LENGTH(TRIM(comentario)) >= 10)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Decision del supervisor sobre el evento. Alimenta la mejora continua.';


-- -----------------------------------------------------------------------------
-- modelo_version  (HU-19)
-- Historial de versiones del modelo YOLO. Solo una puede estar activa, lo que
-- garantiza el indice unico parcial emulado con la columna generada.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS modelo_version (
  id           INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  nombre       VARCHAR(80)   NOT NULL,
  version      VARCHAR(40)   NOT NULL,
  metrica_map  DECIMAL(6,4)  NULL COMMENT 'mAP en el set de validacion fijo.',
  error_conteo DECIMAL(6,4)  NULL COMMENT 'Error medio de conteo de sacos por carga.',
  ruta_pesos   VARCHAR(500)  NOT NULL COMMENT 'Ruta del archivo de pesos en MinIO.',
  activo       BOOLEAN       NOT NULL DEFAULT FALSE,
  fecha        DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  -- Columna generada que vale 1 solo cuando el modelo esta activo y NULL en el
  -- resto. Como MySQL ignora los NULL en un indice unico, esto obliga a que
  -- exista a lo sumo un modelo activo.
  unico_activo TINYINT UNSIGNED
               GENERATED ALWAYS AS (IF(activo, 1, NULL)) STORED,
  PRIMARY KEY (id),
  UNIQUE KEY uq_modelo_nombre_version (nombre, version),
  UNIQUE KEY uq_modelo_unico_activo (unico_activo),
  KEY ix_modelo_fecha (fecha)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Historial de versiones del modelo YOLO con posibilidad de reversion.';


-- #############################################################################
-- PARTE 3 - VISTAS DE APOYO
-- #############################################################################

-- Ultimo estado conocido de cada componente. Es lo que muestra el panel de
-- salud de HU-18 y lo que consulta GET /salud. Disponible desde el Sprint 1.
CREATE OR REPLACE VIEW v_salud_actual AS
SELECT s.componente, s.estado, s.mensaje, s.verificado_en
FROM (
  SELECT
    componente, estado, mensaje, verificado_en,
    ROW_NUMBER() OVER (PARTITION BY componente ORDER BY verificado_en DESC, id DESC) AS rn
  FROM salud_componente
) AS s
WHERE s.rn = 1;

-- Listado de eventos para HU-11. Requiere la parte 2.
-- Omitir esta vista si solo se ejecuta el Sprint 1.
CREATE OR REPLACE VIEW v_evento_dashboard AS
SELECT
  e.id                 AS evento_id,
  e.creado_en,
  o.numero_orden,
  o.cliente,
  o.producto,
  o.peso_esperado_kg,
  p.peso_real_kg,
  p.fecha_hora         AS pesada_fecha_hora,
  p.bascula_id,
  e.diferencia_kg,
  e.diferencia_pct,
  o.sacos_esperados,
  e.sacos_contados,
  e.personas_detectadas,
  e.severidad,
  e.estado,
  e.clip_url
FROM evento e
JOIN pesada p          ON p.id = e.pesada_id
JOIN orden_despacho o  ON o.id = p.orden_id;





-- #############################################################################
-- PARTE 5 - DATOS INICIALES
--
-- No se crea ningun usuario aqui. Una contrasena escrita en un script que se
-- versiona contradice la seccion 8. El administrador inicial lo crea la
-- aplicacion al arrancar, a partir de ADMIN_EMAIL y ADMIN_PASSWORD del archivo
-- .env, hasheando con bcrypt.
-- #############################################################################

-- Tolerancias por producto. Los tres productos coinciden con el catalogo del
-- stub erp-mock para que el Sprint 1 tenga datos coherentes de extremo a extremo.
-- 50.00 kg equivale a un saco completo: por debajo de eso la diferencia es ruido
-- de bascula. El porcentaje solo se vuelve mas restrictivo que los kg en ordenes
-- menores a 10 000 kg, que es justo donde interesa afinar.
INSERT INTO configuracion (producto, tolerancia_kg, tolerancia_pct, canales_por_severidad)
VALUES
  ('Quinua blanca organica',     50.00, 0.50, JSON_OBJECT('alta', JSON_ARRAY('correo'), 'media', JSON_ARRAY('correo'), 'baja', JSON_ARRAY('correo'))),
  ('Quinua roja organica',       50.00, 0.50, JSON_OBJECT('alta', JSON_ARRAY('correo'), 'media', JSON_ARRAY('correo'), 'baja', JSON_ARRAY('correo'))),
  ('Quinua negra convencional',  50.00, 0.75, JSON_OBJECT('alta', JSON_ARRAY('correo'), 'media', JSON_ARRAY('correo'), 'baja', JSON_ARRAY('correo')))
-- VALUES() y no la sintaxis de alias de MySQL 8.0.20 (`AS nuevo ... = nuevo.col`)
-- ni VALUE(), que es la forma que MariaDB prefiere desde 10.3: cada una funciona
-- en un solo motor. VALUES() dentro de ON DUPLICATE KEY UPDATE sigue siendo
-- valida en los dos, incluida la serie 11.4 de MariaDB, y es lo unico que
-- permite un solo script para ambos.
ON DUPLICATE KEY UPDATE producto = VALUES(producto);


-- #############################################################################
-- PARTE 6 - PRIVILEGIOS
--
-- Ejecutar como root. Refuerza a nivel de motor lo que exige HU-16: la
-- aplicacion puede insertar en auditoria pero no modificarla ni borrarla.
-- Sustituir 'quinor' por el valor de MYSQL_USER si se cambio en .env.
-- #############################################################################

-- REVOKE UPDATE, DELETE ON quinor.auditoria FROM 'quinor'@'%';
-- FLUSH PRIVILEGES;


-- =============================================================================
-- Verificacion rapida tras la ejecucion:
--   SHOW TABLES;
--   SELECT producto, tolerancia_kg, tolerancia_pct FROM configuracion;
--   SELECT TRIGGER_NAME, EVENT_MANIPULATION, EVENT_OBJECT_TABLE
--     FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = DATABASE();
-- =============================================================================
