"""Fail-closed export — never announce success without Gerbers + drill.

Règle projet : un succès n'est annoncé QUE par une opération réellement
exécutée ET aboutie. L'ancien `/export/all` journalisait les échecs
gerbers/drill/pos puis renvoyait `skipped=False` avec un ZIP potentiellement
vide — un paquet de fabrication incomplet présenté comme prêt à commander.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from routers import export as export_router  # noqa: E402
from routers.export import (  # noqa: E402
    ExportAllRequest,
    _is_drill_file,
    _is_gerber_file,
    _require_manufacturing_deliverables,
    export_all,
)

_PCB_B64 = base64.b64encode(b"(kicad_pcb (version 20240108))").decode("ascii")


def _req() -> ExportAllRequest:
    return ExportAllRequest(kicad_pcb_b64=_PCB_B64, project_id="test-board")


def _run_result(rc: int, stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=rc, stdout="", stderr=stderr)


# ---------------------------------------------------------------------------
# Unit helpers — deliverable detection
# ---------------------------------------------------------------------------

def test_is_gerber_and_drill_recognise_common_names():
    assert _is_gerber_file("board-F_Cu.gbr")
    assert _is_gerber_file("board.gtl")
    assert _is_gerber_file("board.gko")
    assert not _is_gerber_file("pos.csv")
    assert not _is_gerber_file("board.drl")

    assert _is_drill_file("board.drl")
    assert _is_drill_file("board.xln")
    assert not _is_drill_file("board.gtl")
    assert not _is_drill_file("bom.csv")


def test_require_manufacturing_deliverables_rejects_partial():
    with pytest.raises(RuntimeError, match="drill"):
        _require_manufacturing_deliverables(["board.gtl", "board.gbl"])
    with pytest.raises(RuntimeError, match="gerber"):
        _require_manufacturing_deliverables(["board.drl"])
    with pytest.raises(RuntimeError, match="missing"):
        _require_manufacturing_deliverables([])
    # Complete package is accepted.
    _require_manufacturing_deliverables(["board.gtl", "board.drl"])


# ---------------------------------------------------------------------------
# Endpoint — sub-commands fail → no success
# ---------------------------------------------------------------------------

def test_export_subcommands_fail_does_not_announce_success(monkeypatch):
    """Gerber + drill + pos all return non-zero → endpoint does not succeed.

    Previously: warnings only, then skipped=False + empty zip.
    """
    monkeypatch.setattr(export_router, "_find_kicad_cli", lambda: "/fake/kicad-cli")
    monkeypatch.setattr(
        export_router,
        "_export_with_kicad_tools",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("kicad-tools down")),
    )

    def _always_fail(cmd, **_kwargs):
        return _run_result(1, stderr=f"fail: {cmd[2:5]}")

    monkeypatch.setattr(export_router.subprocess, "run", _always_fail)

    with pytest.raises(HTTPException) as exc_info:
        export_all(_req())

    assert exc_info.value.status_code == 500
    detail = str(exc_info.value.detail).lower()
    # Must not look like a soft skip — this is a hard failure.
    assert "export failed" in detail or "gerbers" in detail or "incomplete" in detail


def test_export_gerbers_without_drill_fails(monkeypatch):
    """Gerbers present but drill files absent → explicit failure, not success."""
    monkeypatch.setattr(export_router, "_find_kicad_cli", lambda: "/fake/kicad-cli")
    monkeypatch.setattr(
        export_router,
        "_export_with_kicad_tools",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("kicad-tools down")),
    )

    def _fake_run(cmd, **_kwargs):
        # Write only Gerbers when the gerbers sub-command runs; drill "succeeds"
        # with rc=0 but produces nothing — the post-check must still fail.
        out_idx = cmd.index("--output") + 1 if "--output" in cmd else -1
        out = Path(cmd[out_idx]) if out_idx > 0 else None
        if "gerbers" in cmd and out is not None:
            out.mkdir(parents=True, exist_ok=True)
            (out / "board.gtl").write_text("G04 gerber*\n", encoding="utf-8")
            (out / "board.gbl").write_text("G04 gerber*\n", encoding="utf-8")
            return _run_result(0)
        if "drill" in cmd:
            return _run_result(0)  # rc=0 but no .drl written
        if "pos" in cmd:
            return _run_result(0)
        return _run_result(0)

    monkeypatch.setattr(export_router.subprocess, "run", _fake_run)

    with pytest.raises(HTTPException) as exc_info:
        export_all(_req())

    assert exc_info.value.status_code == 500


def test_export_success_requires_gerber_and_drill(monkeypatch):
    """Happy path still works when both Gerbers and drill are produced."""
    monkeypatch.setattr(export_router, "_find_kicad_cli", lambda: "/fake/kicad-cli")
    monkeypatch.setattr(
        export_router,
        "_export_with_kicad_tools",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("kicad-tools down")),
    )

    def _fake_run(cmd, **_kwargs):
        out_idx = cmd.index("--output") + 1 if "--output" in cmd else -1
        out = Path(cmd[out_idx]) if out_idx > 0 else None
        if "gerbers" in cmd and out is not None:
            out.mkdir(parents=True, exist_ok=True)
            (out / "board.gtl").write_bytes(b"G04*\n")
            (out / "board.gbl").write_bytes(b"G04*\n")
            return _run_result(0)
        if "drill" in cmd and out is not None:
            out.mkdir(parents=True, exist_ok=True)
            (out / "board.drl").write_bytes(b"M48\n")
            return _run_result(0)
        if "pos" in cmd and out is not None:
            # pos --output is a file path
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("Designator,Mid X,Mid Y\n", encoding="utf-8")
            return _run_result(0)
        return _run_result(0)

    monkeypatch.setattr(export_router.subprocess, "run", _fake_run)

    resp = export_all(_req())
    assert resp.skipped is False
    assert resp.zip_b64
    assert any(_is_gerber_file(f) for f in resp.files)
    assert any(_is_drill_file(f) for f in resp.files)
    assert resp.quote_usd is None
    assert resp.lead_time_days is None
    response_payload = resp.model_dump(exclude_none=True)
    assert "quote_usd" not in response_payload
    assert "lead_time_days" not in response_payload
    export_route = next(
        route for route in export_router.router.routes if route.path == "/export/all"
    )
    assert export_route.response_model_exclude_none is True


def test_export_kicad_cli_absent_still_skipped():
    """kicad-cli missing → skipped=True (existing soft path), never a fake package."""
    # No monkeypatch of _find_kicad_cli to a real path — force None.
    # Temporarily replace finder.
    import routers.export as mod

    original = mod._find_kicad_cli
    try:
        mod._find_kicad_cli = lambda: None  # type: ignore[assignment]
        resp = export_all(_req())
    finally:
        mod._find_kicad_cli = original

    assert resp.skipped is True
    assert resp.zip_b64 is None
    assert resp.files == []
    assert resp.quote_usd is None
    assert resp.lead_time_days is None
