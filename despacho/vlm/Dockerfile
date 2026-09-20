# =============================================================================
# Imagen del servicio de vision-lenguaje (HU-09).
#
# Es la mas pequena de las cuatro: aqui no hay modelo, hay una llamada HTTP.
# Va en su propio contenedor por lo contrario que el de YOLO: no por tamano,
# sino porque es el unico servicio que sale a internet. Tenerlo aparte deja esa
# salida en un solo sitio que se puede cortar, vigilar y ponerle una cuota.
#
# La clave del proveedor no entra en la imagen: llega por variable de entorno o
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
EXPOSE 8003
CMD ["uvicorn", "app.main:create_app", "--factory", \
     "--host=0.0.0.0", "--port=8003"]
