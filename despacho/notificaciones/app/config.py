"""Ajustes del servicio de notificaciones. HU-10.

Un unico objeto inmutable que create_app construye una vez, igual que en los
otros cuatro servicios. Ningun modulo lee variables de entorno por su cuenta.

Apartado 8 del documento funcional: "Las claves de API del modelo de
vision-lenguaje y de los canales de notificacion se gestionan como variables de
entorno o secretos de Docker, nunca en el codigo". La contrasena del buzon de
salida entra por SMTP_PASSWORD y no aparece en ningun fichero versionado.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# Criterio 3: "La notificacion se envia en menos de 60 s tras el analisis". Ese
# es el limite del criterio, y aqui sirve para dos cosas: para decidir cuanto
# tiempo se puede gastar en reintentos antes de que insistir ya no sirva de
# nada, y para poder decir en el log que un envio llego tarde.
SEGUNDOS_DEL_CRITERIO = 60.0

# Modos de cifrado de la conexion con el servidor de correo.
#   starttls: puerto 587, lo normal en un relay corporativo.
#   ssl:      puerto 465, conexion cifrada desde el principio.
#   ninguno:  puerto 1025 del buzon de desarrollo. En produccion no se usa.
STARTTLS = "starttls"
SSL = "ssl"
SIN_CIFRAR = "ninguno"
CIFRADOS = (STARTTLS, SSL, SIN_CIFRAR)


@dataclass(frozen=True)
class Ajustes:
    """Configuracion resuelta de una instancia del servicio."""

    # --- Base de datos --------------------------------------------------------
    # El servicio es invitado en el esquema del orquestador: lee `usuario` para
    # saber a quien avisar y escribe `notificacion` para dejar constancia.
    database_url: str = ""

    # --- Servidor de correo ---------------------------------------------------
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    # Nunca en el codigo (apartado 8), y fuera de repr: estos ajustes acaban en
    # un log tarde o temprano, y una contrasena que se imprime sola es una
    # contrasena filtrada.
    smtp_password: str = field(default="", repr=False)
    cifrado: str = SIN_CIFRAR
    # Un relay que no contesta en 20 s no va a contestar. El criterio 3 da 60 s
    # en total para tres intentos, asi que ninguno puede quedarse colgado mas
    # que esto.
    timeout_s: float = 20.0

    # De quien sale el correo. Conviene un buzon del sistema y no el de una
    # persona: los avisos siguen saliendo cuando esa persona se va de la empresa.
    remitente: str = "alertas@quinor.com.pe"
    nombre_del_remitente: str = "QUINOR - Control de despacho"
    # A donde van los rebotes y las respuestas de "quien manda esto". Vacio deja
    # el propio remitente.
    responder_a: str = ""

    # --- Enlace del criterio 2 ------------------------------------------------
    # "La notificacion incluye orden, diferencia y enlace al evento". El enlace
    # tiene que abrir el dashboard, y este servicio no sabe en que host esta
    # publicado, asi que se lo dicen.
    dashboard_url: str = "http://localhost:8050"

    # --- Reintentos -----------------------------------------------------------
    # Un relay devuelve 421 o 451 cuando esta saturado, y eso se arregla
    # esperando. Tres intentos con una espera corta caben dentro de los 60 s del
    # criterio 3; una espera larga no cabria, y llegar tarde es casi tan malo
    # como no llegar.
    intentos: int = 3
    espera_inicial_s: float = 2.0

    # --- Contexto del mensaje -------------------------------------------------
    producto: str = "quinua en sacos de 50 kg"

    app_env: str = "development"
    log_level: str = "INFO"

    @property
    def configurado(self) -> bool:
        """Sin host no hay envio posible, y eso hay que saberlo antes del primer
        evento y no con el camion en la rampa."""
        return bool(self.smtp_host) and bool(self.remitente)

    @property
    def usa_credenciales(self) -> bool:
        return bool(self.smtp_user)

    @property
    def en_produccion(self) -> bool:
        return str(self.app_env).lower() in ("production", "produccion", "prod")

    @property
    def viaja_en_claro(self) -> bool:
        """Correo sin cifrar en produccion. No se impide arrancar, porque un
        relay interno en una red cerrada es una decision defendible; pero se
        avisa al arrancar, para que sea una decision y no un descubrimiento."""
        return self.en_produccion and self.cifrado == SIN_CIFRAR

    @property
    def enlace_base(self) -> str:
        return self.dashboard_url.rstrip("/")

    def enlace_del_evento(self, evento_id: int) -> str:
        """El enlace del criterio 2. Apunta al detalle del evento en HU-11."""
        return f"{self.enlace_base}/eventos/{evento_id}"


def _env(nombre: str, por_defecto):
    valor = os.environ.get(nombre)
    return por_defecto if valor is None or valor == "" else valor


def cargar_ajustes(**sobrescrituras) -> Ajustes:
    """Construye los ajustes desde el entorno, con sobrescrituras explicitas."""
    base = {
        "database_url": _env("DATABASE_URL", ""),
        "smtp_host": _env("SMTP_HOST", "localhost"),
        "smtp_port": int(_env("SMTP_PORT", 1025)),
        "smtp_user": _env("SMTP_USER", ""),
        "smtp_password": _env("SMTP_PASSWORD", ""),
        "cifrado": str(_env("SMTP_SECURITY", SIN_CIFRAR)).lower(),
        "timeout_s": float(_env("SMTP_TIMEOUT_SECONDS", 20.0)),
        "remitente": _env("SMTP_FROM", "alertas@quinor.com.pe"),
        "nombre_del_remitente": _env("SMTP_FROM_NAME",
                                     "QUINOR - Control de despacho"),
        "responder_a": _env("SMTP_REPLY_TO", ""),
        "dashboard_url": _env("DASHBOARD_BASE_URL", "http://localhost:8050"),
        "intentos": int(_env("NOTIFY_MAX_ATTEMPTS", 3)),
        "espera_inicial_s": float(_env("NOTIFY_BACKOFF_SECONDS", 2.0)),
        "producto": _env("PLANTA_PRODUCTO", "quinua en sacos de 50 kg"),
        "app_env": _env("APP_ENV", "development"),
        "log_level": _env("LOG_LEVEL", "INFO"),
    }
    base.update({k: v for k, v in sobrescrituras.items() if v is not None})

    if base["cifrado"] not in CIFRADOS:
        raise ValueError(
            f"SMTP_SECURITY '{base['cifrado']}' no existe. "
            f"Los valores validos son: {', '.join(CIFRADOS)}.")
    if not 1 <= int(base["smtp_port"]) <= 65535:
        raise ValueError("SMTP_PORT esta fuera del rango de puertos.")
    if base["intentos"] < 1:
        raise ValueError("NOTIFY_MAX_ATTEMPTS tiene que ser 1 o mas.")
    if base["espera_inicial_s"] < 0:
        raise ValueError("NOTIFY_BACKOFF_SECONDS no puede ser negativo.")
    if base["timeout_s"] <= 0:
        raise ValueError("SMTP_TIMEOUT_SECONDS tiene que ser mayor que cero.")
    if "@" not in str(base["remitente"]):
        raise ValueError("SMTP_FROM tiene que ser una direccion de correo.")
    return Ajustes(**base)
