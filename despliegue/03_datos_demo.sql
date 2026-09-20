-- =============================================================================
-- QUINOR S.A.C. - Datos de demostracion
--
-- Opcional. Deja la base con algo que mirar desde el primer minuto: usuarios con
-- sus roles, una orden, su pesada, y un evento ya analizado y notificado, que es
-- el recorrido completo de HU-01 a HU-10.
--
-- Se puede ejecutar mas de una vez: cada bloque comprueba antes si su fila ya
-- existe.
--
-- CONTRASENA DE LOS CUATRO USUARIOS: Quinor2026!
-- Los hashes son bcrypt de verdad, generados con la misma funcion que usa la
-- aplicacion (HU-15, criterio 3). Cambiala en el dashboard despues de la primera
-- entrada: una contrasena que viaja en un script deja de ser secreta.
-- =============================================================================

SET NAMES utf8mb4;

-- --------------------------------------------------------------- usuarios
-- De aqui salen los destinatarios de las alertas de HU-10: la severidad Alta va
-- a supervisores y administradores, la Media y la Baja solo a supervisores. El
-- rol consulta no recibe alertas, y el inactivo tampoco.
INSERT INTO usuario (nombre, correo, rol, hash_password, activo) VALUES
  ('Administrador QUINOR', 'admin@quinor.com.pe', 'administrador',
   '$2b$12$pD4Vqwriv1TpRCtZb6a05OB65D2oEm0Wp3NJp0LF.Vm277QfCQ5XG', TRUE),
  ('Ana Quispe',           'ana.quispe@quinor.com.pe', 'supervisor',
   '$2b$12$8M98PR7im2R/M3m1Z1BUAOPym/0ykla./cG2lN03vFqPjF5mJfpbO', TRUE),
  ('Luis Mendoza',         'luis.mendoza@quinor.com.pe', 'supervisor',
   '$2b$12$3zxZ7Dlv76O/da1tz.1e5e044FGydama6kgX6CmmH7.zJRyWRhM1i', TRUE),
  ('Rosa Ccahuana',        'rosa.ccahuana@quinor.com.pe', 'consulta',
   '$2b$12$W/iySEMuJ9LH33HG7lTktuyRHDcKnAUzimdfP4pdXWly.14nk/8Um', TRUE)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), rol = VALUES(rol),
                        activo = VALUES(activo);

-- ------------------------------------------------------------------ orden
INSERT INTO orden_despacho
  (numero_orden, cliente, producto, peso_esperado_kg, sacos_esperados, fecha)
VALUES
  ('OD-2026-0148', 'Andean Grains LLC', 'Quinua blanca organica',
   20000.00, 400, CURRENT_DATE)
ON DUPLICATE KEY UPDATE cliente = VALUES(cliente);

-- ----------------------------------------------------------------- pesada
-- Peso real 400 kg por debajo del esperado: ocho sacos de 50 kg.
INSERT INTO pesada (orden_id, bascula_id, peso_real_kg, fecha_hora, inicio_carga, origen)
SELECT o.id, 'BASCULA-01', 19600.00,
       NOW(6), DATE_SUB(NOW(6), INTERVAL 42 MINUTE), 'bascula'
FROM orden_despacho o
WHERE o.numero_orden = 'OD-2026-0148'
  AND NOT EXISTS (SELECT 1 FROM pesada p WHERE p.orden_id = o.id);

-- ----------------------------------------------------------------- evento
-- Ya analizado: conteo de sacos (HU-07), personas en zona (HU-08), descripcion
-- y severidad (HU-09). La severidad sale de la RN-04, no del modelo; la del
-- modelo viaja dentro de descripcion_ia como severidad_ia.
INSERT INTO evento
  (pesada_id, diferencia_kg, diferencia_pct, sacos_contados, diferencia_sacos,
   personas_detectadas, personal_anomalo, severidad, descripcion_ia, estado,
   clip_url, creado_en)
SELECT
  p.id, -400.00, -2.00, 392, -8, 5, TRUE, 'alta',
  JSON_OBJECT(
    'descripcion', 'Dos personas retiran sacos del pallet junto a la rampa y los sacan del encuadre por el lado opuesto al camion, a los 4 minutos de iniciada la carga.',
    'severidad_ia', 'alta',
    'evidencia', JSON_ARRAY('Ocho sacos menos que la orden',
                            'Dos sacos cruzan la linea hacia fuera en el minuto 4',
                            'Cinco personas en zona; lo habitual son tres'),
    'confianza', 0.82,
    'modelo', 'demo',
    'proveedor', 'demo',
    'intentos', 1,
    'segundos', 3.4),
  'pendiente',
  's3://clips/demo/OD-2026-0148/evento.mkv',
  NOW(6)
FROM pesada p
JOIN orden_despacho o ON o.id = p.orden_id
WHERE o.numero_orden = 'OD-2026-0148'
  AND NOT EXISTS (SELECT 1 FROM evento e WHERE e.pesada_id = p.id);

-- ------------------------------------------------- personas del clip (HU-08)
-- Un identificador temporal, unos segundos y dos numeros de fotograma. Nada
-- mas: la RN-08 prohibe la identificacion facial y los datos biometricos, y la
-- forma de cumplirla es no tener nada que identificar.
INSERT INTO persona_en_evento
  (evento_id, id_temporal, segundos_en_zona, primer_fotograma, ultimo_fotograma, creado_en)
SELECT e.id, v.id_temporal, v.segundos, v.primero, v.ultimo, NOW(6)
FROM evento e
JOIN pesada p ON p.id = e.pesada_id
JOIN orden_despacho o ON o.id = p.orden_id
JOIN (SELECT 1 AS id_temporal, 612.50 AS segundos,   30 AS primero, 18400 AS ultimo
      UNION ALL SELECT 2, 410.00,  240, 12500
      UNION ALL SELECT 3,  98.40, 5100,  8050) AS v
WHERE o.numero_orden = 'OD-2026-0148'
  AND NOT EXISTS (SELECT 1 FROM persona_en_evento pe WHERE pe.evento_id = e.id);

-- ------------------------------------------------- aviso enviado (HU-10)
-- Constancia de que se aviso: a quien, con que asunto y cuanto se tardo desde
-- que termino el analisis. El criterio 3 pide menos de 60 s.
INSERT INTO notificacion
  (evento_id, canal, severidad, destinatarios, asunto, estado, intentos,
   segundos_desde_analisis, enviada_en, creado_en)
SELECT
  e.id, 'correo', 'alta',
  JSON_ARRAY('ana.quispe@quinor.com.pe', 'luis.mendoza@quinor.com.pe',
             'admin@quinor.com.pe'),
  '[ALERTA ALTA] Orden OD-2026-0148: faltan 8 sacos (Andean Grains LLC)',
  'enviada', 1, 0.41, NOW(6), NOW(6)
FROM evento e
JOIN pesada p ON p.id = e.pesada_id
JOIN orden_despacho o ON o.id = p.orden_id
WHERE o.numero_orden = 'OD-2026-0148'
  AND NOT EXISTS (SELECT 1 FROM notificacion n WHERE n.evento_id = e.id);

-- ------------------------------------------------- salud de componentes
-- Para que el panel de HU-18 no aparezca vacio.
INSERT INTO salud_componente (componente, estado, mensaje, verificado_en) VALUES
  ('bascula',   'ok', 'Ultima lectura 19600.00 kg', NOW(6)),
  ('erp',       'ok', 'Orden OD-2026-0148 sincronizada', NOW(6)),
  ('camara-01', 'ok', 'Grabando en buffer circular', NOW(6));
