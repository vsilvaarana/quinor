-- =============================================================================
-- QUINOR S.A.C. - Verificacion del despliegue
--
-- Ejecutar al final y pegarme la salida. No modifica nada.
-- Lo que tiene que salir si todo fue bien:
--   tablas = 13, vistas = 2, triggers = 3, tolerancias = 3
-- =============================================================================

SELECT 'tablas' AS objeto, COUNT(*) AS cuantos, 13 AS esperado
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'
UNION ALL
SELECT 'vistas', COUNT(*), 2
FROM information_schema.VIEWS WHERE TABLE_SCHEMA = DATABASE()
UNION ALL
SELECT 'triggers', COUNT(*), 3
FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = DATABASE()
UNION ALL
SELECT 'tolerancias', COUNT(*), 3 FROM configuracion;

-- Las tablas, una por una, con su motor y su colacion.
SELECT TABLE_NAME, ENGINE, TABLE_COLLATION
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'
ORDER BY TABLE_NAME;

-- Todas las tablas deben compartir colacion. Si esto devuelve mas de una fila,
-- hay una mezcla, y el primer JOIN que compare un VARCHAR entre esas dos tablas
-- fallara con "Illegal mix of collations". Pasa cuando la base cambia de
-- colacion por defecto entre una creacion de tablas y otra, que es justo lo que
-- puede ocurrir al actualizar de la serie 10.x a la 11.4.
SELECT TABLE_COLLATION AS colacion, COUNT(*) AS tablas
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'
GROUP BY TABLE_COLLATION;

-- Los tres triggers que sostienen la RN-06 y HU-16.
SELECT TRIGGER_NAME, EVENT_MANIPULATION, EVENT_OBJECT_TABLE
FROM information_schema.TRIGGERS
WHERE TRIGGER_SCHEMA = DATABASE()
ORDER BY TRIGGER_NAME;

-- Si se cargaron los datos de demo, esto los resume.
SELECT
  (SELECT COUNT(*) FROM usuario)          AS usuarios,
  (SELECT COUNT(*) FROM orden_despacho)   AS ordenes,
  (SELECT COUNT(*) FROM pesada)           AS pesadas,
  (SELECT COUNT(*) FROM evento)           AS eventos,
  (SELECT COUNT(*) FROM persona_en_evento) AS personas,
  (SELECT COUNT(*) FROM notificacion)     AS avisos;

-- La vista del dashboard, que es lo que vera HU-11.
SELECT evento_id, numero_orden, cliente, diferencia_kg, sacos_esperados,
       sacos_contados, severidad, estado
FROM v_evento_dashboard
ORDER BY evento_id;
