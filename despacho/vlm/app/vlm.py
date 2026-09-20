"""Llamada al modelo de vision-lenguaje. HU-09, criterios 2 y 3.

  2. La respuesta es un JSON con descripcion, severidad (Baja/Media/Alta) y
     evidencia observada.
  3. Si la API falla se reintenta 3 veces y luego se marca Pendiente de analisis.

Lo que este modulo hace es pedir, reintentar y validar. Marcar el evento es del
grabador, que es quien tiene la base; aqui se devuelve el fallo con su motivo y
se deja constancia de cuantos intentos costo.

Sobre la validacion. Un modelo puede devolver JSON envuelto en un bloque de
codigo, una severidad en ingles, una severidad inventada o texto donde iba una
lista. Nada de eso es un error de red y nada de eso se puede guardar tal cual en
la base. Se normaliza lo que tiene arreglo evidente y se rechaza lo que no,
porque una severidad inventada que llegue a la tabla es peor que un evento en
Pendiente de analisis: el segundo se ve, el primero no.
"""
from __future__ import annotations

import dataclasses
import json
import re
import time

import httpx
import structlog

from app import prompt as plantilla
from app import proveedores
from app.config import STUB, Ajustes
from app.severidad import SEVERIDADES, es_valida

log = structlog.get_logger("quinor.vlm")

# Codigos que se arreglan esperando. Un 400 o un 401 no: insistir con una clave
# mala tres veces solo retrasa el momento de leer el error.
REINTENTABLES = {408, 409, 425, 429, 500, 502, 503, 504}

# Los modelos devuelven a veces el JSON dentro de un bloque de codigo. Es lo mas
# comun que hay que perdonar, y perdonarlo no oculta ningun problema real.
BLOQUE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.S)

# Traducciones que si son inequivocas. Nada mas: "critica" o "urgente" no son
# ninguna de las tres de la RN-04, y adivinar cual quiso decir seria inventarse
# la severidad de un evento.
EQUIVALENTES = {
    "low": "baja", "medium": "media", "high": "alta",
    "baja": "baja", "media": "media", "alta": "alta",
}


class AnalisisFallido(RuntimeError):
    """No se pudo obtener un analisis valido tras los reintentos."""

    def __init__(self, mensaje: str, intentos: int = 0, ultimo_motivo: str = ""):
        super().__init__(mensaje)
        self.intentos = intentos
        self.ultimo_motivo = ultimo_motivo


class RespuestaInvalida(ValueError):
    """El modelo respondio, pero no con lo que pide el criterio 2."""


class SinConfigurar(RuntimeError):
    """Falta la clave del proveedor. El servicio esta en pie pero no puede pedir."""


@dataclasses.dataclass(frozen=True)
class Analisis:
    """El JSON del criterio 2, ya validado."""

    descripcion: str
    severidad_ia: str
    evidencia: tuple[str, ...]
    confianza: float
    modelo: str
    proveedor: str
    intentos: int
    segundos: float

    def a_json(self) -> dict:
        """Lo que se guarda en evento.descripcion_ia."""
        return {
            "descripcion": self.descripcion,
            "severidad_ia": self.severidad_ia,
            "evidencia": list(self.evidencia),
            "confianza": self.confianza,
            "modelo": self.modelo,
            "proveedor": self.proveedor,
            "intentos": self.intentos,
            "segundos": self.segundos,
        }


def _extraer_json(texto: str) -> dict:
    """Saca el objeto JSON de lo que devolvio el modelo."""
    crudo = (texto or "").strip()
    if not crudo:
        raise RespuestaInvalida("El modelo devolvio una respuesta vacia.")

    bloque = BLOQUE.search(crudo)
    if bloque:
        crudo = bloque.group(1).strip()
    elif not crudo.startswith("{"):
        # Algun modelo antepone una frase antes del objeto. Se busca el primer
        # objeto de nivel superior en lugar de rendirse.
        inicio, fin = crudo.find("{"), crudo.rfind("}")
        if inicio == -1 or fin <= inicio:
            raise RespuestaInvalida(
                f"El modelo no devolvio JSON: {crudo[:160]}")
        crudo = crudo[inicio:fin + 1]

    try:
        datos = json.loads(crudo)
    except json.JSONDecodeError as exc:
        raise RespuestaInvalida(f"El JSON del modelo no se puede leer: {exc}") from exc
    if not isinstance(datos, dict):
        raise RespuestaInvalida("El modelo devolvio JSON pero no un objeto.")
    return datos


def _normalizar_severidad(valor) -> str:
    nivel = str(valor or "").strip().lower()
    nivel = EQUIVALENTES.get(nivel, nivel)
    if not es_valida(nivel):
        raise RespuestaInvalida(
            f"La severidad '{valor}' no es ninguna de las de la RN-04 "
            f"({', '.join(SEVERIDADES)}).")
    return nivel


