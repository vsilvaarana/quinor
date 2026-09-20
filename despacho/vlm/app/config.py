"""Ajustes del servicio de vision-lenguaje.

Un unico objeto inmutable que create_app construye una vez, igual que en los
otros tres servicios. Ningun modulo lee variables de entorno por su cuenta.

Apartado 8 del documento funcional: "Las claves de API del modelo de
vision-lenguaje y de los canales de notificacion se gestionan como variables de
entorno o secretos de Docker, nunca en el codigo".
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# Criterio 3 de HU-09: "si la API falla se reintenta 3 veces y luego se marca
# Pendiente de analisis".
INTENTOS = 3

# Proveedores para los que hay adaptador. El contrato del servicio es el mismo
# para todos: cambiar de proveedor es cambiar esta variable, no el codigo.
ANTHROPIC = "anthropic"
OPENAI = "openai"
STUB = "stub"
PROVEEDORES = (ANTHROPIC, OPENAI, STUB)

# Concordancia minima entre la severidad del modelo y la del supervisor. Por
# debajo, el apartado 9.2 manda revisar el prompt.
CONCORDANCIA_MINIMA_PCT = 85.0


@dataclass(frozen=True)
class Ajustes:
    """Configuracion resuelta de una instancia del servicio."""

    # --- El proveedor ---------------------------------------------------------
    proveedor: str = STUB
    # Nunca en el codigo (apartado 8). Vacia deja el servicio en pie pero
    # respondiendo 503, que es mejor que arrancar y fallar con el primer evento.
    api_key: str = ""
    modelo: str = "claude-sonnet-4-5"
    # Sirve para apuntar a un stub o a una pasarela interna sin tocar el codigo.
    base_url: str = ""

    # Un clip de 7 minutos con cuatro imagenes no necesita mas que esto, y un
    # modelo que tarde mas ya esta fallando de otra manera.
    timeout_s: float = 120.0
    # Criterio 3. Los reintentos son del servicio y no de quien llama: quien
    # llama ya tiene los suyos, y duplicarlos multiplicaria el gasto.
    intentos: int = INTENTOS
    # Espera entre intentos, que se duplica en cada uno. Un 429 o un 503 del
    # proveedor se arreglan esperando; insistir de inmediato solo empeora.
    espera_inicial_s: float = 2.0

    # Cuanto texto se le pide de vuelta. La descripcion es para leerla de un
    # vistazo antes de abrir el clip, no para sustituirlo.
    max_tokens: int = 1024
    # Temperatura baja: aqui no se busca variedad, se busca que el mismo clip
    # describa lo mismo dos veces.
    temperatura: float = 0.2

    # --- Contexto de planta (apartado 9.2) ------------------------------------
    # El prompt necesita saber como es una carga normal para poder decir que
    # algo no lo fue. Estos valores se ajustan en el piloto.
    producto: str = "quinua en sacos de 50 kg"
    sacos_por_camion: int = 400
    duracion_tipica_min: int = 45
    personas_habituales: int = 3

    app_env: str = "development"
    log_level: str = "INFO"

    @property
    def configurado(self) -> bool:
        """Con el stub no hace falta clave; con un proveedor real, si."""
        return self.proveedor == STUB or bool(self.api_key)


def _env(nombre: str, por_defecto):
    valor = os.environ.get(nombre)
    return por_defecto if valor is None or valor == "" else valor


def cargar_ajustes(**sobrescrituras) -> Ajustes:
    """Construye los ajustes desde el entorno, con sobrescrituras explicitas."""
    base = {
        "proveedor": str(_env("VLM_PROVIDER", STUB)).lower(),
        "api_key": _env("VLM_API_KEY", ""),
        "modelo": _env("VLM_MODEL", "claude-sonnet-4-5"),
        "base_url": _env("VLM_BASE_URL", ""),
        "timeout_s": float(_env("VLM_TIMEOUT_SECONDS", 120.0)),
        "intentos": int(_env("VLM_MAX_ATTEMPTS", INTENTOS)),
        "espera_inicial_s": float(_env("VLM_BACKOFF_SECONDS", 2.0)),
        "max_tokens": int(_env("VLM_MAX_TOKENS", 1024)),
        "temperatura": float(_env("VLM_TEMPERATURE", 0.2)),
        "producto": _env("PLANTA_PRODUCTO", "quinua en sacos de 50 kg"),
        "sacos_por_camion": int(_env("PLANTA_SACOS_POR_CAMION", 400)),
        "duracion_tipica_min": int(_env("PLANTA_DURACION_CARGA_MIN", 45)),
        "personas_habituales": int(_env("PERSONAS_HABITUALES", 3)),
        "app_env": _env("APP_ENV", "development"),
        "log_level": _env("LOG_LEVEL", "INFO"),
    }
    base.update({k: v for k, v in sobrescrituras.items() if v is not None})

    if base["proveedor"] not in PROVEEDORES:
        raise ValueError(
            f"VLM_PROVIDER '{base['proveedor']}' no tiene adaptador. "
            f"Los que hay: {', '.join(PROVEEDORES)}.")
    if base["intentos"] < 1:
        raise ValueError("VLM_MAX_ATTEMPTS tiene que ser 1 o mas.")
    if base["espera_inicial_s"] < 0:
        raise ValueError("VLM_BACKOFF_SECONDS no puede ser negativo.")
    if base["timeout_s"] <= 0:
        raise ValueError("VLM_TIMEOUT_SECONDS tiene que ser mayor que cero.")
    if not 0.0 <= base["temperatura"] <= 2.0:
        raise ValueError("VLM_TEMPERATURE va entre 0 y 2.")
    return Ajustes(**base)
