"""
Layrix — Placement
Deux modes :
  1. place_components(pcb_path, components, output_path) — positions explicites fournies par l'agent
  2. auto_place(pcb_b64, board_w, board_h) → dict
       Primaire : kicad-tools CMA-ES place_unplaced (cluster=True)
       Fallback  : pcbnew grille simple
"""

from __future__ import annotations

import base64
import logging
import re
import shutil
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
# Mode 2 : auto-placement (I/O base64)
# ---------------------------------------------------------------------------

def auto_place(
    kicad_pcb_b64: str,
    board_width_mm: float,
    board_height_mm: float,
) -> dict:
    pcb_text = base64.b64decode(kicad_pcb_b64).decode("utf-8", errors="replace")

    # Only inject Edge.Cuts when the PCB has no valid board outline.
    # PCBFromSchematic already writes correct Edge.Cuts at the board origin;
    # injecting new lines at (0,0) shifts the kicad-tools bounds by -board_origin
    # and causes CMA-ES to place footprints outside the visible board area.
    _needs_outline = '"Edge.Cuts"' not in pcb_text
    if _needs_outline:
        pcb_text = _inject_board_outline(pcb_text, board_width_mm, board_height_mm)

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.kicad_pcb"
        dst = Path(tmp) / "output.kicad_pcb"
        src.write_text(pcb_text, encoding="utf-8")

        # Primaire : kct optimize-placement --strategy cmaes
        # Placement determines component positions, then we fit the board outline.
        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "kicad_tools.cli", "optimize-placement",
                    str(src), "--output", str(dst),
                    "--strategy", "cmaes",
                ],
                capture_output=True, text=True, timeout=130, check=False,
            )
            placed_src = dst if dst.exists() else None
            if placed_src:
                # Fit board outline to actual placed component positions
                output_bytes = _fit_board_outline_to_components(placed_src.read_bytes())
                import re as _re
                fp_count = len(_re.findall(r'\(footprint\s+"', output_bytes.decode("utf-8", errors="replace")))
                logger.info("kct optimize-placement + board fit: %d footprints", fp_count)
                return {
                    "kicad_pcb_b64": base64.b64encode(output_bytes).decode(),
                    "placed_count": fp_count,
                    "positions": [],
                }
            logger.warning("kct optimize-placement: no output (rc=%d) %s",
                           result.returncode, result.stderr[:200])
        except Exception as exc:
            logger.warning("kct optimize-placement failed (%s) — fallback", exc)

        # Fallback 1 : place_unplaced cluster (pour composants hors-board)
        try:
            from kicad_tools.placement.place_unplaced import place_unplaced
            pu_result = place_unplaced(
                str(src), output_path=str(dst),
                margin=3.0, spacing=3.0, cluster=True,
            )
            output_bytes = dst.read_bytes() if dst.exists() else src.read_bytes()
            logger.info("place_unplaced fallback: %d composants placés", len(pu_result.placed_refs))
            return {
                "kicad_pcb_b64": base64.b64encode(output_bytes).decode(),
                "placed_count": len(pu_result.placed_refs),
                "positions": [{"ref": r} for r in pu_result.placed_refs],
            }
        except Exception as exc:
            logger.warning("place_unplaced échoué (%s) — fallback pcbnew grille", exc)

        # Fallback 2 : pcbnew grille simple
        placed = _pcbnew_grid_place(str(src), str(dst), board_width_mm, board_height_mm)
        output_bytes = dst.read_bytes() if dst.exists() else src.read_bytes()
        logger.info("pcbnew grille fallback: %d composants placés", len(placed))
        return {
            "kicad_pcb_b64": base64.b64encode(output_bytes).decode(),
            "placed_count": len(placed),
            "positions": [{"ref": r} for r in placed],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pcbnew_grid_place(
    src: str, dst: str, board_width_mm: float, board_height_mm: float
) -> list[str]:
    """Grille déterministe via pcbnew. Retourne [] si pcbnew indisponible."""
    try:
        import pcbnew  # type: ignore
    except ImportError:
        logger.warning("pcbnew indisponible — copie brute")
        shutil.copy2(src, dst)
        return []

    try:
        board = pcbnew.LoadBoard(src)
    except Exception as exc:
        logger.warning("pcbnew LoadBoard échoué (%s) — copie brute", exc)
        shutil.copy2(src, dst)
        return []

    footprints = list(board.GetFootprints())
    if not footprints:
        pcbnew.SaveBoard(dst, board)
        return []

    margin = 5.0
    cols = max(1, int((board_width_mm - 2 * margin) / 15))
    step_x = (board_width_mm - 2 * margin) / max(1, cols)
    step_y = 15.0
    placed: list[str] = []

    for i, fp in enumerate(footprints):
        x = margin + (i % cols) * step_x + step_x / 2
        y = margin + (i // cols) * step_y
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        placed.append(fp.GetReference())

    pcbnew.SaveBoard(dst, board)
    return placed


def _fit_board_outline_to_components(pcb_bytes: bytes, margin_mm: float = 10.0) -> bytes:
    """Create board outline (Edge.Cuts) from actual placed footprint positions.

    Reads all footprint (at x y) positions from the PCB, computes bounding box,
    adds margin, and replaces Edge.Cuts with a fitted rectangle.
    Called after kct optimize-placement to define final board dimensions.
    """
    import re as _re, uuid as _uuid, tempfile as _tmp
    text = pcb_bytes.decode("utf-8", errors="replace")

    # Extract footprint (at x y) positions — matches standalone "(at X Y)" lines
    xs, ys = [], []
    for m in _re.finditer(r'^\s+\(at\s+([\d.\-]+)\s+([\d.\-]+)\)$', text, _re.MULTILINE):
        xs.append(float(m.group(1)))
        ys.append(float(m.group(2)))

    if not xs:
        logger.warning("_fit_board_outline: no footprint positions found")
        return pcb_bytes

    x0 = round(min(xs) - margin_mm, 2)
    y0 = round(min(ys) - margin_mm, 2)
    x1 = round(max(xs) + margin_mm, 2)
    y1 = round(max(ys) + margin_mm, 2)

    # Remove old Edge.Cuts
    text = _re.sub(
        r'\(gr_(?:rect|line)[^\n]*"Edge\.Cuts"[^\n]*\n?',
        "", text,
    )
    text = _re.sub(
        r'\(gr_rect\s+\(start[^)]+\)\s+\(end[^)]+\)[\s\S]*?"Edge\.Cuts"[\s\S]*?\)\)',
        "", text,
    )

    outline = (
        f'\n  (gr_rect (start {x0} {y0}) (end {x1} {y1})'
        f'\n    (stroke (width 0.05) (type solid)) (layer "Edge.Cuts")'
        f'\n    (uuid "{_uuid.uuid4()}"))\n'
    )
    last = text.rfind(")")
    if last >= 0:
        text = text[:last] + outline + text[last:]

    logger.info(
        "_fit_board_outline: %.1f×%.1fmm  (%d comps)",
        x1 - x0, y1 - y0, len(xs),
    )
    return text.encode("utf-8")


def _fit_board_to_components(pcb_bytes: bytes, margin_mm: float = 10.0) -> bytes:
    """Resize board outline to fit placed components with a margin.

    After kct optimize-placement, component positions may not fill the
    original 500×500mm board. This recalculates Edge.Cuts from the actual
    bounding box of all footprint reference points + margin_mm.
    """
    try:
        from kicad_tools.schema.pcb import PCB as _PCB
        import tempfile as _tmp

        with _tmp.TemporaryDirectory() as t:
            p = Path(t) / "board.kicad_pcb"
            p.write_bytes(pcb_bytes)
            pcb = _PCB.load(str(p))

            fps = list(pcb.footprints)
            if not fps:
                return pcb_bytes

            xs = [fp.position[0] for fp in fps]
            ys = [fp.position[1] for fp in fps]
            x0 = min(xs) - margin_mm
            y0 = min(ys) - margin_mm
            x1 = max(xs) + margin_mm
            y1 = max(ys) + margin_mm

            board_w = round(x1 - x0, 2)
            board_h = round(y1 - y0, 2)

            # Shift all footprints so board starts at (board_origin)
            # Then replace Edge.Cuts with the fitted outline
            text = pcb_bytes.decode("utf-8", errors="replace")
            text = _replace_edge_cuts(text, x0, y0, x1, y1)
            logger.info("Board fitted to components: %.1f×%.1fmm", board_w, board_h)
            return text.encode("utf-8")
    except Exception as exc:
        logger.warning("_fit_board_to_components failed (%s) — keeping original", exc)
        return pcb_bytes


def _replace_edge_cuts(pcb_text: str, x0: float, y0: float, x1: float, y1: float) -> str:
    """Replace existing Edge.Cuts with a rectangle from (x0,y0) to (x1,y1)."""
    import re as _re
    # Remove old Edge.Cuts lines/rects
    pcb_text = _re.sub(
        r'\(gr_(?:line|rect)[^\)]*"Edge\.Cuts"[^\)]*\)',
        "", pcb_text, flags=_re.DOTALL,
    )
    outline = (
        f'\n  (gr_rect (start {x0} {y0}) (end {x1} {y1})'
        f'\n    (stroke (width 0.05) (type solid)) (layer "Edge.Cuts")'
        f'\n    (uuid "{__import__("uuid").uuid4()}"))\n'
    )
    last = pcb_text.rfind(")")
    if last < 0:
        return pcb_text + outline
    return pcb_text[:last] + outline + pcb_text[last:]


def _inject_board_outline(pcb_text: str, width_mm: float, height_mm: float) -> str:
    """Remplace les gr_line Edge.Cuts existantes par un rectangle propre."""
    pcb_text = re.sub(
        r'\(gr_line[^)]*\([^)]*\)[^)]*"Edge\.Cuts"[^)]*\)',
        "",
        pcb_text,
        flags=re.DOTALL,
    )
    w, h = width_mm, height_mm
    outline = (
        f'\n  (gr_line (start 0 0) (end {w} 0) (layer "Edge.Cuts") (width 0.05))'
        f'\n  (gr_line (start {w} 0) (end {w} {h}) (layer "Edge.Cuts") (width 0.05))'
        f'\n  (gr_line (start {w} {h}) (end 0 {h}) (layer "Edge.Cuts") (width 0.05))'
        f'\n  (gr_line (start 0 {h}) (end 0 0) (layer "Edge.Cuts") (width 0.05))\n'
    )
    last = pcb_text.rfind(")")
    if last == -1:
        return pcb_text + outline
    return pcb_text[:last] + outline + pcb_text[last:]
