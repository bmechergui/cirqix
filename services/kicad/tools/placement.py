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
import json
import logging
import math
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Env partagé des sous-processus kicad-tools : UTF-8 forcé + PYTHONPATH vers
# kicad-tools/src en local/CI seulement (jamais en Docker, où le paquet est
# pip-installé avec le backend C++).
from tools.kct_route import _kct_env

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

    rules = DesignRules(courtyard_margin=_COURTYARD_MARGIN_MM)
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


# PlacementAnalyzer APPROXIME le courtyard par « pads + marge », alors que
# kicad-cli utilise la géométrie réelle F.CrtYd du footprint. Sur un boîtier
# traversant (DIP-8), le corps déborde largement des pads : l'analyseur voyait
# « 0 conflit » là où kicad-cli rapportait un courtyards_overlap ERROR, que
# l'Inspecteur ne corrigeait donc jamais. Mesuré le 2026-07-27 sur
# examples/led-blinker-full-pipeline (NE555 DIP-8 + 0805).
# Marge élargie pour que l'approximation couvre le courtyard réel — valeur
# calibrée par mesure, cf. le README de la fixture.
_COURTYARD_MARGIN_MM: float = 0.5

_CMAES_RUNNER = Path(__file__).resolve().parent / "cmaes_runner.py"


def _run_cmaes_in_subprocess(pcb_path: Path, out_path: Path, time_budget_s: float) -> int:
    """Lance le CMA-ES dans un processus enfant. Retourne son code de sortie.

    ``run_optimize_placement`` installe des handlers de signal, interdits hors
    thread principal — or uvicorn exécute ``auto_place`` dans un thread de
    worker. En appel direct, l'exception tombait AVANT toute optimisation et le
    Géomètre ne tournait jamais en production (mesuré en conteneur le
    2026-07-27). Un processus enfant a un vrai thread principal.

    Voir ``tools/cmaes_runner.py`` pour le détail, notamment pourquoi le CLI
    ``kct optimize-placement`` ne convient pas (pas de ``--seed current``).
    """
    payload = json.dumps({
        "pcb": str(pcb_path),
        "output": str(out_path),
        "max_iterations": _CMAES_MAX_ITERATIONS,
        "time_budget": time_budget_s,
    })
    try:
        proc = subprocess.run(
            [sys.executable, str(_CMAES_RUNNER), payload],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=time_budget_s + 120, check=False, env=_kct_env(),
        )
    except subprocess.TimeoutExpired:
        logger.warning("_refine_with_cmaes: sous-processus CMA-ES expiré")
        return 1
    if proc.returncode not in (0, 2):
        logger.warning(
            "_refine_with_cmaes: sous-processus CMA-ES exit=%d — stderr: %s",
            proc.returncode, (proc.stderr or "").strip()[:300],
        )
    return proc.returncode


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
    from kicad_tools.schema.pcb import PCB

    before = {fp.reference: (fp.position, fp.rotation) for fp in PCB.load(str(pcb_path)).footprints}

    cmaes_out = pcb_path.with_name(pcb_path.stem + "_cmaes" + pcb_path.suffix)
    start = time.monotonic()
    exit_code = _run_cmaes_in_subprocess(pcb_path, cmaes_out, time_budget_s)
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


# Retrait du bord pour reposer un composant sorti du contour, et pas d'une
# recherche de case libre. 2,5 mm ≈ demi-courtyard d'un 0805 + marge : assez
# lâche pour que l'Inspecteur n'ait qu'un réglage fin à faire, assez serré pour
# ne pas gaspiller la surface d'une petite carte.
_OFF_BOARD_MARGIN_MM: float = 2.0
_OFF_BOARD_SPACING_MM: float = 2.5
# Alternances réparation ↔ Inspecteur avant abandon. L'Inspecteur ignore le
# contour et ressort ce qu'on vient de rentrer ; la dernière passe répare donc
# sans le relancer. 3 suffit largement : mesuré, le point fixe tombe en 1 ou 2.
_OFF_BOARD_MAX_PASSES: int = 3


