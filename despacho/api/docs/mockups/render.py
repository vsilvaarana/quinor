"""Convierte cada mockup HTML en un PNG, para pegarlo en el documento."""
import asyncio
import pathlib
import sys

from playwright.async_api import async_playwright

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
AQUI = pathlib.Path(__file__).resolve().parent


async def main():
    ancho = int(sys.argv[1]) if len(sys.argv) > 1 else 1480
    async with async_playwright() as p:
        nav = await p.chromium.launch(executable_path=CHROME)
        pag = await nav.new_page(viewport={"width": ancho, "height": 1200},
                                 device_scale_factor=2)
        for fuente in sorted(AQUI.glob("opcion_*.html")):
            await pag.goto(fuente.as_uri(), wait_until="networkidle")
            await pag.wait_for_timeout(600)
            destino = fuente.with_suffix(".png")
            await pag.screenshot(path=str(destino), full_page=True)
            print(destino.name, destino.stat().st_size // 1024, "KB")
        await nav.close()


asyncio.run(main())
