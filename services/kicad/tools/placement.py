"""
Cirqix — Placement (tools/placement.py)

100% commandes natives kicad-tools (aucun algo custom — règle CLAUDE.md) :
  1. place_components()  — positions explicites fournies par l'agent (pcbnew)
  2. auto_place()        — pipeline natif 3 étapes (kct placement / kct
                           optimize-placement) :
       ① Architecte  `kct placement optimize --strategy hybrid --cluster`
          OptimizationWorkflow : phase évolutionnaire (groupement fonctionnel
          via detect_functional_clusters) + raffinement physique
          force-directed. Connecteurs (J*/P*) ancrés, clampés Edge.Cuts.
       ② Géomètre    `kct optimize-placement --strategy cmaes --seed-method
          current --max-iterations 30` (_refine_with_cmaes) — CMA-ES (CMAwM)
          seedé sur la position issue de ①, micro-raffine (voir benchmark
          chiffré sur _CMAES_MAX_ITERATIONS). Connecteurs préservés (le CLI
          natif n'a pas de notion de verrouillage — restauré après coup).
       ③ Inspecteur  `kct placement fix` (_resolve_remaining_conflicts) —
          PlacementFixer.iterative_fix, élimine les conflits ERROR restants
          (court-circuits réels) en réparation locale (~0.05-0.1s).
"""

from __future__ import annotations

import base64
import logging
import tempfile
import time
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
# Helpers — connecteurs ancrés (fixed_refs)
# ---------------------------------------------------------------------------

def _connector_refs(pcb) -> list[str]:
    """Références des connecteurs (J*, P*) — ancrés (contrainte mécanique :
    un connecteur a une position imposée par le boîtier / l'utilisateur)."""
    return [fp.reference for fp in pcb.footprints
            if fp.reference and fp.reference[0] in ("J", "P")]


def _resolve_remaining_conflicts(pcb_path: Path, anchored: list[str]) -> tuple[int, int]:
    """Réparation native — équivalent ``kct placement fix`` (PlacementFixer.iterative_fix).

    ``OptimizationWorkflow`` (hybrid+cluster) est stochastique (pas de seed
    fixe) : un benchmark de 5 runs sur le board STM32 a donné 8/0/3/0/5
    conflits selon le tirage. Plutôt que relancer le GA (~98s/run — un
    best-of-N serait inutilisable en synchrone), on chaîne une passe de
    réparation locale qui ne déplace que les composants en conflit
    (≤0.1s, pas de ré-optimisation globale) : élimine les conflits ERROR
    (pad clearance / hole ≤0 — risque de court-circuit réel) ET les WARNING
    résorbables (courtyard_overlap, pad_clearance/hole/edge en WARNING), via
    la logique native du fixer (_calc_courtyard_fix, etc.). Conformément à la
    règle CLAUDE.md « commande native avant algo custom ». Avant ce fix, seuls
    les ERROR déclenchaient le fixer → un board « 0 ERROR / N courtyard_overlap »
    (cas R1-R2 du STM32) sortait non-réparé.

    Retourne ``(erreurs_avant, erreurs_après)`` — comptes ERROR uniquement,
    conservés pour la décision de revert CMA-ES (keyée sur les ERROR, pas les
    WARNING : un courtyard résiduel n'est pas un court-circuit, le fixer le
    nettoie sans risque).
    """
    from kicad_tools.placement.analyzer import DesignRules, PlacementAnalyzer
    from kicad_tools.placement.conflict import ConflictSeverity
    from kicad_tools.placement.fixer import FixStrategy, PlacementFixer

    rules = DesignRules()
    before = PlacementAnalyzer().find_conflicts(str(pcb_path), rules)
    n_errors_before = sum(1 for c in before if c.severity == ConflictSeverity.ERROR)
    # Le fixer natif résout aussi les WARNING (courtyard_overlap via
    # _calc_courtyard_fix) : on le déclenche dès qu'il y a un conflit
    # résorbable (ERROR ou WARNING), pas seulement sur ERROR.
    n_fixable_before = sum(
        1 for c in before
        if c.severity in (ConflictSeverity.ERROR, ConflictSeverity.WARNING)
    )

    if n_fixable_before == 0:
        return 0, 0

    fixer = PlacementFixer(strategy=FixStrategy.SPREAD, anchored=set(anchored))
    fixer.iterative_fix(str(pcb_path), rules=rules, output_path=str(pcb_path), max_passes=10)

    after = PlacementAnalyzer().find_conflicts(str(pcb_path), rules)
    n_errors_after = sum(1 for c in after if c.severity == ConflictSeverity.ERROR)
    n_warnings_after = sum(1 for c in after if c.severity == ConflictSeverity.WARNING)
    if n_errors_after or n_warnings_after:
        # Observabilité : le fixer natif n'a pas tout résorbé (ex: courtyard
        # entre 2 composants anchored qu'il ne peut pas déplacer). Le retour
        # reste keyé ERROR (le revert CMA-ES ne se déclenche pas sur un WARNING
        # résiduel — ce n'est pas un court-circuit), mais on laisse une trace.
        logger.info(
            "_resolve_remaining_conflicts: %d ERROR / %d WARNING résiduels "
            "(avant fix: %d ERROR / %d résorbables)",
            n_errors_after, n_warnings_after, n_errors_before, n_fixable_before,
        )
    return n_errors_before, n_errors_after


