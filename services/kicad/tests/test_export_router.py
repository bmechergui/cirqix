"""FastAPI integration tests for ``routers/export.py`` — POST /export/all."""
from __future__ import annotations

import base64
import io
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from main import app  # noqa: E402
import routers.export as export_router  # noqa: E402


client = TestClient(app)

MINIMAL_PCB = b"(kicad_pcb (version 20240108) (generator pcbnew))\n"


def _b64(content: bytes = MINIMAL_PCB) -> str:
    return base64.b64encode(content).decode("ascii")


class TestExportSkippedWhenKicadCliMissing:
    def test_skipped_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(export_router, "_find_kicad_cli", lambda: None)
        resp = client.post("/export/all", json={"kicad_pcb_b64": _b64(), "project_id": "test"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["skipped"] is True
        assert body["files"] == []
        assert "kicad-cli" in (body.get("warning") or "")
        assert body.get("zip_b64") is None


class TestExportSuccess:
    def test_returns_zip_with_files(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(export_router, "_find_kicad_cli", lambda: "/fake/kicad-cli")

        def fake_export(_cli: str, _pcb: Path, out_dir: Path) -> list[str]:
            # Simulate kicad-cli producing 3 gerber files
            out_dir.mkdir(parents=True, exist_ok=True)
            for name in ("F_Cu.gbr", "B_Cu.gbr", "Edge_Cuts.gm1"):
                (out_dir / name).write_bytes(b"G-code data")
            return ["F_Cu.gbr", "B_Cu.gbr", "Edge_Cuts.gm1"]

        monkeypatch.setattr(export_router, "_kicad_export_all", fake_export)

        resp = client.post(
            "/export/all",
            json={"kicad_pcb_b64": _b64(), "project_id": "test-proj"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["skipped"] is False
        assert len(body["files"]) == 3
        # The returned zip must contain the listed files
        zip_bytes = base64.b64decode(body["zip_b64"])
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = set(zf.namelist())
            assert "F_Cu.gbr" in names
            assert "B_Cu.gbr" in names
            assert "Edge_Cuts.gm1" in names

    def test_includes_quote(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(export_router, "_find_kicad_cli", lambda: "/fake/kicad-cli")

        def fake_export(_cli: str, _pcb: Path, out_dir: Path) -> list[str]:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "F_Cu.gbr").write_bytes(b"x")
            return ["F_Cu.gbr"]

        monkeypatch.setattr(export_router, "_kicad_export_all", fake_export)

        resp = client.post("/export/all", json={"kicad_pcb_b64": _b64(), "project_id": "test"})
        body = resp.json()
        assert isinstance(body["quote_usd"], (int, float))
        assert body["quote_usd"] > 0
        assert isinstance(body["lead_time_days"], int)
        assert body["lead_time_days"] >= 1


class TestExportErrorMapping:
    def test_returns_500_on_kicad_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(export_router, "_find_kicad_cli", lambda: "/fake/kicad-cli")

        def boom(*_args: Any, **_kwargs: Any) -> list[str]:
            raise RuntimeError("kicad-cli crashed")

        monkeypatch.setattr(export_router, "_kicad_export_all", boom)

        resp = client.post("/export/all", json={"kicad_pcb_b64": _b64(), "project_id": "test"})
        assert resp.status_code == 500
        # Generic message — no leak of stderr
        assert "kicad-cli crashed" not in (resp.json().get("detail") or "")

    def test_pydantic_invalid_b64(self) -> None:
        # No base64 input — Pydantic accepts but downstream fails
        resp = client.post(
            "/export/all",
            json={"kicad_pcb_b64": "!!!not base64!!!", "project_id": "test"},
        )
        # 422 from base64 decode failure (mapped via HTTPException)
        assert resp.status_code in (422, 500)
