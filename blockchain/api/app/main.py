"""API REST de despachos sobre una red blockchain simulada (2 nodos).

Autenticación por API key en el header X-API-Key.
"""

import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, Field

from app.blockchain import BlockchainNetwork

DEFAULT_API_KEY = "quinor-secret-key"
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class DespachoRequest(BaseModel):
    """Campos básicos de un despacho."""

    producto: str = Field(..., min_length=1, description="Producto despachado")
    cantidad: float = Field(..., gt=0, description="Cantidad despachada")
    unidad: str = Field("kg", min_length=1, description="Unidad de medida")
    origen: str = Field(..., min_length=1, description="Punto de origen")
    destino: str = Field(..., min_length=1, description="Punto de destino")
    transportista: str = Field(..., min_length=1, description="Empresa transportista")
    conductor: Optional[str] = Field(None, description="Nombre del conductor")
    placa_vehiculo: Optional[str] = Field(None, description="Placa del vehículo")
    observaciones: Optional[str] = Field(None, description="Observaciones")


def create_app(data_dir: str = None, api_key: str = None) -> FastAPI:
    data_dir = data_dir or os.environ.get("DATA_DIR", "./data")
    expected_key = api_key or os.environ.get("API_KEY", DEFAULT_API_KEY)

    network = BlockchainNetwork(data_dir)
    app = FastAPI(
        title="API de Despachos Blockchain",
        description="Registro de despachos replicado en 2 nodos blockchain sobre LevelDB",
        version="1.0.0",
    )
    app.state.network = network

    def require_api_key(provided: str = Security(api_key_header)) -> str:
        if not provided or not secrets.compare_digest(provided, expected_key):
            raise HTTPException(status_code=401, detail="API key inválida o ausente")
        return provided

    auth = [Depends(require_api_key)]

    def _get_node_or_404(node_id: str):
        node = network.get_node(node_id)
        if node is None:
            raise HTTPException(status_code=404, detail=f"Nodo '{node_id}' no existe")
        return node

    @app.get("/")
    def info():
        return {
            "servicio": "API de Despachos Blockchain",
            "nodos": list(network.nodes.keys()),
            "autenticacion": "header X-API-Key",
        }

    @app.post("/despachos", status_code=201, dependencies=auth)
    def crear_despacho(despacho: DespachoRequest):
        data = despacho.model_dump()
        data["id_despacho"] = uuid.uuid4().hex
        data["fecha_registro"] = datetime.now(timezone.utc).isoformat()
        block = network.registrar_despacho(data)
        return {
            "mensaje": "Despacho registrado en ambos nodos",
            "id_despacho": data["id_despacho"],
            "bloque": block.index,
            "hash": block.hash,
            "despacho": data,
        }

    @app.get("/despachos", dependencies=auth)
    def listar_despachos():
        despachos = network.get_node("nodo1").list_despachos()
        return {"total": len(despachos), "despachos": despachos}

    @app.get("/despachos/{despacho_id}", dependencies=auth)
    def obtener_despacho(despacho_id: str):
        block = network.get_node("nodo1").get_despacho_block(despacho_id)
        if block is None:
            raise HTTPException(
                status_code=404, detail=f"Despacho '{despacho_id}' no encontrado"
            )
        return {"bloque": block.index, "hash": block.hash, "despacho": block.data}

    @app.get("/nodos", dependencies=auth)
    def listar_nodos():
        return {
            node_id: {
                "altura": node.height,
                "ultimo_hash": node.last_block.hash,
            }
            for node_id, node in network.nodes.items()
        }

    @app.get("/nodos/{node_id}/cadena", dependencies=auth)
    def obtener_cadena(node_id: str):
        node = _get_node_or_404(node_id)
        return {
            "nodo": node_id,
            "altura": node.height,
            "cadena": [block.to_dict() for block in node.get_chain()],
        }

    @app.get("/nodos/{node_id}/validar", dependencies=auth)
    def validar_cadena(node_id: str):
        node = _get_node_or_404(node_id)
        return {"nodo": node_id, "valida": node.is_valid()}

    @app.get("/consenso", dependencies=auth)
    def consenso():
        return network.consenso()

    return app


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=8000)
