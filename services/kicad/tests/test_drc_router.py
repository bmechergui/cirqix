"""FastAPI integration tests for ``routers/drc.py`` — POST /drc/auto."""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from main import app  # noqa: E402
import routers.drc as drc_router  # noqa: E402


client = TestClient(app)

MINIMAL_PCB = b"(kicad_pcb (version 20240108) (generator pcbnew))\n"


def _b64(content: bytes = MINIMAL_PCB) -> str:
    return base64.b64encode(content).decode("ascii")


class TestDrcSkippedWhenKicadCliMissing:
    def test_skipped_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(drc_router, "_find_kicad_cli", lambda: None)
        resp = client.post("/drc/auto", json={"kicad_pcb_b64": _b64(), "auto_fix": True})
        assert resp.status_code == 200
        body = resp.json()
        assert body["drc_clean"] is True
        assert body["skipped"] is True
        assert body["violations"] == []
        assert "kicad-cli" in (body.get("warning") or "")


class TestDrcCleanReport:
    def test_no_violations(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(drc_router, "_find_kicad_cli", lambda: "/fake/kicad-cli")
        monkeypatch.setattr(
            drc_router,
            "_run_kicad_drc",
            lambda _cli, _pcb_path: json.dumps({"violations": [], "unconnected_items": []}),
        )

        resp = client.post("/drc/auto", json={"kicad_pcb_b64": _b64(), "auto_fix": True})
        assert resp.status_code == 200
        body = resp.json()
        assert body["drc_clean"] is True
        assert body["skipped"] is False
        assert body["fixed_count"] == 0
        assert body["violations"] == []


class TestDrcAutoFixSucceeds:
    def test_one_iter_fixes_clearance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(drc_router, "_find_kicad_cli", lambda: "/fake/kicad-cli")

        call_count = {"n": 0}

        def fake_run(_cli: str, _pcb: Path) -> str:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return json.dumps({
                    "violations": [
                        {
                            "type": "unfilled_zone",
                            "severity": "warning",
                            "description": "Unfilled zone",
                            "items": [{"description": "Zone", "pos": {"x": 1, "y": 1}}],
                        }
                    ]
                })
            return json.dumps({"violations": []})

        monkeypatch.setattr(drc_router, "_run_kicad_drc", fake_run)
        monkeypatch.setattr(
            drc_router,
            "_apply_fixes",
            lambda content, _violations: (content + b"\n;fixed", 1),
        )

        resp = client.post("/drc/auto", json={"kicad_pcb_b64": _b64(), "auto_fix": True})
        assert resp.status_code == 200
        body = resp.json()
        assert body["drc_clean"] is True
        assert body["fixed_count"] == 1
        assert body["kicad_pcb_b64"] is not None


class TestDrcViolationsPersist:
    def test_returns_unclean_after_3_iters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(drc_router, "_find_kicad_cli", lambda: "/fake/kicad-cli")
        monkeypatch.setattr(
            drc_router,
            "_run_kicad_drc",
            lambda _cli, _pcb: json.dumps({
                "violations": [
                    {
                        "type": "clearance",
                        "severity": "error",
                        "description": "Clearance violation",
                        "items": [{"description": "Track", "pos": {"x": 5, "y": 5}}],
                    }
                ]
            }),
        )
        # Fixes don't actually resolve the violation in this mock
        monkeypatch.setattr(drc_router, "_apply_fixes", lambda content, _v: (content, 0))

        resp = client.post("/drc/auto", json={"kicad_pcb_b64": _b64(), "auto_fix": True})
        assert resp.status_code == 200
        body = resp.json()
        assert body["drc_clean"] is False
        assert len(body["violations"]) >= 1


class TestDrcInternalError:
    def test_returns_500_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(drc_router, "_find_kicad_cli", lambda: "/fake/kicad-cli")

        def boom(*_args: Any, **_kwargs: Any) -> str:
            raise RuntimeError("kicad-cli crashed")

        monkeypatch.setattr(drc_router, "_run_kicad_drc", boom)

        resp = client.post("/drc/auto", json={"kicad_pcb_b64": _b64(), "auto_fix": True})
        assert resp.status_code == 500
