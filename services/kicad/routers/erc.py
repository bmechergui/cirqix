"""FastAPI router for Electrical Rules Check (ERC) via kicad-cli.

POST /erc takes a base64-encoded .kicad_sch + auto_fix flag and runs
``kicad-cli sch erc`` in a loop (max 3 iterations) until the schematic is
clean or violations persist. Auto-fix only adds ``(no_connect ...)`` markers —
NEVER modifies connectivity.

If ``kicad-cli`` is not available on the host PATH, the endpoint returns
``erc_clean=true, skipped=true`` so the agentic pipeline continues unblocked.
"""
from __future__ import annotations

import base64
import json
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

# Maximum auto-fix iterations before giving up
_MAX_ITERATIONS: int = 3
_KICAD_CLI_TIMEOUT_S: int = 30


# ----------------------------------------------------------------------------
# Pydantic models
# ----------------------------------------------------------------------------

class ERCRequest(BaseModel):
    kicad_sch_b64: str = Field(..., description="Contenu .kicad_sch encodé base64")
    auto_fix: bool = Field(default=True, description="Add no_connect markers for pin_not_connected")


class ERCViolationDTO(BaseModel):
    id: str
    severity: str  # 'error' | 'warning'
    message: str
    type: Optional[str] = None
    ref: Optional[str] = None
    pin: Optional[str] = None
    x_mm: Optional[float] = None
    y_mm: Optional[float] = None


class ERCResponse(BaseModel):
    erc_clean: bool
    violations: list[dict[str, Any]] = Field(default_factory=list)
    fixed_count: int = 0
    kicad_sch_b64: Optional[str] = None
    skipped: bool = False
    warning: Optional[str] = None


# ----------------------------------------------------------------------------
# Internal helpers (mocked in tests)
# ----------------------------------------------------------------------------

def _find_kicad_cli() -> Optional[str]:
    """Locate the ``kicad-cli`` binary, honoring KICAD_CLI_PATH env override."""
    override = os.environ.get("KICAD_CLI_PATH")
    if override and Path(override).exists():
        return override
    return shutil.which("kicad-cli")


def _run_kicad_erc(cli_path: str, sch_path: Path) -> str:
    """Run kicad-cli sch erc on the given file, return the JSON report content."""
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
        # ERC may exit non-zero when violations are present but still write the report
        raise RuntimeError(
            f"kicad-cli sch erc failed (rc={result.returncode}): {result.stderr[:500]}"
        )
    if not report_path.exists():
        # Some KiCad versions emit to stdout
        return result.stdout or "{}"
    return report_path.read_text(encoding="utf-8")


# ----------------------------------------------------------------------------
# Endpoint
# ----------------------------------------------------------------------------

@router.post("/erc", response_model=ERCResponse)
def run_erc(req: ERCRequest) -> ERCResponse:
    """Run ERC on the provided .kicad_sch and return violations + (optionally) fixed file."""
    cli_path = _find_kicad_cli()
    if cli_path is None:
        logger.info("kicad-cli not on PATH — skipping ERC")
        return ERCResponse(
            erc_clean=True,
            violations=[],
            fixed_count=0,
            kicad_sch_b64=None,
            skipped=True,
            warning="kicad-cli not available",
        )

    # Lazy import to keep router import cheap when pcbnew-only tests run
    from tools.erc import apply_no_connect_fixes, parse_erc_report

    try:
        sch_bytes = base64.b64decode(req.kicad_sch_b64)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid base64: {exc}") from exc

    try:
        with tempfile.TemporaryDirectory() as tmp:
            sch_path = Path(tmp) / "schematic.kicad_sch"
            sch_path.write_bytes(sch_bytes)

            violations: list[dict[str, Any]] = []
            total_fixed = 0
            current_content = sch_bytes.decode("utf-8", errors="replace")

            for iteration in range(_MAX_ITERATIONS):
                sch_path.write_text(current_content, encoding="utf-8")
                report_json = _run_kicad_erc(cli_path, sch_path)
                violations = parse_erc_report(report_json)

                if not violations:
                    break  # clean

                if not req.auto_fix:
                    break  # stop without attempting fixes

                fixable = [v for v in violations if v.get("type") == "pin_not_connected"]
                if not fixable:
                    break  # nothing we can auto-fix

                new_content, fixed_this_iter = apply_no_connect_fixes(current_content, fixable)
                total_fixed += fixed_this_iter
                if fixed_this_iter == 0:
                    break  # no progress, exit
                current_content = new_content
                logger.info(
                    "ERC iter %d: fixed %d pin_not_connected (total=%d)",
                    iteration + 1, fixed_this_iter, total_fixed,
                )

            erc_clean = len(violations) == 0
            updated_b64 = (
                base64.b64encode(current_content.encode("utf-8")).decode("ascii")
                if total_fixed > 0
                else None
            )
            return ERCResponse(
                erc_clean=erc_clean,
                violations=violations,
                fixed_count=total_fixed,
                kicad_sch_b64=updated_b64,
                skipped=False,
                warning=None,
            )
    except HTTPException:
        raise
    except Exception as exc:
        # Log the full exception server-side; never leak filesystem paths or
        # kicad-cli stderr to the HTTP client.
        logger.exception("ERC execution failed: %s", exc)
        raise HTTPException(status_code=500, detail="ERC execution failed") from exc
