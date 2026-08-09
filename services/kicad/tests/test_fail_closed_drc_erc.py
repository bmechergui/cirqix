"""Fail-closed DRC/ERC — sans kicad-cli ou rapport invalide, jamais clean.

Règle projet (2026-07 / 2026-08) : un statut DRC_CLEAN / ERC_CLEAN ne peut
être émis QUE par un contrôle d'autorité réellement exécuté et passé.

Le pré-filtre (kct check / Schematic.validate) n'a aucune autorité. Un
rapport JSON tronqué ou un kct check en rc≠0/1 ne doit jamais se lire
comme « zéro violation ».
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[1]  # services/kicad
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from routers import drc as drc_router  # noqa: E402
from routers import erc as erc_router  # noqa: E402
from routers.drc import DRCAutoRequest, run_drc_auto  # noqa: E402
from routers.erc import ERCRequest, run_erc  # noqa: E402
from tools.drc import InvalidReportError as DrcInvalidReportError  # noqa: E402
from tools.drc import parse_drc_report  # noqa: E402
from tools.erc import InvalidReportError as ErcInvalidReportError  # noqa: E402
from tools.erc import parse_erc_report  # noqa: E402

_PCB_B64 = base64.b64encode(b"(kicad_pcb (version 20240108))").decode("ascii")
_SCH_B64 = base64.b64encode(b"(kicad_sch (version 20231120) (generator test))").decode("ascii")


# ---------------------------------------------------------------------------
# 1. kicad-cli absent → drc_clean False + skipped True
# ---------------------------------------------------------------------------

def test_drc_kicad_cli_absent_is_fail_closed(monkeypatch):
    """Sans kicad-cli, le pré-filtre propre ne promeut jamais drc_clean."""
    prefilter_violations = [
        {"type": "min_trace_width", "description": "trace too thin", "severity": "error"},
    ]
    monkeypatch.setattr(
        drc_router, "_run_python_drc", lambda pcb_bytes: prefilter_violations,
    )
    monkeypatch.setattr(drc_router, "_find_kicad_cli", lambda: None)

    resp = run_drc_auto(DRCAutoRequest(kicad_pcb_b64=_PCB_B64, auto_fix=True))

    assert resp.drc_clean is False
    assert resp.skipped is True
    assert resp.warning is not None
    assert "authority DRC not run" in resp.warning
    # Diagnostic du pré-filtre conservé (pas d'autorité).
    assert resp.violations == prefilter_violations


def test_drc_kicad_cli_absent_and_prefilter_clean_still_fail_closed(monkeypatch):
    monkeypatch.setattr(drc_router, "_run_python_drc", lambda pcb_bytes: [])
    monkeypatch.setattr(drc_router, "_find_kicad_cli", lambda: None)

    resp = run_drc_auto(DRCAutoRequest(kicad_pcb_b64=_PCB_B64, auto_fix=False))

    assert resp.drc_clean is False
    assert resp.skipped is True


# ---------------------------------------------------------------------------
# 2. kct check rc=2 / JSON tronqué → pas « zéro violation »
# ---------------------------------------------------------------------------

def test_run_python_drc_rc2_returns_none(monkeypatch, tmp_path):
    """rc hors (0, 1) = échec d'exécution, pas une liste vide de violations."""
    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=2, stdout="", stderr="fatal: crash")

    monkeypatch.setattr(drc_router.subprocess, "run", fake_run)
    # _run_python_drc imports subprocess from the module globals after local
    # import — patch both the local import path used inside the function
    # (it does `import subprocess` inside try) and sys.modules is fine via
    # monkeypatch on the stdlib after import inside the function.
    import subprocess as sp

    monkeypatch.setattr(sp, "run", fake_run)

    result = drc_router._run_python_drc(b"(kicad_pcb)")

    assert result is None


def test_run_python_drc_truncated_json_returns_none(monkeypatch):
    """JSON tronqué ne doit pas se lire comme « zéro violation »."""
    def fake_run(cmd, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout='{"errors": [{"rule": "x"',  # truncated
            stderr="",
        )

    import subprocess as sp

    monkeypatch.setattr(sp, "run", fake_run)

    result = drc_router._run_python_drc(b"(kicad_pcb)")

    assert result is None


def test_run_python_drc_success_empty_returns_list(monkeypatch):
    """rc=0 + JSON valide vide → liste (exécution OK), distinct de None."""
    def fake_run(cmd, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"errors": [], "warnings": []}),
            stderr="",
        )

    import subprocess as sp

    monkeypatch.setattr(sp, "run", fake_run)

    result = drc_router._run_python_drc(b"(kicad_pcb)")

    assert result is not None
    assert result == []


