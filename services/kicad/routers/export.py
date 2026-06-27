"""FastAPI router for PCB export — Gerbers + drill + pick-and-place.

POST /export/all prend un .kicad_pcb base64 et retourne un ZIP de fichiers
de fabrication + devis JLCPCB estimé.

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


# ----------------------------------------------------------------------------
# Pydantic models
# ----------------------------------------------------------------------------

class ExportAllRequest(BaseModel):
    kicad_pcb_b64: str = Field(..., description=".kicad_pcb encoded as base64")
    project_id: str = Field(default="cirqix-pcb", description="Project identifier for filenames")


class ExportAllResponse(BaseModel):
    files: list[str] = Field(default_factory=list)
    zip_b64: Optional[str] = None
    quote_usd: float = 0.0
    lead_time_days: int = 0
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


def _export_with_kicad_tools(pcb_path: Path, out_dir: Path) -> list[str]:
    """kicad-tools kct export --mfr jlcpcb.
    JLCPCB layer names, BOM LCSC, CPL rotation corrections.
    Returns list of generated files. Raises on failure.
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
    return sorted(p.name for p in out_dir.rglob("*") if p.is_file())


def _kicad_export_all(cli_path: str, pcb_path: Path, out_dir: Path) -> list[str]:
    """Run kicad-cli to produce Gerbers + drill + position files. Returns file list."""
    out_dir.mkdir(parents=True, exist_ok=True)

    commands = [
        # Gerbers (all enabled layers)
        [cli_path, "pcb", "export", "gerbers", str(pcb_path), "--output", str(out_dir)],
        # Drill files (Excellon)
        [cli_path, "pcb", "export", "drill", str(pcb_path), "--output", str(out_dir)],
        # Pick & place (CPL) for JLCPCB assembly
        [
            cli_path, "pcb", "export", "pos",
            str(pcb_path),
            "--output", str(out_dir / "pos.csv"),
            "--format", "csv",
            "--units", "mm",
        ],
    ]
    for cmd in commands:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_KICAD_CLI_TIMEOUT_S, check=False,
        )
        if result.returncode != 0:
            logger.warning("kicad-cli command failed: %s (rc=%d)", cmd[2:5], result.returncode)
            # Continue — some sub-commands may fail (e.g. no assembly layer); the zip
            # will still contain whatever the other commands produced.

    return sorted(p.name for p in out_dir.iterdir() if p.is_file())


def _make_zip(out_dir: Path, files: list[str]) -> bytes:
    """Build an in-memory ZIP of the given files."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in files:
            path = out_dir / name
            if path.is_file():
                zf.write(path, name)
    return buf.getvalue()


def _estimate_quote(file_count: int) -> tuple[float, int]:
    """Return a coarse (price_usd, lead_time_days) estimate. JLCPCB-style baseline."""
    base_price = 5.0
    per_file = 0.5
    price = base_price + per_file * file_count
    lead_time = 7
    return round(price, 2), lead_time


# ----------------------------------------------------------------------------
# Endpoint
# ----------------------------------------------------------------------------

@router.post("/export/all", response_model=ExportAllResponse)
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
            files=[], zip_b64=None, quote_usd=0.0, lead_time_days=0,
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

            zip_bytes = _make_zip(out_dir, files)
            quote_usd, lead_time_days = _estimate_quote(len(files))
            return ExportAllResponse(
                files=files,
                zip_b64=base64.b64encode(zip_bytes).decode("ascii"),
                quote_usd=quote_usd,
                lead_time_days=lead_time_days,
                skipped=False,
                warning=None if used_kicad_tools else "kicad-tools unavailable — kicad-cli export",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Export échoué: %s", exc)
        raise HTTPException(status_code=500, detail="export failed") from exc
