"""FastAPI router for auto-routing.

Two endpoints:

- ``POST /route``         — path-based, kept for backwards compatibility.
- ``POST /route/auto``    — base64 I/O. Pipeline:
    1. Freerouting (Java) — preferred, handles all complexity.
    2. kicad-tools Python router — fallback when Java absent, ≤ 10 nets, 60s budget.
    3. skipped=True — when both are unavailable or board is too complex.

Pipeline Freerouting: ``.kicad_pcb`` → Specctra DSN → Freerouting (Java) → SES → ``.kicad_pcb``.
Pipeline kicad-tools: ``.kicad_pcb`` → Python A* negotiated router → ``.kicad_pcb``.
"""
from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import subprocess
import sys
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

_KICAD_TOOLS_MAX_NETS: int = 30
_KICAD_TOOLS_MAX_COMPS: int = 30
_PYTHON_ROUTER_TIMEOUT_S: int = 60


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


def _count_routable_nets(pcb_bytes: bytes) -> int:
    """Count nets that actually require routing (≥ 2 pads assigned).

    In a .kicad_pcb file each net appears exactly once as a top-level
    declaration ``(net N "name")`` plus once per pad that carries it.
    Total occurrences = 1 (declaration) + pad_count.
    A net needs routing only when pad_count ≥ 2, i.e. total count ≥ 3.

    Single-pad nets (unconnected Arduino pins → Net-(U1-X)) appear exactly
    twice (declaration + 1 pad) and are correctly excluded.
    """
    text = pcb_bytes.decode("utf-8", errors="replace")
    from collections import Counter
    all_occurrences = re.findall(r'\(net\s+(\d+)\s+"[^"]+"\)', text)
    counts = Counter(all_occurrences)
    # ≥3 = 1 top-level declaration + at least 2 pad assignments
    return sum(1 for c in counts.values() if c >= 3)


def _count_footprints(pcb_bytes: bytes) -> int:
    """Count footprint blocks in a .kicad_pcb S-expression."""
    text = pcb_bytes.decode("utf-8", errors="replace")
    return len(re.findall(r'\(footprint\s+"', text))


def _route_with_kicad_tools(pcb_bytes: bytes) -> tuple[bytes, int]:
    """
    Route via kicad-tools pure Python A* negotiated router (Python API).

    Uses load_pcb_for_routing + route_all_negotiated + merge_routes_into_pcb
    instead of the CLI subprocess to get real (segment ...) tracks in the PCB.
    VCC_5V and other power nets are automatically handled as copper-pour zones.
    Single-pad nets (e.g. Net-(U1-X) from unconnected Arduino pins) are skipped.

    Returns (routed_pcb_bytes, routed_percent).
    Raises RuntimeError on failure.
    """
    from kicad_tools.router import load_pcb_for_routing, merge_routes_into_pcb

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.kicad_pcb"
        src.write_bytes(pcb_bytes)

        router, _ = load_pcb_for_routing(
            str(src),
            skip_nets=["GND"],
            validate_drc=False,
            strict_drc=False,
        )

        routes = router.route_all_negotiated(
            timeout=float(_PYTHON_ROUTER_TIMEOUT_S),
            per_net_timeout=15.0,
            max_iterations=10,
        )

        route_sexp = router.to_sexp()
        pcb_content = pcb_bytes.decode("utf-8", errors="replace")
        merged = merge_routes_into_pcb(pcb_content, route_sexp)

        stats = router.get_statistics()
        nets_routed = stats.get("nets_routed", len(routes))
        nets_total = stats.get("nets_to_route", max(nets_routed, 1))
        routed_pct = round(nets_routed / nets_total * 100) if nets_total else 100

        seg_count = len(re.findall(r'\(segment[\s\n]', merged))
        logger.info(
            "kicad-tools A*: %d segments, %d nets routés (%d%%)",
            seg_count, nets_routed, routed_pct,
        )
        return merged.encode("utf-8"), routed_pct


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
    """
    Auto-route a board.

    Priority:
      1. kicad-tools A* (negotiated) — ≤30 composants ET ≤30 nets, timeout 60s.
      2. Freerouting (Java)          — circuits complexes ou si kicad-tools échoue.
      3. skipped=True                — aucun routeur disponible → GND plane seulement.
    """
    try:
        pcb_bytes = base64.b64decode(req.kicad_pcb_b64)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid base64: {exc}") from exc

    net_count = _count_routable_nets(pcb_bytes)
    comp_count = _count_footprints(pcb_bytes)
    is_simple = net_count <= _KICAD_TOOLS_MAX_NETS and comp_count <= _KICAD_TOOLS_MAX_COMPS

    logger.info(
        "route_auto: %d routable nets, %d composants — simple=%s",
        net_count, comp_count, is_simple,
    )

    # --- Niveau 1 : kicad-tools A* (circuits simples) ---
    if is_simple:
        try:
            new_pcb, routed_pct = _route_with_kicad_tools(pcb_bytes)
            logger.info("kicad-tools A*: %d%% routé", routed_pct)
            return RouteAutoResponse(
                kicad_pcb_b64=base64.b64encode(new_pcb).decode("ascii"),
                routed_percent=routed_pct,
                layers=req.layers,
                skipped=False,
            )
        except Exception as exc:
            logger.warning("kicad-tools A* échoué (%s) — Freerouting", exc)

    # --- Niveau 2 : Freerouting Java ---
    paths = _find_freerouting()
    if paths is not None:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dsn = Path(tmp) / "board.dsn"
                ses = Path(tmp) / "board.ses"
                _export_specctra(pcb_bytes, dsn)
                _run_freerouting(paths, dsn, ses, req.timeout_s)
                new_pcb = _specctra_roundtrip(pcb_bytes, ses)
            logger.info("Freerouting: 100%% routé")
            return RouteAutoResponse(
                kicad_pcb_b64=base64.b64encode(new_pcb).decode("ascii"),
                routed_percent=100,
                layers=req.layers,
                skipped=False,
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Freerouting échoué: %s", exc)
            raise HTTPException(status_code=500, detail="routing failed") from exc

    # --- Niveau 3 : skipped → GND plane seulement (TypeScript addGroundPlane) ---
    reason = (
        f"kicad-tools A* indisponible et Freerouting (Java) introuvable"
        if is_simple
        else f"Circuit complexe ({net_count} nets, {comp_count} composants) — Freerouting (Java) introuvable"
    )
    logger.info("Routage ignoré — %s", reason)
    return RouteAutoResponse(
        kicad_pcb_b64=None,
        routed_percent=0,
        layers=req.layers,
        skipped=True,
        warning=reason,
    )
