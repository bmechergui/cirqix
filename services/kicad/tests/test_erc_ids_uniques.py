"""Chaque violation ERC rendue porte un id UNIQUE, meme quand deux violations
visent le meme objet du schema.

Mesure du 2026-09-13 (run 09f7ee80 depuis le dashboard) : ErcView refusait
« two children with the same key » — l id etait l uuid KiCad de l objet, et un
meme pin figure dans plusieurs violations (non connecte, entree non pilotee).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from tools.erc import parse_erc_report  # noqa: E402

_PIN = {"description": "Symbol U1 Pin 3 [SDA, Input]", "uuid": "6ed13db8-05cb-4c77-b781-31c3637895fb", "pos": {"x": 10.0, "y": 20.0}}


def _rapport(violations):
    return json.dumps({"sheets": [{"violations": violations}]})


def test_deux_violations_sur_le_meme_objet_ont_deux_ids():
    out = parse_erc_report(_rapport([
        {"type": "pin_not_connected", "severity": "error", "description": "Pin not connected", "items": [_PIN]},
        {"type": "pin_not_driven", "severity": "error", "description": "Input pin not driven", "items": [_PIN]},
    ]))
    ids = [v["id"] for v in out]
    assert len(ids) == 2 and len(set(ids)) == 2, ids
    assert all(v["item_uuid"] == _PIN["uuid"] for v in out)


def test_un_objet_repete_dans_une_meme_violation_aussi():
    out = parse_erc_report(_rapport([
        {"type": "x", "severity": "warning", "description": "d", "items": [_PIN, _PIN]},
    ]))
    assert len({v["id"] for v in out}) == 2


def test_sans_uuid_l_id_reste_unique_et_sans_item_uuid():
    out = parse_erc_report(_rapport([
        {"type": "x", "severity": "warning", "description": "d", "items": [{"description": "Pin 1"}]},
        {"type": "y", "severity": "warning", "description": "e"},
    ]))
    assert len({v["id"] for v in out}) == 2
    assert "item_uuid" not in out[0]