def _outline_bounds(pcb) -> tuple[float, float, float, float] | None:
    """Bornes du contour Edge.Cuts, dans le repère des positions de footprints.

    ``fp.position`` est board-local alors que ``outline.vertices`` est en
    coordonnées page : seule la soustraction de ``pcb.board_origin`` les
    réconcilie. C'est précisément la confusion qui a fait échouer une tentative
    de réparation via ``place_unplaced`` (2026-07-31).
    """
    from kicad_tools.optim.board_outline import extract_board_outline

    outline = extract_board_outline(pcb)
    if outline is None or not outline.vertices:
        return None
    ox, oy = pcb.board_origin
    xs = [v.x - ox for v in outline.vertices]
    ys = [v.y - oy for v in outline.vertices]
    return min(xs), max(xs), min(ys), max(ys)


def _refs_outside(pcb, bornes: tuple[float, float, float, float]) -> list[str]:
    """Références dont le centre tombe hors du contour."""
    min_x, max_x, min_y, max_y = bornes
    return [fp.reference for fp in pcb.footprints
            if not (min_x <= fp.position[0] <= max_x
                    and min_y <= fp.position[1] <= max_y)]


def _repair_off_board(pcb_path: Path, anchored: list[str]) -> list[str]:
    """Ramène dans le contour les seuls footprints signalés ``OFF_BOARD``.

    ``PlacementAnalyzer`` classe un composant hors carte en ``OFF_BOARD`` /
    ERROR, mais ``PlacementFixer`` n'a **aucun** traitement de ce type de
    conflit (zéro occurrence dans ``fixer.py``) : ``_resolve_remaining_conflicts``
    ne peut donc structurellement pas le résoudre, et tourne ses 10 passes pour
    rien. ``kct route`` refuse ensuite le board (« placement invalid »).

    La détection est **géométrique et non déléguée à l'analyseur** : mesuré le
    2026-07-31, ``ConflictType.OFF_BOARD`` n'existe pas dans la révision de
    kicad-tools installée dans l'image Docker (5 types seulement), et y référer
    lève une ``AttributeError`` qui tue le placement en cours de route. Le test
    de contour ci-dessous fonctionne sur toute révision.

    Deux voies natives ont été essayées et rejetées PAR LA MESURE (2026-07-31,
    board ``examples/stm32-validation`` en Docker) :

    - clamp de tous les footprints sur le rectangle du contour : les fautifs
      s'empilent sur le même coin, créant des conflits ERROR que
      ``test_placement.py`` attrape immédiatement ;
    - ``place_unplaced``, qui documente pourtant détecter les footprints
      « outside the board bounds » : il a signalé 15 composants sur 17, en a
      regrillé 8 en repère local en laissant les autres en coordonnées page, et
      a posé R2 à x = 61,1 mm sur une carte de 60 mm — le défaut à corriger.

    D'où cette réparation ciblée, minimale et conservatrice : seuls les refs
    réellement ``OFF_BOARD`` bougent, chacun vers la case libre la plus proche
    de sa position clampée. Le placement du GA — clusters, halo d'escape — est
    préservé pour tous les autres. Les conflits induits restent traités par
    l'Inspecteur, appelé par l'appelant.

    Repère : ``fp.position`` est board-local, ``outline.vertices`` est en
    coordonnées page ; la soustraction de ``pcb.board_origin`` les réconcilie.
    C'est exactement la confusion qui faisait échouer ``place_unplaced``.

    Renvoie les refs déplacées ; liste vide si rien n'est hors carte.
    """
    from kicad_tools.schema.pcb import PCB

    pcb = PCB.load(str(pcb_path))
    bornes = _outline_bounds(pcb)
    if bornes is None:
        return []
    fautifs = set(_refs_outside(pcb, bornes))
    if not fautifs:
        return []

    min_x, max_x = bornes[0] + _OFF_BOARD_MARGIN_MM, bornes[1] - _OFF_BOARD_MARGIN_MM
    min_y, max_y = bornes[2] + _OFF_BOARD_MARGIN_MM, bornes[3] - _OFF_BOARD_MARGIN_MM
    if min_x >= max_x or min_y >= max_y:
        return []

    occupes = [fp.position for fp in pcb.footprints if fp.reference not in fautifs]
    deplaces: list[str] = []

    for fp in pcb.footprints:
        if fp.reference not in fautifs:
            continue
        x, y = fp.position
        cible = (min(max(x, min_x), max_x), min(max(y, min_y), max_y))
        place = _nearest_free_cell(cible, occupes, (min_x, max_x, min_y, max_y))
        if place is None:
            logger.warning("réparation hors-carte: aucune case libre pour %s",
                           fp.reference)
            continue
        logger.warning(
            "réparation hors-carte: %s (%.2f,%.2f) -> (%.2f,%.2f)",
            fp.reference, x, y, place[0], place[1])
        fp.position = place
        occupes.append(place)
        deplaces.append(fp.reference)

    if deplaces:
        pcb.save(str(pcb_path))
    return deplaces


