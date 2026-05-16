"""FastAPI integration tests for ``routers/erc.py``.

Mocks ``shutil.which`` + ``subprocess.run`` so the router contract (HTTP codes,
Pydantic shape, skip-on-missing-kicad-cli, auto-fix loop) is exercised without
KiCad installed.
"""
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
import routers.erc as erc_router  # noqa: E402


client = TestClient(app)

MINIMAL_SCH = b'(kicad_sch (version 20231120) (generator "test"))\n'


def _b64(content: bytes = MINIMAL_SCH) -> str:
    return base64.b64encode(content).decode("ascii")


class TestErcSkippedWhenKicadCliMissing:
    def test_skipped_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(erc_router, "_find_kicad_cli", lambda: None)
        resp = client.post("/erc", json={"kicad_sch_b64": _b64(), "auto_fix": True})
        assert resp.status_code == 200
        body = resp.json()
        assert body["erc_clean"] is True
        assert body["skipped"] is True
        assert body["violations"] == []
        assert "kicad-cli" in (body.get("warning") or "")


class TestErcCleanReport:
    def test_no_violations(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(erc_router, "_find_kicad_cli", lambda: "/fake/kicad-cli")

        def fake_run_erc(_cli: str, _path: Path) -> str:
            return json.dumps({"violations": []})

        monkeypatch.setattr(erc_router, "_run_kicad_erc", fake_run_erc)

        resp = client.post("/erc", json={"kicad_sch_b64": _b64(), "auto_fix": True})
        assert resp.status_code == 200
        body = resp.json()
        assert body["erc_clean"] is True
        assert body["skipped"] is False
        assert body["fixed_count"] == 0
        assert body["violations"] == []


class TestErcAutoFixSucceeds:
    def test_one_iter_fixes_pin_not_connected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(erc_router, "_find_kicad_cli", lambda: "/fake/kicad-cli")

        call_count = {"n": 0}

        def fake_run_erc(_cli: str, _path: Path) -> str:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return json.dumps({
                    "violations": [
                        {
                            "type": "pin_not_connected",
                            "severity": "warning",
                            "description": "Pin not connected",
                            "items": [
                                {"description": "Symbol U1 Pin 5", "pos": {"x": 10, "y": 10}}
                            ],
                        }
                    ]
                })
            return json.dumps({"violations": []})

        monkeypatch.setattr(erc_router, "_run_kicad_erc", fake_run_erc)

        resp = client.post("/erc", json={"kicad_sch_b64": _b64(), "auto_fix": True})
        assert resp.status_code == 200
        body = resp.json()
        assert body["erc_clean"] is True
        assert body["fixed_count"] == 1
        # Updated .kicad_sch is returned
        assert body["kicad_sch_b64"] is not None
        decoded = base64.b64decode(body["kicad_sch_b64"])
        assert b"no_connect" in decoded


class TestErcViolationsPersistAfterMaxIterations:
    def test_returns_unclean_after_3_iters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(erc_router, "_find_kicad_cli", lambda: "/fake/kicad-cli")

        def fake_run_erc(_cli: str, _path: Path) -> str:
            # Always returns one error violation that auto_fix cannot resolve
            return json.dumps({
                "violations": [
                    {
                        "type": "different_net_no_marker",
                        "severity": "error",
                        "description": "Different nets connected without marker",
                        "items": [{"description": "Symbol U1 Pin VCC", "pos": {"x": 0, "y": 0}}],
                    }
                ]
            })

        monkeypatch.setattr(erc_router, "_run_kicad_erc", fake_run_erc)

        resp = client.post("/erc", json={"kicad_sch_b64": _b64(), "auto_fix": True})
        assert resp.status_code == 200
        body = resp.json()
        assert body["erc_clean"] is False
        assert len(body["violations"]) >= 1


class TestErcAutoFixDisabled:
    def test_returns_violations_without_attempting_fix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(erc_router, "_find_kicad_cli", lambda: "/fake/kicad-cli")

        call_count = {"n": 0}

        def fake_run_erc(_cli: str, _path: Path) -> str:
            call_count["n"] += 1
            return json.dumps({
                "violations": [
                    {
                        "type": "pin_not_connected", "severity": "warning",
                        "items": [{"description": "Symbol U1 Pin 5", "pos": {"x": 1, "y": 1}}],
                    }
                ]
            })

        monkeypatch.setattr(erc_router, "_run_kicad_erc", fake_run_erc)

        resp = client.post("/erc", json={"kicad_sch_b64": _b64(), "auto_fix": False})
        assert resp.status_code == 200
        body = resp.json()
        assert body["erc_clean"] is False
        assert body["fixed_count"] == 0
        # Only one call when auto_fix=false
        assert call_count["n"] == 1


class TestErcInternalErrorMapping:
    def test_kicad_cli_runtime_error_returns_500(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(erc_router, "_find_kicad_cli", lambda: "/fake/kicad-cli")

        def boom(*_args: Any, **_kwargs: Any) -> str:
            raise RuntimeError("kicad-cli crashed")

        monkeypatch.setattr(erc_router, "_run_kicad_erc", boom)

        resp = client.post("/erc", json={"kicad_sch_b64": _b64(), "auto_fix": True})
        assert resp.status_code == 500
