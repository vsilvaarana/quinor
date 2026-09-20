# =============================================================================
# Imagen unica compartida por api, dashboard, scale-sim y erp-mock.
# Mantener una sola imagen simplifica el Sprint 1; cuando el servicio YOLO
# entre en el Sprint 3 necesitara su propia imagen con CUDA.
# =============================================================================
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=America/Lima

WORKDIR /code

# curl: healthcheck de los servicios HTTP.
# default-mysql-client: diagnostico manual contra el contenedor de MySQL.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl default-mysql-client tzdata \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

# --- Etapa de desarrollo: la que usa docker-compose en el Sprint 1 -----------
FROM base AS dev
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
COPY . .

# --- Etapa de produccion: sin herramientas de prueba -------------------------
FROM base AS runtime
COPY . .
RUN useradd --create-home --uid 1000 quinor && chown -R quinor:quinor /code
USER quinor
