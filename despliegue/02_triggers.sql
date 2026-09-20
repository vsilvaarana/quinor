-- =============================================================================
-- QUINOR S.A.C. - Triggers de reglas de negocio
--
-- Van aparte porque necesitan DELIMITER, que es una instruccion del cliente y
-- no del servidor. El cliente mysql, el de MariaDB y phpMyAdmin la entienden;
-- algunos plugins de editor, no. Si el tuyo se queja, ejecuta cada bloque
-- CREATE TRIGGER completo por separado y sin las lineas DELIMITER.
--
-- Que protegen, comprobado sobre MariaDB 10.11:
--   trg_evento_no_reabrir    RN-06: un evento Confirmado no retrocede
--   trg_auditoria_no_update  HU-16: la auditoria no se modifica
--   trg_auditoria_no_delete  HU-16: la auditoria no se borra
-- =============================================================================

-- #############################################################################
-- PARTE 4 - TRIGGERS DE REGLAS DE NEGOCIO
--
-- DELIMITER es una instruccion del cliente mysql, no del servidor. Si este
-- script se ejecuta desde un driver de Python, separar los triggers en otro
-- archivo y enviarlos de uno en uno sin DELIMITER.
-- #############################################################################

DELIMITER $$

-- RN-06: un evento Confirmado no puede regresar a Pendiente.
-- Falso positivo tambien es un estado final segun la seccion 5.3, pero la RN-06
-- solo legisla sobre Confirmado, asi que el trigger no va mas alla de la regla.
DROP TRIGGER IF EXISTS trg_evento_no_reabrir $$
CREATE TRIGGER trg_evento_no_reabrir
BEFORE UPDATE ON evento
FOR EACH ROW
BEGIN
  IF OLD.estado = 'confirmado' AND NEW.estado = 'pendiente' THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'RN-06: un evento Confirmado no puede regresar al estado Pendiente.';
  END IF;
END $$

-- HU-16 criterio 3: los registros de auditoria no pueden borrarse ni alterarse.
DROP TRIGGER IF EXISTS trg_auditoria_no_update $$
CREATE TRIGGER trg_auditoria_no_update
BEFORE UPDATE ON auditoria
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'La auditoria es de solo insercion: no admite modificaciones.';
END $$

DROP TRIGGER IF EXISTS trg_auditoria_no_delete $$
CREATE TRIGGER trg_auditoria_no_delete
BEFORE DELETE ON auditoria
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'La auditoria es de solo insercion: no admite borrados.';
END $$

DELIMITER ;
