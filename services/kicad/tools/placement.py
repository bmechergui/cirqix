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

def _optimize_with_priors(pcb_path: str, output_path: str,
                           max_iterations: int = 300, time_budget: float = 90.0) -> bool:
    """CMA-ES avec priors physiques complets :
      · schematic_proximity_prior  → seed CMA-ES basé sur connectivité schéma
      · detect_power_domains       → identifie groupes VCC/GND (log)
      · detect_signal_flow         → ordre topologique connectors→MCU→sensors (log)

    Workflow :
      1. Lire PCB → components, nets, board
      2. Calculer schematic_proximity_prior → PlacementVector initial
      3. Écrire ce seed dans le PCB (positions initiales physiquement correctes)
      4. CMA-ES raffine depuis ce seed (bypass caps déjà près MCU, flux signal déjà correct)
    """
    try:
        from kicad_tools.cli.optimize_placement_cmd import (
            _read_board_data, _write_placements_to_pcb, run_optimize_placement,
        )
        from kicad_tools.placement.priors import (
            schematic_proximity_prior, detect_power_domains, detect_signal_flow,
        )
        import tempfile as _tmp2

        # 1. Lire les données du PCB
        components, nets, board_outline, rules, origin = _read_board_data(str(pcb_path))
        if not components:
            return False

        # 2. Règles physiques — log + calcul du seed
        try:
            power_groups = detect_power_domains(components, nets)
            logger.info("power_domains: %d domaines (VCC/GND groups)", len(power_groups))
        except Exception as exc:
            logger.warning("detect_power_domains: %s", exc)

        try:
            signal_flow = detect_signal_flow(components, nets)
            ordered = getattr(signal_flow, 'ordered_refs', getattr(signal_flow, 'ordered', []))
            logger.info("signal_flow: %d composants dans l'ordre topologique", len(ordered))
        except Exception as exc:
            logger.warning("detect_signal_flow: %s", exc)

        # 3. schematic_proximity_prior → seed CMA-ES physiquement correct
        # Composants fortement connectés (bypass caps ↔ MCU) déjà proches dans le seed
        prior_vector = schematic_proximity_prior(components, nets, board_outline)
        logger.info("schematic_proximity_prior: seed calculé (%d composants)", len(components))

        # 4. Écrire le seed dans le PCB temporaire → starting point pour CMA-ES
        seeded_pcb = Path(_tmp2.mktemp(suffix='.kicad_pcb'))
        _write_placements_to_pcb(str(pcb_path), str(seeded_pcb),
                                  prior_vector, components, origin)
        logger.info("seed écrit dans PCB: %s", seeded_pcb.name)

        # 5. CMA-ES raffine depuis le seed physique
        # wirelength×2 = boost des contraintes réseau, area×0.5 = minimize board
        success = run_optimize_placement(
            pcb_path=str(seeded_pcb),
            strategy_name="cmaes",
            max_iterations=max_iterations,
            output_path=str(output_path),
            seed_method="force-directed",  # repart du seed écrit dans PCB
            weights_json='{"wirelength": 2.0, "overlap": 1e6, "area": 0.5}',
            time_budget=time_budget,
            quiet=True,
        )
        logger.info("CMA-ES avec priors: résultat=%s", success)
        return success == 0 or success is True or success is None

    except Exception as exc:
        logger.warning("_optimize_with_priors échoué (%s)", exc)
        return False


