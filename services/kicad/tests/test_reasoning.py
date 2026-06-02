"""Unit tests for the LLM reasoner helpers (the parts that don't call Claude)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from tools import reasoning


def test_extract_json_from_llm_text():
    assert reasoning._extract_json(
        'Je propose: {"type":"route_net","net":"DHT_DATA"} voilà'
    ) == {"type": "route_net", "net": "DHT_DATA"}
    assert reasoning._extract_json(
        '{"type":"place_component","ref":"C1","near":"U1","offset":[2,0]}'
    ) == {"type": "place_component", "ref": "C1", "near": "U1", "offset": [2, 0]}


def test_extract_json_returns_none_without_json():
    assert reasoning._extract_json("aucune commande ici") is None
    assert reasoning._extract_json("{cassé") is None


def test_available_false_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert reasoning.available() is False
