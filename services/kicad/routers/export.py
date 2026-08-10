"""FastAPI router for PCB export — Gerbers + drill + pick-and-place.

POST /export/all prend un .kicad_pcb base64 et retourne un ZIP de fichiers
de fabrication.

Pipeline :
  1. kicad-tools kct export --mfr jlcpcb
     → noms couches JLCPCB (GTL/GBL/GKO), BOM LCSC, CPL rotation corrections
  2. kicad-cli pcb export {gerbers,drill,pos}
     → export standard si kicad-tools échoue
  3. skipped=True → BOM CSV uniquement (kicad-cli absent)

JAMAIS commander JLCPCB sans "OUI JE CONFIRME" explicite.
"""
from __future__ import annotations

import base64
import io
import logging
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["export"])

_KICAD_CLI_TIMEOUT_S: int = 60

# Extensions / names that count as mandatory manufacturing deliverables.
# Gerbers: RS-274X (.gbr) + Protel-style JLCPCB names (GTL/GBL/GKO…).
# Drill: Excellon (.drl) and common alternates.
_GERBER_SUFFIXES: frozenset[str] = frozenset({
    ".gbr", ".gtl", ".gbl", ".gts", ".gbs", ".gto", ".gbo",
    ".gko", ".gm1", ".gm3", ".gtp", ".gbp",
})
_DRILL_SUFFIXES: frozenset[str] = frozenset({".drl", ".xln", ".exc"})


# ----------------------------------------------------------------------------
# Pydantic models
# ----------------------------------------------------------------------------

class ExportAllRequest(BaseModel):
    kicad_pcb_b64: str = Field(..., description=".kicad_pcb encoded as base64")
    project_id: str = Field(
        default="cirqix-pcb",
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Safe project identifier used for filenames",
    )


class ExportAllResponse(BaseModel):
    files: list[str] = Field(default_factory=list)
    zip_b64: Optional[str] = None
    # A file count has no relationship to PCB pricing and is not a quote.
    quote_usd: Optional[float] = None
    lead_time_days: Optional[int] = None
    skipped: bool = False
    warning: Optional[str] = None


# ----------------------------------------------------------------------------
# Internal helpers (mocked in tests)
# ----------------------------------------------------------------------------

def _find_kicad_cli() -> Optional[str]:
    override = os.environ.get("KICAD_CLI_PATH")
    if override and Path(override).exists():
        return override
    return shutil.which("kicad-cli")


def _is_gerber_file(name: str) -> bool:
    """True if *name* looks like a copper/mask/silkscreen/edge Gerber layer."""
    lower = name.lower()
    suffix = Path(lower).suffix
    if suffix in _GERBER_SUFFIXES:
        return True
    # kicad-cli may emit e.g. board-F_Cu.gbr already covered; also bare protel stems
    stem = Path(lower).stem
    return stem.endswith((
        "-f_cu", "-b_cu", "-f_mask", "-b_mask", "-f_silks", "-b_silks",
        "-edge_cuts", "-f_paste", "-b_paste",
    ))


def _is_drill_file(name: str) -> bool:
    """True if *name* looks like an Excellon / drill manufacturing file."""
    lower = name.lower()
    if Path(lower).suffix in _DRILL_SUFFIXES:
        return True
    # Some exporters use e.g. board-PTH.drl (suffix) or board.drl already covered.
    return lower.endswith("-npth.txt") or lower.endswith("-pth.txt")


def _require_manufacturing_deliverables(files: list[str]) -> None:
    """Fail closed: a successful export must include Gerbers AND drill files.

    An empty or partial ZIP must never be presented as a successful fabrication
    package — it gates a real paid JLCPCB order.
    """
    has_gerber = any(_is_gerber_file(f) for f in files)
    has_drill = any(_is_drill_file(f) for f in files)
    if has_gerber and has_drill:
        return
    missing: list[str] = []
    if not has_gerber:
        missing.append("gerber layers")
    if not has_drill:
        missing.append("drill files")
    raise RuntimeError(
        "export incomplete — missing required manufacturing files: "
        + ", ".join(missing)
        + f" (got: {files or '[]'})"
    )


def _export_with_kicad_tools(pcb_path: Path, out_dir: Path) -> list[str]:
    """kicad-tools kct export --mfr jlcpcb.
    JLCPCB layer names, BOM LCSC, CPL rotation corrections.
    Returns list of generated files. Raises on failure or incomplete package.
    """
    import sys as _sys
    out_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            _sys.executable, "-m", "kicad_tools.cli", "export",
            str(pcb_path),
            "--mfr", "jlcpcb",
            "--output", str(out_dir),
            "--skip-preflight",   # DRC already done by call_agent_drc
        ],
        capture_output=True, text=True,
        timeout=_KICAD_CLI_TIMEOUT_S + 30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"kicad-tools export failed (rc={result.returncode}): {result.stderr[:300]}"
        )
    files = sorted(p.name for p in out_dir.rglob("*") if p.is_file())
    _require_manufacturing_deliverables(files)
    return files


