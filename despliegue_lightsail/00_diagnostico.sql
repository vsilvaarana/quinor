-- =============================================================================
-- QUINOR S.A.C. - Diagnostico previo al despliegue
--
-- Ejecutar ESTO PRIMERO y guardar la salida. No modifica nada: solo lee.
-- Responde las tres preguntas que deciden si el resto del despliegue funciona:
--   1. Que motor y que version corre el hosting.
--   2. Con que usuario y privilegios entramos.
--   3. Si la base ya tiene algo dentro, para no pisar nada.
-- =============================================================================

SELECT
  VERSION()        AS motor_y_version,
  DATABASE()       AS base_actual,
  CURRENT_USER()   AS usuario_efectivo,
  USER()           AS usuario_conectado,
  @@character_set_database AS juego_de_caracteres,
  @@collation_database     AS colacion,
  @@sql_mode       AS sql_mode,
  @@time_zone      AS zona_horaria;

-- Con que colacion naceran las tablas. Importa por la serie 11.4: desde
-- 11.4.2 la colacion por defecto de utf8mb4 pasa a ser utf8mb4_uca1400_ai_ci,
-- mientras que en 10.x era utf8mb4_general_ci. El esquema no fija ninguna, asi
-- que hereda la de la base y cualquiera de las dos le sirve. Lo que si conviene
-- es saber cual, y que sea una sola: mezclar colaciones entre tablas produce
-- "Illegal mix of collations" en el primer JOIN que compare textos.
SELECT
  @@collation_database AS colacion_que_heredaran_las_tablas,
  @@collation_server   AS colacion_del_servidor,
  CASE WHEN @@collation_database = @@collation_server
       THEN 'coinciden'
       ELSE 'DIFIEREN: las tablas tomaran la de la base' END AS observacion;

-- Privilegios. Para el despliegue hacen falta CREATE, ALTER, INDEX, CREATE VIEW
-- y TRIGGER sobre esta base. Si falta TRIGGER, el paso 02 fallara y hay que
-- pedirselo al proveedor del hosting.
SHOW GRANTS FOR CURRENT_USER();

-- Que hay ya en la base. Si esto devuelve filas, avisame antes de seguir:
-- el esquema es idempotente y no borra nada, pero conviene saber con que
-- convive.
SELECT TABLE_NAME, TABLE_TYPE, TABLE_ROWS, ENGINE, TABLE_COLLATION
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
ORDER BY TABLE_NAME;

-- Espacio ocupado, por si el plan del hosting tiene cuota.
SELECT
  IFNULL(ROUND(SUM(DATA_LENGTH + INDEX_LENGTH) / 1024 / 1024, 2), 0) AS megas_usados
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE();

-- -----------------------------------------------------------------------------
-- Comprobaciones propias de AWS Lightsail (MySQL 8 administrado)
-- -----------------------------------------------------------------------------
-- 1. Triggers. En Lightsail el usuario maestro no tiene SUPER y el binlog esta
--    activo (lo exigen las copias automaticas). Con log_bin_trust_function_creators
--    en 0, el paso 02 falla con ERROR 1419. Tiene que salir 1; si sale 0, correr
--    antes configurar_lightsail.ps1.
-- 2. Zona horaria. Lightsail trabaja en UTC. El instalador fija la sesion en
--    -05:00 (Lima, sin horario de verano) para que las fechas que pone el script
--    coincidan con las que escribe la aplicacion. Aqui debe salir -05:00.
-- 3. SSL. Si la conexion va cifrada, 'cifrado' muestra el algoritmo.
SELECT
  @@log_bin                         AS binlog_activo,
  @@log_bin_trust_function_creators AS triggers_permitidos,
  CASE WHEN @@log_bin = 1 AND @@log_bin_trust_function_creators = 0
       THEN 'FALTA: correr configurar_lightsail.ps1 antes del paso 02'
       ELSE 'ok' END                AS diagnostico_triggers,
  @@global.time_zone                AS zona_del_servidor,
  @@session.time_zone               AS zona_de_esta_sesion,
  NOW()                             AS hora_que_vera_el_script;

SHOW SESSION STATUS LIKE 'Ssl_cipher';
