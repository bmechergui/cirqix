"""
Layrix — Placement (tools/placement.py)

Délègue au workflow officiel kicad-tools (aucun algo custom) :
  1. place_components()  — positions explicites fournies par l'agent
  2. auto_place()        — placement auto 2 phases COMPLÉMENTAIRES :
       Phase 1 : PlacementOptimizer (physique locale, clustering, connecteurs ancrés)
       Bridge  : bypass caps repositionnés près du MCU (seed CMA-ES)
       Phase 2 : run_optimize_placement --strategy cmaes --seed current
                 CMA-ES (CMAwM) seeded depuis Phase 1 → raffinement global
"""

from __future__ import annotations

import base64
import logging
import math
import tempfile
from pathlib import Path

from kicad_tools.explain.mistakes import is_bypass_cap as _kt_is_bypass_cap

logger = logging.getLogger(__name__)

# Seuil en mm : cap à plus de X mm du MCU après Phase 1 → repositionné pour Phase 2
_BYPASS_CAP_DIST_THRESHOLD_MM: float = 12.0


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
# Mode 2 : auto-placement — 2 phases COMPLÉMENTAIRES
#   Phase 1 : PlacementOptimizer (physique locale, clustering, connecteurs ancrés)
#   Phase 2 : CMA-ES (CMAwM) via run_optimize_placement, seedé depuis Phase 1
# ---------------------------------------------------------------------------

# Phase 2 CMA-ES — nombre max d'itérations (budget mural en secondes)
_CMAES_MAX_ITER: int = 300
_CMAES_TIME_BUDGET: float = 60.0  # secondes max pour Phase 2


def _find_mcu_footprint(pcb) -> object | None:
    """Retourne le footprint avec le plus de pads (>10) — le MCU."""
    if not pcb.footprints:
        return None
    best = max(pcb.footprints, key=lambda fp: len(fp.pads) if fp.pads else 0)
    return best if best.pads and len(best.pads) > 10 else None


def _restore_bypass_caps_near_mcu(
    phase1_pcb,
    initial_positions: dict[str, tuple[float, float]],
    *,
    dist_threshold_mm: float = _BYPASS_CAP_DIST_THRESHOLD_MM,
) -> bool:
    """Repositionne les condensateurs de découplage qui ont dérivé loin du MCU.

    Phase 1 (force-directed) optimise globalement sans notion de groupe fonctionnel :
    les bypass caps MCU peuvent se retrouver à 25+ mm de leur IC, dégradant la seed
    CMA-ES Phase 2. On les restaure à la position initiale (générateur PCB) — proche
    du MCU — pour que Phase 2 raffine depuis un point de départ de qualité.

    Critères : 2 pads + partage ≥1 net avec le MCU + distance > dist_threshold_mm.
    """
    mcu = _find_mcu_footprint(phase1_pcb)
    if mcu is None:
        return False

    mcu_x, mcu_y = mcu.position
    mcu_nets: set[str] = {str(p.net) for p in (mcu.pads or []) if p.net}

    changed = False
    for fp in phase1_pcb.footprints:
        if not fp.pads or len(fp.pads) != 2:
            continue
        fp_nets = {str(p.net) for p in fp.pads if p.net}
        if not (fp_nets & mcu_nets):
            continue  # pas connecté au MCU
        dist = math.sqrt((fp.position[0] - mcu_x) ** 2 + (fp.position[1] - mcu_y) ** 2)
        if dist > dist_threshold_mm and fp.reference in initial_positions:
            new_pos = initial_positions[fp.reference]
            logger.info(
                "bypass %s repositionné vers MCU: (%.1f,%.1f) Δ=%.1fmm → init (%.1f,%.1f)",
                fp.reference, fp.position[0], fp.position[1], dist, new_pos[0], new_pos[1],
            )
            fp.position = new_pos
            changed = True
    return changed


