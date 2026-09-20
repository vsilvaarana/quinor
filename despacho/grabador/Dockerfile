# =============================================================================
# Imagen del grabador de video (HU-05).
#
# Separada de la del orquestador porque necesita ffmpeg, que son unos 200 MB de
# codecs que la API no usa para nada. Tambien la usa el simulador de camaras,
# que publica con el mismo binario.
# =============================================================================
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=America/Lima

WORKDIR /code

# ffmpeg es el grabador de verdad: este servicio solo lo supervisa.
# El apartado 6.7 exige relojes sincronizados por NTP, y tzdata es lo que hace
# que la marca que -strftime escribe en el nombre sea la hora de planta.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg default-mysql-client tzdata \
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
# El usuario tiene que poder escribir en el volumen del buffer.
RUN useradd --create-home --uid 1000 quinor \
 && mkdir -p /video && chown -R quinor:quinor /code /video
USER quinor
CMD ["python", "-m", "app.grabador"]
