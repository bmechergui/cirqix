"""
Layrix — Placement
Deux modes :
  1. place_components(pcb_path, components, output_path) — positions explicites fournies par l'agent
  2. auto_place(pcb_b64, board_w, board_h) → dict  — kicad-tools CMA-ES, pur Python, I/O base64
"""

from __future__ import annotations

import base64
import logging
import re
import tempfile
from pathlib import Path

from tools.placement_layout import compute_layout

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers pcbnew (mode 1 — placement explicite)
# ---------------------------------------------------------------------------

def _load_pcbnew():
    try:
        import pcbnew  # type: ignore
        return pcbnew
    except ImportError as exc:
        raise ImportError(
            "pcbnew non disponible — KiCad doit être installé dans l'environnement Python"
        ) from exc


# ---------------------------------------------------------------------------
# Mode 1 : placement explicite (coordonnées fournies)
# ---------------------------------------------------------------------------

def place_components(pcb_path: str, components: list[dict], output_path: str) -> dict:
    pcbnew = _load_pcbnew()
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
# Mode 2 : auto-placement — kicad-tools CMA-ES (pur Python, version-agnostic)
# ---------------------------------------------------------------------------

def auto_place(
    kicad_pcb_b64: str,
    board_width_mm: float,
    board_height_mm: float,
) -> dict:
    """
    Auto-placement via kicad-tools CMA-ES place_unplaced.
    Pur Python — ne dépend PAS de pcbnew, compatible toutes versions KiCad.
    Fallback : placement grille déterministe si kicad-tools échoue.
    I/O base64.
    """
    pcb_bytes = base64.b64decode(kicad_pcb_b64)
    pcb_text = pcb_bytes.decode("utf-8", errors="replace")

    # Réinitialiser les positions des footprints à (0 0) pour que CMA-ES les place
    # (kicad_gen.py pré-place avec une grille basique — CMA-ES fait mieux)
    pcb_text = _reset_footprint_positions(pcb_text)

    # Injecter le contour Edge.Cuts (manipulation texte S-expression)
    pcb_text = _inject_board_outline(pcb_text, board_width_mm, board_height_mm)

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.kicad_pcb"
        dst = Path(tmp) / "output.kicad_pcb"
        src.write_text(pcb_text, encoding="utf-8")

        placed_refs: list[str] = []

        # Étape 1 : kicad-tools place_unplaced (CMA-ES, pur Python)
        try:
            from kicad_tools.placement.place_unplaced import place_unplaced
            result = place_unplaced(
                str(src),
                output_path=str(dst),
                margin=1.0,
                spacing=1.0,
                cluster=True,
            )
            placed_refs = result.placed_refs
            logger.info(
                "kicad-tools CMA-ES: %d placed, %d overflow",
                result.placed_count,
                result.overflow_count,
            )
        except Exception as exc:
            logger.warning("kicad-tools placement failed (%s) — fallback grille", exc)
            placed_refs = _fallback_grid_place(src, dst, board_width_mm, board_height_mm)

        output_bytes = dst.read_bytes() if dst.exists() else src.read_bytes()
        return {
            "kicad_pcb_b64": base64.b64encode(output_bytes).decode(),
            "placed_count": len(placed_refs),
            "positions": [{"ref": r} for r in placed_refs],
        }


def _reset_footprint_positions(pcb_text: str) -> str:
    """
    Moves all footprints to (-10, -10) — outside any board boundary —
    so kicad-tools detects them as "unplaced" and runs CMA-ES on all of them.
    Handles two S-expression variants:
      • multiline: (footprint "Ref"\n   (at X Y [rot]))
      • inline:    (footprint "Ref" ... (at X Y [rot]) ...)
    """
    # Multiline variant: (at ...) is the first token on the next line
    pcb_text = re.sub(
        r'(\(footprint\s+"[^"]*"\s*\n\s*)\(at\s+[\d\.\-]+\s+[\d\.\-]+(?:\s+[\d\.\-]+)?\)',
        r'\1(at -10 -10)',
        pcb_text,
    )
    # Inline variant: (at ...) appears later on the same line after other attributes
    pcb_text = re.sub(
        r'(\(footprint\s+"[^"]*"(?:\s+\([^()]+\))*\s+)\(at\s+[\d\.\-]+\s+[\d\.\-]+(?:\s+[\d\.\-]+)?\)',
        r'\1(at -10 -10)',
        pcb_text,
    )
    return pcb_text


def _inject_board_outline(pcb_text: str, width_mm: float, height_mm: float) -> str:
    """
    Supprime les gr_line sur Edge.Cuts existantes et injecte un rectangle propre.
    Manipulation pure texte S-expression — compatible toutes versions KiCad.
    """
    # Supprimer les gr_line Edge.Cuts existantes
    pcb_text = re.sub(
        r'\(gr_line[^)]*\([^)]*\)[^)]*"Edge\.Cuts"[^)]*\)',
        "",
        pcb_text,
        flags=re.DOTALL,
    )

    w = width_mm
    h = height_mm
    outline = (
        f'\n  (gr_line (start 0 0) (end {w} 0) (layer "Edge.Cuts") (width 0.05))'
        f'\n  (gr_line (start {w} 0) (end {w} {h}) (layer "Edge.Cuts") (width 0.05))'
        f'\n  (gr_line (start {w} {h}) (end 0 {h}) (layer "Edge.Cuts") (width 0.05))'
        f'\n  (gr_line (start 0 {h}) (end 0 0) (layer "Edge.Cuts") (width 0.05))'
        f'\n'
    )

    # Insérer avant la dernière parenthèse fermante du fichier
    last_paren = pcb_text.rfind(")")
    if last_paren == -1:
        return pcb_text + outline
    return pcb_text[:last_paren] + outline + pcb_text[last_paren:]


def _fallback_grid_place(
    src: Path,
    dst: Path,
    board_width_mm: float,
    board_height_mm: float,
) -> list[str]:
    """Fallback grille déterministe via pcbnew. Retourne [] si pcbnew indisponible."""
    try:
        import pcbnew  # type: ignore
    except ImportError:
        logger.warning("pcbnew indisponible — placement ignoré")
        import shutil
        shutil.copy2(src, dst)
        return []

    try:
        board = pcbnew.LoadBoard(str(src))
    except OSError as exc:
        logger.warning("pcbnew ne peut pas lire le fichier (%s) — copie brute", exc)
        import shutil
        shutil.copy2(src, dst)
        return []

    footprints = list(board.GetFootprints())
    refs = [fp.GetReference() for fp in footprints]
    if not refs:
        pcbnew.SaveBoard(str(dst), board)
        return []

    layout = compute_layout(refs, board_width_mm, board_height_mm)
    placed: list[str] = []

    for fp in footprints:
        ref = fp.GetReference()
        if ref not in layout:
            continue
        x_mm, y_mm, rotation = layout[ref]
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x_mm), pcbnew.FromMM(y_mm)))
        if hasattr(fp, "SetOrientationDegrees"):
            fp.SetOrientationDegrees(rotation)
        placed.append(ref)

    pcbnew.SaveBoard(str(dst), board)
    return placed