def _normalizar_evidencia(valor) -> tuple[str, ...]:
    """Una lista de frases. Un texto suelto se acepta como una sola."""
    if valor is None:
        return ()
    if isinstance(valor, str):
        return (valor.strip(),) if valor.strip() else ()
    if not isinstance(valor, list):
        raise RespuestaInvalida("La evidencia no es una lista de frases.")
    return tuple(str(v).strip() for v in valor if str(v).strip())


def _normalizar_confianza(valor) -> float:
    try:
        confianza = float(valor)
    except (TypeError, ValueError):
        # Sin confianza utilizable se asume la peor, no la mejor: una cifra
        # inventada al alza haria que el dashboard ordenara mal la cola.
        return 0.0
    return round(min(max(confianza, 0.0), 1.0), 2)


def validar(datos: dict) -> dict:
    """Comprueba el criterio 2 sobre lo que devolvio el modelo."""
    descripcion = str(datos.get("descripcion") or "").strip()
    if not descripcion:
        raise RespuestaInvalida("El modelo no devolvio descripcion.")
    return {
        "descripcion": descripcion,
        "severidad_ia": _normalizar_severidad(datos.get("severidad")),
        "evidencia": _normalizar_evidencia(datos.get("evidencia")),
        "confianza": _normalizar_confianza(datos.get("confianza")),
    }


def _pedir_una_vez(ajustes: Ajustes, peticion: proveedores.Peticion,
                   cliente=None) -> dict:
    """Una llamada. Los reintentos son de quien la usa."""
    enviar = cliente.post if cliente is not None else httpx.post
    respuesta = enviar(peticion.url, json=peticion.cuerpo,
                       headers=peticion.cabeceras, timeout=ajustes.timeout_s)
    respuesta.raise_for_status()
    return respuesta.json()


def analizar(ajustes: Ajustes, contexto: dict, imagenes: list[proveedores.Imagen],
             cliente=None, dormir=time.sleep) -> Analisis:
    """Pide el analisis y reintenta. Criterios 2 y 3.

    `dormir` se inyecta para que las pruebas comprueben los reintentos sin
    esperarlos de verdad: una prueba que tarda seis segundos en verificar una
    espera acaba desactivada.
    """
    if not ajustes.configurado:
        raise SinConfigurar(
            "Falta VLM_API_KEY: el servicio no puede llamar al modelo. "
            "Se configura como variable de entorno o secreto de Docker "
            "(apartado 8), nunca en el codigo.")

    sistema = plantilla.sistema(ajustes)
    texto = plantilla.datos_del_evento(contexto)
    peticion = proveedores.construir(ajustes, sistema, texto, imagenes)

    empezo = time.monotonic()
    espera = ajustes.espera_inicial_s
    ultimo = ""
    for intento in range(1, ajustes.intentos + 1):
        try:
            sobre = _pedir_una_vez(ajustes, peticion, cliente)
            crudo = proveedores.texto_de_la_respuesta(ajustes, sobre)
            campos = validar(_extraer_json(crudo))
        except httpx.HTTPStatusError as exc:
            codigo = exc.response.status_code
            ultimo = f"HTTP {codigo}: {exc.response.text[:200]}"
            if codigo not in REINTENTABLES:
                # Una clave mala o una peticion mal formada no se arreglan
                # insistiendo. Mejor fallar ya y que se lea el motivo.
                raise AnalisisFallido(
                    f"El proveedor respondio {codigo} y no es un error "
                    f"pasajero: {exc.response.text[:200]}",
                    intentos=intento, ultimo_motivo=ultimo) from exc
        except (httpx.HTTPError, ValueError) as exc:
            # ValueError cubre RespuestaInvalida y el JSON del sobre: un modelo
            # que devolvio algo ilegible puede devolver algo legible al repetir.
            ultimo = str(exc)
        else:
            tardo = round(time.monotonic() - empezo, 2)
            analisis = Analisis(
                **campos, modelo=ajustes.modelo, proveedor=ajustes.proveedor,
                intentos=intento, segundos=tardo)
            log.info("evento_analizado", severidad_ia=analisis.severidad_ia,
                     confianza=analisis.confianza, intentos=intento,
                     modelo=ajustes.modelo, segundos=tardo)
            return analisis

        log.warning("analisis_reintentado", intento=intento,
                    de=ajustes.intentos, motivo=ultimo)
        if intento < ajustes.intentos:
            dormir(espera)
            espera *= 2      # un 429 no se arregla insistiendo mas rapido

    raise AnalisisFallido(
        f"El modelo de vision-lenguaje fallo en los {ajustes.intentos} intentos. "
        f"Ultimo motivo: {ultimo}",
        intentos=ajustes.intentos, ultimo_motivo=ultimo)


def es_stub(ajustes: Ajustes) -> bool:
    """El stub de desarrollo no es un mock: es un servicio HTTP que habla el
    mismo dialecto que el proveedor real. Se informa en /salud para que nadie
    confunda una respuesta de mentira con un analisis."""
    return ajustes.proveedor == STUB
