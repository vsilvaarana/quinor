"""API de mentira para ver el dashboard sin levantar el entorno.

Sirve datos de ejemplo fijos por HTTP, con las mismas rutas y formas que la API
real, para poder abrir el dashboard en un navegador y sacar las capturas del
manual de usuario (`docs/ux/capturar.py`). No valida nada, no guarda nada en
disco y acepta cualquier contrasena: **no es un entorno de pruebas** ni
sustituye a la suite, que corre contra la API y la base de verdad.

Uso, desde despacho/api:

    python docs/ux/api_simulada.py            # escucha en 127.0.0.1:8999
    API_INTERNAL_URL=http://127.0.0.1:8999 streamlit run dashboard/app.py

Todos los nombres, ordenes y pesos son inventados.
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

PUERTO = 8999
BASE = f"http://127.0.0.1:{PUERTO}"

USUARIOS = [
    {"id": 1, "nombre": "Ana Torres", "correo": "ana.torres@quinor.local",
     "rol": "administrador", "activo": True},
    {"id": 2, "nombre": "Luis Paredes", "correo": "luis.paredes@quinor.local",
     "rol": "supervisor", "activo": True},
    {"id": 3, "nombre": "Rosa Quispe", "correo": "rosa.quispe@quinor.local",
     "rol": "consulta", "activo": True},
    {"id": 4, "nombre": "Jorge Mamani", "correo": "jorge.mamani@quinor.local",
     "rol": "supervisor", "activo": False},
]
ESTADO = {"carga_abierta": False, "pesada": None}


def _fila(i, orden, cliente, kg, pct, esperados, contados, severidad, estado,
          cuando, anomalo=False):
    return {"id": i, "creado_en": cuando, "numero_orden": orden, "cliente": cliente,
            "diferencia_kg": kg, "diferencia_pct": pct, "sacos_esperados": esperados,
            "sacos_contados": contados,
            "diferencia_sacos": None if contados is None else contados - esperados,
            "personas_detectadas": 3 if contados is not None else None,
            "personal_anomalo": anomalo if contados is not None else None,
            "severidad": severidad, "estado": estado, "tiene_clip": True}


FILAS = [
    _fila(214, "ORD-2026-0148", "Cliente demo A", "-350.00", "-1.75", 400, 400,
          "alta", "pendiente", "2026-11-15T09:12:00", anomalo=True),
    _fila(213, "ORD-2026-0145", "Cliente demo B", "-150.00", "-0.75", 400, 397,
          "media", "pendiente", "2026-11-14T16:40:00"),
    _fila(212, "ORD-2026-0141", "Cliente demo C", "-95.00", "-0.63", 300, None,
          None, "pendiente", "2026-11-14T11:05:00"),
]


def _detalle(i):
    fila = next((f for f in FILAS if f["id"] == i), FILAS[0])
    kg = float(fila["diferencia_kg"])
    esperado = fila["sacos_esperados"] * 50
    return {
        "id": fila["id"], "estado": fila["estado"], "numero_orden": fila["numero_orden"],
        "cliente": fila["cliente"], "producto": "Quinua blanca organica",
        "inicio_carga": "2026-11-15T08:57:10", "segundo_de_entrada": 412,
        "pesos": {"esperado_kg": f"{esperado:.2f}", "real_kg": f"{esperado + kg:.2f}",
                  "diferencia_kg": fila["diferencia_kg"],
                  "diferencia_pct": fila["diferencia_pct"],
                  "tolerancia_aplicada_kg": "50.00",
                  "exceso_sobre_la_tolerancia_kg": f"{abs(kg) - 50:.2f}"},
        "sacos": {"analizado": fila["sacos_contados"] is not None,
                  "esperados": fila["sacos_esperados"],
                  "contados": fila["sacos_contados"],
                  "diferencia": fila["diferencia_sacos"]},
        "peso_corto_con_sacos_completos": kg < 0 and fila["diferencia_sacos"] == 0,
        "clip": {"desde": "2026-11-15T08:52:10", "hasta": "2026-11-15T09:14:05",
                 "camara": "camara-rampa-01", "reproducible": True, "formato": "mp4",
                 "completo": True, "cobertura_pct": 100, "motivo_sin_clip": None,
                 "enlace": {"url": f"{BASE}/demo/clip.mp4", "minutos": 15,
                            "explicacion": None, "direccion": None}},
        "fotogramas": [
            {"motivo": motivo, "segundo": segundo, "fotograma": segundo * 25,
             "detalle": None,
             "enlace": {"reproducible": True, "url": f"{BASE}/demo/fotograma_{segundo}.png",
                        "explicacion": None}}
            for motivo, segundo in (("pico_de_personas", 412), ("primer_saco", 130),
                                    ("ultimo_saco", 1180), ("centro_del_clip", 657))],
        "anomalia": {"es_anomalia": True, "motivo": "pico_de_personas", "segundo": 412},
        "analisis": {"severidad": fila["severidad"], "hay_descripcion": True,
                     "descripcion": "La carga se realiza de forma continua. Tres personas "
                                    "permanecen junto al camion durante cerca de dos "
                                    "minutos sin movimiento de sacos.",
                     "evidencia": ["400 sacos cruzan la linea de carga",
                                   "Permanencia prolongada sin carga hacia el segundo 412"],
                     "discrepan": False, "severidad_ia": fila["severidad"]},
        "personas": {"analizado": True, "detectadas": 3, "personal_anomalo": True,
                     "presencias": [
                         {"id_temporal": 1, "segundos_en_zona": 112,
                          "primer_fotograma": 9250, "ultimo_fotograma": 12050},
                         {"id_temporal": 2, "segundos_en_zona": 96,
                          "primer_fotograma": 9600, "ultimo_fotograma": 12000},
                         {"id_temporal": 3, "segundos_en_zona": 41,
                          "primer_fotograma": 10300, "ultimo_fotograma": 11325}],
                     "nota": "Los identificadores son temporales y no corresponden a "
                             "personas concretas.",
                     "permanencia_maxima_s": 112, "segundos_totales": 249},
        "veredicto": None, "decisiones": [],
        "clasificaciones_posibles": ["confirmado", "falso_positivo", "en_revision"],
    }


PRODUCTOS = [
    {"id": 1, "producto": "Quinua blanca organica", "tolerancia_kg": "50.00",
     "tolerancia_pct": "0.50", "actualizado_por": 1,
     "actualizado_por_nombre": "Ana Torres", "fecha": "2026-10-02T10:15:00",
     "canales_por_severidad": {"alta": ["sms", "slack"], "media": ["slack", "correo"],
                               "baja": ["correo"]}},
    {"id": 2, "producto": "Quinua roja organica", "tolerancia_kg": "50.00",
     "tolerancia_pct": "0.50", "actualizado_por": None, "actualizado_por_nombre": None,
     "fecha": "2026-09-14T00:00:00",
     "canales_por_severidad": {"alta": ["sms", "slack"], "media": ["slack", "correo"],
                               "baja": ["correo"]}},
    {"id": 3, "producto": "Quinua negra convencional", "tolerancia_kg": "50.00",
     "tolerancia_pct": "0.75", "actualizado_por": None, "actualizado_por_nombre": None,
     "fecha": "2026-09-14T00:00:00",
     "canales_por_severidad": {"alta": ["sms", "slack"], "media": ["slack", "correo"],
                               "baja": ["correo"]}},
]
ORDEN = {"numero_orden": "ORD-2026-0152", "cliente": "Cliente demo A",
         "producto": "Quinua blanca organica", "peso_esperado_kg": "20000.00",
         "sacos_esperados": 400, "fecha": "2026-11-15",
         "sincronizado_en": "2026-11-15T10:27:41"}
PESADAS = [
    {"id": 531, "numero_orden": "ORD-2026-0148", "cliente": "Cliente demo A",
     "producto": "Quinua blanca organica", "bascula_id": "BASCULA-01",
     "peso_real_kg": "19650.00", "peso_esperado_kg": "20000.00",
     "fecha_hora": "2026-11-15T09:12:04", "origen": "bascula"},
    {"id": 530, "numero_orden": "ORD-2026-0147", "cliente": "Cliente demo C",
     "producto": "Quinua roja organica", "bascula_id": "BASCULA-01",
     "peso_real_kg": "14985.00", "peso_esperado_kg": "15000.00",
     "fecha_hora": "2026-11-15T08:03:51", "origen": "bascula"},
    {"id": 529, "numero_orden": "ORD-2026-0145", "cliente": "Cliente demo B",
     "producto": "Quinua blanca organica", "bascula_id": "BASCULA-01",
     "peso_real_kg": "19850.00", "peso_esperado_kg": "20000.00",
     "fecha_hora": "2026-11-14T16:40:22", "origen": "manual"},
]


def _png(texto: str) -> bytes:
    from PIL import Image, ImageDraw
    imagen = Image.new("RGB", (640, 360), "#2B312E")
    lienzo = ImageDraw.Draw(imagen)
    lienzo.text((24, 20), "FOTOGRAMA DE EJEMPLO", fill="#C9D1CC")
    lienzo.text((24, 44), texto, fill="#C9D1CC")
    salida = io.BytesIO()
    imagen.save(salida, "PNG")
    return salida.getvalue()


_CLIP: bytes | None = None


def _clip() -> bytes:
    """Un video de barras de prueba, generado una vez con ffmpeg si lo hay."""
    global _CLIP
    if _CLIP is None:
        with tempfile.NamedTemporaryFile(suffix=".mp4") as destino:
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                     "testsrc=duration=20:size=640x360:rate=10", "-pix_fmt", "yuv420p",
                     "-movflags", "+faststart", destino.name], check=True, timeout=60)
                _CLIP = open(destino.name, "rb").read()
            except (OSError, subprocess.SubprocessError):
                _CLIP = b""
    return _CLIP


def responder(metodo: str, ruta: str, consulta: dict, cuerpo: dict):
    """(codigo, json) para una peticion. Lo mas especifico, primero."""
    if ruta == "/auth/login":
        correo = cuerpo.get("correo", "")
        usuario = next((u for u in USUARIOS if u["correo"] == correo), USUARIOS[1])
        return 200, {"token": "token-de-ejemplo", "usuario": usuario}
    if ruta == "/salud":
        return 200, {"estado": "ok", "componentes": [
            {"componente": "bascula", "estado": "ok",
             "mensaje": "ultima lectura 19650.00 kg", "verificado_en": "2026-11-15T10:40:00"},
            {"componente": "camara-rampa-01", "estado": "ok", "mensaje": "grabando",
             "verificado_en": "2026-11-15T10:41:00"},
            {"componente": "camara-rampa-02", "estado": "ok", "mensaje": "grabando",
             "verificado_en": "2026-11-15T10:41:00"},
            {"componente": "erp", "estado": "ok", "mensaje": "responde",
             "verificado_en": "2026-11-15T10:27:41"}]}
    if ruta == "/salud/historial":
        return 200, []
    if ruta == "/eventos/bandeja":
        return 200, {"filas": FILAS, "filtros": {"por_defecto": ["estado", "desde"]},
                     "resumen": {"abiertos": 3, "con_faltante_de_sacos": 1,
                                 "con_peso_corto_y_sacos_completos": 1,
                                 "con_personal_anomalo": 1},
                     "total": 3, "desde_fila": 1, "hasta_fila": 3, "pagina": 1,
                     "paginas": 1, "segundos": 0.12, "dentro_del_criterio": True}
    if m := re.fullmatch(r"/eventos/(\d+)/detalle", ruta):
        return 200, _detalle(int(m.group(1)))
    if re.fullmatch(r"/eventos/\d+/avisos", ruta):
        return 200, {"notificaciones": [{
            "canal": "correo", "estado": "enviada", "enviada_en": "2026-11-15T09:16:02",
            "creado_en": "2026-11-15T09:15:54", "intentos": 1, "error": None,
            "destinatarios": ["luis.paredes@quinor.local"],
            "segundos_desde_analisis": 8.4, "dentro_del_criterio": True}]}
    if re.fullmatch(r"/eventos/\d+/veredicto", ruta):
        return 201, {"evento_id": 214, "estado": cuerpo.get("estado_nuevo", "confirmado")}
    if ruta == "/eventos":
        return 200, [{"id": 214, "pesada_id": 531}, {"id": 213, "pesada_id": 529}]
    if ruta == "/pesadas/lectura-previa":
        return 200, {"numero_orden": ORDEN["numero_orden"], "bascula_id": "BASCULA-01",
                     "peso_kg": "19650.00", "estable": True,
                     "leido_en": "2026-11-15T10:42:31", "peso_esperado_kg": "20000.00",
                     "diferencia_kg": "-350.00", "diferencia_pct": "-1.75",
                     "tolerancia_kg": "50.00", "generaria_evento": True}
    if ruta == "/pesadas" and metodo == "GET":
        return 200, PESADAS
    if ruta == "/pesadas":
        return 201, {"id": 532, **{k: ORDEN[k] for k in ("numero_orden", "cliente", "producto")},
                     "bascula_id": "BASCULA-01", "peso_real_kg": "19650.00",
                     "peso_esperado_kg": "20000.00", "fecha_hora": "2026-11-15T10:43:02",
                     "origen": "bascula", "evaluada": True, "motivo_sin_evaluar": None,
                     "evento": {"id": 215, "creado_en": "2026-11-15T10:43:03",
                                "pesada_fecha_hora": "2026-11-15T10:43:02",
                                "tolerancia_aplicada_kg": "50.00",
                                "diferencia_kg": "-350.00", "diferencia_pct": "-1.75"}}
    if ruta == "/ordenes":
        return 200, [ORDEN]
    if ruta.startswith("/ordenes/"):
        return 200, ORDEN
    if ruta == "/cargas":
        abiertas = ([{"numero_orden": ORDEN["numero_orden"], "bascula_id": "BASCULA-01",
                      "inicio": ESTADO["inicio"]}] if ESTADO["carga_abierta"] else [])
        return 200, abiertas
    if ruta.startswith("/cargas/"):
        import datetime as dt
        ESTADO["carga_abierta"] = True
        ESTADO["inicio"] = (dt.datetime.now() - dt.timedelta(minutes=14, seconds=32)
                            ).isoformat(timespec="seconds")
        return 201, {}
    if ruta == "/configuracion":
        return 200, PRODUCTOS
    if m := re.fullmatch(r"/configuracion/(.+)/aplicada", ruta):
        fila = next(p for p in PRODUCTOS if p["producto"] == m.group(1))
        peso = float(consulta.get("peso_esperado_kg", ["20000"])[0])
        del_pct = peso * float(fila["tolerancia_pct"]) / 100
        kg = float(fila["tolerancia_kg"])
        return 200, {"tolerancia_efectiva_kg": f"{min(kg, del_pct):.2f}",
                     "equivalente_del_pct_kg": f"{del_pct:.2f}",
                     "manda": "porcentaje" if del_pct < kg else "kg"}
    if m := re.fullmatch(r"/configuracion/(.+)/historial", ruta):
        if m.group(1) != PRODUCTOS[0]["producto"]:
            return 200, []
        return 200, [{"id": 1, "fecha": "2026-10-02T10:15:00", "usuario_id": 1,
                      "usuario_nombre": "Ana Torres",
                      "detalle": {"antes": {"kg": "40.00", "pct": "0.50"},
                                  "despues": {"kg": "50.00", "pct": "0.50"}}}]
    if ruta.startswith("/configuracion/"):
        return 200, PRODUCTOS[0]
    if ruta == "/auth/tokens" and metodo == "GET":
        return 200, [
            {"id": 7, "nombre": "Laptop de rampa 1", "expira_en": "2026-11-16T10:00:00",
             "ultimo_uso_en": "2026-11-15T10:41:00", "revocado_en": None},
            {"id": 6, "nombre": "Tablet de supervision", "expira_en": "2026-11-15T20:00:00",
             "ultimo_uso_en": None, "revocado_en": "2026-11-14T18:00:00"}]
    if ruta.startswith("/auth/tokens"):
        return 200, {"id": 7}
    if ruta == "/usuarios" and metodo == "GET":
        return 200, USUARIOS
    if ruta.startswith("/usuarios"):
        return 200, USUARIOS[1]
    return 404, {"detail": f"La API simulada no conoce {metodo} {ruta}"}


class Peticion(BaseHTTPRequestHandler):
    def _atender(self) -> None:
        partes = urlparse(self.path)
        ruta = unquote(partes.path)
        if ruta.startswith("/demo/"):
            if ruta.endswith(".mp4"):
                self._enviar(200, _clip(), "video/mp4")
            else:
                self._enviar(200, _png(ruta.rsplit("/", 1)[1]), "image/png")
            return
        largo = int(self.headers.get("Content-Length") or 0)
        cuerpo = json.loads(self.rfile.read(largo) or b"{}") if largo else {}
        codigo, datos = responder(self.command, ruta, parse_qs(partes.query), cuerpo)
        self._enviar(codigo, json.dumps(datos).encode(), "application/json")

    def _enviar(self, codigo: int, cuerpo: bytes, tipo: str) -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Accept-Ranges", "none")
        self.end_headers()
        self.wfile.write(cuerpo)

    do_GET = do_POST = do_PATCH = do_DELETE = _atender

    def log_message(self, *_):       # silencio: lo que importa es la pantalla
        pass


if __name__ == "__main__":
    print(f"API simulada en {BASE} (Ctrl+C para salir)")
    ThreadingHTTPServer(("127.0.0.1", PUERTO), Peticion).serve_forever()
