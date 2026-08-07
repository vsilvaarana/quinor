"""Simulación de nodos blockchain con persistencia en LevelDB.

Cada nodo mantiene su propia base LevelDB. Los bloques se encadenan
mediante hashes SHA-256 y cada despacho registrado queda indexado
para consulta directa.
"""

import hashlib
import json
import os
import time

import plyvel

KEY_HEIGHT = b"height"
GENESIS_HASH = "0" * 64


def _block_key(index: int) -> bytes:
    return f"block:{index:010d}".encode()


def _despacho_key(despacho_id: str) -> bytes:
    return f"despacho:{despacho_id}".encode()


class Block:
    """Bloque de la cadena."""

    def __init__(self, index, timestamp, data, previous_hash, hash=None):
        self.index = index
        self.timestamp = timestamp
        self.data = data
        self.previous_hash = previous_hash
        self.hash = hash or self.compute_hash()

    def compute_hash(self) -> str:
        payload = json.dumps(
            {
                "index": self.index,
                "timestamp": self.timestamp,
                "data": self.data,
                "previous_hash": self.previous_hash,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "data": self.data,
            "previous_hash": self.previous_hash,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Block":
        return cls(
            index=raw["index"],
            timestamp=raw["timestamp"],
            data=raw["data"],
            previous_hash=raw["previous_hash"],
            hash=raw["hash"],
        )


class BlockchainNode:
    """Nodo blockchain respaldado por una base LevelDB propia."""

    def __init__(self, node_id: str, db_path: str):
        self.node_id = node_id
        self.db = plyvel.DB(db_path, create_if_missing=True)
        if self.height == 0:
            genesis = Block(0, 0.0, {"genesis": True}, GENESIS_HASH)
            self._store_block(genesis)

    @property
    def height(self) -> int:
        raw = self.db.get(KEY_HEIGHT)
        return int(raw) if raw else 0

    def _store_block(self, block: Block) -> None:
        with self.db.write_batch() as batch:
            batch.put(_block_key(block.index), json.dumps(block.to_dict()).encode())
            batch.put(KEY_HEIGHT, str(block.index + 1).encode())
            despacho_id = block.data.get("id_despacho")
            if despacho_id:
                batch.put(_despacho_key(despacho_id), str(block.index).encode())

    def get_block(self, index: int):
        raw = self.db.get(_block_key(index))
        if raw is None:
            return None
        return Block.from_dict(json.loads(raw))

    @property
    def last_block(self) -> Block:
        return self.get_block(self.height - 1)

    def add_block(self, data: dict, timestamp: float = None) -> Block:
        previous = self.last_block
        block = Block(
            index=previous.index + 1,
            timestamp=timestamp if timestamp is not None else time.time(),
            data=data,
            previous_hash=previous.hash,
        )
        self._store_block(block)
        return block

    def get_chain(self) -> list:
        return [self.get_block(i) for i in range(self.height)]

    def is_valid(self) -> bool:
        chain = self.get_chain()
        for i, block in enumerate(chain):
            if block.hash != block.compute_hash():
                return False
            if i > 0 and block.previous_hash != chain[i - 1].hash:
                return False
        return True

    def get_despacho_block(self, despacho_id: str):
        raw = self.db.get(_despacho_key(despacho_id))
        if raw is None:
            return None
        return self.get_block(int(raw))

    def list_despachos(self) -> list:
        result = []
        for block in self.get_chain()[1:]:
            result.append({"bloque": block.index, "hash": block.hash, **block.data})
        return result

    def close(self) -> None:
        self.db.close()


class BlockchainNetwork:
    """Red simulada de dos nodos que replican cada despacho."""

    NODE_IDS = ("nodo1", "nodo2")

    def __init__(self, base_dir: str):
        os.makedirs(base_dir, exist_ok=True)
        self.nodes = {
            node_id: BlockchainNode(node_id, os.path.join(base_dir, node_id))
            for node_id in self.NODE_IDS
        }

    def get_node(self, node_id: str):
        return self.nodes.get(node_id)

    def registrar_despacho(self, data: dict) -> Block:
        timestamp = time.time()
        blocks = [node.add_block(data, timestamp) for node in self.nodes.values()]
        return blocks[0]

    def consenso(self) -> dict:
        estados = {}
        for node_id, node in self.nodes.items():
            estados[node_id] = {
                "altura": node.height,
                "ultimo_hash": node.last_block.hash,
                "valida": node.is_valid(),
            }
        valores = list(estados.values())
        en_consenso = (
            valores[0]["altura"] == valores[1]["altura"]
            and valores[0]["ultimo_hash"] == valores[1]["ultimo_hash"]
            and all(v["valida"] for v in valores)
        )
        return {"consenso": en_consenso, "nodos": estados}

    def close(self) -> None:
        for node in self.nodes.values():
            node.close()
