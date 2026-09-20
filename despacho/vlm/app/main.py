"""Servicio de vision-lenguaje de QUINOR S.A.C. HU-09.

Como supervisor de despacho, quiero que un modelo de vision-lenguaje describa lo
ocurrido en el clip y asigne un nivel de severidad, para priorizar que eventos
revisar primero.

Criterios de aceptacion:
  1. Solo se invoca cuando YOLO confirma diferencia de sacos o personal anomalo.
  2. La respuesta es un JSON con descripcion, severidad (Baja/Media/Alta) y
     evidencia observada.
  3. Si la API falla se reintenta 3 veces y luego se marca Pendiente de analisis.

El apartado 6.6 lo describe asi: `POST /analisis/vlm`, "envia fotogramas y datos
al modelo de vision-lenguaje". Va en su propio contenedor, como el de YOLO, por
una razon distinta: no son gigas de PyTorch, es que este es el unico servicio
del sistema que sale a internet. Tenerlo aparte deja esa salida en un solo sitio
que se puede cortar, vigilar y ponerle una cuota.

El criterio 3 lo cumple entre los dos: aqui se reintenta y se dice que fallo; el
grabador, que es quien tiene la base, marca el evento en Pendiente de analisis.
Ese estado existe en el apartado 5.3 y vuelve a Pendiente al reintentar.

Sobre la severidad. El criterio 2 pide que el modelo la devuelva, y se pide y se
guarda. Pero la que manda en el evento sale de la RN-04, que es una regla escrita
con umbrales exactos: una alerta de madrugada no puede depender de la temperatura
de un modelo. Las dos viajan en la respuesta y de compararlas sale la
concordancia semanal del apartado 9.2.
"""
from __future__ import annotations

import contextlib
import logging

import structlog
from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader

