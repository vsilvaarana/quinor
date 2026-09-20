"""Adaptadores por proveedor de vision-lenguaje.

El servicio habla un contrato propio: recibe un prompt, unos datos y unas
imagenes, y devuelve el JSON del criterio 2. Lo que cambia entre un proveedor y
otro es como se empaqueta esa peticion y donde viene la respuesta dentro del
sobre, y eso es todo lo que vive aqui.

Por que agnostico. El documento no fija proveedor, y esta es una pieza que se
cambia: por precio, por disponibilidad, o porque el modelo de dentro de un ano
sea otro. Con un adaptador por proveedor, cambiarlo es cambiar VLM_PROVIDER; sin
el, es reescribir el servicio y volver a probarlo entero.

Los adaptadores no reintentan ni validan la respuesta. Eso lo hace `app/vlm.py`
una sola vez para todos: un reintento por adaptador seria el mismo codigo escrito
tres veces y con tres comportamientos distintos el dia que alguien toque uno.
"""
from __future__ import annotations

import dataclasses

from app.config import ANTHROPIC, OPENAI, STUB, Ajustes

# El de Anthropic exige version; los demas no tienen equivalente.
VERSION_ANTHROPIC = "2023-06-01"

URLS = {
    ANTHROPIC: "https://api.anthropic.com/v1/messages",
    OPENAI: "https://api.openai.com/v1/chat/completions",
}


class ProveedorDesconocido(ValueError):
    """VLM_PROVIDER apunta a algo para lo que no hay adaptador."""


@dataclasses.dataclass(frozen=True)
class Peticion:
    """Una llamada lista para enviarse, sin saber a quien."""

    url: str
    cabeceras: dict
    cuerpo: dict


@dataclasses.dataclass(frozen=True)
class Imagen:
    """Un fotograma clave, ya en base64."""

    base64: str
    pie: str
    tipo: str = "image/jpeg"


def _url(ajustes: Ajustes) -> str:
    """La del proveedor, salvo que se apunte a otra cosa.

    VLM_BASE_URL existe para el stub de desarrollo y para una pasarela interna;
    en planta se deja vacia y se va al proveedor.
    """
    if ajustes.base_url:
        return ajustes.base_url.rstrip("/") + "/v1/messages"
    if ajustes.proveedor in URLS:
        return URLS[ajustes.proveedor]
    raise ProveedorDesconocido(
        f"No hay adaptador para '{ajustes.proveedor}' y VLM_BASE_URL esta vacia.")


def _anthropic(ajustes: Ajustes, sistema: str, texto: str,
               imagenes: list[Imagen]) -> Peticion:
    contenido: list[dict] = [{"type": "text", "text": texto}]
    for imagen in imagenes:
        contenido.append({"type": "text", "text": imagen.pie})
        contenido.append({
            "type": "image",
            "source": {"type": "base64", "media_type": imagen.tipo,
                       "data": imagen.base64},
        })
    return Peticion(
        url=_url(ajustes),
        cabeceras={"x-api-key": ajustes.api_key,
                   "anthropic-version": VERSION_ANTHROPIC,
                   "content-type": "application/json"},
        cuerpo={"model": ajustes.modelo,
                "max_tokens": ajustes.max_tokens,
                "temperature": ajustes.temperatura,
                "system": sistema,
                "messages": [{"role": "user", "content": contenido}]},
    )


def _openai(ajustes: Ajustes, sistema: str, texto: str,
            imagenes: list[Imagen]) -> Peticion:
    contenido: list[dict] = [{"type": "text", "text": texto}]
    for imagen in imagenes:
        contenido.append({"type": "text", "text": imagen.pie})
        contenido.append({
            "type": "image_url",
            "image_url": {"url": f"data:{imagen.tipo};base64,{imagen.base64}"},
        })
    return Peticion(
        url=(ajustes.base_url.rstrip("/") + "/v1/chat/completions"
             if ajustes.base_url else URLS[OPENAI]),
        cabeceras={"Authorization": f"Bearer {ajustes.api_key}",
                   "content-type": "application/json"},
        cuerpo={"model": ajustes.modelo,
                "max_tokens": ajustes.max_tokens,
                "temperature": ajustes.temperatura,
                "messages": [{"role": "system", "content": sistema},
                             {"role": "user", "content": contenido}]},
    )


def construir(ajustes: Ajustes, sistema: str, texto: str,
              imagenes: list[Imagen]) -> Peticion:
    """Arma la peticion del proveedor configurado."""
    if ajustes.proveedor in (ANTHROPIC, STUB):
        # El stub habla el formato de Anthropic: hace falta un formato concreto
        # para poder probar de verdad, y elegir el del proveedor por defecto
        # evita mantener un cuarto dialecto que no existe en ninguna parte.
        return _anthropic(ajustes, sistema, texto, imagenes)
    if ajustes.proveedor == OPENAI:
        return _openai(ajustes, sistema, texto, imagenes)
    raise ProveedorDesconocido(f"No hay adaptador para '{ajustes.proveedor}'.")


def texto_de_la_respuesta(ajustes: Ajustes, datos: dict) -> str:
    """Saca el texto del sobre del proveedor.

    Un sobre sin texto no es un fallo de red: es una respuesta que no sirve, y se
    trata como tal para que el reintento del criterio 3 la vuelva a pedir.
    """
    if ajustes.proveedor == OPENAI:
        opciones = datos.get("choices") or []
        if not opciones:
            raise ValueError("La respuesta no trae 'choices'.")
        return (opciones[0].get("message") or {}).get("content") or ""

    bloques = datos.get("content") or []
    if not bloques:
        raise ValueError("La respuesta no trae 'content'.")
    return "".join(b.get("text", "") for b in bloques if b.get("type") == "text")
