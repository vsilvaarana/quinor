"""Entrenamiento del modelo de sacos sobre el set sintetico. HU-07, criterio 2.

El modelo preentrenado de ultralytics conoce 80 clases de COCO y ninguna es un
saco de quinua. Para contar sacos hace falta un modelo que los reconozca, y para
tenerlo hace falta un dataset.

Mientras QUINOR no entregue fotogramas de la rampa, el dataset es el sintetico
de `sim/rampa_sim.py`. El entrenamiento parte de los pesos preentrenados, como
dice el apartado 9.1: con un dataset pequeno, entrenar desde cero no converge y
partir de COCO si.

Este script es el hermano pequeno del que pide HU-19. Cuando lleguen las
imagenes reales etiquetadas en CVAT, se apunta `--dataset` a esa carpeta y el
resto no cambia: el formato YOLO es el mismo.

    python -m sim.entrenar --epocas 40 --salida modelos/sacos.pt
"""
from __future__ import annotations

import argparse
import pathlib
import shutil

RAIZ = pathlib.Path(__file__).resolve().parent.parent
BASE_PREENTRENADA = RAIZ / "modelos" / "yolo11n.pt"


def entrenar(
    dataset: pathlib.Path,
    salida: pathlib.Path,
    *,
    epocas: int = 40,
    tamano: int = 640,
    base: pathlib.Path = BASE_PREENTRENADA,
    dispositivo: str = "cpu",
    paciencia: int = 100,
) -> dict:
    """Entrena y deja los pesos en `salida`. Devuelve las metricas de validacion."""
    from ultralytics import YOLO

    modelo = YOLO(str(base) if base.exists() else "yolo11n.pt")
    modelo.train(
        data=str(dataset),
        epochs=epocas,
        imgsz=tamano,
        device=dispositivo,
        project=str(salida.parent / "entrenamientos"),
        name=salida.stem,
        exist_ok=True,
        patience=paciencia,
        verbose=False,
        plots=False,
        # El set es sintetico y ya trae su variacion; el aumento de color y
        # mosaico de ultralytics solo alarga el entrenamiento aqui.
        mosaic=0.0,
        erasing=0.0,
        val=True,
    )
    mejores = salida.parent / "entrenamientos" / salida.stem / "weights" / "best.pt"
    salida.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(mejores, salida)

    metricas = modelo.metrics
    return {
        "pesos": str(salida),
        # mAP50-95 y mAP50 son las metricas que la tabla modelo_version guarda
        # en metrica_map, y las que HU-19 comparara para decidir el despliegue.
        "map50_95": round(float(getattr(metricas.box, "map", 0.0)), 4),
        "map50": round(float(getattr(metricas.box, "map50", 0.0)), 4),
    }


def main() -> int:      # pragma: no cover - punto de entrada
    from sim.rampa_sim import generar_dataset

    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--dataset", type=pathlib.Path, default=None,
                            help="data.yaml de un dataset YOLO. Si falta, se genera uno sintetico.")
    analizador.add_argument("--imagenes", type=int, default=240)
    analizador.add_argument("--epocas", type=int, default=40)
    analizador.add_argument("--tamano", type=int, default=640)
    analizador.add_argument("--dispositivo", default="cpu")
    analizador.add_argument("--salida", type=pathlib.Path,
                            default=RAIZ / "modelos" / "sacos.pt")
    argumentos = analizador.parse_args()

    dataset = argumentos.dataset
    if dataset is None:
        carpeta = RAIZ / "datos" / "sintetico"
        print(f"Generando dataset sintetico de {argumentos.imagenes} imagenes en {carpeta}")
        dataset = generar_dataset(carpeta, imagenes=argumentos.imagenes)

    resultado = entrenar(dataset, argumentos.salida, epocas=argumentos.epocas,
                         tamano=argumentos.tamano, dispositivo=argumentos.dispositivo)
    print(f"Modelo entrenado: {resultado['pesos']}")
    print(f"  mAP50:    {resultado['map50']}")
    print(f"  mAP50-95: {resultado['map50_95']}")
    return 0


if __name__ == "__main__":      # pragma: no cover
    raise SystemExit(main())