def _max_displacement_mm(
    before_positions: dict[str, tuple[float, float]], pcb_path: Path, exclude: list[str]
) -> float:
    """Déplacement max (mm) entre ``before_positions`` et l'état actuel de
    ``pcb_path``, hors références ``exclude`` (connecteurs ancrés). Utilisé
    par le filet de sécurité Option B (_CMAES_MAX_DISPLACEMENT_MM).

    Une référence présente après coup mais absente de ``before_positions``
    (renommage/ajout inattendu côté CLI natif) est traitée comme un
    déplacement infini plutôt qu'ignorée — un filet de sécurité ne doit
    jamais exclure silencieusement un footprint qu'il ne peut pas comparer.
    """
    from kicad_tools.schema.pcb import PCB

    after = {fp.reference: fp.position for fp in PCB.load(str(pcb_path)).footprints}
    excluded = set(exclude)
    tracked = {ref: pos for ref, pos in after.items() if ref not in excluded}

    unmatched = [ref for ref in tracked if ref not in before_positions]
    if unmatched:
        logger.warning(
            "_max_displacement_mm: référence(s) %s absente(s) du snapshot pré-CMA-ES "
            "— déplacement non vérifiable, traité comme dépassement du seuil",
            unmatched,
        )
        return float("inf")

    displacements = [
        ((before_positions[ref][0] - pos[0]) ** 2 + (before_positions[ref][1] - pos[1]) ** 2) ** 0.5
        for ref, pos in tracked.items()
    ]
    return max(displacements) if displacements else 0.0


