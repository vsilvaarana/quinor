"""Saca las capturas del manual de usuario con datos de ejemplo.

Levanta la API simulada (`api_simulada.py`) y el dashboard, recorre las
pantallas con un navegador sin ventana y guarda un PNG de cada una en
`docs/ux/capturas/`. Las capturas son del codigo real del dashboard, pero los
datos son inventados: sirven para el manual, no como evidencia de una historia.

Uso, desde despacho/api:

    pip install playwright && playwright install chromium   # una sola vez
    python docs/ux/capturar.py

Necesita streamlit en el mismo interprete, o la variable STREAMLIT con la ruta
de su ejecutable.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import Page, sync_playwright

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]                       # despacho/api
SALIDA = AQUI / "capturas"
PUERTO_API, PUERTO_WEB = 8999, 8601
WEB = f"http://127.0.0.1:{PUERTO_WEB}"
SUPERVISOR, ADMINISTRADOR = "luis.paredes@quinor.local", "ana.torres@quinor.local"


def esperar(url: str, segundos: int = 60) -> None:
    limite = time.time() + segundos
    while time.time() < limite:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:               # noqa: BLE001 - todavia no arranco
            time.sleep(0.5)
    raise RuntimeError(f"{url} no respondio en {segundos} s")


def quieta(pagina: Page) -> None:
    """Espera a que Streamlit termine de redibujar."""
    pagina.wait_for_timeout(600)
    pagina.wait_for_function(
        """() => !document.querySelector('[data-testid="stStatusWidget"]')""", timeout=30000)
    pagina.wait_for_timeout(500)


def captura(pagina: Page, nombre: str, alto: int = 900) -> None:
    # Streamlit desplaza un contenedor interno, no la pagina: para que la
    # captura muestre la pantalla entera se agranda la ventana.
    pagina.set_viewport_size({"width": 1440, "height": alto})
    quieta(pagina)
    pagina.screenshot(path=str(SALIDA / f"{nombre}.png"))
    print("  ", nombre)


def entrar(pagina: Page, correo: str) -> None:
    pagina.goto(WEB)
    pagina.get_by_label("Correo electrónico").fill(correo)
    pagina.get_by_label("Contraseña").fill("clave-de-ejemplo")
    pagina.get_by_role("button", name="Iniciar sesión").click()
    pagina.get_by_role("button", name="Cerrar sesión").wait_for()
    quieta(pagina)


def menu(pagina: Page, pantalla: str) -> None:
    pagina.locator('[data-testid="stSidebarNav"]').get_by_text(pantalla, exact=False).first.click()
    quieta(pagina)


def recorrer(pagina: Page) -> None:
    pagina.goto(WEB)
    pagina.get_by_role("button", name="Iniciar sesión").wait_for()
    captura(pagina, "01_ingreso", 760)

    entrar(pagina, SUPERVISOR)
    captura(pagina, "02_eventos", 1000)
    pagina.get_by_role("button", name="Ver detalle").first.click()
    pagina.get_by_role("button", name="← Volver a Eventos").wait_for()
    captura(pagina, "03_evento", 2300)
    pagina.get_by_role("button", name="← Volver a Eventos").click()

    menu(pagina, "Registro de pesada")
    captura(pagina, "04_pesada_paso_1_orden", 800)
    pagina.get_by_label("Número de orden de despacho").fill("ORD-2026-0152")
    pagina.get_by_role("button", name="Consultar orden").click()
    pagina.get_by_role("button", name="Iniciar carga").wait_for()
    captura(pagina, "05_pesada_paso_2_carga", 850)
    pagina.get_by_role("button", name="Iniciar carga").click()
    pagina.get_by_role("button", name="Leer báscula").wait_for()
    captura(pagina, "06_pesada_paso_3_pesaje", 900)
    pagina.get_by_role("button", name="Leer báscula").click()
    pagina.get_by_role("button", name="Registrar pesada y cerrar carga").wait_for()
    captura(pagina, "07_pesada_lectura_previa", 1150)
    pagina.get_by_role("button", name="Registrar pesada y cerrar carga").click()
    pagina.get_by_role("button", name="Registrar otra pesada").wait_for()
    captura(pagina, "08_pesada_resultado", 1000)

    menu(pagina, "Tolerancias")
    captura(pagina, "09_tolerancias_supervisor", 900)
    pagina.get_by_role("button", name="Cerrar sesión").click()

    entrar(pagina, ADMINISTRADOR)
    menu(pagina, "Tolerancias")
    captura(pagina, "10_tolerancias_administrador", 950)
    menu(pagina, "Usuarios")
    captura(pagina, "11_usuarios", 800)
    pagina.get_by_role("button", name="Desactivar").nth(1).click()
    pagina.get_by_role("button", name="Desactivar usuario").wait_for()
    captura(pagina, "12_confirmacion", 800)
    pagina.get_by_role("button", name="Cancelar").click()
    menu(pagina, "Tokens de acceso")
    captura(pagina, "13_tokens", 700)


def main() -> None:
    SALIDA.mkdir(exist_ok=True)
    streamlit = os.environ.get("STREAMLIT") or [sys.executable, "-m", "streamlit"]
    streamlit = [streamlit] if isinstance(streamlit, str) else streamlit
    entorno = {**os.environ, "API_INTERNAL_URL": f"http://127.0.0.1:{PUERTO_API}"}
    procesos = [
        subprocess.Popen([sys.executable, str(AQUI / "api_simulada.py")],
                         stdout=subprocess.DEVNULL),
        subprocess.Popen(
            [*streamlit, "run", "dashboard/app.py", "--server.port", str(PUERTO_WEB),
             "--server.headless", "true", "--server.address", "127.0.0.1"],
            cwd=RAIZ, env=entorno, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
    ]
    try:
        esperar(f"http://127.0.0.1:{PUERTO_API}/salud")
        esperar(f"{WEB}/_stcore/health")
        with sync_playwright() as p:
            navegador = p.chromium.launch(channel=os.environ.get("NAVEGADOR", "chromium"))
            pagina = navegador.new_page(viewport={"width": 1440, "height": 900},
                                        locale="es-PE", timezone_id="America/Lima")
            recorrer(pagina)
            navegador.close()
    finally:
        for proceso in procesos:
            proceso.terminate()


if __name__ == "__main__":
    main()
