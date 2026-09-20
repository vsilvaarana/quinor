"""Stub del proveedor de vision-lenguaje, para desarrollo y pruebas.

No es un mock. Es un servicio HTTP que habla el mismo dialecto que el proveedor
real, con sus cabeceras, sus codigos de error y su forma de respuesta. Contra un
mock del cliente no se puede comprobar lo que de verdad falla en planta: que la
clave no viaja, que un 429 se reintenta y un 401 no, que el modelo devuelve el
JSON dentro de un bloque de codigo, o que el sobre viene sin texto.

Lo que si es de mentira es el contenido: aqui no hay ningun modelo mirando
imagenes. Compone una descripcion a partir de los datos que recibe, y por eso
`/salud` del servicio avisa en voz alta cuando se esta hablando con el stub.

    python -m sim.vlm_stub --puerto 8404

Para provocar fallos y comprobar el criterio 3:
    --fallar 429 --veces 2     dos 429 y luego responde bien
    --fallar 401               una clave mala, que no se reintenta
    --basura                   responde algo que no es JSON
"""
from __future__ import annotations

import argparse
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Cuanto de la carga se describe. El stub no ve las imagenes, asi que redacta
# con los numeros que le llegan en el texto, que son los del apartado 9.2.
PATRON_SACOS = re.compile(r"diferencia\s+([+-]?\d+)\)")
PATRON_SALIENTES = re.compile(r"SALIERON de la zona de carga: (\d+)")
PATRON_PERSONAS = re.compile(r"Personas en la zona de carga: (\d+)")


def _severidad(salientes: int, diferencia: int, personas: int) -> str:
    """La RN-04, para que el stub no devuelva siempre lo mismo."""
    if salientes > 0 or abs(diferencia) >= 2:
        return "alta"
    if abs(diferencia) == 1 or personas > 3:
        return "media"
    return "baja"


def redactar(texto: str, imagenes: int) -> dict:
    """Compone una respuesta con la forma que pide el criterio 2."""
    sacos = PATRON_SACOS.search(texto)
    salientes = PATRON_SALIENTES.search(texto)
    personas = PATRON_PERSONAS.search(texto)

    diferencia = int(sacos.group(1)) if sacos else 0
    cuantos_salen = int(salientes.group(1)) if salientes else 0
    cuantas = int(personas.group(1)) if personas else 0

    evidencia = []
    if cuantos_salen:
        evidencia.append(
            f"Se observan {cuantos_salen} saco(s) saliendo de la zona de carga "
            f"hacia fuera del camion.")
    if diferencia:
        evidencia.append(
            f"El conteo del video difiere de la orden en {diferencia:+d} sacos.")
    if cuantas:
        evidencia.append(f"Hay {cuantas} operario(s) en la zona de carga.")
    if not evidencia:
        evidencia.append("La carga transcurre sin incidencias visibles.")

    if cuantos_salen:
        descripcion = ("Se observa a un operario retirando sacos de la zona de "
                       "carga hacia fuera del camion durante la operacion. El "
                       "resto de la carga transcurre con normalidad.")
    elif diferencia:
        descripcion = (f"La carga transcurre con aparente normalidad, pero el "
                       f"conteo del video no coincide con la orden en "
                       f"{diferencia:+d} sacos.")
    else:
        descripcion = ("La carga se desarrolla con normalidad: los operarios "
                       "trasladan sacos hacia el camion sin interrupciones "
                       "aparentes.")

    return {
        "descripcion": f"{descripcion} (respuesta generada por el stub de "
                       f"desarrollo, sin mirar los {imagenes} fotograma(s))",
        "severidad": _severidad(cuantos_salen, diferencia, cuantas),
        "evidencia": evidencia,
        "confianza": 0.7,
    }


class Estado:
    """Lo que se le puede pedir al stub que haga, para provocar fallos."""

    def __init__(self, fallar: int = 0, veces: int = -1, basura: bool = False,
                 clave: str = ""):
        """`veces` en -1 falla siempre; en N falla N veces y luego responde."""
        self.fallar = fallar
        self.veces = veces
        self.basura = basura
        self.clave = clave
        self.peticiones: list[dict] = []
        self._candado = threading.Lock()

    def siguiente_fallo(self) -> int:
        """El codigo que toca devolver, o 0 si toca responder bien."""
        with self._candado:
            if not self.fallar:
                return 0
            if self.veces < 0:
                return self.fallar
            if self.veces > 0:
                self.veces -= 1
                return self.fallar
            return 0


def construir_manejador(estado: Estado):
    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):          # noqa: N802
            largo = int(self.headers.get("Content-Length", 0))
            cuerpo = json.loads(self.rfile.read(largo) or b"{}")
            estado.peticiones.append({
                "ruta": self.path,
                "cuerpo": cuerpo,
                "clave": self.headers.get("x-api-key"),
                "version": self.headers.get("anthropic-version"),
            })

            if estado.clave and self.headers.get("x-api-key") != estado.clave:
                self._responder(401, {"error": {"message": "invalid x-api-key"}})
                return

            codigo = estado.siguiente_fallo()
            if codigo:
                self._responder(codigo, {"error": {"message": "provocado por el stub"}})
                return

            texto, imagenes = _de_la_peticion(cuerpo)
            if estado.basura:
                salida = "Claro, aqui tienes el analisis: no es JSON."
            else:
                salida = json.dumps(redactar(texto, imagenes), ensure_ascii=False)
            self._responder(200, {
                "id": "msg_stub", "type": "message", "role": "assistant",
                "model": cuerpo.get("model", "stub"),
                "content": [{"type": "text", "text": salida}],
            })

        def _responder(self, codigo: int, datos: dict):
            cuerpo = json.dumps(datos, ensure_ascii=False).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

    return Manejador


def _de_la_peticion(cuerpo: dict) -> tuple[str, int]:
    """Saca el texto y cuenta las imagenes del formato de Anthropic."""
    mensajes = cuerpo.get("messages") or []
    contenido = mensajes[0].get("content", []) if mensajes else []
    if isinstance(contenido, str):
        return contenido, 0
    textos = [b.get("text", "") for b in contenido if b.get("type") == "text"]
    imagenes = sum(1 for b in contenido if b.get("type") == "image")
    return "\n".join(textos), imagenes


def arrancar(puerto: int = 0, estado: Estado | None = None):
    """Levanta el stub y devuelve (servidor, estado, url)."""
    estado = estado or Estado()
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto),
                                   construir_manejador(estado))
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    url = f"http://127.0.0.1:{servidor.server_address[1]}"
    return servidor, estado, url


def main() -> int:      # pragma: no cover - punto de entrada
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--puerto", type=int, default=8404)
    analizador.add_argument("--fallar", type=int, default=0,
                            help="Codigo HTTP a devolver.")
    analizador.add_argument("--veces", type=int, default=-1,
                            help="Cuantas veces fallar antes de responder bien. "
                                 "-1 falla siempre.")
    analizador.add_argument("--basura", action="store_true",
                            help="Responder algo que no es JSON.")
    analizador.add_argument("--clave", default="",
                            help="Exigir esta clave en x-api-key.")
    argumentos = analizador.parse_args()

    estado = Estado(fallar=argumentos.fallar, veces=argumentos.veces,
                    basura=argumentos.basura, clave=argumentos.clave)
    servidor, _, url = arrancar(argumentos.puerto, estado)
    print(f"Stub de vision-lenguaje escuchando en {url}")
    print("Las respuestas son de desarrollo: aqui no hay ningun modelo.")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        servidor.shutdown()
    return 0


if __name__ == "__main__":      # pragma: no cover
    raise SystemExit(main())
