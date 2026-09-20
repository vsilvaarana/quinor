"""Generador del set de validacion sintetico. HU-07, criterio 2.

QUINOR todavia no ha entregado imagenes de la rampa: el dataset propio, con
fotogramas etiquetados en CVAT o Label Studio, es HU-19. Sin imagenes reales no
hay contra que medir el 95 % que pide el criterio 2.

Este modulo genera el material que si permite medirlo: clips en los que un
numero conocido de sacos cruza la linea de carga, y las imagenes etiquetadas en
formato YOLO para entrenar un modelo que los reconozca.

Lo que eso mide, y lo que no. Mide el contador: deteccion, seguimiento,
oclusiones, sacos que vuelven atras, cruces a distinta velocidad. No mide como
se comportara el modelo con sacos de yute reales, polvo y contraluz; esa cifra
sale del piloto con el dataset de HU-19. El README lo dice con todas las letras
y el reporte de validacion lo repite en su cabecera.

Un saco se dibuja como un rectangulo claro con textura, del tamano relativo que
tiene un saco de 50 kg en el cuadro de una camara de rampa.
"""
from __future__ import annotations

import dataclasses
import pathlib
import random

import numpy as np

# Un saco de 50 kg visto desde la camara de rampa ocupa aproximadamente esto.
ANCHO_SACO = 0.10
ALTO_SACO = 0.07
# Un operario cruzando el cuadro: mas alto que ancho.
ANCHO_PERSONA = 0.07
ALTO_PERSONA = 0.28

COLOR_FONDO = (70, 75, 80)
COLOR_SACO = (190, 175, 140)
COLOR_PERSONA = (40, 60, 120)
COLOR_LINEA = (0, 200, 255)


@dataclasses.dataclass(frozen=True)
class Caja:
    """Caja en coordenadas relativas, como las que espera YOLO."""

    clase: int
    x: float
    y: float
    ancho: float
    alto: float

    def a_pixeles(self, w: int, h: int) -> tuple[int, int, int, int]:
        x1 = int((self.x - self.ancho / 2) * w)
        y1 = int((self.y - self.alto / 2) * h)
        x2 = int((self.x + self.ancho / 2) * w)
        y2 = int((self.y + self.alto / 2) * h)
        return x1, y1, x2, y2


@dataclasses.dataclass
class _Movil:
    """Un objeto que atraviesa el cuadro."""

    clase: int
    x: float
    y: float
    dx: float
    ancho: float
    alto: float
    aparece_en: int
    desaparece_en: int

    def visible(self, fotograma: int) -> bool:
        return self.aparece_en <= fotograma < self.desaparece_en

    def posicion(self, fotograma: int) -> tuple[float, float]:
        return self.x + self.dx * (fotograma - self.aparece_en), self.y


def _textura(alto: int, ancho: int, color, semilla: int) -> np.ndarray:
    """Un rectangulo liso no se parece a un saco ni entrena nada util."""
    generador = np.random.default_rng(semilla)
    base = np.full((alto, ancho, 3), color, dtype=np.int16)
    ruido = generador.integers(-22, 22, size=(alto, ancho, 1))
    return np.clip(base + ruido, 0, 255).astype(np.uint8)


def _dibujar(lienzo: np.ndarray, caja: Caja, color, semilla: int) -> None:
    alto, ancho = lienzo.shape[:2]
    x1, y1, x2, y2 = caja.a_pixeles(ancho, alto)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(ancho, x2), min(alto, y2)
    if x2 <= x1 or y2 <= y1:
        return
    lienzo[y1:y2, x1:x2] = _textura(y2 - y1, x2 - x1, color, semilla)
    # Un borde oscuro: sin el, dos sacos pegados se ven como una mancha y el
    # detector aprende a juntarlos.
    lienzo[y1:y1 + 2, x1:x2] = 30
    lienzo[y2 - 2:y2, x1:x2] = 30
    lienzo[y1:y2, x1:x1 + 2] = 30
    lienzo[y1:y2, x2 - 2:x2] = 30


@dataclasses.dataclass(frozen=True)
class Carga:
    """Un clip sintetico con su verdad conocida."""

    ruta: pathlib.Path
    sacos_reales: int
    sacos_que_vuelven: int
    personas: int
    fotogramas: int
    fps: int


