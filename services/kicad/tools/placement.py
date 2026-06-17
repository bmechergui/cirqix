"""
Layrix — Placement (tools/placement.py)

Délègue au workflow officiel kicad-tools (aucun algo custom) :
  1. place_components()  — positions explicites fournies par l'agent
  2. auto_place()        — placement auto 3 phases COMPLÉMENTAIRES :
       Phase 1 : PlacementOptimizer (physique locale, clustering, connecteurs ancrés)
       Bridge  : bypass caps repositionnés près du MCU (seed Phase 2)
       Phase 2 : EvolutionaryPlacementOptimizer (GA — résout overlaps + wirelength, sans C++)
       Phase 3 : PlaceRouteOptimizer (routing-aware, C++ requis — bonus si disponible)
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

# Phase 2 — EvolutionaryPlacementOptimizer (GA, sans C++, résout overlaps)
_EVO_GENERATIONS: int = 50
_EVO_POPULATION: int = 30

# Phase 3 routing-aware — nombre max d'itérations placement+routage
# Actif uniquement si le backend C++ est compilé (kct build-native) ;
# sans C++, le routeur Python prend 4+ min/iter → Phase 3 ignorée.
_ROUTING_AWARE_MAX_ITER: int = 5


def _has_cpp_router() -> bool:
    """Vrai si le routeur C++ kicad-tools est compilé (kct build-native)."""
    try:
        from kicad_tools.router import router_cpp  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


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
    snap_offset_mm: float = 3.5,
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

        # Placement en grille sous l'IC owner
        idx = ic_snap_idx.get(owner.reference, 0)
        col = idx % 4
        row = idx // 4
        new_x = ic_x - (col_spacing_mm * 1.5) + col * col_spacing_mm
        new_y = ic_y + snap_offset_mm + row * row_spacing_mm

        logger.info(
            "snap bypass %s → %s: (%.1f,%.1f) Δ=%.1fmm → (%.1f,%.1f)",
            fp.reference, owner.reference,
            fp.position[0], fp.position[1], dist, new_x, new_y,
        )
        fp.position = (new_x, new_y)
        ic_snap_idx[owner.reference] = idx + 1
        changed = True

    return changed


def _add_bypass_cap_clusters(
    opt,
    pcb,
    initial_positions: dict[str, tuple[float, float]],
    conn_refs: list[str],
    *,
    max_distance_mm: float = 4.0,
) -> int:
    """Ajoute les clusters POWER manquants pour les bypass caps non détectés.

    kicad-tools `detect_functional_clusters` ne détecte pas tous les bypass caps
    quand ils sont connectés à un rail partagé (GND/+3.3V) : seul le 1er cap
    détecté par rail est inclus dans le cluster POWER. Les autres reçoivent
    uniquement des springs GND (stiffness=5 × 15 nets ≈ 75), qui dominent le
    cluster_stiffness par défaut (50) et tirent tout vers U1 (LDO hub GND).

    On ajoute explicitement un cluster POWER pour chaque bypass cap manquant,
    en déterminant l'IC owner via la position initiale du générateur (intent).
    L'IC owner est l'IC (≥4 pads, hors connecteur) le plus proche de la position
    initiale du cap, parmi ceux partageant ≥1 net avec le cap.
    """
    from kicad_tools.optim import FunctionalCluster
    from kicad_tools.optim.clustering import ClusterType

    ics = [fp for fp in pcb.footprints
           if fp.pads and len(fp.pads) >= 4 and fp.reference not in conn_refs]
    if not ics:
        return 0

    ic_nets: dict[str, set[str]] = {
        ic.reference: {str(p.net) for p in ic.pads if p.net}
        for ic in ics
    }

    already_clustered: set[str] = {m for c in opt.clusters for m in c.members}

    added = 0
    for fp in pcb.footprints:
        if not _is_bypass_cap(fp) or fp.reference in already_clustered:
            continue
        fp_nets = {str(p.net) for p in fp.pads if p.net}
        connected_ics = [ic for ic in ics if fp_nets & ic_nets.get(ic.reference, set())]
        if not connected_ics:
            continue

        init_pos = initial_positions.get(fp.reference, fp.position)
        owner = min(
            connected_ics,
            key=lambda ic: math.sqrt(
                (initial_positions.get(ic.reference, ic.position)[0] - init_pos[0]) ** 2
                + (initial_positions.get(ic.reference, ic.position)[1] - init_pos[1]) ** 2
            ),
        )

        opt.add_cluster(FunctionalCluster(
            cluster_type=ClusterType.POWER,
            anchor=owner.reference,
            members=[fp.reference],
            max_distance_mm=max_distance_mm,
        ))
        logger.debug("cluster POWER: %s → %s", fp.reference, owner.reference)
        added += 1

    return added


def _snap_timing_cluster_to_mcu(
    pcb,
    timing_refs: set[str],
    *,
    threshold_mm: float = 10.0,
    offset_mm: float = 7.0,
    col_spacing_mm: float = 3.0,
) -> bool:
    """Repositionne cristal + caps de charge près du MCU après Phase 1.

    La TIMING cluster spring ne converge pas toujours si la position initiale
    est déjà trop éloignée (>10mm). On utilise les TIMING cluster members de
    kicad-tools (cristal, load caps) détectés en Phase 1 — PAS un filtre
    générique 2-pads pour éviter d'inclure des résistances de pull-down, etc.
    """
    mcu = _find_mcu_footprint(pcb)
    if not mcu or not timing_refs:
        return False

    mcu_x, mcu_y = mcu.position
    changed = False
    idx = 0

    for fp in pcb.footprints:
        if fp.reference not in timing_refs:
            continue
        dist = math.sqrt((fp.position[0] - mcu_x) ** 2 + (fp.position[1] - mcu_y) ** 2)
        if dist <= threshold_mm:
            continue
        col = idx % 3
        row = idx // 3
        new_x = mcu_x - offset_mm + col * col_spacing_mm
        new_y = mcu_y - offset_mm + row * col_spacing_mm
        logger.info(
            "snap timing %s → MCU: (%.1f,%.1f) Δ=%.1fmm → (%.1f,%.1f)",
            fp.reference, fp.position[0], fp.position[1], dist, new_x, new_y,
        )
        fp.position = (new_x, new_y)
        idx += 1
        changed = True

    return changed


def _connector_refs(pcb) -> list[str]:
    """Références des connecteurs (J*, P*) — ancrés en Phase 1 et protégés
    en Phase 2 routing-aware (fixed_refs → jamais nudgés)."""
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


def auto_place(kicad_pcb_b64: str, board_width_mm: float, board_height_mm: float) -> dict:
    """Placement en 3 phases COMPLÉMENTAIRES (agent placement ⑤).

    Phase 1 — PlacementOptimizer (physique LOCALE) : regroupe les composants
      (``enable_clustering`` → quartz+caps, découplage) et ANCRE les connecteurs
      (``fixed_refs``, clampés dans le contour). Pose la structure.
    Phase 2 — EvolutionaryPlacementOptimizer (GA) : résout les overlaps laissés
      par Phase 1 (force-directed) et affine le wirelength. Disponible sans C++.
    Phase 3 — PlaceRouteOptimizer (routing-aware, C++ requis) : itère
      placement+routage jusqu'à convergence si kct build-native est compilé.

    Re-ancrage : positions connecteurs restaurées après Phase 2/3 (garde-fou).
    """
    pcb_bytes = base64.b64decode(kicad_pcb_b64)

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.kicad_pcb"
        interm = Path(tmp) / "phase1.kicad_pcb"
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
        # cluster_stiffness=150 > GND force totale (5×15=75) → clusters dominent
        from kicad_tools.optim.config import PlacementConfig
        config = PlacementConfig(cluster_stiffness=150.0)
        opt = PlacementOptimizer.from_pcb(pcb, config=config, fixed_refs=conn, enable_clustering=True)
        # Ajouter les clusters POWER manquants (bypass caps non détectés par kicad-tools)
        n_clusters = _add_bypass_cap_clusters(opt, pcb, initial_positions, conn)
        if n_clusters:
            logger.info("Phase 1: %d clusters POWER ajoutés (bypass caps → IC owner)", n_clusters)
        opt.run(iterations=1000)
        opt.snap_rotations_to_90()
        opt.write_to_pcb(pcb)
        pcb.save(str(interm))
        conn_positions = {fp.reference: fp.position
                          for fp in PCB.load(str(interm)).footprints
                          if fp.reference in conn}
        # Extraire les membres TIMING (cristal + load caps) pour le bridge
        from kicad_tools.optim.clustering import ClusterType
        timing_refs: set[str] = {
            m for c in opt.clusters
            if c.cluster_type == ClusterType.TIMING
            for m in c.members
        }
        logger.info("Phase 1 - PlacementOptimizer: clustering + %d connecteurs ancrés, timing=%s",
                    len(conn), timing_refs)

        # ── Bridge Phase 1→2 : repositionnement fonctionnel ─────────────────
        phase1_pcb = PCB.load(str(interm))
        bridge_changed = False
        # Bypass caps dérivés loin du MCU → restaurer à la position initiale
        if _restore_bypass_caps_near_mcu(phase1_pcb, initial_positions):
            bridge_changed = True
            logger.info("Bridge: bypass caps restaurés près du MCU")
        # Cristal + load caps trop loin du MCU → snap explicite (seed TIMING)
        if _snap_timing_cluster_to_mcu(phase1_pcb, timing_refs):
            bridge_changed = True
            logger.info("Bridge: cristal/load caps snappés près du MCU")
        if bridge_changed:
            phase1_pcb.save(str(interm))

        # ── Snap pre-Phase 2 : bypass caps → IC owner (seed routing-aware) ───
        # Donner au PlaceRouteOptimizer une seed propre : les caps de découplage
        # snappés près de leur IC owner minimisent d'emblée les wirelengths,
        # réduisant les itérations avant convergence routage.
        snap_pcb = PCB.load(str(interm))
        if _snap_bypass_caps_to_ics(snap_pcb, initial_positions):
            snap_pcb.save(str(interm))
            logger.info("Snap pre-Phase 2: bypass caps snappés vers IC owner")

        # Snapshot Phase 1 pour le retour (avant que Phase 2 modifie interm)
        phase1_snap_bytes = interm.read_bytes()

        # ── Phase 2 : EvolutionaryPlacementOptimizer (GA — résout overlaps) ──
        # Genetic algorithm natif kicad-tools, disponible sans C++. Résout les
        # overlaps laissés par Phase 1 (force-directed) et affine le wirelength.
        # fixed_refs=conn → connecteurs protégés, enable_clustering → clusters conservés.
        try:
            from kicad_tools.optim import EvolutionaryPlacementOptimizer, EvolutionaryConfig

            evo_pcb = PCB.load(str(interm))
            evo = EvolutionaryPlacementOptimizer.from_pcb(
                evo_pcb,
                config=EvolutionaryConfig(generations=_EVO_GENERATIONS, population_size=_EVO_POPULATION),
                fixed_refs=conn,
                enable_clustering=True,
            )
            evo.optimize(generations=_EVO_GENERATIONS, population_size=_EVO_POPULATION)
            evo.write_to_pcb(evo_pcb)
            evo_pcb.save(str(interm))
            logger.info("Phase 2 - EVO: %d gen × %d pop, overlaps résolus", _EVO_GENERATIONS, _EVO_POPULATION)
        except Exception as exc:
            logger.warning("Phase 2 - EVO échoué (%s) — Phase 1 conservé", exc)

        # ── Phase 3 (bonus) : PlaceRouteOptimizer (routing-aware, C++ requis) ─
        # En Docker, kct build-native est précompilé → 10-100× plus rapide.
        # Sans C++, le routeur Python prend 4+ min/itération → ignoré en local.
        if _has_cpp_router():
            try:
                from kicad_tools.optim.place_route import PlaceRouteOptimizer

                seed_pcb = PCB.load(str(interm))
                pro = PlaceRouteOptimizer.from_pcb(
                    seed_pcb,
                    pcb_path=str(interm),
                    manufacturer="jlcpcb",
                    verbose=False,
                    fixed_refs=conn,
                )
                result = pro.optimize(
                    max_iterations=_ROUTING_AWARE_MAX_ITER,
                    allow_placement_changes=True,
                    skip_drc=False,
                )
                logger.info(
                    "Phase 3 - routing-aware: success=%s, %d iter, %d routes",
                    result.success, result.iterations, len(result.routes or []),
                )
            except Exception as exc:
                logger.warning("Phase 3 - routing-aware échoué (%s) — Phase 2 conservé", exc)
        else:
            logger.info("Phase 3 routing-aware ignorée — routeur C++ non compilé (kct build-native)")

        # ── Re-ancrage : restaurer les positions connecteurs de Phase 1 ──────
        # Garde-fou : EVO/PlaceRouteOptimizer ont fixed_refs=conn, mais on vérifie
        # qu'aucun connecteur n'a dérivé (ex. fixer bug ou nudge marginal).
        final = PCB.load(str(interm))
        restored = 0
        for fp in final.footprints:
            anchor = conn_positions.get(fp.reference)
            if anchor is not None and fp.position != anchor:
                fp.position = anchor
                restored += 1
        if restored:
            logger.info("Re-ancrage : %d connecteur(s) restauré(s) post-Phase 2", restored)

        # ── Snap final : sécurité si Phase 2/3 a déplacé des caps ─────────────
        if _snap_bypass_caps_to_ics(final, initial_positions):
            logger.info("Snap final: bypass caps repositionnés post-Phase 2/3")

        final.save(str(interm))
        footprints = PCB.load(str(interm)).footprints
        return {
            "kicad_pcb_b64": base64.b64encode(interm.read_bytes()).decode(),
            "kicad_pcb_phase1_b64": base64.b64encode(phase1_snap_bytes).decode(),
            "placed_count": len(footprints),
            "positions": [
                {"ref": fp.reference,
                 "x": round(fp.position[0], 2), "y": round(fp.position[1], 2)}
                for fp in footprints
            ],
        }
