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

# Clearance impliquant un pad SANS net (pin NC du LQFP-48) vs une piste d'escape.
# Mesure réelle board STM32 routé (2026-07-06) : 17/21 violations clearance de ce
# type — électriquement inoffensives (un pad sans net ne peut pas court-circuiter).
_NC_CLEARANCE = {
    "type": "clearance",
    "severity": "error",
    "description": "Clearance violation (0.198 mm < 0.200 mm)",
    "items": [
        {
            "uuid": "nc-pad",
            "description": "Pad 33 [<no net>] de U2",
            "pos": {"x": 55.0, "y": 42.0},
        },
        {
            "uuid": "nc-track",
            "description": "Piste [GPIO1] sur F.Cu",
            "pos": {"x": 55.1, "y": 42.0},
        },
    ],
}

# Clearance normale entre deux items connectés — vraie erreur bloquante.
_REAL_CLEARANCE = {
    "type": "clearance",
    "severity": "error",
    "description": "Clearance violation (0.05 mm < 0.2 mm)",
    "items": [
        {
            "uuid": "real-pad",
            "description": "Pad 12 [GND] de U1",
            "pos": {"x": 10.0, "y": 20.0},
        },
        {
            "uuid": "real-track",
            "description": "Piste [+3V3] sur F.Cu",
            "pos": {"x": 10.1, "y": 20.0},
        },
    ],
}

_CLI_REPORT_NC_AND_REAL_CLEARANCE = json.dumps(
    {"violations": [_NC_CLEARANCE, _REAL_CLEARANCE]},
)

_CLI_REPORT_NC_CLEARANCE_ONLY = json.dumps({"violations": [_NC_CLEARANCE]})


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


def test_nc_pad_clearance_is_warning_but_real_clearance_blocks(monkeypatch):
    """1 clearance NC (pad <no net>) + 1 clearance normale → la NC est reclassée
    severity=warning (visible, non bloquante) MAIS la normale reste error
    → drc_clean=False."""
    monkeypatch.setattr(drc_router, "_run_python_drc", lambda pcb_bytes: [])
    monkeypatch.setattr(drc_router, "_find_kicad_cli", lambda: "/fake/kicad-cli")
    monkeypatch.setattr(
        drc_router, "_run_kicad_drc",
        lambda cli_path, pcb_path: _CLI_REPORT_NC_AND_REAL_CLEARANCE,
    )

    resp = run_drc_auto(DRCAutoRequest(kicad_pcb_b64=_PCB_B64, auto_fix=False))

    assert resp.drc_clean is False
    assert resp.skipped is False
    by_id = {v["id"]: v for v in resp.violations}
    # La clearance NC est reclassée warning — mais reste dans la réponse.
    assert by_id["nc-pad"]["severity"] == "warning"
    assert by_id["nc-track"]["severity"] == "warning"
    # La clearance normale reste une erreur bloquante.
    assert by_id["real-pad"]["severity"] == "error"
    assert by_id["real-track"]["severity"] == "error"


def test_only_nc_pad_clearances_is_drc_clean(monkeypatch):
    """Uniquement des clearance NC (pad <no net>) → drc_clean=True :
    aucune violation de sévérité error, mais les warnings restent visibles."""
    monkeypatch.setattr(drc_router, "_run_python_drc", lambda pcb_bytes: [])
    monkeypatch.setattr(drc_router, "_find_kicad_cli", lambda: "/fake/kicad-cli")
    monkeypatch.setattr(
        drc_router, "_run_kicad_drc",
        lambda cli_path, pcb_path: _CLI_REPORT_NC_CLEARANCE_ONLY,
    )

    resp = run_drc_auto(DRCAutoRequest(kicad_pcb_b64=_PCB_B64, auto_fix=False))

    assert resp.drc_clean is True
    assert resp.skipped is False
    # Les violations NC ne sont PAS supprimées — juste reclassées warning.
    assert len(resp.violations) == 2
    assert all(v["severity"] == "warning" for v in resp.violations)


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