def test_run_python_drc_success_with_errors(monkeypatch):
    def fake_run(cmd, **kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps({
                "errors": [{"rule": "short", "message": "short circuit"}],
                "warnings": [{"rule": "silk", "message": "silk overlap"}],
            }),
            stderr="",
        )

    import subprocess as sp

    monkeypatch.setattr(sp, "run", fake_run)

    result = drc_router._run_python_drc(b"(kicad_pcb)")

    assert result is not None
    assert len(result) == 2
    assert result[0]["severity"] == "error"
    assert result[1]["severity"] == "warning"


def test_run_python_drc_none_keeps_kt_ok_false(monkeypatch):
    """Si le pré-filtre échoue, kt_ok reste faux ; sans cli → fail-closed."""
    monkeypatch.setattr(drc_router, "_run_python_drc", lambda pcb_bytes: None)
    monkeypatch.setattr(drc_router, "_find_kicad_cli", lambda: None)

    resp = run_drc_auto(DRCAutoRequest(kicad_pcb_b64=_PCB_B64, auto_fix=True))

    assert resp.drc_clean is False
    assert resp.skipped is True
    assert resp.violations == []


# ---------------------------------------------------------------------------
# 3. kicad-cli absent → erc_clean False + skipped True
# ---------------------------------------------------------------------------

def test_erc_kicad_cli_absent_is_fail_closed(monkeypatch):
    prefilter = (
        [{"id": "1", "severity": "warning", "message": "off-grid", "type": "off_grid"}],
        "(kicad_sch fixed)",
        1,
    )
    monkeypatch.setattr(
        "tools.erc.run_kicad_tools_erc",
        lambda content, auto_fix: prefilter,
    )
    monkeypatch.setattr(erc_router, "_find_kicad_cli", lambda: None)

    resp = run_erc(ERCRequest(kicad_sch_b64=_SCH_B64, auto_fix=True))

    assert resp.erc_clean is False
    assert resp.skipped is True
    assert resp.fixed_count == 1
    assert len(resp.violations) == 1
    assert resp.warning is not None
    assert "authority ERC not run" in resp.warning
    assert resp.kicad_sch_b64 is not None  # fixed content preserved


def test_erc_kicad_cli_absent_empty_prefilter_still_fail_closed(monkeypatch):
    monkeypatch.setattr(
        "tools.erc.run_kicad_tools_erc",
        lambda content, auto_fix: ([], content, 0),
    )
    monkeypatch.setattr(erc_router, "_find_kicad_cli", lambda: None)

    resp = run_erc(ERCRequest(kicad_sch_b64=_SCH_B64, auto_fix=False))

    assert resp.erc_clean is False
    assert resp.skipped is True
    assert resp.fixed_count == 0
    assert resp.violations == []


# ---------------------------------------------------------------------------
# 4. Rapport officiel tronqué → InvalidReportError (pas [])
# ---------------------------------------------------------------------------

def test_parse_drc_report_truncated_json_raises():
    with pytest.raises(DrcInvalidReportError):
        parse_drc_report('{"violations": [')


def test_parse_drc_report_empty_object_raises():
    """Objet JSON valide mais sans sections attendues ≠ zéro violation."""
    with pytest.raises(DrcInvalidReportError):
        parse_drc_report("{}")


def test_parse_drc_report_wrong_type_raises():
    with pytest.raises(DrcInvalidReportError):
        parse_drc_report("[]")


def test_parse_drc_report_violations_not_list_raises():
    with pytest.raises(DrcInvalidReportError):
        parse_drc_report(json.dumps({"violations": "oops"}))


def test_parse_drc_report_valid_empty_returns_empty_list():
    assert parse_drc_report(json.dumps({"violations": []})) == []


def test_parse_erc_report_truncated_json_raises():
    with pytest.raises(ErcInvalidReportError):
        parse_erc_report('{"violations": [')


def test_parse_erc_report_missing_violations_raises():
    with pytest.raises(ErcInvalidReportError):
        parse_erc_report("{}")


def test_parse_erc_report_violations_not_list_raises():
    with pytest.raises(ErcInvalidReportError):
        parse_erc_report(json.dumps({"violations": {}}))


def test_parse_erc_report_valid_empty_returns_empty_list():
    assert parse_erc_report(json.dumps({"violations": []})) == []
