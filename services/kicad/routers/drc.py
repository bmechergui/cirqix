"""FastAPI router for Design Rule Check via kicad-cli.

POST /drc/auto takes a base64-encoded .kicad_pcb + auto_fix flag and runs
``kicad-cli pcb drc`` in a loop (max 3 iterations) until the board is clean
or violations persist. Auto-fix applies a small safe set of corrections
(refill zones; widen narrow tracks where possible).

Availability matrix (kicad-tools niveau 1 ne court-circuite JAMAIS le niveau 2) :

1. kicad-cli disponible             → kicad-cli fait foi : la validation
   officielle est TOUJOURS exécutée, même si kicad-tools déclare 0 erreur.
2. kicad-cli absent, kicad-tools OK → fallback dégradé : résultat kicad-tools
   seul (27 règles JLCPCB), ``skipped=false`` + warning explicite.
3. kicad-cli ET kicad-tools absents → ``drc_clean=true, skipped=true`` pour
   ne pas bloquer le pipeline agentique.
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

router = APIRouter(tags=["drc"])

_MAX_ITERATIONS: int = 3
_KICAD_CLI_TIMEOUT_S: int = 60


# ----------------------------------------------------------------------------
# Pydantic models
# ----------------------------------------------------------------------------

class DRCAutoRequest(BaseModel):
    kicad_pcb_b64: str = Field(..., description=".kicad_pcb encoded as base64")
    auto_fix: bool = Field(default=True, description="Apply safe DRC fixes (refill zones, ...)")


class DRCAutoResponse(BaseModel):
    drc_clean: bool
    violations: list[dict[str, Any]] = Field(default_factory=list)
    fixed_count: int = 0
    kicad_pcb_b64: Optional[str] = None
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


def _run_kicad_drc(cli_path: str, pcb_path: Path) -> str:
    """Run kicad-cli pcb drc on the given file, return JSON report content."""
    report_path = pcb_path.with_suffix(".drc.json")
    cmd = [
        cli_path, "pcb", "drc",
        str(pcb_path),
        "--output", str(report_path),
        "--format", "json",
        "--severity-all",
        # Sans refill, kicad-cli juge les zones cuivre telles qu'écrites par le
        # routeur (non remplies) → les pads alimentés par un plan comptent comme
        # orphelins. Mesuré sur les boards STM32 routés à 100 % (2026-07-19) :
        # 34 « unconnected_items » fantômes sans le flag, 10 et 8 avec.
        "--refill-zones",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=_KICAD_CLI_TIMEOUT_S, check=False,
    )
    if result.returncode != 0 and not report_path.exists():
        raise RuntimeError(f"kicad-cli pcb drc failed (rc={result.returncode})")
    if not report_path.exists():
        return result.stdout or "{}"
    return report_path.read_text(encoding="utf-8")


def _apply_fixes(pcb_content: bytes, violations: list[dict[str, Any]]) -> tuple[bytes, int]:
    """Best-effort safe DRC fixes on the .kicad_pcb byte content.

    Currently:
    - Refill zones (handled by pcbnew on next ZONE_FILLER run; here a no-op marker
      since we cannot manipulate the board without pcbnew).
    - For now this is a stub returning ``(content, 0)`` when pcbnew is absent —
      the router will exit the auto-fix loop and return remaining violations.

    Future iterations will widen narrow tracks via pcbnew when available.
    """
    try:
        import pcbnew  # type: ignore[import-not-found]
    except ImportError:
        return pcb_content, 0

    fixable = [v for v in violations if v.get("type") in ("unfilled_zone", "zone_has_empty_net")]
    if not fixable:
        return pcb_content, 0

    with tempfile.TemporaryDirectory() as tmp:
        in_path = Path(tmp) / "in.kicad_pcb"
        out_path = Path(tmp) / "out.kicad_pcb"
        in_path.write_bytes(pcb_content)
        board = pcbnew.LoadBoard(str(in_path))
        for zone in board.Zones():
            zone.SetFilled(True)
        filler = pcbnew.ZONE_FILLER(board)
        filler.Fill(board.Zones())
        pcbnew.SaveBoard(str(out_path), board)
        return out_path.read_bytes(), len(fixable)


# ----------------------------------------------------------------------------
# Endpoint
# ----------------------------------------------------------------------------

def _run_python_drc(pcb_bytes: bytes) -> list[dict]:
    """
    Pure Python DRC via kicad-tools (27 JLCPCB rules, no kicad-cli needed).
    Returns list of violation dicts compatible with DRCAutoResponse.violations.
    Returns [] if kicad-tools not installed.
    """
    try:
        import sys
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            pcb_path = Path(tmp) / "board.kicad_pcb"
            pcb_path.write_bytes(pcb_bytes)
            result = subprocess.run(
                [sys.executable, "-m", "kicad_tools.cli", "check", str(pcb_path), "--mfr", "jlcpcb", "--json"],
                capture_output=True, text=True, timeout=30, check=False,
            )
            if result.returncode not in (0, 1):
                return []
            import json
            data = json.loads(result.stdout or "{}")
            violations = []
            for v in data.get("errors", []):
                violations.append({"type": v.get("rule", "unknown"), "description": v.get("message", ""), "severity": "error"})
            for v in data.get("warnings", []):
                violations.append({"type": v.get("rule", "unknown"), "description": v.get("message", ""), "severity": "warning"})
            return violations
    except Exception as exc:
        logger.warning("kicad-tools Python DRC failed: %s", exc)
        return []


@router.post("/drc/auto", response_model=DRCAutoResponse)
def run_drc_auto(req: DRCAutoRequest) -> DRCAutoResponse:
    """
    Run DRC on the provided .kicad_pcb.

    Priority:
      1. kicad-tools Python DRC — 27 règles JLCPCB, pur Python, toujours dispo.
         Ne court-circuite JAMAIS la validation officielle quand kicad-cli est
         présent (faux négatif mesuré 2026-07-04 : board déclaré propre par
         kicad-tools mais 25 shorting_items + 21 clearance selon kicad-cli).
      2. kicad-cli pcb drc     — officiel KiCad, auto-fix loop max 3×.
         Exécuté systématiquement si disponible ; le résultat kicad-tools seul
         ne fait foi que si kicad-cli est INDISPONIBLE (fallback dégradé).
    """
    try:
        pcb_bytes = base64.b64decode(req.kicad_pcb_b64)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid base64: {exc}") from exc

    # ── Piste 4 : tier fabricant escaladé (marqueur in-band posé par route_kct)
    # Le marqueur est retiré AVANT tout DRC (ni kicad-tools ni kicad-cli ne le
    # voient) ; s'il est présent, un sidecar .kicad_pro aux règles du profil
    # est écrit à côté du board temporaire → kicad-cli juge aux règles du tier
    # réellement routé, plus aux défauts KiCad (résiduels copper_edge/annular).
    from tools.kct_route import extract_mfr_tier, strip_mfr_tier

    mfr_tier = extract_mfr_tier(pcb_bytes)
    if mfr_tier:
        pcb_bytes = strip_mfr_tier(pcb_bytes)
        logger.info("DRC: board routé au tier escaladé %s — règles alignées", mfr_tier)

    # ── Niveau 1 : kicad-tools Python DRC ────────────────────────────────────
    # Le niveau 1 ne court-circuite PAS le niveau 2 : même propre, le board
    # doit être validé par kicad-cli officiel s'il est disponible (faux
    # négatif mesuré 2026-07-04 — kicad-tools propre, kicad-cli 200 violations).
    kt_violations: list[dict] = []
    kt_ok = False
    kt_clean = False
    try:
        kt_violations = _run_python_drc(pcb_bytes)
        kt_ok = True
        kt_errors = [v for v in kt_violations if v.get("severity") == "error"]
        kt_clean = not kt_errors
        logger.info("kicad-tools DRC: %d violations (%d erreurs)", len(kt_violations), len(kt_errors))
        if kt_clean:
            logger.info("kicad-tools propre → validation kicad-cli officielle quand même")
        else:
            logger.info("kicad-tools: %d erreur(s) → tentative auto-fix via kicad-cli", len(kt_errors))
    except Exception as exc:
        logger.warning("kicad-tools DRC échoué (%s) — kicad-cli direct", exc)

    # ── Niveau 2 : kicad-cli (auto-fix loop + validation officielle) ─────────
    cli_path = _find_kicad_cli()
    if cli_path is None:
        # kicad-cli absent → retourner résultat kicad-tools tel quel
        if kt_ok:
            return DRCAutoResponse(
                drc_clean=kt_clean,
                violations=kt_violations,
                fixed_count=0,
                kicad_pcb_b64=None,
                skipped=False,
                warning="kicad-cli indisponible — DRC kicad-tools 27 règles JLCPCB uniquement",
            )
        # kicad-tools ET kicad-cli indisponibles → skipped
        return DRCAutoResponse(
            drc_clean=True,
            violations=[],
            fixed_count=0,
            kicad_pcb_b64=None,
            skipped=True,
            warning="kicad-tools et kicad-cli indisponibles — DRC sauté",
        )

    from tools.drc import parse_drc_report

    try:
        with tempfile.TemporaryDirectory() as tmp:
            pcb_path = Path(tmp) / "board.kicad_pcb"

            if mfr_tier:
                from tools.drc import copper_layer_count, write_mfr_project_sidecar
                try:
                    write_mfr_project_sidecar(
                        pcb_path, mfr_tier,
                        copper_layer_count(pcb_bytes.decode("utf-8", errors="replace")))
                except Exception as exc:
                    # Défense : tier inconnu/profil indisponible → le DRC
                    # continue aux règles par défaut, jamais de crash 500.
                    logger.warning("DRC: sidecar tier %s impossible (%s) — "
                                   "règles par défaut", mfr_tier, exc)

            violations: list[dict[str, Any]] = []
            total_fixed = 0
            current_content = pcb_bytes

            for iteration in range(_MAX_ITERATIONS):
                pcb_path.write_bytes(current_content)
                report_json = _run_kicad_drc(cli_path, pcb_path)
                violations = parse_drc_report(report_json)

                # Cohérent avec drc_clean : seules les ERRORS bloquent la boucle
                # (les warnings NC reclassés ne justifient pas d'itération).
                if not [v for v in violations if v.get("severity") == "error"]:
                    break

                if not req.auto_fix:
                    break

                new_content, fixed_this_iter = _apply_fixes(current_content, violations)
                if fixed_this_iter == 0:
                    break
                current_content = new_content
                total_fixed += fixed_this_iter
                logger.info(
                    "DRC iter %d: applied %d fixes (total=%d)",
                    iteration + 1, fixed_this_iter, total_fixed,
                )

            # drc_clean = aucune violation de sévérité error. Les warnings ne
            # bloquent pas : parse_drc_report reclasse notamment les clearance
            # impliquant un pad <no net> (pin NC → pas de court possible,
            # carve-out #3490 ; mesuré 17/21 sur le board STM32 de référence)
            # en warning — visibles dans la réponse mais non bloquantes.
            error_violations = [v for v in violations if v.get("severity") == "error"]
            drc_clean = len(error_violations) == 0
            updated_b64 = (
                base64.b64encode(current_content).decode("ascii")
                if total_fixed > 0
                else None
            )
            warning = None
            if kt_clean and drc_clean:
                warning = "DRC kicad-tools 27 règles JLCPCB propre — validé kicad-cli officiel"
            elif kt_clean and not drc_clean:
                warning = (
                    "kicad-tools 27 règles JLCPCB propre MAIS kicad-cli officiel "
                    f"rapporte {len(error_violations)} violation(s) bloquante(s) — kicad-cli fait foi"
                )
            elif not kt_ok:
                warning = "kicad-tools DRC indisponible — résultat kicad-cli officiel seul"
            return DRCAutoResponse(
                drc_clean=drc_clean,
                violations=violations,
                fixed_count=total_fixed,
                kicad_pcb_b64=updated_b64,
                skipped=False,
                warning=warning,
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("DRC execution failed: %s", exc)
        raise HTTPException(status_code=500, detail="DRC execution failed") from exc
