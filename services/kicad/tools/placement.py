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


def _clamp_fixed_refs_to_outline(pcb, fixed_refs: list[str], margin_mm: float = 2.0) -> list[str]:
    """Ramène les footprints ``fixed_refs`` à l'intérieur du contour Edge.Cuts.

    ``PlacementOptimizer`` traite ``fixed_refs`` comme des ancrages immobiles :
    si call_agent_gen_pcb a posé un connecteur hors-carte (ex: J1 à y=135 sur
    un board 0..40), l'optimiseur le laisse hors-carte → nets inroutables (bug
    trouvé par examples/stm32-full-pipeline, routage 22%).

    Retourne la liste des références effectivement clampées.
    """
    from kicad_tools.optim.board_outline import extract_board_outline

    outline = extract_board_outline(pcb)
    if outline is None or not outline.vertices:
        return []

    # extract_board_outline() lit pcb._sexp (coordonnées sheet-absolute, voir
    # _detect_board_origin) alors que fp.position est board-relative — convertir
    # le contour dans le même repère avant de comparer aux positions.
    ox, oy = pcb.board_origin
    xs = [v.x - ox for v in outline.vertices]
    ys = [v.y - oy for v in outline.vertices]
    min_x, max_x = min(xs) + margin_mm, max(xs) - margin_mm
    min_y, max_y = min(ys) + margin_mm, max(ys) - margin_mm

    clamped: list[str] = []
    for fp in pcb.footprints:
        if fp.reference not in fixed_refs:
            continue
        x, y = fp.position
        cx = min(max(x, min_x), max_x)
        cy = min(max(y, min_y), max_y)
        if (cx, cy) != (x, y):
            logger.warning(
                "connector %s hors-carte (%.2f,%.2f) -> clampé (%.2f,%.2f)",
                fp.reference, x, y, cx, cy,
            )
            fp.position = (cx, cy)
            clamped.append(fp.reference)
    return clamped


def auto_place(kicad_pcb_b64: str, board_width_mm: float, board_height_mm: float) -> dict:
    """Optimise le placement d'un PCB déjà placé (fichier "unrouted" produit par
    l'agent gen) via l'API officielle ``PlacementOptimizer`` :
      · fixed_refs        → connecteurs (J*/P*) ancrés
      · enable_clustering → regroupe les grappes (caps/quartz près du MCU)
      · run() + snap_rotations_to_90() → rotations cardinales

    Filet : si des footprints arrivent hors-carte (vieux PCB à -1000), on fait
    d'abord un ``place_unplaced`` pour les ramener sur la carte.
    """
    pcb_bytes = base64.b64decode(kicad_pcb_b64)

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.kicad_pcb"
        out = Path(tmp) / "out.kicad_pcb"
        src.write_bytes(pcb_bytes)

        from kicad_tools.schema.pcb import PCB
        from kicad_tools.optim import PlacementOptimizer

        pcb = PCB.load(str(src))

        # Filet : footprints hors-carte (vieux PCB pré-placé à -1000) → placement initial
        if any(fp.position[0] < -100 or fp.position[1] < -100 for fp in pcb.footprints):
            from kicad_tools.placement.place_unplaced import place_unplaced
            place_unplaced(str(src), output_path=str(src),
                           margin=2.0, spacing=2.0, cluster=True)
            pcb = PCB.load(str(src))
            logger.info("footprints hors-carte → place_unplaced appliqué")

        # Optimisation officielle : clustering + connecteurs ancrés
        conn = _connector_refs(pcb)
        _clamp_fixed_refs_to_outline(pcb, conn)
        opt = PlacementOptimizer.from_pcb(pcb, fixed_refs=conn, enable_clustering=True)
        opt.run(iterations=1000)
        opt.snap_rotations_to_90()
        opt.write_to_pcb(pcb)
        pcb.save(str(out))
        logger.info("PlacementOptimizer: clustering + %d connecteurs ancrés", len(conn))

        footprints = PCB.load(str(out)).footprints
        return {
            "kicad_pcb_b64": base64.b64encode(out.read_bytes()).decode(),
            "placed_count": len(footprints),
            "positions": [
                {"ref": fp.reference,
                 "x": round(fp.position[0], 2), "y": round(fp.position[1], 2)}
                for fp in footprints
            ],
        }