from app import invocacion, severidad as regla, vlm
from app.config import Ajustes, cargar_ajustes
from app.proveedores import Imagen
from app.prompt import pie_de_imagen
from app.schemas import (AnalisisLeido, PeticionDeAnalisis, RespuestaDeAnalisis,
                         RespuestaDeSalud)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _configurar_logging(nivel: str) -> None:
    logging.basicConfig(format="%(message)s",
                        level=getattr(logging, nivel.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )


def create_app(
    proveedor: str = None,
    api_key_proveedor: str = None,
    modelo: str = None,
    base_url: str = None,
    intentos: int = None,
    espera_inicial_s: float = None,
    api_key: str = None,
    ajustes: Ajustes = None,
    cliente=None,
    dormir=None,
) -> FastAPI:
    """Construye una instancia del servicio.

    `cliente` y `dormir` se pueden inyectar: es lo que permite comprobar los
    tres reintentos del criterio 3 sin esperarlos de verdad ni salir a internet.
    """
    ajustes = ajustes or cargar_ajustes(
        proveedor=proveedor, api_key=api_key_proveedor, modelo=modelo,
        base_url=base_url, intentos=intentos, espera_inicial_s=espera_inicial_s)
    _configurar_logging(ajustes.log_level)
    log = structlog.get_logger("quinor.vlm.api")

    # Como en el de YOLO: este servicio vive en la red interna del apartado 8 y
    # solo lo llama el grabador. La clave evita que cualquier cosa de esa red le
    # mande eventos a analizar, que aqui ademas cuesta dinero por llamada.
    clave = api_key if api_key is not None else _api_key_del_entorno()

    @contextlib.asynccontextmanager
    async def ciclo_de_vida(app_: FastAPI):
        if not ajustes.configurado:
            log.error(
                "sin_clave",
                detalle=(f"VLM_PROVIDER es '{ajustes.proveedor}' y VLM_API_KEY "
                         f"esta vacia. El servicio arranca y responde 503 hasta "
                         f"que exista la clave."))
        elif vlm.es_stub(ajustes):
            log.warning(
                "proveedor_stub",
                detalle=("Se esta hablando con el stub de desarrollo, no con un "
                         "modelo. Las descripciones no son analisis reales."))
        else:
            log.info("proveedor_listo", proveedor=ajustes.proveedor,
                     modelo=ajustes.modelo)
        yield

    app = FastAPI(
        title="QUINOR - Servicio de vision-lenguaje",
        description="Describe lo ocurrido en el clip de un evento y asigna "
                    "severidad (HU-09). La severidad del evento sale de la "
                    "RN-04; la del modelo se guarda aparte para medir la "
                    "concordancia del apartado 9.2.",
        version="1.0.0",
        lifespan=ciclo_de_vida,
    )
    app.state.ajustes = ajustes

    def requiere_clave(entregada: str = Security(api_key_header)) -> None:
        if not clave:
            return
        import secrets as _secrets

        if not entregada or not _secrets.compare_digest(entregada, clave):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                                detail="Clave de servicio invalida")

    @app.get("/", tags=["servicio"])
    def info():
        """Lo unico publico: healthcheck del compose, sin analizar nada."""
        return {
            "servicio": "Servicio de vision-lenguaje de QUINOR",
            "version": app.version,
            "historia": "HU-09 descripcion del evento y severidad",
            "documentacion": "/docs",
        }

    @app.get("/salud", response_model=RespuestaDeSalud, tags=["servicio"],
             dependencies=[Depends(requiere_clave)])
    def salud() -> RespuestaDeSalud:
        """Sin clave el servicio esta en pie pero no puede pedir nada, y eso hay
        que saberlo antes del primer evento y no con el camion en la rampa."""
        listo = ajustes.configurado
        stub = vlm.es_stub(ajustes)
        mensaje = None
        if not listo:
            mensaje = (f"Falta VLM_API_KEY para el proveedor "
                       f"'{ajustes.proveedor}': el analisis respondera 503.")
        elif stub:
            mensaje = ("Proveedor 'stub': las respuestas son de desarrollo, no "
                       "analisis reales de un modelo.")
        return RespuestaDeSalud(
            estado="ok" if listo and not stub else
                   ("degradado" if listo else "error"),
            proveedor=ajustes.proveedor,
            modelo=ajustes.modelo,
            configurado=listo,
            es_stub=stub,
            intentos=ajustes.intentos,
            mensaje=mensaje,
        )

    @app.post("/analisis/vlm", response_model=RespuestaDeAnalisis,
              tags=["analisis"], dependencies=[Depends(requiere_clave)],
              summary="Describe el evento y asigna severidad (HU-09)")
    def analizar_evento(cuerpo: PeticionDeAnalisis) -> RespuestaDeAnalisis:
        """Los tres criterios, en este orden: se decide, se pide, se valida."""
        # --- Criterio 1 y RN-03 ------------------------------------------
        decision = invocacion.decidir(
            diferencia_sacos=cuerpo.diferencia_sacos,
            sacos_salientes=cuerpo.sacos_salientes,
            personal_anomalo=cuerpo.personal_anomalo)

        if not decision.invocar and not cuerpo.forzar:
            log.info("no_invocado", evento_id=cuerpo.evento_id,
                     motivo=decision.codigo)
            # La severidad si se calcula: la RN-04 no necesita al modelo, y una
            # carga con el peso corto y los sacos completos es Baja con o sin
            # descripcion. Dejarla en blanco obligaria a HU-11 a ordenar sin
            # criterio la mitad de la cola.
            nivel = _severidad(cuerpo)
            return RespuestaDeAnalisis(
                invocado=False, motivo_de_invocacion=decision.codigo,
                explicacion=decision.explicacion,
                severidad=nivel.nivel, motivo_de_severidad=nivel.motivo)

        if cuerpo.forzar and not decision.invocar:
            log.info("invocacion_forzada", evento_id=cuerpo.evento_id,
                     motivo_original=decision.codigo)

        # --- Criterios 2 y 3 ---------------------------------------------
        imagenes = [
            Imagen(base64=f.jpeg_base64,
                   pie=pie_de_imagen({"segundo": f.segundo, "motivo": f.motivo,
                                      "detalle": f.detalle}))
            for f in cuerpo.fotogramas]
        try:
            analisis = vlm.analizar(ajustes, cuerpo.model_dump(), imagenes,
                                    cliente=cliente,
                                    dormir=dormir or __import__("time").sleep)
        except vlm.SinConfigurar as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                                detail=str(exc)) from exc
        except vlm.AnalisisFallido as exc:
            # Criterio 3. No es un 500: el servicio funciono, lo que fallo fue
            # el proveedor. Quien llama marca el evento en Pendiente de analisis.
            log.error("analisis_fallido", evento_id=cuerpo.evento_id,
                      intentos=exc.intentos, motivo=exc.ultimo_motivo)
            nivel = _severidad(cuerpo)
            return RespuestaDeAnalisis(
                invocado=True, motivo_de_invocacion=decision.codigo,
                explicacion=decision.explicacion,
                severidad=nivel.nivel, motivo_de_severidad=nivel.motivo,
                fallo=True, motivo_del_fallo=str(exc), intentos=exc.intentos)

        nivel = _severidad(cuerpo)
        return RespuestaDeAnalisis(
            invocado=True, motivo_de_invocacion=decision.codigo,
            explicacion=decision.explicacion,
            severidad=nivel.nivel, motivo_de_severidad=nivel.motivo,
            concuerdan=analisis.severidad_ia == nivel.nivel,
            analisis=AnalisisLeido(**analisis.a_json()),
            intentos=analisis.intentos)

    return app


def _severidad(cuerpo: PeticionDeAnalisis) -> regla.Severidad:
    """La del evento, por la RN-04. No depende del modelo ni de que responda."""
    return regla.calcular(
        diferencia_sacos=cuerpo.diferencia_sacos,
        sacos_salientes=cuerpo.sacos_salientes,
        personal_anomalo=bool(cuerpo.personal_anomalo),
        hay_diferencia_de_peso=bool(cuerpo.diferencia_kg))


def _api_key_del_entorno() -> str:
    import os

    return os.environ.get("VLM_SERVICE_API_KEY", "")


if __name__ == "__main__":      # pragma: no cover
    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=8003)