def _nearest_free_cell(cible: tuple[float, float],
                       occupes: list[tuple[float, float]],
                       bornes: tuple[float, float, float, float],
                       ) -> tuple[float, float] | None:
    """Case libre la plus proche de ``cible``, dans ``bornes``.

    « Libre » = à plus de ``_OFF_BOARD_SPACING_MM`` de tout centre occupé. Une
    approximation par distance entre centres suffit : l'Inspecteur affine
    ensuite avec les vrais courtyards. Recherche en spirale carrée bornée —
    jamais de boucle non terminante.
    """
    min_x, max_x, min_y, max_y = bornes
    pas = _OFF_BOARD_SPACING_MM

    def libre(p: tuple[float, float]) -> bool:
        return all(math.dist(p, q) >= pas for q in occupes)

    if libre(cible):
        return cible
    rayon_max = int(max(max_x - min_x, max_y - min_y) / pas) + 1
    for anneau in range(1, rayon_max + 1):
        for dx in range(-anneau, anneau + 1):
            for dy in (-anneau, anneau) if abs(dx) != anneau else range(-anneau, anneau + 1):
                cand = (cible[0] + dx * pas, cible[1] + dy * pas)
                if not (min_x <= cand[0] <= max_x and min_y <= cand[1] <= max_y):
                    continue
                if libre(cand):
                    return cand
    return None


def _outside_outline_refs(pcb_path: Path) -> int:
    """Compte et journalise les footprints restés hors du contour.

    Contrôle d'observabilité, exécuté APRÈS :func:`_repair_off_board` : s'il
    reste quoi que ce soit, la réparation a échoué et le routage sera plafonné
    — ``kct route`` refusera même le board (« placement invalid »). Ne modifie
    jamais rien.
    """
    from kicad_tools.schema.pcb import PCB

    try:
        pcb = PCB.load(str(pcb_path))
        bornes = _outline_bounds(pcb)
    except Exception:
        logger.exception("auto_place: contrôle hors-contour impossible")
        return 0
    if bornes is None:
        return 0

    hors = _refs_outside(pcb, bornes)
    for ref in hors:
        logger.warning(
            "auto_place: %s hors contour — contour %.1f..%.1f / %.1f..%.1f ; "
            "ses nets seront INROUTABLES",
            ref, bornes[0], bornes[1], bornes[2], bornes[3])
    return len(hors)


# ---------------------------------------------------------------------------
# Brique 1 — Halo d'escape autour des composants fine-pitch
# ---------------------------------------------------------------------------
# Cause racine mesurée (iso-prod Docker, 2026-07-22) du blocage 100% routable →
# routé → fabricable : un boîtier fine-pitch dense (LQFP-48 0,5mm) encerclé par
# ses voisins ne peut pas échapper ses broches proprement. À placement égal, le
# routage strict passe de 55% (voisins collés) à 73% (canal d'escape dégagé), en
# restant électriquement propre (0 court réel). On réserve donc un canal d'escape
# autour des composants denses AVANT de livrer le placement. 100% natif :
# détection = seuil `_dense_package_count` (≥16 pads) ; halo = keepout natif
# `create_keepout_from_component` ; résolution des overlaps induits = PlacementFixer.