def _refine_with_cmaes(pcb_path: Path, anchored: list[str], time_budget_s: float = 20.0) -> dict:
    """Micro-raffinement natif — équivalent ``kct optimize-placement --strategy
    cmaes --seed-method current`` (CMAwM, patch Cirqix ``seed="current"`` :
    encode la position issue de l'hybrid+cluster comme moyenne initiale, donc
    le CMA-ES RAFFINE — décale/tourne les composants de quelques dixièmes de
    millimètre pour aligner les broches et résorber les chevauchements —
    plutôt que de relancer un placement depuis zéro.

    ``max_iterations`` est plafonné à ``_CMAES_MAX_ITERATIONS`` — voir sa
    docstring pour le détail chiffré du benchmark qui justifie ce plafond.

    Le CLI natif n'a pas de notion de position verrouillée (seul
    ``time_budget``/``max_iterations`` borne le calcul) : il traite tous les
    footprints, y compris les connecteurs, comme mobiles. On laisse le CMA-ES
    voir le board complet (les connecteurs comptent comme obstacles dans
    l'évaluation overlap/wirelength) puis on restaure la position pré-CMA-ES
    des refs ``anchored`` avant d'écraser le fichier — l'ancrage mécanique des
    connecteurs (J*/P*) reste garanti.

    Retourne ``{"refined": bool, "elapsed_s": float}``.
    """
    from kicad_tools.cli.optimize_placement_cmd import run_optimize_placement
    from kicad_tools.schema.pcb import PCB

    before = {fp.reference: (fp.position, fp.rotation) for fp in PCB.load(str(pcb_path)).footprints}

    cmaes_out = pcb_path.with_name(pcb_path.stem + "_cmaes" + pcb_path.suffix)
    start = time.monotonic()
    exit_code = run_optimize_placement(
        str(pcb_path),
        strategy_name="cmaes",
        seed_method="current",
        output_path=str(cmaes_out),
        max_iterations=_CMAES_MAX_ITERATIONS,
        time_budget=time_budget_s,
        quiet=True,
        allow_infeasible=True,
    )
    elapsed = time.monotonic() - start

    if exit_code not in (0, 2) or not cmaes_out.exists():
        logger.warning(
            "auto_place: CMA-ES refine natif a échoué (exit=%d, %.1fs) — board hybrid+cluster conservé",
            exit_code, elapsed,
        )
        return {"refined": False, "elapsed_s": elapsed}

    refined_pcb = PCB.load(str(cmaes_out))
    for fp in refined_pcb.footprints:
        if fp.reference in before and fp.reference in anchored:
            fp.position, fp.rotation = before[fp.reference]
    refined_pcb.save(str(pcb_path))

    logger.info(
        "auto_place: CMA-ES refine natif (seed=current) — %.1fs, %d réf(s) ancrée(s) préservée(s)",
        elapsed, len(anchored),
    )
    return {"refined": True, "elapsed_s": elapsed}