def _is_bypass_cap(fp) -> bool:
    """Vrai si fp est un condensateur de découplage, en déléguant à kicad-tools.

    kicad-tools `is_bypass_cap(reference, value)` identifie par VALEUR (100nF, 10nF,
    1uF...) — plus précis qu'un filtre topologique. Exclut les bulk caps (100uF)
    qui ne doivent pas être snappés près d'un IC.
    Critère minimal : 2 pads (bypass cap SMD passif).
    """
    if not fp.pads or len(fp.pads) != 2:
        return False
    ref = fp.reference or ""
    val = fp.value if hasattr(fp, "value") else ""
    return _kt_is_bypass_cap(ref, val or "")


def _snap_bypass_caps_to_ics(
    pcb,
    initial_positions: dict[str, tuple[float, float]],
    *,
    max_dist_mm: float = 10.0,
    snap_offset_mm: float = 2.0,
    col_spacing_mm: float = 2.5,
    row_spacing_mm: float = 2.5,
    max_initial_dist_mm: float = 20.0,
) -> bool:
    """Snappe les condensateurs de découplage encore loin de leur IC owner après Phase 2.

    Détection via kicad-tools `is_bypass_cap(reference, value)` — identifie par
    VALUE (100nF, 10nF, 1uF...), plus précis qu'un filtre de topologie réseau.
    Exclut les bulk caps (100uF) qui ont des contraintes différentes.

    IC owner = IC (≥3 pads) partageant ≥1 net avec le cap ET le plus proche de la
    position INITIALE du cap (positions Phase 2 des ICs exclues — elles ont bougé).
    Si le cap était déjà loin de tout IC initialement (>max_initial_dist_mm), on ne
    snapp pas (placement délibéré hors-cluster par le générateur).

    Résultat : grille compacte autour de l'IC owner.
    """
    # ICs = tout composant avec ≥3 pads (MCU, LDO, connecteurs)
    ics = [fp for fp in pcb.footprints if fp.pads and len(fp.pads) >= 3]
    if not ics:
        return False

    ic_nets: dict[str, set[str]] = {
        ic.reference: {str(p.net) for p in ic.pads if p.net}
        for ic in ics
    }

    changed = False
    ic_snap_idx: dict[str, int] = {}

    for fp in pcb.footprints:
        # Condensateurs de découplage uniquement (kicad-tools is_bypass_cap)
        if not _is_bypass_cap(fp):
            continue

        fp_nets = {str(p.net) for p in fp.pads if p.net}
        init_pos = initial_positions.get(fp.reference)
        if init_pos is None:
            continue

        # ICs partageant ≥1 net avec ce cap
        connected_ics = [ic for ic in ics if fp_nets & ic_nets.get(ic.reference, set())]
        if not connected_ics:
            continue

        # IC owner = IC le plus proche de la position INITIALE du cap (intent générateur)
        # On utilise initial_positions des ICs pour ne pas être biaisé par Phase 2
        owner = min(
            connected_ics,
            key=lambda ic: math.sqrt(
                (initial_positions.get(ic.reference, ic.position)[0] - init_pos[0]) ** 2
                + (initial_positions.get(ic.reference, ic.position)[1] - init_pos[1]) ** 2
            ),
        )

        # Vérifier que le cap était initialement proche de son owner (intent générateur)
        owner_init = initial_positions.get(owner.reference, owner.position)
        initial_dist_to_owner = math.sqrt(
            (owner_init[0] - init_pos[0]) ** 2 + (owner_init[1] - init_pos[1]) ** 2
        )
        if initial_dist_to_owner > max_initial_dist_mm:
            continue  # cap jamais prévu près de cet IC → ne pas forcer

        ic_x, ic_y = owner.position
        dist = math.sqrt((fp.position[0] - ic_x) ** 2 + (fp.position[1] - ic_y) ** 2)
        if dist <= max_dist_mm:
            continue

        # Offset vertical = demi-étendue pads de l'IC + snap_offset → caps SOUS
        # le corps de l'IC, hors de ses pads (zéro court-circuit, même sur LQFP).
        _ox, oy = _ic_pad_extent(owner)

        # Placement en grille sous l'IC owner
        idx = ic_snap_idx.get(owner.reference, 0)
        col = idx % 4
        row = idx // 4
        new_x = ic_x - (col_spacing_mm * 1.5) + col * col_spacing_mm
        new_y = ic_y + oy + snap_offset_mm + row * row_spacing_mm

        logger.info(
            "snap bypass %s → %s: (%.1f,%.1f) Δ=%.1fmm → (%.1f,%.1f)",
            fp.reference, owner.reference,
            fp.position[0], fp.position[1], dist, new_x, new_y,
        )
        fp.position = (new_x, new_y)
        ic_snap_idx[owner.reference] = idx + 1
        changed = True

    return changed