# Seuil « boîtier dense » — identique à
# kicad_tools.optim.fom_features._dense_package_count (BGA, QFP/QFN denses).
_DENSE_PAD_COUNT: int = 16
# Largeur du canal d'escape réservé au-delà du courtyard d'un composant dense.
# Calibré (iso-prod Docker, board STM32) : 2,5 mm → 73% routé mais 1 court réel
# résiduel (kicad-cli) ; 5,0 mm approche le halo manuel (~6 mm de clearance) qui
# donnait 0 court. Un halo trop large sur une petite carte repousse trop de
# voisins vers les bords → re-mesurer si augmenté.
_ESCAPE_HALO_MM: float = 5.0
# Pas et plafond du push radial hors du keepout (borné — jamais de boucle infinie).
_HALO_PUSH_STEP_MM: float = 0.5
_HALO_PUSH_MAX_STEPS: int = 60


def _dense_part_refs(pcb) -> list[str]:
    """Refs des composants fine-pitch haut-broches (≥ ``_DENSE_PAD_COUNT`` pads).

    Seuil identique à ``kicad_tools.optim.fom_features._dense_package_count``
    (pas de constante custom). Ces boîtiers (BGA, QFP/QFN denses) ont besoin
    d'un canal d'escape dégagé pour router leurs broches sans quasi-courts.
    """
    return [fp.reference for fp in pcb.footprints
            if fp.reference and len(fp.pads) >= _DENSE_PAD_COUNT]