def _try_optimize_placement(pcb_bytes: bytes) -> bytes | None:
    """Run `kct optimize-placement --strategy cmaes`.

    Returns the optimized PCB bytes only when the optimizer reports a FEASIBLE
    final result (no overlap/DRC). Returns None when infeasible or on error, so
    the caller falls back to place_unplaced — this is the case for large shield
    footprints (Arduino/STM32) where optimize-placement's pad-bbox overlap model
    leaves components stacked.
    """
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.kicad_pcb"
        dst = Path(tmp) / "out.kicad_pcb"
        src.write_bytes(pcb_bytes)
        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "kicad_tools.cli", "optimize-placement",
                    str(src), "--output", str(dst),
                    "--strategy", "cmaes",
                    "--seed", "force-directed",
                ],
                capture_output=True, text=True, timeout=130, check=False,
            )
        except Exception as exc:
            logger.warning("optimize-placement subprocess failed: %s", exc)
            return None

        # Keep result only if the FINAL line is feasible (not INFEASIBLE)
        final_line = ""
        for ln in result.stdout.splitlines():
            if ln.strip().startswith("Final:"):
                final_line = ln
        feasible = "feasible" in final_line.lower() and "infeasible" not in final_line.lower()
        if dst.exists() and feasible:
            logger.info("optimize-placement: feasible — %s", final_line.strip()[:80])
            return dst.read_bytes()
        logger.info(
            "optimize-placement: infeasible/no-output — fallback place_unplaced (%s)",
            final_line.strip()[:80] or f"rc={result.returncode}",
        )
        return None


def auto_place(
    kicad_pcb_b64: str,
    board_width_mm: float,
    board_height_mm: float,
) -> dict:
    """Pipeline placement call_agent_placement — 3 niveaux.

    Ordre optimal : place_unplaced D'ABORD (bon starting point),
    puis kct optimize-placement TOUJOURS pour raffiner.

    Niveau 1 : kicad-tools
      a. place_unplaced(cluster=True)   ← grille initiale cluster-by-net
         footprints déjà à (-1000,-1000) par _generate_with_kicad_tools
      b. kct optimize-placement         ← raffine TOUJOURS depuis la grille
         si result.area > 50mm² (pas stacked) → utilise le résultat

    Niveau 2 : pcbnew grille simple
      → si kicad-tools indisponible ou exception

    Niveau 3 : TypeScript S-expr
      → retourné comme '' par generate_pcb() → TypeScript runCircuitSynthEngine()
    """
    pcb_bytes = base64.b64decode(kicad_pcb_b64)

    # --- Niveau 1 : place_unplaced → puis kct optimize-placement ---
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.kicad_pcb"
        dst = Path(tmp) / "placed.kicad_pcb"
        opt = Path(tmp) / "optimized.kicad_pcb"

        try:
            from kicad_tools.schema.pcb import PCB
            from kicad_tools.placement.place_unplaced import place_unplaced, _get_board_bounds

            src.write_bytes(pcb_bytes)

            # Étape 1 : place_unplaced — grille cluster-by-net
            result = place_unplaced(
                str(src), output_path=str(dst),
                margin=3.0, spacing=3.0, cluster=True,
            )
            placed_count = len(result.placed_refs)
            logger.info("place_unplaced: %d placés, %d overflow",
                        placed_count, len(result.overflow_refs))

            if not dst.exists() or placed_count == 0:
                raise RuntimeError("place_unplaced n'a rien placé")

            # Étape 2 : CMA-ES avec priors physiques (detect_power_domains +
            # detect_signal_flow + schematic_proximity_prior) pour raffiner
            # le résultat de place_unplaced avec les contraintes physiques réelles.
            try:
                ok = _optimize_with_priors(str(dst), str(opt), max_iterations=200, time_budget=60.0)
                if ok and opt.exists():
                    dst = opt
                    logger.info("optimize_with_priors: placement physique activé")
                else:
                    # Fallback : CLI kct optimize-placement sans priors
                    opt_r = subprocess.run(
                        [sys.executable, "-m", "kicad_tools.cli", "optimize-placement",
                         str(dst), "--output", str(opt), "--strategy", "cmaes"],
                        capture_output=True, text=True, timeout=90, check=False,
                    )
                    final_line = next(
                        (l for l in opt_r.stdout.splitlines() if l.strip().startswith("Final:")), ""
                    )
                    import re as _re
                    area_m = _re.search(r'area=([\d.]+)', final_line)
                    area_val = float(area_m.group(1)) if area_m else 0.0
                    feasible = "feasible" in final_line.lower() and "infeasible" not in final_line.lower()
                    if opt.exists() and feasible and area_val > 50.0:
                        dst = opt
                        logger.info("kct optimize-placement CLI: %s", final_line.strip()[:70])
            except Exception as exc:
                logger.warning("optimize échoué (%s) — garder place_unplaced", exc)

            return {
                "kicad_pcb_b64": base64.b64encode(dst.read_bytes()).decode(),
                "placed_count": placed_count,
                "positions": [{"ref": r} for r in result.placed_refs],
            }
        except Exception as exc:
            logger.warning("place_unplaced échoué (%s) — fallback pcbnew grille", exc)

        # Fallback : pcbnew grille simple
        src.write_bytes(pcb_bytes)
        placed = _pcbnew_grid_place(str(src), str(dst), board_width_mm, board_height_mm)
        output_bytes = dst.read_bytes() if dst.exists() else src.read_bytes()
        logger.info("pcbnew grille fallback: %d composants placés", len(placed))
        return {
            "kicad_pcb_b64": base64.b64encode(output_bytes).decode(),
            "placed_count": len(placed),
            "positions": [{"ref": r} for r in placed],
        }