def _kicad_export_all(cli_path: str, pcb_path: Path, out_dir: Path) -> list[str]:
    """Run kicad-cli to produce Gerbers + drill + position files. Returns file list.

    Gerbers and drill are mandatory: non-zero exit or missing output fails hard.
    Pick-and-place (pos) is best-effort — bare-board orders do not require it.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Required: Gerbers ────────────────────────────────────────────────────
    gerber_cmd = [
        cli_path, "pcb", "export", "gerbers",
        str(pcb_path), "--output", str(out_dir),
    ]
    gerber_result = subprocess.run(
        gerber_cmd, capture_output=True, text=True,
        timeout=_KICAD_CLI_TIMEOUT_S, check=False,
    )
    if gerber_result.returncode != 0:
        raise RuntimeError(
            f"kicad-cli gerbers failed (rc={gerber_result.returncode}): "
            f"{(gerber_result.stderr or '')[:300]}"
        )

    # ── Required: Drill (Excellon) ───────────────────────────────────────────
    drill_cmd = [
        cli_path, "pcb", "export", "drill",
        str(pcb_path), "--output", str(out_dir),
    ]
    drill_result = subprocess.run(
        drill_cmd, capture_output=True, text=True,
        timeout=_KICAD_CLI_TIMEOUT_S, check=False,
    )
    if drill_result.returncode != 0:
        raise RuntimeError(
            f"kicad-cli drill failed (rc={drill_result.returncode}): "
            f"{(drill_result.stderr or '')[:300]}"
        )

    # ── Optional: Pick & place (CPL) — warn only ─────────────────────────────
    pos_cmd = [
        cli_path, "pcb", "export", "pos",
        str(pcb_path),
        "--output", str(out_dir / "pos.csv"),
        "--format", "csv",
        "--units", "mm",
    ]
    pos_result = subprocess.run(
        pos_cmd, capture_output=True, text=True,
        timeout=_KICAD_CLI_TIMEOUT_S, check=False,
    )
    if pos_result.returncode != 0:
        logger.warning(
            "kicad-cli pos (CPL) failed (rc=%d) — continuing without pick-and-place",
            pos_result.returncode,
        )

    files = sorted(p.name for p in out_dir.iterdir() if p.is_file())
    _require_manufacturing_deliverables(files)
    return files


def _make_zip(out_dir: Path, files: list[str]) -> bytes:
    """Build an in-memory ZIP of the given files."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in files:
            path = out_dir / name
            if path.is_file():
                zf.write(path, name)
    return buf.getvalue()


# ----------------------------------------------------------------------------
# Endpoint
# ----------------------------------------------------------------------------

@router.post(
    "/export/all",
    response_model=ExportAllResponse,
    response_model_exclude_none=True,
)
def export_all(req: ExportAllRequest) -> ExportAllResponse:
    """Generate manufacturing files (Gerbers + drill + CPL) and return as zip.

    Priority:
      1. kicad-tools kct export --mfr jlcpcb  (JLCPCB-optimisé)
      2. kicad-cli pcb export {gerbers,drill,pos}  (fallback standard)
      3. skipped=True  (kicad-cli absent)
    """
    try:
        pcb_bytes = base64.b64decode(req.kicad_pcb_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="invalid base64 in kicad_pcb_b64") from exc

    cli_path = _find_kicad_cli()
    if cli_path is None:
        logger.info("kicad-cli absent — export ignoré")
        return ExportAllResponse(
            files=[], zip_b64=None,
            skipped=True, warning="kicad-cli not available",
        )

    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            pcb_path = tmp_dir / f"{req.project_id}.kicad_pcb"
            pcb_path.write_bytes(pcb_bytes)

            # ── Niveau 1 : kicad-tools (JLCPCB-optimisé) ─────────────────────
            files: list[str] = []
            out_dir = tmp_dir / "manufacturing"
            used_kicad_tools = False
            try:
                files = _export_with_kicad_tools(pcb_path, out_dir)
                used_kicad_tools = True
                logger.info("kicad-tools export: %d fichiers", len(files))
            except Exception as exc:
                logger.warning("kicad-tools export échoué (%s) — kicad-cli direct", exc)

            # ── Niveau 2 : kicad-cli standard ────────────────────────────────
            if not files:
                out_dir.mkdir(parents=True, exist_ok=True)
                files = _kicad_export_all(cli_path, pcb_path, out_dir)
                logger.info("kicad-cli export: %d fichiers", len(files))

            # Fail closed: never return skipped=False without Gerbers + drill.
            # Both export paths already enforce this; re-check before success.
            _require_manufacturing_deliverables(files)

            zip_bytes = _make_zip(out_dir, files)
            return ExportAllResponse(
                files=files,
                zip_b64=base64.b64encode(zip_bytes).decode("ascii"),
                skipped=False,
                warning=None if used_kicad_tools else "kicad-tools unavailable — kicad-cli export",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Export échoué: %s", exc)
        raise HTTPException(status_code=500, detail="export failed") from exc