def _reserve_escape_halos(pcb_path: Path, anchored: list[str],
                          halo_mm: float = _ESCAPE_HALO_MM) -> int:
    """Écarte les voisins mobiles du halo d'escape des composants denses.

    Pour chaque composant dense (``_dense_part_refs``), crée un keepout natif
    (courtyard + ``halo_mm`` via ``create_keepout_from_component``) et pousse
    radialement hors du keepout tout footprint mobile dont le centre y tombe.
    Les composants ancrés (connecteurs) et les composants denses eux-mêmes ne
    bougent jamais. Les overlaps induits sont résolus par ``PlacementFixer``
    (``_resolve_remaining_conflicts``). Positions clampées dans le contour.

    Générique : **no-op** (retourne 0, board inchangé) si aucun composant dense
    — une carte simple (NE555, LED blinker) n'est jamais touchée.

    Renvoie le nombre de footprints déplacés.
    """
    from kicad_tools.schema.pcb import PCB
    from kicad_tools.optim.keepout import create_keepout_from_component
    from kicad_tools.optim.board_outline import extract_board_outline

    pcb = PCB.load(str(pcb_path))
    dense = _dense_part_refs(pcb)
    if not dense:
        return 0

    outline = extract_board_outline(pcb)
    ox, oy = pcb.board_origin
    if outline is not None and outline.vertices:
        xs = [v.x - ox for v in outline.vertices]
        ys = [v.y - oy for v in outline.vertices]
        bx0, bx1 = min(xs) + 2.0, max(xs) - 2.0
        by0, by1 = min(ys) + 2.0, max(ys) - 2.0
    else:
        bx0 = by0 = float("-inf")
        bx1 = by1 = float("inf")

    keep = set(anchored) | set(dense)
    pushed = 0
    for dref in dense:
        zone = create_keepout_from_component(pcb, dref, clearance_mm=halo_mm)
        if zone is None:
            continue
        dfp = next(fp for fp in pcb.footprints if fp.reference == dref)
        dcx, dcy = dfp.position
        for fp in pcb.footprints:
            if fp.reference in keep:
                continue
            x, y = fp.position
            if not zone.contains_point(x, y):
                continue
            dx, dy = x - dcx, y - dcy
            d = math.hypot(dx, dy) or 1.0
            ux, uy = dx / d, dy / d
            nx, ny = x, y
            for _ in range(_HALO_PUSH_MAX_STEPS):
                if not zone.contains_point(nx, ny):
                    break
                nx += ux * _HALO_PUSH_STEP_MM
                ny += uy * _HALO_PUSH_STEP_MM
            nx = min(max(nx, bx0), bx1)
            ny = min(max(ny, by0), by1)
            if (nx, ny) != (x, y):
                fp.position = (nx, ny)
                pushed += 1

    if pushed:
        pcb.save(str(pcb_path))
        # Overlaps induits par le push → réparation locale native (dense + ancrés figés).
        _resolve_remaining_conflicts(pcb_path, list(keep))
    return pushed


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

        # ── Brique 1 : halo d'escape — dégage le canal de routage des boîtiers
        # denses (fine-pitch) en écartant leurs voisins mobiles. No-op sur une
        # carte sans composant dense. Dernière étape placement : ni le GA ni le
        # CMA-ES ne peuvent re-tasser les voisins ensuite.
        n_halo = _reserve_escape_halos(out, conn)
        if n_halo:
            logger.info(
                "auto_place: halo d'escape — %d voisin(s) écarté(s) du périmètre "
                "des composants denses (fine-pitch)", n_halo)

        # ── Filet final : aucun composant ne sort du contour. Le GA peut parquer
        # un footprint au-delà du bord (mesuré 2026-07-30 : U1 à X=183,37 sur une
        # carte 100..160), rendant ses nets inroutables — 64 % de routage au lieu
        # de 100 %. Vient APRÈS le halo, qui écarte des voisins et peut lui-même
        # pousser un composant vers l'extérieur. Les chevauchements éventuels
        # sont réglés par l'Inspecteur juste après.
        # ── Contrôle final : signale (sans corriger) tout composant hors
        # contour. Le GA peut en parquer un au-delà du bord — mesuré le
        # 2026-07-30, U1 à X=183,37 sur une carte 100..160 — ce qui rend ses
        # nets inroutables et plafonne le routage (64 % au lieu de 100 %).
        # La réparation reste à écrire : cf. _outside_outline_refs.
        # Réparation et Inspecteur se contredisent : PlacementFixer écarte les
        # composants sans aucune notion de contour et RESSORT ceux qu'on vient
        # de rentrer (mesuré 2026-07-31 : 5 composants toujours dehors après une
        # passe unique). On alterne donc les deux jusqu'à point fixe, borné.
        for passe in range(_OFF_BOARD_MAX_PASSES):
            repares = _repair_off_board(out, conn)
            if not repares:
                break
            logger.warning(
                "auto_place: passe %d — %d composant(s) hors carte réparé(s) "
                "(%s) ; leurs nets auraient été inroutables et kct route aurait "
                "refusé le board", passe + 1, len(repares), ", ".join(repares))
            # Dernière passe : ne pas relancer l'Inspecteur, il les ressortirait
            # sans qu'une réparation ne suive.
            if passe < _OFF_BOARD_MAX_PASSES - 1:
                _resolve_remaining_conflicts(out, conn)
        n_hors = _outside_outline_refs(out)
        if n_hors:
            logger.error(
                "auto_place: %d composant(s) TOUJOURS hors contour après "
                "réparation — routage plafonné", n_hors)

        footprints = PCB.load(str(out)).footprints
        return {
            "kicad_pcb_b64": base64.b64encode(out.read_bytes()).decode(),
            "placed_count": len(footprints),
            # Clés `x_mm`/`y_mm` — contrat documenté par AutoPlacementResponse et
            # attendu par le client TS (`placement-service.ts::isValidPosition`).
            # Le code émettait `x`/`y`, contredisant son propre modèle : le client
            # filtrait donc TOUTES les positions et `call_agent_placement`
            # renvoyait `placements: []`. Invisible aux tests mockés, qui
            # reproduisaient l'hypothèse du client et non la réalité du service ;
            # révélé le 2026-07-27 par `pipeline-live.test.ts`.
            "positions": [
                {"ref": fp.reference,
                 "x_mm": round(fp.position[0], 2), "y_mm": round(fp.position[1], 2)}
                for fp in footprints
            ],
        }
