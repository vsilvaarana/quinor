# =============================================================================
# Imagen del servicio YOLO de conteo de sacos (HU-07).
#
# Separada de las otras dos porque PyTorch y sus dependencias son varios gigas
# que ni el orquestador ni el grabador usan, y porque en planta la GPU del
# RNF-06 se le asigna solo a este contenedor.
#
# La imagen no trae el modelo: los pesos llegan por volumen (/modelos) para
# poder cambiarlos sin reconstruir nada, que es lo que HU-19 va a necesitar
# cuando el modelo se reentrene con el dataset real de la rampa.
# =============================================================================
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=America/Lima \
    # ultralytics escribe sus ajustes y descargas aqui; sin esto intenta
    # escribir en el home de root y falla al correr como usuario sin permisos.
    YOLO_CONFIG_DIR=/tmp/ultralytics

WORKDIR /code

# libgl1 y libglib: opencv-python-headless sigue necesitando estas dos para
# abrir video. ffmpeg: los clips del grabador son matroska.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ffmpeg libgl1 libglib2.0-0 tzdata curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

# --- Etapa de desarrollo: la que usa docker-compose --------------------------
FROM base AS dev
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
COPY . .

# --- Etapa de produccion: sin herramientas de prueba -------------------------
FROM base AS runtime
COPY . .
RUN useradd --create-home --uid 1000 quinor \
 && mkdir -p /modelos /video /tmp/ultralytics \
 && chown -R quinor:quinor /code /modelos /tmp/ultralytics
USER quinor
EXPOSE 8002
CMD ["uvicorn", "app.main:create_app", "--factory", \
     "--host=0.0.0.0", "--port=8002"]