def _set_edge_cuts_rect(pcb_text: str, x0: float, y0: float, x1: float, y1: float) -> str:
    """Replace all Edge.Cuts shapes with a single rectangle (x0,y0)-(x1,y1)."""
    import uuid as _uuid
    pcb_text = re.sub(r'\(gr_line[^)]*"Edge\.Cuts"[^)]*\)', "", pcb_text, flags=re.DOTALL)
    pcb_text = re.sub(
        r'\(gr_rect\s+\(start[^)]*\)\s+\(end[^)]*\)[\s\S]*?"Edge\.Cuts"[\s\S]*?\)\)',
        "", pcb_text,
    )
    outline = (
        f'\n  (gr_rect (start {x0} {y0}) (end {x1} {y1})'
        f'\n    (stroke (width 0.1) (type solid)) (fill none) (layer "Edge.Cuts")'
        f'\n    (uuid "{_uuid.uuid4()}"))\n'
    )
    last = pcb_text.rfind(")")
    return pcb_text[:last] + outline + pcb_text[last:] if last >= 0 else pcb_text + outline


def _fit_board_outline_to_components(pcb_bytes: bytes, margin_mm: float = 10.0) -> bytes:
    """Create Edge.Cuts rectangle fitted to placed footprint positions + margin."""
    import uuid as _uuid
    text = pcb_bytes.decode("utf-8", errors="replace")

    xs, ys = [], []
    for m in re.finditer(r'^\s+\(at\s+([\d.\-]+)\s+([\d.\-]+)\)\s*$', text, re.MULTILINE):
        xs.append(float(m.group(1)))
        ys.append(float(m.group(2)))
    if not xs:
        return pcb_bytes

    x0 = round(min(xs) - margin_mm, 2)
    y0 = round(min(ys) - margin_mm, 2)
    x1 = round(max(xs) + margin_mm, 2)
    y1 = round(max(ys) + margin_mm, 2)

    # Remove existing Edge.Cuts (gr_line and gr_rect)
    text = re.sub(r'\(gr_line[^)]*"Edge\.Cuts"[^)]*\)', "", text, flags=re.DOTALL)
    text = re.sub(
        r'\(gr_rect\s+\(start[^)]*\)\s+\(end[^)]*\)[\s\S]*?"Edge\.Cuts"[\s\S]*?\)\)',
        "", text,
    )
    outline = (
        f'\n  (gr_rect (start {x0} {y0}) (end {x1} {y1})'
        f'\n    (stroke (width 0.1) (type solid)) (fill none) (layer "Edge.Cuts")'
        f'\n    (uuid "{_uuid.uuid4()}"))\n'
    )
    last = text.rfind(")")
    if last >= 0:
        text = text[:last] + outline + text[last:]
    return text.encode("utf-8")


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