def generar_carga(
    destino: pathlib.Path,
    sacos: int,
    *,
    semilla: int = 0,
    fps: int = 10,
    ancho: int = 640,
    alto: int = 360,
    con_personas: int = 1,
    sacos_que_vuelven: int = 0,
    con_oclusiones: bool = True,
    dibujar_linea: bool = False,
) -> Carga:
    """Genera un clip donde exactamente `sacos` cruzan la linea de izquierda a derecha.

    `sacos_que_vuelven` cruzan y regresan: es el caso de la RN-04, un saco que
    sale de la zona de carga, y el que distingue contar cruces de contar sacos.
    """
    import cv2

    azar = random.Random(semilla)
    total = sacos + sacos_que_vuelven
    # Espacio de sobra entre sacos para que el rastreador no los confunda, y
    # margen al final para que el ultimo termine de cruzar.
    separacion = 8
    fotogramas = separacion * (total + 1) + 40

    moviles: list[_Movil] = []
    for indice in range(total):
        aparece = 10 + indice * separacion
        vuelve = indice >= sacos
        moviles.append(_Movil(
            clase=0,
            x=-0.08 if not vuelve else -0.08,
            y=azar.uniform(0.35, 0.65),
            dx=azar.uniform(0.030, 0.045),
            ancho=ANCHO_SACO, alto=ALTO_SACO,
            aparece_en=aparece,
            desaparece_en=aparece + 40,
        ))
    # Los que vuelven se tratan al dibujar: recorren y regresan.
    que_vuelven = set(range(sacos, total))

    if con_personas:
        for persona in range(con_personas):
            moviles.append(_Movil(
                clase=1, x=1.05, y=0.55, dx=-0.012,
                ancho=ANCHO_PERSONA, alto=ALTO_PERSONA,
                aparece_en=5 + persona * 20,
                desaparece_en=fotogramas,
            ))

    destino.parent.mkdir(parents=True, exist_ok=True)
    etiquetas: dict[int, list[Caja]] = {}
    escritor = cv2.VideoWriter(str(destino), cv2.VideoWriter_fourcc(*"mp4v"),
                               fps, (ancho, alto))
    try:
        for fotograma in range(fotogramas):
            lienzo = _textura(alto, ancho, COLOR_FONDO, semilla * 1000 + fotograma)
            if dibujar_linea:
                lienzo[:, ancho // 2 - 1:ancho // 2 + 1] = COLOR_LINEA
            cajas = []
            for indice, movil in enumerate(moviles):
                if not movil.visible(fotograma):
                    continue
                x, y = movil.posicion(fotograma)
                if indice in que_vuelven and x > 0.75:
                    # Ya paso la linea: da media vuelta y se sale por donde entro.
                    x = 1.5 - x
                if not -0.2 < x < 1.2:
                    continue
                caja = Caja(clase=movil.clase, x=x, y=y,
                            ancho=movil.ancho, alto=movil.alto)
                color = COLOR_SACO if movil.clase == 0 else COLOR_PERSONA
                # Las personas se dibujan encima: son las que tapan sacos, que es
                # la oclusion que el apartado 11 senala como riesgo.
                cajas.append((movil.clase, caja, color, semilla * 100 + indice))
            cajas.sort(key=lambda c: c[0])
            for _clase, caja, color, sem in cajas:
                if not con_oclusiones and _clase == 1:
                    continue
                _dibujar(lienzo, caja, color, sem)
            etiquetas[fotograma] = [c[1] for c in cajas]
            escritor.write(lienzo)
    finally:
        escritor.release()

    return Carga(ruta=destino, sacos_reales=sacos, sacos_que_vuelven=sacos_que_vuelven,
                 personas=con_personas, fotogramas=fotogramas, fps=fps)


def generar_dataset(
    carpeta: pathlib.Path,
    imagenes: int = 240,
    *,
    semilla: int = 7,
    ancho: int = 640,
    alto: int = 360,
    proporcion_validacion: float = 0.2,
) -> pathlib.Path:
    """Escribe un dataset en formato YOLO y devuelve la ruta de su data.yaml.

    Formato YOLO: una imagen y un .txt por imagen, con `clase x y ancho alto` en
    coordenadas relativas. Es el mismo formato que HU-19 espera del etiquetado
    en CVAT, de modo que cambiar este dataset por el real sera cambiar la carpeta.
    """
    import cv2

    azar = random.Random(semilla)
    for division in ("train", "val"):
        (carpeta / "images" / division).mkdir(parents=True, exist_ok=True)
        (carpeta / "labels" / division).mkdir(parents=True, exist_ok=True)

    for indice in range(imagenes):
        division = "val" if indice < int(imagenes * proporcion_validacion) else "train"
        lienzo = _textura(alto, ancho, COLOR_FONDO, semilla * 10_000 + indice)
        cajas: list[Caja] = []

        for _ in range(azar.randint(1, 4)):
            cajas.append(Caja(clase=0,
                              x=azar.uniform(0.12, 0.88), y=azar.uniform(0.25, 0.75),
                              ancho=ANCHO_SACO * azar.uniform(0.85, 1.15),
                              alto=ALTO_SACO * azar.uniform(0.85, 1.15)))
        for _ in range(azar.randint(0, 2)):
            cajas.append(Caja(clase=1,
                              x=azar.uniform(0.1, 0.9), y=azar.uniform(0.3, 0.7),
                              ancho=ANCHO_PERSONA, alto=ALTO_PERSONA))

        for orden, caja in enumerate(sorted(cajas, key=lambda c: c.clase)):
            color = COLOR_SACO if caja.clase == 0 else COLOR_PERSONA
            _dibujar(lienzo, caja, color, semilla + indice * 10 + orden)

        nombre = f"rampa_{indice:04d}"
        cv2.imwrite(str(carpeta / "images" / division / f"{nombre}.jpg"), lienzo)
        (carpeta / "labels" / division / f"{nombre}.txt").write_text(
            "".join(f"{c.clase} {c.x:.6f} {c.y:.6f} {c.ancho:.6f} {c.alto:.6f}\n"
                    for c in cajas),
            encoding="utf-8")

    configuracion = carpeta / "data.yaml"
    configuracion.write_text(
        f"path: {carpeta.resolve()}\n"
        "train: images/train\n"
        "val: images/val\n"
        "names:\n"
        "  0: saco\n"
        "  1: person\n",
        encoding="utf-8")
    return configuracion
