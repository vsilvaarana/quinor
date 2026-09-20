"""Contrasenas y tokens de acceso. Nucleo de HU-15.

Criterio 3: las contrasenas se almacenan con hash bcrypt.
Criterio 4: la autenticacion usa un token opaco guardado en la tabla api_token.

Dos secretos, dos tratamientos distintos, y la diferencia es deliberada:

  Contrasena  bcrypt, con sal y coste. La escribe una persona, asi que hay que
              asumir que es corta y adivinable, y encarecer cada intento.
  Token       SHA-256 a secas. Lo genera el sistema con 256 bits de entropia:
              no hay diccionario que lo alcance, y en cambio se verifica en cada
              peticion, donde un bcrypt por request seria un lastre.

Ninguno de los dos se almacena en claro. El token se muestra una sola vez, al
emitirlo; despues solo existe su hash, de modo que quien lea la tabla api_token
no puede usar ningun token.
"""
from __future__ import annotations

import hashlib
import secrets

from passlib.context import CryptContext

# bcrypt trunca en 72 bytes. passlib lo hacia en silencio y bcrypt 4.x lanza
# error; en cualquier caso una contrasena mas larga no aporta seguridad real,
# asi que se rechaza antes con un mensaje claro.
LIMITE_BCRYPT_BYTES = 72
BYTES_DE_TOKEN = 32          # 256 bits de entropia

_contexto = CryptContext(schemes=["bcrypt"], deprecated="auto")


class ClaveDemasiadoLarga(ValueError):
    """bcrypt no mira mas alla de 72 bytes: aceptarla enganaria al usuario."""


def hash_password(clave: str) -> str:
    if len(clave.encode("utf-8")) > LIMITE_BCRYPT_BYTES:
        raise ClaveDemasiadoLarga(
            f"La contrasena supera los {LIMITE_BCRYPT_BYTES} bytes que bcrypt considera."
        )
    return _contexto.hash(clave)


def verificar_password(clave: str, hash_guardado: str) -> bool:
    """Verifica sin lanzar: un hash corrupto en base es un fallo de acceso, no una caida."""
    try:
        return _contexto.verify(clave, hash_guardado)
    except (ValueError, TypeError):
        return False


def generar_token() -> tuple[str, str]:
    """Devuelve (token en claro, hash a guardar). El claro no vuelve a existir."""
    token = secrets.token_urlsafe(BYTES_DE_TOKEN)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
