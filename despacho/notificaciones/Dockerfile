# =============================================================================
# Imagen del servicio de notificaciones (HU-10).
#
# Pequena, como la del servicio de vision-lenguaje y por la misma razon: aqui no
# hay modelo, hay una conexion SMTP. Va en su propio contenedor porque es uno de
# los dos servicios que hablan con un servidor de fuera, y tenerlo aparte deja
# esa salida en un sitio que se puede cortar, vigilar y limitar.
#
# La contrasena del buzon no entra en la imagen: llega por variable de entorno o
# por secreto de Docker, como manda el apartado 8.
# =============================================================================
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=America/Lima

WORKDIR /code

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl tzdata \
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
RUN useradd --create-home --uid 1000 quinor && chown -R quinor:quinor /code
USER quinor
EXPOSE 8004
CMD ["uvicorn", "app.main:create_app", "--factory", \
     "--host=0.0.0.0", "--port=8004"]