def _clamp_fixed_refs_to_outline(pcb, fixed_refs: list[str], margin_mm: float = 2.0) -> list[str]:
    """Ramène les footprints ``fixed_refs`` à l'intérieur du contour Edge.Cuts.

    ``OptimizationWorkflow`` traite ``fixed_refs`` comme des ancrages immobiles :
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


# ---------------------------------------------------------------------------
# Mode 2 : auto-placement — commande native kct placement optimize --cluster
# ---------------------------------------------------------------------------

# Paramètres de la commande native `kct placement optimize --strategy hybrid`
_WF_ITERATIONS: int = 1000   # raffinement physique force-directed
_WF_GENERATIONS: int = 100   # phase évolutionnaire (groupement)
_WF_POPULATION: int = 50

# Budget temps du micro-raffinement CMA-ES (Géomètre) — borné pour rester
# compatible avec l'appel synchrone POST /place/auto (le GA hybrid+cluster
# prend déjà ~100s sur le board STM32 réel).
_CMAES_TIME_BUDGET_S: float = 20.0

# Plafond d'itérations du Géomètre — SEULE source de vérité pour ces chiffres
# (ne pas dupliquer ailleurs, juste y faire référence). Le défaut de la lib
# (1000) laisse le CMA-ES dériver loin du seed "current" malgré une moyenne
# initiale correcte : avec seed_method="current", la moyenne initiale EST la
# position Architecte (vérifié dans kicad_tools/placement/cmaes_strategy.py),
# mais le budget de 20s laisse largement le temps à 1000 itérations de
# s'éloigner de ce point de départ. Benchmark réel (board STM32, 17
# composants, 2026-06-19, repartant du même run GA Architecte) :
#   max_iterations=1000 -> déplacement moyen 7.5mm, max 15mm (jusqu'à 68mm
#     sur un autre run, comparaison run-à-run)
#   max_iterations=30   -> déplacement moyen 2.1-3.1mm, max 4.0-11.8mm,
#     stable sur 5 essais déterministes (board fixture test : ~9mm à 1000
#     itérations contre ~5mm à 30)
# Garde le Géomètre fidèle à sa description : un micro-raffinement, pas un
# quasi-re-placement. Plafonné à 30 indépendamment de _CMAES_TIME_BUDGET_S
# (20s) : sur un board plus gros/lent, le budget temps peut interrompre avant
# 30 itérations (encore moins de raffinement, pas un problème) ; sur un board
# petit/rapide, 30 itérations se terminent bien avant 20s (budget inutilisé,
# comportement voulu — le plafond d'itérations est le frein actif, pas le
# temps). Si ce plafond est augmenté, re-mesurer le déplacement avant de
# merger (voir test_refine_with_cmaes_keeps_displacement_small).
_CMAES_MAX_ITERATIONS: int = 30

# Filet de sécurité défense-en-profondeur (Option B) — REVERT si le Géomètre
# déplace un composant non-ancré de plus de ce seuil, MÊME si l'Inspecteur
# ramène 0 ERROR. Complète le revert existant basé sur le compte d'ERROR
# (n_err_after > 0) : ce dernier ne détecte que les chevauchements/court-
# circuits, pas une dérive silencieuse "0 ERROR mais board dégradé" — le bug
# trouvé le 2026-06-19 (max_iterations non plafonné) produisait exactement ce
# symptôme (0 ERROR/0 WARNING, mais des déplacements de 15-68mm). Avec le
# plafond _CMAES_MAX_ITERATIONS=30 ce filet ne devrait jamais se déclencher en
# fonctionnement normal (benchmark : max 4.0-11.8mm) — il protège contre une
# régression future de ce plafond ou un comportement inattendu de la lib.
_CMAES_MAX_DISPLACEMENT_MM: float = 20.0


def auto_place(kicad_pcb_b64: str, board_width_mm: float, board_height_mm: float) -> dict:
    """Auto-placement via la commande native kicad-tools (agent placement ⑤).

    Équivalent de ``kct placement optimize --strategy hybrid --cluster
    --fixed <connecteurs>`` : ``OptimizationWorkflow`` enchaîne une phase
    évolutionnaire (qui respecte les clusters fonctionnels détectés par
    ``detect_functional_clusters`` — bypass caps près des ICs, quartz + load
    caps groupés) puis un raffinement physique force-directed. Les connecteurs
    (J*/P*) sont ancrés (``fixed_refs``) et clampés dans le contour Edge.Cuts.

    Aucun algo custom : 100% natif, conforme à la règle kicad-tools de CLAUDE.md.
    """
    pcb_bytes = base64.b64decode(kicad_pcb_b64)

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.kicad_pcb"
        out = Path(tmp) / "placed.kicad_pcb"
        src.write_bytes(pcb_bytes)

        from kicad_tools.schema.pcb import PCB
        from kicad_tools.optim import OptimizationWorkflow, WorkflowConfig

        pcb = PCB.load(str(src))

        # Filet : footprints hors-carte (vieux PCB pré-placé à -1000) → place_unplaced
        if any(fp.position[0] < -100 or fp.position[1] < -100 for fp in pcb.footprints):
            from kicad_tools.placement.place_unplaced import place_unplaced
            place_unplaced(str(src), output_path=str(src), margin=2.0, spacing=2.0, cluster=True)
            pcb = PCB.load(str(src))
            logger.info("footprints hors-carte → place_unplaced appliqué")

        # Connecteurs ancrés + clampés dans le contour AVANT l'optimisation
        conn = _connector_refs(pcb)
        _clamp_fixed_refs_to_outline(pcb, conn)

        # ── Commande native : kct placement optimize --strategy hybrid --cluster ──
        cfg = WorkflowConfig(
            strategy="hybrid",
            enable_clustering=True,
            fixed_refs=conn,
            iterations=_WF_ITERATIONS,
            generations=_WF_GENERATIONS,
            population=_WF_POPULATION,
        )
        workflow = OptimizationWorkflow(pcb=pcb, config=cfg)
        result = workflow.run()
        # run() calcule l'optimisation mais N'ÉCRIT PAS les positions dans le PCB.
        # write_to_pcb() applique les positions optimisées dans `pcb` — sans cet
        # appel, pcb.save() sauve le board NON MODIFIÉ (placement = no-op).
        updated = workflow.write_to_pcb()
        logger.info(
            "auto_place natif (hybrid+cluster): %d composants écrits, wirelength=%.1fmm, %d connecteurs ancrés",
            updated,
            getattr(result, "wire_length_mm", 0.0) or getattr(result, "wire_length", 0.0),
            len(conn),
        )

        pcb.save(str(out))

        # Architecte garanti 0 erreur AVANT le micro-raffinement — snapshot de
        # secours : le CLI CMA-ES n'a pas de verrouillage de position et peut
        # introduire plus de chevauchements que l'Inspecteur ne peut en réparer
        # (benchmark board STM32 réel, 2026-06-18 : 17 conflits → 3 ERROR
        # restants après 10 passes). Mieux vaut garder un board moins "tassé"
        # mais garanti propre que livrer un court-circuit potentiel.
        _resolve_remaining_conflicts(out, conn)
        pre_cmaes_bytes = out.read_bytes()
        pre_cmaes_positions = {fp.reference: fp.position for fp in PCB.load(str(out)).footprints}

        # ── Géomètre : kct optimize-placement --strategy cmaes --seed-method current ──
        # Raffine la position issue du GA (décalages sub-mm, rotations fines,
        # alignement broches) — connecteurs préservés (voir _refine_with_cmaes).
        # Le CLI natif peut lever (pas seulement renvoyer un code d'échec) : une
        # exception ici ne doit jamais faire échouer toute la requête tant que le
        # board pré-CMA-ES (déjà garanti 0 erreur) est disponible en snapshot.
        try:
            refine = _refine_with_cmaes(out, conn, time_budget_s=_CMAES_TIME_BUDGET_S)
        except Exception:
            logger.exception("auto_place: CMA-ES refine natif a levé une exception — board pré-CMA-ES conservé")
            refine = {"refined": False, "elapsed_s": 0.0}

        if refine["refined"]:
            n_err_before, n_err_after = _resolve_remaining_conflicts(out, conn)
            if n_err_after > 0:
                logger.warning(
                    "auto_place: CMA-ES a introduit %d conflit(s) ERROR non résorbé(s) "
                    "par l'Inspecteur (%d avant fix) — board pré-CMA-ES restauré",
                    n_err_after, n_err_before,
                )
                out.write_bytes(pre_cmaes_bytes)
            else:
                # Filet de sécurité Option B (défense en profondeur, voir
                # _CMAES_MAX_DISPLACEMENT_MM) : 0 ERROR ne garantit pas une
                # bonne qualité de placement — une dérive silencieuse du
                # Géomètre (ex. max_iterations non plafonné, bug 2026-06-19)
                # passerait ce contrôle ERROR alors que le board livré est
                # dégradé. On vérifie donc aussi le déplacement max.
                max_disp = _max_displacement_mm(pre_cmaes_positions, out, exclude=conn)
                if max_disp > _CMAES_MAX_DISPLACEMENT_MM:
                    logger.warning(
                        "auto_place: déplacement CMA-ES %.1fmm > seuil %.1fmm "
                        "(0 ERROR mais dérive excessive) — board pré-CMA-ES restauré",
                        max_disp, _CMAES_MAX_DISPLACEMENT_MM,
                    )
                    out.write_bytes(pre_cmaes_bytes)
                elif n_err_before:
                    logger.info(
                        "auto_place: kct placement fix natif (post-CMA-ES) — %d erreur(s) -> %d après réparation",
                        n_err_before, n_err_after,
                    )

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