def _connector_refs(pcb) -> list[str]:
    """Références des connecteurs (J*, P*) — ancrés en Phase 1 (contrainte
    physique/mécanique) puis restaurés après la Phase 2 CMA-ES."""
    return [fp.reference for fp in pcb.footprints
            if fp.reference and fp.reference[0] in ("J", "P")]


def _clamp_fixed_refs_to_outline(pcb, fixed_refs: list[str], margin_mm: float = 2.0) -> list[str]:
    """Ramène les footprints ``fixed_refs`` à l'intérieur du contour Edge.Cuts.

    ``PlacementOptimizer`` traite ``fixed_refs`` comme des ancrages immobiles :
    si call_agent_gen_pcb a posé un connecteur hors-carte, l'optimiseur le laisse
    hors-carte → nets inroutables. On le clampe AVANT l'ancrage.
    """
    from kicad_tools.optim.board_outline import extract_board_outline

    outline = extract_board_outline(pcb)
    if outline is None or not outline.vertices:
        return []

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
            logger.warning("connector %s hors-carte (%.2f,%.2f) -> clampé (%.2f,%.2f)",
                           fp.reference, x, y, cx, cy)
            fp.position = (cx, cy)
            clamped.append(fp.reference)
    return clamped


def _ic_pad_extent(ic) -> tuple[float, float]:
    """Demi-étendue (rx, ry) des pads de l'IC autour de son centre, en mm.

    Sert à calculer un offset de snap qui place les caps HORS du corps de l'IC
    (évite les courts-circuits : caps posés sur les pads du MCU). Générique :
    lit les positions de pads relatives au centre du footprint.
    """
    xs = [abs(p.position[0]) for p in ic.pads if hasattr(p, "position") and p.position]
    ys = [abs(p.position[1]) for p in ic.pads if hasattr(p, "position") and p.position]
    return (max(xs) if xs else 2.0, max(ys) if ys else 2.0)


def _snap_timing_group_to_mcu(
    pcb,
    *,
    clearance_mm: float = 2.0,
    cap_pitch_mm: float = 3.0,
) -> bool:
    """Snappe le quartz (Y*/X*) + ses load caps en colonne à GAUCHE du MCU.

    Déterministe (≠ force-directed mou) : garantit quartz collé au MCU. L'offset
    horizontal = demi-étendue des pads du MCU + clearance + marge → les composants
    timing sont posés hors du corps du MCU (zéro court-circuit). Générique :
    détecte le quartz par convention de ref (Y*/X*) et ses load caps par net partagé.
    """
    mcu = _find_mcu_footprint(pcb)
    if mcu is None:
        return False

    crystal = next((fp for fp in pcb.footprints
                    if (fp.reference or "")[:1] in ("Y", "X") and fp.pads), None)
    if crystal is None:
        return False

    crystal_nets = {str(p.net) for p in crystal.pads if p.net}
    # load caps = caps 2 pads partageant ≥1 net avec le quartz
    load_caps = [fp for fp in pcb.footprints
                 if (fp.reference or "")[:1] == "C" and fp.pads and len(fp.pads) == 2
                 and {str(p.net) for p in fp.pads if p.net} & crystal_nets]

    mcu_x, mcu_y = mcu.position
    rx, _ry = _ic_pad_extent(mcu)
    base_x = mcu_x - rx - clearance_mm - 1.0  # 1mm = demi-largeur cap ~0402

    group = [crystal] + load_caps
    start_y = mcu_y - (len(group) - 1) * cap_pitch_mm / 2.0
    for i, fp in enumerate(group):
        fp.position = (base_x, start_y + i * cap_pitch_mm)
        logger.info("snap timing %s → gauche MCU (%.1f,%.1f)",
                    fp.reference, fp.position[0], fp.position[1])
    return True


