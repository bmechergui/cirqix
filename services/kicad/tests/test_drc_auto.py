"""Tests POST /drc/auto — faux négatif niveau 1 (kicad-tools propre ≠ DRC_CLEAN).

Régression mesurée 2026-07-04 sur board STM32 réel : kicad-tools (27 règles
JLCPCB) déclarait le board propre alors que kicad-cli officiel rapportait
25 shorting_items + 21 clearance + 154 copper_edge_clearance. L'ancien code
retournait drc_clean=True dès le niveau 1 SANS jamais exécuter kicad-cli —
violation de la règle projet « NEVER accepter DRC violations comme OK ».

Règle attendue : le niveau 1 ne court-circuite QUE si kicad-cli est
indisponible (fallback dégradé). Si kicad-cli est présent, la validation
officielle tourne toujours, même quand kicad-tools est propre.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]  # services/kicad
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from routers import drc as drc_router  # noqa: E402
from routers.drc import DRCAutoRequest, run_drc_auto  # noqa: E402

_PCB_B64 = base64.b64encode(b"(kicad_pcb (version 20240108))").decode("ascii")

# Rapport kicad-cli avec violations — types réels mesurés sur le board STM32.
_CLI_REPORT_WITH_VIOLATIONS = json.dumps({
    "violations": [
        {
            "type": "shorting_items",
            "severity": "error",
            "description": "Items shorting two nets (GND, +3V3)",
            "items": [{"uuid": "aaa-bbb", "pos": {"x": 10.0, "y": 20.0}}],
        },
        {
            "type": "clearance",
            "severity": "error",
            "description": "Clearance violation (0.05 mm < 0.2 mm)",
        },
    ],
})

_CLI_REPORT_CLEAN = json.dumps({"violations": []})


def test_level1_clean_still_validates_with_kicad_cli(monkeypatch):
    """kicad-tools propre MAIS kicad-cli dispo et rapporte des violations
    → drc_clean=False avec les violations kicad-cli (plus de faux négatif)."""
    monkeypatch.setattr(drc_router, "_run_python_drc", lambda pcb_bytes: [])
    monkeypatch.setattr(drc_router, "_find_kicad_cli", lambda: "/fake/kicad-cli")
    monkeypatch.setattr(
        drc_router, "_run_kicad_drc",
        lambda cli_path, pcb_path: _CLI_REPORT_WITH_VIOLATIONS,
    )

    resp = run_drc_auto(DRCAutoRequest(kicad_pcb_b64=_PCB_B64, auto_fix=False))

    assert resp.drc_clean is False
    assert resp.skipped is False
    types = {v.get("type") for v in resp.violations}
    assert "shorting_items" in types
    assert "clearance" in types


def test_level1_clean_and_cli_clean_reports_official_validation(monkeypatch):
    """kicad-tools propre + kicad-cli propre → DRC_CLEAN, warning explicite
    « validé kicad-cli officiel » (distinct du fallback kicad-tools seul)."""
    monkeypatch.setattr(drc_router, "_run_python_drc", lambda pcb_bytes: [])
    monkeypatch.setattr(drc_router, "_find_kicad_cli", lambda: "/fake/kicad-cli")
    monkeypatch.setattr(
        drc_router, "_run_kicad_drc",
        lambda cli_path, pcb_path: _CLI_REPORT_CLEAN,
    )

    resp = run_drc_auto(DRCAutoRequest(kicad_pcb_b64=_PCB_B64, auto_fix=True))

    assert resp.drc_clean is True
    assert resp.skipped is False
    assert resp.warning is not None
    assert "kicad-cli officiel" in resp.warning


def test_level1_clean_without_kicad_cli_keeps_fallback(monkeypatch):
    """kicad-cli ABSENT → fallback dégradé conservé : drc_clean=True basé sur
    kicad-tools seul, warning « kicad-cli indisponible »."""
    monkeypatch.setattr(drc_router, "_run_python_drc", lambda pcb_bytes: [])
    monkeypatch.setattr(drc_router, "_find_kicad_cli", lambda: None)

    resp = run_drc_auto(DRCAutoRequest(kicad_pcb_b64=_PCB_B64, auto_fix=True))

    assert resp.drc_clean is True
    assert resp.skipped is False
    assert resp.warning is not None
    assert "indisponible" in resp.warning
    assert "kicad-tools" in resp.warning


def test_both_validators_absent_returns_skipped(monkeypatch):
    """kicad-tools crash + kicad-cli absent → skipped=True (pipeline non bloqué)."""
    def _crash(pcb_bytes: bytes) -> list[dict]:
        raise RuntimeError("kicad-tools indisponible")

    monkeypatch.setattr(drc_router, "_run_python_drc", _crash)
    monkeypatch.setattr(drc_router, "_find_kicad_cli", lambda: None)

    resp = run_drc_auto(DRCAutoRequest(kicad_pcb_b64=_PCB_B64, auto_fix=True))

    assert resp.skipped is True
    assert resp.drc_clean is True
    assert resp.violations == []
