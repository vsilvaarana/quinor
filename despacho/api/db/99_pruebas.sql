-- Pruebas funcionales del esquema. No forma parte del despliegue.
-- Verifica que las reglas de negocio se cumplan en el motor, no solo en la aplicacion.

-- Camino feliz: usuario -> orden -> pesada -> evento -> veredicto
INSERT INTO usuario (nombre, correo, rol, hash_password)
VALUES ('Ana Quispe', 'ana@quinor.local', 'supervisor', '$2b$12$abcdefghijklmnopqrstuv');

INSERT INTO orden_despacho (numero_orden, cliente, producto, peso_esperado_kg, sacos_esperados, fecha)
VALUES ('ORD-2026-0001', 'Andean Foods GmbH', 'Quinua blanca organica', 20000.00, 400, '2026-09-14');

INSERT INTO pesada (orden_id, bascula_id, peso_real_kg, fecha_hora, origen)
VALUES (1, 'BASCULA-01', 19850.00, '2026-09-14 08:15:32.481900', 'bascula');

INSERT INTO evento (pesada_id, diferencia_kg, diferencia_pct, estado)
VALUES (1, -150.00, -0.75, 'pendiente');

INSERT INTO veredicto (evento_id, usuario_id, estado_nuevo, comentario)
VALUES (1, 1, 'confirmado', 'Faltan tres sacos, se revisa el video con seguridad.');

UPDATE evento SET estado = 'confirmado' WHERE id = 1;

INSERT INTO auditoria (entidad, entidad_id, accion, usuario_id, detalle)
VALUES ('evento', 1, 'cambio_estado', 1, JSON_OBJECT('de','pendiente','a','confirmado'));

INSERT INTO salud_componente (componente, estado, mensaje, verificado_en)
VALUES ('bascula','ok','lectura correcta','2026-09-14 08:00:00.000000'),
       ('bascula','error','sin respuesta en 5 s','2026-09-14 09:00:00.000000'),
       ('erp','ok','responde 200','2026-09-14 09:00:05.000000');

SELECT '--- camino feliz OK ---' AS resultado;
SELECT numero_orden, peso_esperado_kg, peso_real_kg, diferencia_kg, severidad, estado
FROM v_evento_dashboard;

SELECT '--- v_salud_actual: debe traer la ultima de cada componente ---' AS resultado;
SELECT componente, estado, verificado_en FROM v_salud_actual ORDER BY componente;
