"""Ajustes de la aplicacion.

Un unico objeto inmutable que create_app construye una vez y guarda en
app.state.ajustes. Ningun modulo lee variables de entorno por su cuenta: las
recibe por parametro. Asi una prueba configura la aplicacion pasando valores,
sin tocar el entorno del proceso ni invalidar caches.

Seccion 8 del documento funcional: ningun secreto vive en el codigo.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# Marcador de desarrollo. No es un secreto: sirve para que docker compose up
# funcione sin configuracion previa, y el arranque avisa cuando sigue en uso.
CLAVE_DESARROLLO = "quinor-desarrollo-cambiar"
ADMIN_POR_DEFECTO = "admin@quinor.local"


@dataclass(frozen=True)
class Ajustes:
    """Configuracion resuelta de una instancia de la aplicacion."""

    database_url: str

    # HU-15 autenticacion. Ya no hay clave estatica: cada peticion trae un token
    # opaco que se resuelve contra la tabla api_token.
    admin_email: str = ADMIN_POR_DEFECTO
    admin_password: str = ""
    token_ttl_hours: float = 12.0

    # HU-01 bascula
    scale_host: str = "scale-sim"
    scale_port: int = 5020
    scale_unit_id: int = 1
    # Criterio 2 de HU-01: presupuesto total de la lectura, reintentos incluidos.
    scale_timeout_seconds: float = 5.0
    # El RNF-04 preve una segunda bascula; cuando llegue, esto sale de un catalogo.
    bascula_id: str = "BASCULA-01"

    # HU-02 ERP
    erp_base_url: str = "http://erp-mock:8001"
    erp_timeout_seconds: float = 5.0
    # Vigencia de la copia local de una orden. Una rampa cargando no deberia
    # depender de una llamada de red por cada pesada, y una orden emitida no
    # cambia cada minuto. 0 desactiva la cache y consulta siempre.
    erp_cache_ttl_seconds: float = 900.0

    # Entorno
    app_env: str = "development"
    log_level: str = "INFO"

    @property
    def clave_por_defecto_en_uso(self) -> bool:
        return self.admin_password == CLAVE_DESARROLLO

    @property
    def sin_administrador_inicial(self) -> bool:
        return not self.admin_password


def _env(nombre: str, por_defecto):
    valor = os.environ.get(nombre)
    return por_defecto if valor is None or valor == "" else valor


def cargar_ajustes(**sobrescrituras) -> Ajustes:
    """Construye los ajustes desde el entorno, con sobrescrituras explicitas.

    Un valor pasado por parametro gana siempre al entorno: es lo que permite a
    las pruebas apuntar a otra base de datos o a otra bascula sin efectos
    laterales sobre el proceso.
    """
    base = {
        "database_url": _env("DATABASE_URL", ""),
        "admin_email": _env("ADMIN_EMAIL", ADMIN_POR_DEFECTO),
        "admin_password": _env("ADMIN_PASSWORD", CLAVE_DESARROLLO),
        "token_ttl_hours": float(_env("TOKEN_TTL_HOURS", 12.0)),
        "scale_host": _env("SCALE_HOST", "scale-sim"),
        "scale_port": int(_env("SCALE_PORT", 5020)),
        "scale_unit_id": int(_env("SCALE_UNIT_ID", 1)),
        "scale_timeout_seconds": float(_env("SCALE_TIMEOUT_SECONDS", 5.0)),
        "bascula_id": _env("BASCULA_ID", "BASCULA-01"),
        "erp_base_url": _env("ERP_BASE_URL", "http://erp-mock:8001"),
        "erp_timeout_seconds": float(_env("ERP_TIMEOUT_SECONDS", 5.0)),
        "erp_cache_ttl_seconds": float(_env("ERP_CACHE_TTL_SECONDS", 900.0)),
        "app_env": _env("APP_ENV", "development"),
        "log_level": _env("LOG_LEVEL", "INFO"),
    }
    base.update({k: v for k, v in sobrescrituras.items() if v is not None})
    if not base["database_url"]:
        raise ValueError("Falta DATABASE_URL: la aplicacion no sabe contra que base trabajar.")
    return Ajustes(**base)
