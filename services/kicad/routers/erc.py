"""FastAPI router — Electrical Rules Check (ERC).

POST /erc — 3-level pipeline:
  1. kicad-tools Schematic.validate()   — pur Python, toujours disponible
  2. kicad-cli sch erc                  — ERC officiel KiCad (si disponible)
  3. skipped=true                       → TypeScript runErcFallback() prend le relais

Auto-fix uniquement : (no_connect ...) markers + corrections off-grid.
JAMAIS modifier la connectivité.
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

router = APIRouter(tags=["erc"])

_MAX_ITERATIONS: int = 3
_KICAD_CLI_TIMEOUT_S: int = 30


# ----------------------------------------------------------------------------
# Pydantic models
# ----------------------------------------------------------------------------

class ERCRequest(BaseModel):
    kicad_sch_b64: str = Field(..., description="Contenu .kicad_sch encodé base64")
    auto_fix: bool = Field(default=True)


class ERCResponse(BaseModel):
    erc_clean: bool
    violations: list[dict[str, Any]] = Field(default_factory=list)
    fixed_count: int = 0
    kicad_sch_b64: Optional[str] = None
    skipped: bool = False
    warning: Optional[str] = None
    engine: str = "kicad-tools"


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _find_kicad_cli() -> Optional[str]:
    override = os.environ.get("KICAD_CLI_PATH")
    if override and Path(override).exists():
        return override
    return shutil.which("kicad-cli")


def _run_kicad_cli_erc(cli_path: str, sch_path: Path) -> str:
    report_path = sch_path.with_suffix(".erc.json")
    cmd = [
        cli_path, "sch", "erc",
        str(sch_path),
        "--output", str(report_path),
        "--format", "json",
        "--severity-all",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=_KICAD_CLI_TIMEOUT_S, check=False,
    )
    if result.returncode != 0 and not report_path.exists():
        raise RuntimeError(
            f"kicad-cli sch erc failed (rc={result.returncode}): {result.stderr[:500]}"
        )
    if not report_path.exists():
        return result.stdout or "{}"
    return report_path.read_text(encoding="utf-8")


# ----------------------------------------------------------------------------
# Endpoint
# ----------------------------------------------------------------------------

@router.post("/erc", response_model=ERCResponse)
def run_erc(req: ERCRequest) -> ERCResponse:
    from tools.erc import apply_no_connect_fixes, parse_erc_report, run_kicad_tools_erc

    try:
        sch_bytes = base64.b64decode(req.kicad_sch_b64)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid base64: {exc}") from exc

    current_content = sch_bytes.decode("utf-8", errors="replace")

    # ── Step 1 : kicad-tools validate (pur Python, toujours disponible) ──────
    kt_violations: list[dict] = []
    kt_fixed = 0
    try:
        kt_violations, current_content, kt_fixed = run_kicad_tools_erc(
            current_content, req.auto_fix
        )
        if kt_fixed > 0:
            logger.info("kicad-tools ERC: %d auto-fix(es) applied", kt_fixed)
    except Exception as exc:
        logger.warning("kicad-tools ERC failed (%s) — continuing to kicad-cli", exc)

    # ── Step 2 : kicad-cli (si disponible) ────────────────────────────────────
    cli_path = _find_kicad_cli()
    if cli_path is None:
        # Fail-closed : sans kicad-cli, jamais erc_clean=True.
        # skipped=True déclenche le vrai ERC de repli TypeScript (runErcFallback).
        # Les violations / fixed_count du pré-filtre restent exposés en diagnostic.
        updated_b64 = (
            base64.b64encode(current_content.encode("utf-8")).decode("ascii")
            if kt_fixed > 0 else None
        )
        return ERCResponse(
            erc_clean=False,
            violations=kt_violations,
            fixed_count=kt_fixed,
            kicad_sch_b64=updated_b64,
            skipped=True,
            warning=(
                "kicad-cli unavailable — authority ERC not run; "
                "pre-filter results are diagnostic only (TypeScript runErcFallback)"
            ),
            engine="kicad-tools",
        )

    try:
        with tempfile.TemporaryDirectory() as tmp:
            sch_path = Path(tmp) / "schematic.kicad_sch"
            pro_path = Path(tmp) / "schematic.kicad_pro"
            pro_path.write_text("{}", encoding="utf-8")

            violations: list[dict[str, Any]] = []
            total_fixed = kt_fixed  # inclut les fixes kicad-tools

            for iteration in range(_MAX_ITERATIONS):
                sch_path.write_text(current_content, encoding="utf-8")
                report_json = _run_kicad_cli_erc(cli_path, sch_path)
                violations = parse_erc_report(report_json)

                if not violations:
                    break

                if not req.auto_fix:
                    break

                fixable = [v for v in violations if v.get("type") == "pin_not_connected"]
                if not fixable:
                    break

                new_content, fixed_this_iter = apply_no_connect_fixes(current_content, fixable)
                total_fixed += fixed_this_iter
                if fixed_this_iter == 0:
                    break
                current_content = new_content
                logger.info(
                    "kicad-cli ERC iter %d: fixed %d pin_not_connected (total=%d)",
                    iteration + 1, fixed_this_iter, total_fixed,
                )

            erc_clean = len(violations) == 0
            updated_b64 = (
                base64.b64encode(current_content.encode("utf-8")).decode("ascii")
                if total_fixed > 0 else None
            )
            return ERCResponse(
                erc_clean=erc_clean,
                violations=violations,
                fixed_count=total_fixed,
                kicad_sch_b64=updated_b64,
                skipped=False,
                engine="kicad-cli",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("kicad-cli ERC failed: %s", exc)
        raise HTTPException(status_code=500, detail="ERC execution failed") from exc
