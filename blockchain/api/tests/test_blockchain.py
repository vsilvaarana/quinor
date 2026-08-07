"""Tests unitarios del módulo blockchain (bloques, nodos y red)."""

import json

from app.blockchain import (
    Block,
    BlockchainNetwork,
    BlockchainNode,
    _block_key,
)


def test_hash_deterministico():
    b1 = Block(1, 123.0, {"a": 1}, "0" * 64)
    b2 = Block(1, 123.0, {"a": 1}, "0" * 64)
    assert b1.hash == b2.hash


def test_to_dict_from_dict():
    original = Block(2, 456.0, {"x": "y"}, "f" * 64)
    copia = Block.from_dict(original.to_dict())
    assert copia.to_dict() == original.to_dict()


def test_nodo_crea_genesis(tmp_path):
    node = BlockchainNode("n1", str(tmp_path / "n1"))
    assert node.height == 1
    assert node.last_block.data == {"genesis": True}
    node.close()


def test_nodo_persiste_tras_reapertura(tmp_path):
    path = str(tmp_path / "n1")
    node = BlockchainNode("n1", path)
    node.add_block({"id_despacho": "d1", "producto": "quinua"})
    node.close()

    reabierto = BlockchainNode("n1", path)
    assert reabierto.height == 2
    assert reabierto.get_despacho_block("d1").data["producto"] == "quinua"
    assert reabierto.is_valid()
    reabierto.close()


def test_get_block_inexistente(tmp_path):
    node = BlockchainNode("n1", str(tmp_path / "n1"))
    assert node.get_block(99) is None
    node.close()


def test_get_despacho_inexistente(tmp_path):
    node = BlockchainNode("n1", str(tmp_path / "n1"))
    assert node.get_despacho_block("nada") is None
    node.close()


def test_add_block_usa_timestamp_actual(tmp_path):
    node = BlockchainNode("n1", str(tmp_path / "n1"))
    block = node.add_block({"k": "v"})
    assert block.timestamp > 0
    node.close()


def test_cadena_invalida_por_enlace_roto(tmp_path):
    node = BlockchainNode("n1", str(tmp_path / "n1"))
    node.add_block({"id_despacho": "d1"})
    node.add_block({"id_despacho": "d2"})
    # Reescribe el bloque 1 con hash recalculado pero rompe el enlace con el 2
    falso = Block(1, 999.0, {"id_despacho": "dx"}, node.get_block(0).hash)
    node.db.put(_block_key(1), json.dumps(falso.to_dict()).encode())
    assert node.is_valid() is False
    node.close()


def test_red_replica_en_dos_nodos(tmp_path):
    red = BlockchainNetwork(str(tmp_path))
    bloque = red.registrar_despacho({"id_despacho": "d1"})
    assert bloque.index == 1
    assert red.get_node("nodo1").last_block.hash == red.get_node("nodo2").last_block.hash
    assert red.consenso()["consenso"] is True
    red.close()


def test_red_nodo_desconocido(tmp_path):
    red = BlockchainNetwork(str(tmp_path))
    assert red.get_node("nodoX") is None
    red.close()
