"""
Layrix — Placement (tools/placement.py)

Délègue au workflow officiel kicad-tools (aucun algo custom) :
  1. place_components()  — positions explicites fournies par l'agent
  2. auto_place()        — placement auto via l'API/CLI officielle :
       a. place_unplaced()          → placement initial (grille cluster-by-net)
       b. kct placement optimize    → raffinement (force-directed, connecteurs fixés)
"""

from __future__ import annotations

import base64
import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mode 1 : placement explicite (coordonnées fournies par l'agent)
# ---------------------------------------------------------------------------

def place_components(pcb_path: str, components: list[dict], output_path: str) -> dict:
    try:
        import pcbnew  # type: ignore
    except ImportError as exc:
        raise ImportError("pcbnew non disponible — KiCad doit être installé") from exc

    board = pcbnew.LoadBoard(pcb_path)
    placed: list[str] = []
    errors: list[str] = []

    for comp in components:
        fp = board.FindFootprintByReference(comp["ref"])
        if not fp:
            errors.append(f"Footprint {comp['ref']} introuvable")
            continue
        x_iu = pcbnew.FromMM(float(comp["x_mm"]))
        y_iu = pcbnew.FromMM(float(comp["y_mm"]))
        if hasattr(pcbnew, "VECTOR2I"):
            fp.SetPosition(pcbnew.VECTOR2I(x_iu, y_iu))
        else:
            fp.SetPosition(pcbnew.wxPoint(x_iu, y_iu))
        rotation = float(comp.get("rotation", 0.0))
        if hasattr(fp, "SetOrientationDegrees"):
            fp.SetOrientationDegrees(rotation)
        else:
            fp.SetOrientation(rotation * 10)
        if comp.get("side") == "back":
            fp.Flip(fp.GetPosition(), False)
        placed.append(comp["ref"])

    pcbnew.SaveBoard(output_path, board)
    return {"status": "ok", "path": output_path, "placed": len(placed), "errors": errors}


# ---------------------------------------------------------------------------
# Mode 2 : auto-placement — workflow officiel kicad-tools
# ---------------------------------------------------------------------------

def _connector_refs(pcb) -> list[str]:
    """Références des connecteurs (J*, P*) à figer pendant l'optimisation.

    Recette officielle (docs/guides/placement-optimization.md) : verrouiller les
    footprints à contrainte physique (connecteurs) et laisser l'optimiseur placer
    le reste.
    """
    return [fp.reference for fp in pcb.footprints
            if fp.reference and fp.reference[0] in ("J", "P")]


def auto_place(kicad_pcb_b64: str, board_width_mm: float, board_height_mm: float) -> dict:
    """Place automatiquement les footprints via le workflow officiel kicad-tools.

    1. ``place_unplaced`` — placement initial déterministe (grille cluster-by-net).
    2. ``kct placement optimize`` — raffinement force-directed, connecteurs fixés.

    Retourne le board optimisé ; sur erreur de l'optimiseur on garde le placement
    initial (toujours valide). Lève si même le placement initial échoue.
    """
    pcb_bytes = base64.b64decode(kicad_pcb_b64)

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.kicad_pcb"
        placed = Path(tmp) / "placed.kicad_pcb"
        optimized = Path(tmp) / "optimized.kicad_pcb"
        src.write_bytes(pcb_bytes)

        from kicad_tools.placement.place_unplaced import place_unplaced
        from kicad_tools.schema.pcb import PCB

        # 1. Placement initial officiel (grille cluster-by-net)
        result = place_unplaced(
            str(src), output_path=str(placed),
            margin=2.0, spacing=2.0, cluster=True,
        )
        placed_refs = list(result.placed_refs)
        logger.info("place_unplaced: %d placés, %d overflow",
                    len(placed_refs), len(result.overflow_refs))
        if not placed.exists() or not placed_refs:
            raise RuntimeError("place_unplaced n'a rien placé")

        best = placed  # fallback = placement initial (toujours valide)

        # 2. Raffinement officiel : kct optimize-placement (CMA-ES).
        #    Recette validée (docs/guides/placement-optimization.md) :
        #    verrouiller les connecteurs (J*/P*) → --anchor-weight garde leurs
        #    nets courts ; le coût wirelength groupe automatiquement les grappes
        #    (Quartz+caps près du MCU) ; --allow-infeasible laisse le routeur
        #    --auto-fix absorber les violations de frontière résiduelles.
        try:
            pcb = PCB.load(str(placed))
            fixed = _connector_refs(pcb)
            for fp in pcb.footprints:
                if fp.reference in fixed:
                    fp.locked = True
            if fixed:
                pcb.save(str(placed))  # persist (locked) so --anchor-weight applies
                logger.info("connecteurs verrouillés: %s", fixed)

            cmd = [
                sys.executable, "-m", "kicad_tools.cli", "optimize-placement",
                str(placed), "-o", str(optimized),
                "--anchor-weight", "2.0",
                "--allow-infeasible",
                "--time-budget", "120",
                "--seed", "force-directed",
            ]
            r = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=180, check=False,
            )
            if optimized.exists():
                best = optimized
                logger.info("kct optimize-placement OK (rc=%s)", r.returncode)
            else:
                logger.warning("kct optimize-placement sans sortie (rc=%s) — garde place_unplaced",
                               r.returncode)
        except Exception as exc:
            logger.warning("optimize-placement exception (%s) — garde place_unplaced", exc)

        out_bytes = best.read_bytes()
        positions = [
            {"ref": fp.reference,
             "x": round(fp.position[0], 2), "y": round(fp.position[1], 2)}
            for fp in PCB.load(str(best)).footprints
        ]
        return {
            "kicad_pcb_b64": base64.b64encode(out_bytes).decode(),
            "placed_count": len(placed_refs),
            "positions": positions,
        }