def auto_place(kicad_pcb_b64: str, board_width_mm: float, board_height_mm: float) -> dict:
    """Placement en 2 phases COMPLÉMENTAIRES (agent placement ⑤).

    Phase 1 — PlacementOptimizer (physique LOCALE) : regroupe les composants
      (``enable_clustering`` → quartz+caps, découplage) et ANCRE les connecteurs
      (``fixed_refs``, clampés dans le contour). Pose la structure.
    Phase 2 — CMA-ES (CMAwM, ``run_optimize_placement --strategy cmaes``) :
      seeded depuis les positions de Phase 1 (``seed_method="current"``).
      Raffinement global : minimise overlap + wirelength + boundary violation.
      CMAwM gère nativement x/y continus + rotation/side discrets. Complète
      Phase 1 sans repartir de zéro (≠ force-directed seed).

    Re-ancrage : positions connecteurs restaurées à celles de Phase 1 après la
    Phase 2 (garde-fou — CMA-ES pourrait micro-déplacer un connecteur).
    """
    pcb_bytes = base64.b64decode(kicad_pcb_b64)

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.kicad_pcb"
        interm = Path(tmp) / "phase1.kicad_pcb"
        out = Path(tmp) / "out.kicad_pcb"
        src.write_bytes(pcb_bytes)

        from kicad_tools.schema.pcb import PCB
        from kicad_tools.optim import PlacementOptimizer

        pcb = PCB.load(str(src))

        # Filet : footprints hors-carte (vieux PCB pré-placé à -1000) → place_unplaced
        if any(fp.position[0] < -100 or fp.position[1] < -100 for fp in pcb.footprints):
            from kicad_tools.placement.place_unplaced import place_unplaced
            place_unplaced(str(src), output_path=str(src), margin=2.0, spacing=2.0, cluster=True)
            pcb = PCB.load(str(src))
            logger.info("footprints hors-carte → place_unplaced appliqué")

        # Sauvegarder les positions initiales (avant Phase 1) — seed bridge Phase 1→2
        initial_positions: dict[str, tuple[float, float]] = {
            fp.reference: fp.position for fp in pcb.footprints
        }

        # ── Phase 1 : PlacementOptimizer (clustering + connecteurs ancrés) ──
        # enable_clustering=True → detect_functional_clusters (natif) regroupe
        # GÉNÉRIQUEMENT, sur N'IMPORTE QUEL board : quartz+caps de charge (TIMING),
        # caps de découplage près de l'alim (POWER), interface, driver — par
        # motif électronique, pas par références hardcodées.
        conn = _connector_refs(pcb)
        _clamp_fixed_refs_to_outline(pcb, conn)
        opt = PlacementOptimizer.from_pcb(pcb, fixed_refs=conn, enable_clustering=True)
        opt.run(iterations=1000)
        opt.snap_rotations_to_90()
        opt.write_to_pcb(pcb)

        # ── Snap déterministe Phase 1 : groupes fonctionnels collés à leur IC ──
        # Le force-directed ne respecte PAS les contraintes de groupement (springs
        # GND dominent). On place donc DÉTERMINISTIQUEMENT, hors du corps de l'IC :
        #   - quartz + load caps → colonne à gauche du MCU
        #   - bypass caps → grille sous leur IC owner
        # Offsets calculés sur la taille réelle de l'IC → zéro court-circuit.
        if _snap_timing_group_to_mcu(pcb):
            logger.info("Phase 1: quartz + load caps snappés à gauche du MCU")
        if _snap_bypass_caps_to_ics(pcb, initial_positions):
            logger.info("Phase 1: bypass caps snappés en grille près de leur IC")

        pcb.save(str(interm))
        conn_positions = {fp.reference: fp.position
                          for fp in PCB.load(str(interm)).footprints
                          if fp.reference in conn}
        logger.info("Phase 1 - PlacementOptimizer: clustering + snap + %d connecteurs ancrés", len(conn))

        # ── Bridge Phase 1→2 : bypass caps repositionnés près du MCU ─────────
        # Phase 1 (force-directed) peut éloigner les caps de découplage du MCU car
        # il optimise globalement sans notion de groupe fonctionnel. On les restaure
        # à leurs positions initiales (proches du MCU selon le générateur) pour que
        # CMA-ES Phase 2 commence depuis une seed de qualité.
        phase1_pcb = PCB.load(str(interm))
        if _restore_bypass_caps_near_mcu(phase1_pcb, initial_positions):
            phase1_pcb.save(str(interm))
            logger.info("Bridge Phase 1→2: bypass caps repositionnés près du MCU pour seed CMA-ES")

        # ── Phase 2 (COMPLÉMENTAIRE) : CMA-ES seedé depuis Phase 1 ──────────
        # run_optimize_placement avec seed_method="current" : encode les positions
        # de Phase 1 comme moyenne initiale CMA-ES → raffinement global autour
        # de la structure de Phase 1 (quartz groupé, connecteurs clampés).
        # CMAwM gère nativement x/y continus + rotation/side discrets.
        # Connecteurs verrouillés via locked flag ou fixed par Phase 1 clamp.
        try:
            from kicad_tools.cli.optimize_placement_cmd import run_optimize_placement

            rc = run_optimize_placement(
                str(interm),
                strategy_name="cmaes",
                max_iterations=_CMAES_MAX_ITER,
                output_path=str(out),
                seed_method="current",
                quiet=True,
                allow_infeasible=True,
                time_budget=_CMAES_TIME_BUDGET,
            )
            if not out.exists():
                raise RuntimeError(f"CMA-ES n'a produit aucun output (rc={rc})")
            logger.info("Phase 2 - CMA-ES terminé (rc=%d)", rc)
        except Exception as exc:
            logger.warning("Phase 2 - CMA-ES échoué (%s) — placement Phase 1 conservé", exc)
            out.write_bytes(interm.read_bytes())

        # ── Re-ancrage : restaurer les positions connecteurs de Phase 1 ──
        final = PCB.load(str(out))
        restored = 0
        for fp in final.footprints:
            anchor = conn_positions.get(fp.reference)
            if anchor is not None and fp.position != anchor:
                fp.position = anchor
                restored += 1
        if restored:
            logger.info("Re-ancrage : %d connecteur(s) restauré(s) post-CMA-ES", restored)

        # ── Snap final : bypass caps → grille proche de leur IC owner ────────
        # CMA-ES optimise la wirelength globale sur les rails power : les bypass
        # caps peuvent encore dériver malgré le bridge Phase 1→2. Ce snap
        # déterministe les force près de leur IC owner (détecté via position initiale).
        if _snap_bypass_caps_to_ics(final, initial_positions):
            logger.info("Snap final: bypass caps repositionnés près de leur IC owner")

        final.save(str(out))
        footprints = PCB.load(str(out)).footprints
        return {
            "kicad_pcb_b64": base64.b64encode(out.read_bytes()).decode(),
            "kicad_pcb_phase1_b64": base64.b64encode(interm.read_bytes()).decode(),
            "placed_count": len(footprints),
            "positions": [
                {"ref": fp.reference,
                 "x": round(fp.position[0], 2), "y": round(fp.position[1], 2)}
                for fp in footprints
            ],
        }
