"""FastAPI router for auto-routing via Freerouting.

Two endpoints:

- ``POST /route``         — path-based, kept for backwards compatibility.
- ``POST /route/auto``    — base64 I/O, fallback skip when Freerouting absent.

Pipeline: ``.kicad_pcb`` → Specctra DSN → Freerouting (Java) → SES → ``.kicad_pcb``.
"""
from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["routing"])

# 2-layer simple boards usually < 90s, 4-layer ~300s, 8-layer ~600s
_DEFAULT_TIMEOUT_S: int = 300


# ----------------------------------------------------------------------------
# Pydantic models
# ----------------------------------------------------------------------------

class RouteAutoRequest(BaseModel):
    kicad_pcb_b64: str = Field(..., description=".kicad_pcb encoded as base64")
    layers: int = Field(default=2, description="Copper layer count (2, 4, or 8)")
    timeout_s: int = Field(default=_DEFAULT_TIMEOUT_S, ge=30, le=900)

    def model_post_init(self, _context: Any) -> None:
        if self.layers not in (2, 4, 8):
            raise ValueError("layers must be 2, 4, or 8")


class RouteAutoResponse(BaseModel):
    kicad_pcb_b64: Optional[str] = None
    routed_percent: int = 0
    layers: int
    via_count: int = 0
    track_length_mm: float = 0.0
    skipped: bool = False
    warning: Optional[str] = None


# ----------------------------------------------------------------------------
# Internal helpers (mocked in tests)
# ----------------------------------------------------------------------------

def _find_freerouting() -> Optional[tuple[str, str]]:
    """Locate (java, freerouting.jar) or return None when either is absent."""
    java = shutil.which("java")
    if not java:
        return None
    candidates = [
        os.environ.get("FREEROUTING_JAR"),
        "/opt/freerouting/freerouting.jar",
        "/usr/local/share/freerouting/freerouting.jar",
        str(Path(__file__).parent.parent / "freerouting" / "freerouting.jar"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return (java, c)
    return None


def _run_freerouting(
    paths: tuple[str, str], dsn: Path, ses: Path, timeout_s: int
) -> None:
    """Invoke Freerouting CLI. Raises on non-zero exit or timeout."""
    java, jar = paths
    cmd = [
        java, "-jar", jar,
        "-de", str(dsn),
        "-do", str(ses),
        "-mp", "100",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout_s, check=False,
    )
    if result.returncode != 0 and not ses.exists():
        raise RuntimeError(f"Freerouting exit {result.returncode}")


def _specctra_roundtrip(pcb_bytes: bytes, ses_path: Path) -> bytes:
    """Apply a .ses session back onto a .kicad_pcb via pcbnew, return new bytes."""
    try:
        import pcbnew  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover — gated by router caller
        raise RuntimeError("pcbnew unavailable for Specctra import") from exc

    with tempfile.TemporaryDirectory() as tmp:
        in_pcb = Path(tmp) / "in.kicad_pcb"
        out_pcb = Path(tmp) / "out.kicad_pcb"
        in_pcb.write_bytes(pcb_bytes)
        board = pcbnew.LoadBoard(str(in_pcb))
        # Remove stale tracks — Freerouting's SES output replaces them entirely.
        # Without this, old tracks (from circuit-synth or a previous routing pass)
        # survive in the final PCB alongside Freerouting's routes and cause
        # "Track has unconnected end" DRC violations.
        for track in list(board.GetTracks()):
            board.Remove(track)
        pcbnew.ImportSpecctraSES(board, str(ses_path))
        for zone in board.Zones():
            zone.SetFilled(True)
        filler = pcbnew.ZONE_FILLER(board)
        filler.Fill(board.Zones())
        pcbnew.SaveBoard(str(out_pcb), board)
        return out_pcb.read_bytes()


def _export_specctra(pcb_bytes: bytes, dsn_path: Path) -> None:
    """Export a .kicad_pcb byte blob to a Specctra DSN file via pcbnew.

    All existing tracks are removed before export so Freerouting starts from
    scratch — without stale TS-generated traces that pointed to pre-placement
    component positions.
    """
    try:
        import pcbnew  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pcbnew unavailable for Specctra export") from exc

    with tempfile.NamedTemporaryFile(suffix=".kicad_pcb", delete=False) as tmp_pcb:
        tmp_pcb.write(pcb_bytes)
        tmp_pcb_path = tmp_pcb.name
    try:
        board = pcbnew.LoadBoard(tmp_pcb_path)
        # Remove all existing tracks so Freerouting routes from clean pads only.
        for track in list(board.GetTracks()):
            board.Remove(track)
        # KiCad 8 uses ExportSpecctraDSN instead of ExportSpecctraSession
        pcbnew.ExportSpecctraDSN(board, str(dsn_path))
    finally:
        Path(tmp_pcb_path).unlink(missing_ok=True)


# ----------------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------------

@router.post("/route/auto", response_model=RouteAutoResponse)
def route_auto(req: RouteAutoRequest) -> RouteAutoResponse:
    """Auto-route a board via Freerouting. Gracefully skips when unavailable."""
    paths = _find_freerouting()
    if paths is None:
        logger.info("Freerouting not on PATH — skipping auto-routing")
        return RouteAutoResponse(
            kicad_pcb_b64=None,
            routed_percent=0,
            layers=req.layers,
            skipped=True,
            warning="Freerouting (java + .jar) not available",
        )

    try:
        pcb_bytes = base64.b64decode(req.kicad_pcb_b64)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid base64: {exc}") from exc

    try:
        with tempfile.TemporaryDirectory() as tmp:
            dsn = Path(tmp) / "board.dsn"
            ses = Path(tmp) / "board.ses"

            _export_specctra(pcb_bytes, dsn)
            _run_freerouting(paths, dsn, ses, req.timeout_s)
            new_pcb = _specctra_roundtrip(pcb_bytes, ses)

        return RouteAutoResponse(
            kicad_pcb_b64=base64.b64encode(new_pcb).decode("ascii"),
            routed_percent=100,
            layers=req.layers,
            skipped=False,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Routing failed: %s", exc)
        raise HTTPException(status_code=500, detail="routing failed") from exc
