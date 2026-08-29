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
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

# Env partagé des sous-processus kicad-tools : UTF-8 forcé + PYTHONPATH vers
# kicad-tools/src en local/CI seulement (jamais en Docker, où le paquet est
# pip-installé avec le backend C++).
from tools.kct_route import _kct_env
from tools.placement_bypass import snap_cluster_members
from tools.sexp_quote import unquote_keepout_values

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


def _outline_extent_board_frame(pcb) -> Optional[tuple[float, float]]:
    """Coin bas-droit du contour Edge.Cuts, ramené en repère board.

    ``fp.position`` est board-relative (l'API PCB soustrait ``board_origin``),
    les graphiques Edge.Cuts sont sheet-absolute — d'où la soustraction ici.
    """
    ox, oy = pcb.board_origin
    xs: list[float] = []
    ys: list[float] = []
    for attr in ("graphic_items", "graphics", "lines"):
        for item in getattr(pcb, attr, None) or []:
            if getattr(item, "layer", None) != "Edge.Cuts":
                continue
            for point_attr in ("start", "end"):
                pt = getattr(item, point_attr, None)
                if pt is not None:
                    xs.append(pt[0] - ox)
                    ys.append(pt[1] - oy)
    if not xs or not ys:
        return None
    return max(xs), max(ys)


def _normalize_to_board_frame(pcb_path: Path) -> int:
    """Ramène les positions en repère board si elles ont été écrites en absolu.

    ``OptimizationWorkflow.write_to_pcb()`` a changé de convention entre
    kicad-tools 0.13.0 et 0.18.0 (bump PR #69) : il écrit désormais les positions
    en **sheet-absolute** dans un champ que l'API PCB relit en **board-relative**.
    Sur la fixture led-blinker (``board_origin`` = 118.5, 82.5), les composants
    ressortaient à x≈124-147 / y≈88-111 pour un contour de 60×45 mm — soit
    exactement ``position + board_origin``. ``kct route`` refusait alors le
    placement, le repli Freerouting rendait un board sans netlist, et le tout
    était rapporté « routé à 100 % » (issue #72).

    Correctif défensif plutôt que dépendant d'une version : on ne translate que
    si le décalage de ``board_origin`` explique l'écart pour TOUS les composants
    hors contour. Un débordement isolé (un composant réellement mal placé) n'est
    pas un problème de repère et n'est pas touché — sinon on déplacerait sept
    composants corrects pour « réparer » le huitième.

    Retourne le nombre de footprints translatés (0 si rien à faire).
    """
    from kicad_tools.schema.pcb import PCB

    pcb = PCB.load(str(pcb_path))
    extent = _outline_extent_board_frame(pcb)
    if extent is None:
        return 0
    width, height = extent
    ox, oy = pcb.board_origin
    if ox == 0 and oy == 0:
        return 0

    def inside(x: float, y: float) -> bool:
        return 0.0 <= x <= width and 0.0 <= y <= height

    outside = [fp for fp in pcb.footprints if not inside(*fp.position[:2])]
    if not outside:
        return 0
    # Le décalage doit expliquer TOUS les cas, sinon ce n'est pas le repère.
    if not all(inside(fp.position[0] - ox, fp.position[1] - oy) for fp in outside):
        logger.warning(
            "_normalize_to_board_frame: %d composant(s) hors contour NON expliqués par "
            "board_origin — placement réellement fautif, pas un décalage de repère",
            len(outside),
        )
        return 0

    for fp in outside:
        fp.position = (fp.position[0] - ox, fp.position[1] - oy)
    pcb.save(str(pcb_path))
    logger.warning(
        "_normalize_to_board_frame: %d position(s) réécrites en repère board "
        "(décalage board_origin %.2f,%.2f appliqué par write_to_pcb — cf. issue #72)",
        len(outside), ox, oy,
    )
    return len(outside)


class DrcInexecutable(RuntimeError):
    """`kicad-cli` est present mais n a rendu aucun rapport exploitable.

    ⚠️ Cette exception existe parce que l absence de rapport se lisait « 0
    erreur ». Mesure du 2026-08-27 sur l ESP32 : le board place etait refuse
    par `kicad-cli` (« Failed to load board »), le rapport revenait VIDE, et
    `_compter_conflits_erreur` annoncait zero conflit sur un board qui en
    portait vingt. La boucle de re-tirage s endormait, et la chaine routait
    vingt-cinq minutes un board condamne d avance.

    Un controle qui n a pas eu lieu ne rend pas un verdict favorable : il ne
    rend pas de verdict.
    """


# Percage minimum du procede STANDARD de JLCPCB, et defaut de KiCad. En
# dessous, la carte part en option payante — ou se fait refuser.
_PERCAGE_MINIMUM_MM = 0.3
# Anneau minimum de part et d autre du percage (defaut KiCad : 0,10 mm).
_ANNEAU_MINIMUM_MM = 0.1

_PERCAGE_RE = re.compile(r"\(drill\s+(\d+(?:\.\d+)?)\)")
_TAILLE_RE = re.compile(r"\(size\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\)")


def elargir_percages_trop_fins(texte: str) -> tuple:
    """Renvoie ``(texte_corrige, nombre_de_percages_elargis)``.

    ⚠️ Mesure du 2026-08-27, ESP32 : les douze dernieres erreurs du board place
    etaient `drill_out_of_range` sur les vias thermiques du module —
    `(drill 0.2)`, tels que la bibliotheque KiCad les fournit. Le minimum par
    defaut de KiCad vaut 0,30 mm, comme le procede standard de JLCPCB.

    ⚠️ On n assouplit PAS la regle dans le `.kicad_pro`. `_projet_kicad` ne le
    fait que pour les boitiers fine-pitch, en assumant l option payante ;
    l appliquer ici ferait passer pour fabricable une carte qui ne l est pas au
    tarif standard. Elargir le percage, lui, ne coute rien.

    ⚠️ La pastille suit : elargir le percage seul remplacerait une erreur de
    percage par une erreur d anneau.

    Garde : tests/test_percages_fabricables.py.
    """
    n = 0

    def sur_un_pad(bloc: str) -> str:
        nonlocal n
        m = _PERCAGE_RE.search(bloc)
        if m is None or float(m.group(1)) >= _PERCAGE_MINIMUM_MM:
            return bloc
        n += 1
        bloc = bloc[:m.start()] + "(drill %s)" % _PERCAGE_MINIMUM_MM + bloc[m.end():]
        mini = _PERCAGE_MINIMUM_MM + 2 * _ANNEAU_MINIMUM_MM
        t = _TAILLE_RE.search(bloc)
        if t is not None and (float(t.group(1)) < mini or float(t.group(2)) < mini):
            bloc = bloc[:t.start()] + "(size %s %s)" % (
                max(float(t.group(1)), mini), max(float(t.group(2)), mini)
            ) + bloc[t.end():]
        return bloc

    # On decoupe par pastille : le percage et la taille d un MEME pad doivent
    # etre corriges ensemble, jamais appareilles au hasard du fichier.
    morceaux = texte.split("(pad ")
    sortie = [morceaux[0]] + [sur_un_pad(m) for m in morceaux[1:]]
    return "(pad ".join(sortie), n


def _rendre_lisible(pcb_path: Path) -> None:
    """Repare, EN PLACE, ce que les lecteurs de KiCad refusent.

    Appelee juste avant de mesurer et de rendre le board — donc avant que
    `kicad-cli` ne le lise, et avant qu il ne quitte le service. Reparer chez
    chaque lecteur revient a en oublier un ; ici il n y en a qu un a ne pas
    oublier.
    """
    brut = pcb_path.read_text(encoding="utf-8", errors="replace")
    corrige, n = unquote_keepout_values(brut)
    if n:
        logger.info(
            "auto_place: %d valeur(s) de keepout deguillemetee(s) — sans quoi "
            "kicad-cli refuse le board et son rapport revient vide", n)
    corrige, n_percages = elargir_percages_trop_fins(corrige)
    if n_percages:
        logger.info(
            "auto_place: %d percage(s) elargi(s) a %s mm — en dessous, JLCPCB "
            "refuse la carte au tarif standard", n_percages, _PERCAGE_MINIMUM_MM)
    if n or n_percages:
        pcb_path.write_text(corrige, encoding="utf-8")


def _rapport_drc_placement(pcb_path: Path) -> dict:
    """Rapport `kicad-cli pcb drc`, ou dict vide s il est indisponible."""
    import json as _json
    import shutil as _shutil

    cli = _shutil.which("kicad-cli")
    if cli is None:
        # Seule absence toleree : l outil n est pas la. Le service traite deja
        # ce cas en amont (`skipped`), et l appelant ne peut pas le confondre
        # avec un board refuse.
        return {}
    with tempfile.TemporaryDirectory() as tmp:
        rapport = Path(tmp) / "drc.json"
        r = subprocess.run(
            [cli, "pcb", "drc", str(pcb_path), "--format", "json",
             "-o", str(rapport)],
            capture_output=True, text=True, timeout=120, check=False,
        )
        if not rapport.is_file():
            raise DrcInexecutable(
                "kicad-cli n a produit aucun rapport (%s)"
                % ((r.stdout or r.stderr or "").strip()[:200] or "sans message"))
        return _json.loads(rapport.read_text(encoding="utf-8"))


# Nombre de conflits rendu quand le DRC n a PAS pu se prononcer. Volontairement
# enorme : `auto_place` garde le tirage au plus petit compte, donc un tirage
# non mesurable ne peut jamais etre retenu comme « le meilleur ».
_CONFLITS_INDETERMINES = 10 ** 6


# Violations de placement au sens du DRC : ce que le verdict final refuse.
_TYPES_CONFLIT = ("courtyards_overlap", "shorting_items",
                  "pth_inside_courtyard", "clearance")


def _compter_conflits_erreur(pcb_path: Path) -> int:
    """Conflits de placement, mesures par `kicad-cli` — l instrument qui tranche.

    ⚠️ On interrogeait `PlacementAnalyzer` (kicad-tools, ses propres
    DesignRules). Mesure du 2026-08-27, ESP32 : il declarait le placement
    PROPRE au tirage 3, et le board final portait ONZE
    `courtyards_overlap`. Le re-tirage s arretait donc sur un placement
    qu il croyait bon, et la chaine routait 25 minutes un board condamne.

    Mesurer avec un autre instrument que celui qui tranche, c est se
    rassurer sans rien garantir. Le DRC coute 1 a 2 s par tirage contre 2 a
    4 MINUTES de placement : le bon outil ne change pas l ordre de grandeur.

    Rend 0 si la mesure est impossible : un compteur en panne ne doit ni
    faire echouer un placement valide, ni declencher des re-tirages inutiles.
    """
    try:
        rapport = _rapport_drc_placement(pcb_path)
    except DrcInexecutable as exc:
        # ⚠️ On rendait 0 — « non mesurable » se lisait « propre ». La boucle
        # de re-tirage acceptait alors un board jamais controle. Un tirage
        # qu on ne sait pas juger doit etre RE-TIRE, donc compte comme pire
        # que n importe quel tirage mesure.
        logger.error(
            "auto_place: conflits NON MESURABLES (%s) — tirage tenu pour "
            "invalide plutot que pour propre", exc)
        return _CONFLITS_INDETERMINES
    except Exception as exc:
        logger.error(
            "auto_place: rapport DRC illisible (%s) — tirage tenu pour invalide",
            exc)
        return _CONFLITS_INDETERMINES
    return sum(
        1 for v in (rapport.get("violations") or [])
        if isinstance(v, dict) and v.get("severity") == "error"
        and v.get("type") in _TYPES_CONFLIT
    )

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


# Messages du Géomètre — nommés pour que la garde d'observabilité puisse les
# retrouver, et pour qu'un futur refactor ne les supprime pas par distraction.
_LOG_GEOMETRE_OK = (
    "auto_place: Géomètre CMA-ES appliqué — %.1fs, déplacement max %.1fmm "
    "(seuil %.1fmm)"
)
_LOG_GEOMETRE_SAUTE = (
    "auto_place: Géomètre CMA-ES NON appliqué (%.1fs) — board de l'Architecte conservé"
)


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


def _clamp_axe(v: float, b0: float, b1: float, lo: float, hi: float) -> float:
    """Ramene ``v`` pour que le segment ``[v + b0, v + b1]`` tienne dans ``[lo, hi]``.

    ⚠️ Rend le CENTRAGE si la piece est plus large que le contour : la
    contrainte est alors insatisfiable, et debordement pour debordement, mieux
    vaut deborder des deux cotes d autant — un coin choisi au hasard mettrait
    tout le corps du meme cote.
    """
    bas, haut = lo - b0, hi - b1
    if bas > haut:
        return (lo + hi) / 2.0 - (b0 + b1) / 2.0
    return min(max(v, bas), haut)


def _clamp_fixed_refs_to_outline(pcb, fixed_refs: list[str], margin_mm: float = 2.0,
                                 exempts: list = None) -> list[str]:
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
        # ⚠️ On ramene la BOITE dans le contour, pas la POSITION. L origine
        # d un connecteur est sur sa broche 1, a une extremite : un Morpho
        # 2x19 mesure 50 mm, et clamper sa position a 2 mm du bord laissait
        # 48 mm de corps DEHORS — le defaut meme que ce clamp doit empecher,
        # puisqu un ancrage n est plus jamais deplace ensuite.
        fx0, fy0, fx1, fy1 = _boite_locale_fp(fp)
        cx = _clamp_axe(x, fx0, fx1, min_x, max_x)
        cy = _clamp_axe(y, fy0, fy1, min_y, max_y)
        # ⚠️ On vérifie la collision de TOUT ancrage, clampé ou non : deux
        # connecteurs superposés À L'INTÉRIEUR du contour produisent le même
        # blocage, et n'étaient pas clampés donc pas examinés.
        # ⚠️ Un boitier DOMINANT est exempt du deplacement anti-collision.
        # Il chevauche forcement ses voisins au moment ou on le pose — c est
        # aux voisins de s ecarter, pas a lui. Sans cette exemption, le
        # module ESP32 centre a 46,5 mm etait POUSSE a 82 sur une carte de
        # 93, ou il debordait de 9,6 mm : deux correctifs qui se combattent,
        # mesure du 2026-08-27.
        if exempts and fp.reference in exempts:
            nx, ny = cx, cy
        else:
            nx, ny = _position_libre_pour_ancrage(pcb, fp.reference, cx, cy,
                                                  min_x, max_x, min_y, max_y)
        if (nx, ny) != (x, y):
            logger.warning("ancrage %s (%.2f,%.2f) -> reposé (%.2f,%.2f)",
                           fp.reference, x, y, nx, ny)
            fp.position = (nx, ny)
            clamped.append(fp.reference)
    return clamped


# Pas de recherche pour reposer un ancrage : la MOITIÉ de son propre encombrement.
# Dérivé du footprint, jamais d'une constante — un connecteur 40 broches et un
# 2 broches n'ont pas le même besoin, et une valeur fixe conviendrait à l'un en
# trahissant l'autre. Plancher à 1 mm pour progresser même sur un footprint
# minuscule ou sans courtyard déclaré.
_PAS_MIN_MM: float = 1.0


def _encombrement_mm(pcb, ref: str) -> float:
    """Plus grande dimension du footprint, d'après ses propres pads."""
    fp = next((f for f in pcb.footprints if f.reference == ref), None)
    if fp is None:
        return _PAS_MIN_MM
    xs, ys = [], []
    for pad in getattr(fp, "pads", []) or []:
        px, py = getattr(pad, "position", (0.0, 0.0))
        xs.append(px)
        ys.append(py)
    if not xs:
        return _PAS_MIN_MM
    return max(max(xs) - min(xs), max(ys) - min(ys), _PAS_MIN_MM)


def _position_libre_pour_ancrage(pcb, ref: str, cx: float, cy: float,
                                 min_x: float, max_x: float,
                                 min_y: float, max_y: float) -> tuple:
    """Repose un ancrage clampé là où il n'entre en collision avec RIEN.

    ⚠️ Le clamp traitait chaque ancrage INDÉPENDAMMENT : deux connecteurs
    hors-carte du même côté atterrissaient au MÊME coin. Mesuré le
    2026-08-23 sur le premier pipeline complet passé par la file —
    l'orchestrateur rapportait « courtyards overlap + PTH inside courtyard
    → J1 et J3 co-localisés (même position x=128.5, y=123) » et re-tirait le
    placement en boucle, trois minutes par tirage.

    Or **le re-tirage ne peut pas réparer ça** : les connecteurs sont ancrés,
    donc l'optimiseur ne les déplace jamais. Le run épuisait ses itérations
    sans pouvoir atteindre DRC_CLEAN.

    La collision est jugée par `PCB.check_placement_collision`, l'API native
    de kicad-tools : elle compare les COURTYARDS RÉELS de chaque composant.
    Aucune constante d'écart, donc aucune hypothèse sur la taille des
    boîtiers — un connecteur 40 broches est traité comme tel.
    """
    try:
        if not pcb.check_placement_collision(ref, cx, cy).has_collision:
            return cx, cy
    except Exception as exc:  # API absente ou footprint atypique
        logger.debug("collision non vérifiable pour %s (%s)", ref, exc)
        return cx, cy

    pas = _encombrement_mm(pcb, ref)
    # On glisse le long des bords : un ancrage clampé y est déjà, et c'est là
    # que la place se trouve. Spirale en croix, jamais en diagonale.
    for i in range(1, 41):
        for nx, ny in ((cx, cy + i * pas), (cx, cy - i * pas),
                       (cx + i * pas, cy), (cx - i * pas, cy)):
            if not (min_x <= nx <= max_x and min_y <= ny <= max_y):
                continue
            try:
                if not pcb.check_placement_collision(ref, nx, ny).has_collision:
                    return nx, ny
            except Exception:
                return cx, cy
    # Aucune place libre : on garde la position clampée. Superposer deux
    # connecteurs reste moins grave que les poser hors du contour, où leurs
    # nets seraient inroutables.
    logger.warning("ancrage %s : aucune position libre trouvée dans la carte", ref)
    return cx, cy
    for i in range(1, len(occupees) + 2):
        for nx, ny in ((cx, cy + i * _ECART_ANCRAGES_MM),
                       (cx, cy - i * _ECART_ANCRAGES_MM),
                       (cx + i * _ECART_ANCRAGES_MM, cy),
                       (cx - i * _ECART_ANCRAGES_MM, cy)):
            if not (min_x <= nx <= max_x and min_y <= ny <= max_y):
                continue
            if any(abs(nx - ox) < _ECART_ANCRAGES_MM and abs(ny - oy) < _ECART_ANCRAGES_MM
                   for ox, oy in occupees):
                continue
            return nx, ny
    # Aucune place : on rend la position clampée telle quelle. Superposer
    # deux connecteurs reste moins grave que les poser hors du contour, où
    # leurs nets seraient inroutables.
    return cx, cy


# Retrait du bord pour reposer un composant sorti du contour, et pas d'une
# recherche de case libre. 2,5 mm ≈ demi-courtyard d'un 0805 + marge : assez
# lâche pour que l'Inspecteur n'ait qu'un réglage fin à faire, assez serré pour
# ne pas gaspiller la surface d'une petite carte.
# Alternances réparation ↔ Inspecteur avant abandon. L'Inspecteur ignore le
# contour et ressort ce qu'on vient de rentrer ; la dernière passe répare donc
# sans le relancer. 3 suffit largement : mesuré, le point fixe tombe en 1 ou 2.




def _off_board_refs(pcb_path: Path) -> list[str]:
    """Refs hors carte **selon PlacementAnalyzer**, la seule autorité fiable.

    Toute tentative de le déterminer géométriquement s'est heurtée à
    l'ambiguïté du repère : ``outline.vertices`` est en coordonnées page,
    ``fp.position`` est tantôt page tantôt board-local, et ``board_origin`` vaut
    tantôt ``(100,100)`` tantôt ``(0,0)``. Trois implémentations s'y sont
    trompées le 2026-07-31, chacune en annonçant l'absurde — ``place_unplaced``
    15 composants sur 17 hors carte, un calcul de bornes maison 14 sur 17, une
    déduction par majorité qui inversait le verdict sur un fixture. L'analyseur,
    lui, sait.

    Le type de conflit est comparé **par son nom** et non via
    ``ConflictType.OFF_BOARD`` : ce membre n'existe pas dans la révision
    kicad-tools installée dans l'image Docker (5 types), et y référer lève une
    ``AttributeError`` qui tue le placement en silence (stdout bufferisé perdu
    au kill). Sur une révision qui l'ignore, on ne répare pas — ``kct route``
    refusera alors le board bruyamment, ce qui vaut mieux qu'une réparation
    fondée sur un repère deviné.
    """
    from kicad_tools.placement.analyzer import DesignRules, PlacementAnalyzer

    try:
        conflicts = PlacementAnalyzer().find_conflicts(
            str(pcb_path), DesignRules(courtyard_margin=_COURTYARD_MARGIN_MM))
    except Exception:
        logger.exception("détection hors-carte: analyseur indisponible")
        return []

    refs: list[str] = []
    for c in conflicts:
        if getattr(getattr(c, "type", None), "name", "") != "OFF_BOARD":
            continue
        for ref in (getattr(c, "component1", None), getattr(c, "component2", None)):
            if ref and ref not in refs:
                refs.append(ref)
    return refs




# Retrait du bord pour reposer un composant sorti du contour, et pas de la
# recherche de case libre. 2,5 mm ~ demi-courtyard d'un 0805 + marge.
_OFF_BOARD_MARGIN_MM: float = 2.0
_OFF_BOARD_SPACING_MM: float = 2.5


def _repair_off_board(pcb_path: Path, anchored: list[str]) -> list[str]:
    """Ramène dans le contour les seuls footprints signalés hors carte.

    Repère établi empiriquement le 2026-07-31 sur cinq boards réels, et
    identique sur tous : ``board_origin`` vaut ``(100,100)``,
    ``outline.vertices`` est en coordonnées PAGE, ``fp.position`` est
    BOARD-LOCAL (écart constant de -100,-100). Les bornes utilisables sont donc
    ``contour - board_origin``. Ce contrôle a été refait parce que trois
    tentatives de réparation avaient conclu à tort à une ambiguïté de repère —
    en réalité les comptes aberrants (14 ou 15 composants sur 17) venaient de
    tirages GA réellement catastrophiques, pas d'un décalage.

    Le point qui faisait échouer la boucle réparation ↔ Inspecteur :
    ``PlacementFixer`` n'a aucune notion de contour et ressortait ce qu'on
    venait de rentrer. On lui passe donc les refs réparées dans ``anchored``,
    qu'il ne déplace jamais — il résout les chevauchements en bougeant les
    AUTRES composants. C'est le mécanisme natif prévu pour ça.

    Renvoie les refs déplacées ; liste vide si rien n'est hors carte.
    """
    from kicad_tools.schema.pcb import PCB

    fautifs = set(_off_board_refs(pcb_path))
    if not fautifs:
        return []

    pcb = PCB.load(str(pcb_path))
    bornes = _outline_bounds(pcb)
    if bornes is None:
        logger.warning("réparation hors-carte: contour illisible — abandon")
        return []

    occupes = [fp.position for fp in pcb.footprints if fp.reference not in fautifs]
    deplaces: list[str] = []

    for fp in pcb.footprints:
        if fp.reference not in fautifs:
            continue
        # Marge PROPRE au composant : ses pads doivent tenir dans le contour,
        # pas seulement son centre (cf. _footprint_reach_mm).
        marge = _footprint_reach_mm(fp) + _OFF_BOARD_MARGIN_MM
        min_x, max_x = bornes[0] + marge, bornes[1] - marge
        min_y, max_y = bornes[2] + marge, bornes[3] - marge
        if min_x >= max_x or min_y >= max_y:
            logger.warning(
                "réparation hors-carte: %s (encombrement %.1f mm) ne tient pas "
                "dans le contour", fp.reference, marge)
            continue
        x, y = fp.position
        cible = (min(max(x, min_x), max_x), min(max(y, min_y), max_y))
        place = _nearest_free_cell(cible, occupes, (min_x, max_x, min_y, max_y))
        if place is None:
            logger.warning("réparation hors-carte: aucune case libre pour %s",
                           fp.reference)
            continue
        logger.warning("réparation hors-carte: %s (%.2f,%.2f) -> (%.2f,%.2f)",
                       fp.reference, x, y, place[0], place[1])
        fp.position = place
        occupes.append(place)
        deplaces.append(fp.reference)

    if deplaces:
        pcb.save(str(pcb_path))
    return deplaces


def _footprint_reach_mm(fp) -> float:
    """Distance du centre au pad le plus éloigné, demi-taille de pad comprise.

    ``kct route`` refuse un board en comptant les **pads** hors Edge.Cuts, pas
    les centres : « ERROR: 2 footprint(s) / 4 pad(s) outside Edge.Cuts ». Une
    marge fixe centre-à-bord ne suffit donc pas — un LQFP-48 fait 9 mm de large
    et un header 1×06 en fait 15, leur centre peut être à 2 mm du bord avec
    des pads dehors. C'est ce qui laissait 2 footprints hors carte après
    réparation (mesuré 2026-07-31).

    ``pad.position`` est relatif au centre du footprint ; on majore la rotation
    en prenant le maximum sur les deux axes, ce qui est conservateur.
    """
    reach = 0.0
    for pad in getattr(fp, "pads", ()) or ():
        px, py = getattr(pad, "position", (0.0, 0.0))
        sx, sy = getattr(pad, "size", (0.0, 0.0)) or (0.0, 0.0)
        reach = max(reach, abs(px) + sx / 2, abs(py) + sy / 2)
    return reach


def _outline_bounds(pcb) -> tuple[float, float, float, float] | None:
    """Bornes du contour dans le repère de ``fp.position`` (board-local).

    ``outline.vertices`` est en coordonnées page ; la soustraction de
    ``pcb.board_origin`` donne le repère board-local des positions de
    footprints. Vérifié sur cinq boards réels : l'écart est exactement
    ``-board_origin`` pour chaque composant.
    """
    from kicad_tools.optim.board_outline import extract_board_outline

    outline = extract_board_outline(pcb)
    if outline is None or not outline.vertices:
        return None
    ox, oy = pcb.board_origin
    xs = [v.x - ox for v in outline.vertices]
    ys = [v.y - oy for v in outline.vertices]
    return min(xs), max(xs), min(ys), max(ys)


def _nearest_free_cell(cible: tuple[float, float],
                       occupes: list[tuple[float, float]],
                       bornes: tuple[float, float, float, float],
                       ) -> tuple[float, float] | None:
    """Case libre la plus proche de ``cible``, dans ``bornes``.

    « Libre » = à plus de ``_OFF_BOARD_SPACING_MM`` de tout centre occupé — une
    approximation par distance entre centres suffit, l'Inspecteur affinant
    ensuite avec les vrais courtyards. Empiler tout sur le coin clampé était le
    défaut de la première tentative, attrapé par ``test_placement.py``.
    Recherche en anneaux carrés bornée : jamais de boucle non terminante.
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
            dys = (-anneau, anneau) if abs(dx) != anneau else range(-anneau, anneau + 1)
            for dy in dys:
                cand = (cible[0] + dx * pas, cible[1] + dy * pas)
                if not (min_x <= cand[0] <= max_x and min_y <= cand[1] <= max_y):
                    continue
                if libre(cand):
                    return cand
    return None


def _normalize_origin_after_write(pcb, skip: list[str]) -> int:
    """Retire le ``board_origin`` surnuméraire appliqué par ``write_to_pcb()``.

    **Contradiction interne d'upstream, mesurée le 2026-07-31.**
    ``PlacementOptimizer.from_pcb`` construit ses ``Component`` avec
    ``x=fp.position[0]`` — du board-local — mais retranslate le polygone de la
    carte en coordonnées PAGE (``placement.py:244``, « Translate the outline
    back into the absolute board frame »), en affirmant en commentaire que
    « the optimizer adds components at their raw *absolute* positions ». Les
    deux ne peuvent pas être vrais en même temps. Conséquence : le GA déplace
    des positions locales vers une région exprimée en page, puis
    ``write_to_pcb()`` les passe à ``update_footprint_position``, dont la
    docstring précise qu'elle attend du **relatif à l'origine** et applique
    l'offset elle-même. L'origine est donc comptée deux fois.

    Effet mesuré sur ``examples/stm32-validation``, 3 tirages sur 3 : 15 à 16
    composants sur 17 hors carte, ``J1`` seul épargné parce qu'ancré et clampé
    AVANT l'optimisation. Positions livrées à 216-250 mm sur un contour
    100-160 mm, soit exactement ``+board_origin``. ``kct route`` refuse alors le
    board (« placement invalid ») et tout le pipeline s'effondre.

    **Auto-détectant, donc sûr dans la durée.** On ne soustrait que si le
    composant est hors contour ET que la soustraction l'y ramène. Le jour où le
    sous-module corrige sa contradiction, cette fonction devient un no-op
    silencieux — aucune position ne bougera. Elle ne peut pas non plus déplacer
    un composant déjà correct.

    ``skip`` : les connecteurs ancrés, que l'optimiseur ne touche pas et dont
    les coordonnées sont déjà justes.

    Renvoie le nombre de footprints normalisés.
    """
    bornes = _outline_bounds_local(pcb)
    if bornes is None:
        return 0
    min_x, max_x, min_y, max_y = bornes
    ox, oy = pcb.board_origin
    if not (ox or oy):
        return 0

    def dedans(x: float, y: float) -> bool:
        return min_x <= x <= max_x and min_y <= y <= max_y

    ignores = set(skip)
    n = 0
    for fp in pcb.footprints:
        if fp.reference in ignores:
            continue
        x, y = fp.position
        if dedans(x, y):
            continue  # déjà correct — ne jamais toucher
        if dedans(x - ox, y - oy):
            fp.position = (x - ox, y - oy)
            n += 1
    if n:
        logger.warning(
            "auto_place: %d composant(s) normalisé(s) — write_to_pcb() avait "
            "appliqué board_origin (%.1f, %.1f) en double", n, ox, oy)
    return n


def _outline_bounds_local(pcb) -> tuple[float, float, float, float] | None:
    """Bornes du contour Edge.Cuts dans le repère de ``fp.position``.

    ``outline.vertices`` est en coordonnées page ; ``fp.position`` est
    board-local. Vérifié empiriquement sur cinq boards réels : l'écart vaut
    exactement ``-board_origin`` pour chaque composant.
    """
    from kicad_tools.optim.board_outline import extract_board_outline

    outline = extract_board_outline(pcb)
    if outline is None or not outline.vertices:
        return None
    ox, oy = pcb.board_origin
    xs = [v.x - ox for v in outline.vertices]
    ys = [v.y - oy for v in outline.vertices]
    return min(xs), max(xs), min(ys), max(ys)


def restore_pad_angles(src_text: str, out_text: str) -> tuple[str, int]:
    """Restaure l'angle des pads tel que la SOURCE le déclare. 204 erreurs → 0.

    Le writer du placement ajoute un angle aux pads que le board d'entrée ne
    déclare pas. Mesuré le 2026-08-01 sur ``examples/stm32-validation`` :

    - source ``gen0`` : ``(footprint ... (at x y))`` sans rotation, pads
      ``(at 4.1625 2.75)`` sans angle — conforme au footprint officiel KiCad ;
    - après placement : footprint toujours **non pivoté**, mais chaque pad
      porte ``(at 4.1625 2.75 90)``.

    Les pads 25-27 d'un LQFP-48 forment une colonne verticale au pas de 0,5 mm ;
    un angle de 90° bascule leur grand axe (1,475 mm) le long de la colonne et
    les fait se recouvrir d'un millimètre. Les positions, elles, ne bougent pas —
    c'est bien l'angle seul qui est corrompu.

    Effet mesuré sur un board SANS UNE SEULE PISTE :

    =================================  ============
    État                               erreurs DRC
    =================================  ============
    ``gen0`` (avant placement)                    0
    après placement                             204
    après restauration des angles            **0**
    =================================  ============

    Le placement introduisait donc la totalité des erreurs, et le routage en
    était innocent de bout en bout.

    **Restaurer plutôt qu'imposer.** On recopie l'angle de la source, pad par
    pad, apparié par référence de boîtier et numéro de pad. Un pad dont la
    bibliothèque déclare légitimement une rotation propre la conserve donc — ce
    qu'une règle du type « angle = rotation du footprint » aurait détruit.

    N'altère ni le placement ni sa méthode : positions, rotations de boîtier et
    stratégie sont inchangées. Réparation de sérialisation, comme
    :func:`_normalize_origin_after_write`.

    Renvoie ``(texte, nombre de pads restaurés)``.
    """
    source = _pad_angles(src_text)
    if not source:
        return out_text, 0

    corriges = 0
    morceaux = re.split(r"(\(footprint )", out_text)
    sorties = [morceaux[0]]
    i = 1
    while i + 1 < len(morceaux):
        sep, bloc = morceaux[i], morceaux[i + 1]
        ref = re.search(r'\(property "Reference" "([^"]+)"', bloc) or             re.search(r'reference "([^"]+)"', bloc)
        entete = re.search(r"\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", bloc)
        rot_fp = float(entete.group(3)) if (entete and entete.group(3)) else 0.0
        if ref:
            nom = ref.group(1)
            parts = re.split(r"(\(pad )", bloc)
            neuf = [parts[0]]
            j = 1
            while j + 1 < len(parts):
                pb = parts[j + 1]
                num = re.match(r'"([^"]+)"', pb)
                cle = (nom, num.group(1)) if num else None
                if cle in source:
                    # Angle ABSOLU = rotation du boîtier + angle RELATIF que la
                    # source déclare (None = 0). C'est la règle qui unifie les
                    # deux corruptions mesurées.
                    relatif = source[cle] or 0.0
                    absolu = (rot_fp + relatif) % 360.0

                    def _fix(m, a=absolu):
                        if a == 0.0:
                            return "(at %s %s)" % (m.group(1), m.group(2))
                        return "(at %s %s %g)" % (m.group(1), m.group(2), a)

                    pb2, _ = re.subn(r"\(at ([-\d.]+) ([-\d.]+)(?: [-\d.]+)?\)",
                                     _fix, pb, count=1)
                    if pb2 != pb:
                        corriges += 1
                    pb = pb2
                neuf.append(parts[j] + pb)
                j += 2
            if j < len(parts):
                neuf.append(parts[j])
            bloc = "".join(neuf)
        sorties.append(sep + bloc)
        i += 2
    if i < len(morceaux):
        sorties.append(morceaux[i])
    return "".join(sorties), corriges


def _pad_angles(text: str) -> dict[tuple[str, str], float | None]:
    """``{(ref_boitier, num_pad): angle}`` — ``None`` quand le pad n'en a pas."""
    angles: dict[tuple[str, str], float | None] = {}
    for bloc in re.split(r"\(footprint ", text)[1:]:
        ref = re.search(r'\(property "Reference" "([^"]+)"', bloc) or             re.search(r'reference "([^"]+)"', bloc)
        if not ref:
            continue
        for chunk in re.split(r"\(pad ", bloc)[1:]:
            num = re.match(r'"([^"]+)"', chunk)
            at = re.search(r"\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", chunk)
            if num and at:
                angles[(ref.group(1), num.group(1))] = (
                    float(at.group(3)) if at.group(3) else None)
    return angles


def _outside_outline_refs(pcb_path: Path) -> int:
    """Compte et journalise les footprints restés hors du contour.

    Contrôle d'observabilité, dernière étape du placement : s'il
    reste quoi que ce soit, la réparation a échoué et le routage sera plafonné
    — ``kct route`` refusera même le board (« placement invalid »). Ne modifie
    jamais rien.
    """
    hors = _off_board_refs(pcb_path)
    for ref in hors:
        logger.warning(
            "auto_place: %s hors contour selon PlacementAnalyzer ; ses nets "
            "seront INROUTABLES et kct route refusera le board", ref)
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


# Part de la surface de carte au-dela de laquelle un boitier est DOMINANT.
# 12 % : un module ESP32-WROOM (41 x 48 mm) sur une carte de 93 x 70 en
# occupe 30, un LQFP-48 (9 x 9) sur la meme carte en occupe 1.
_PART_DOMINANTE = 0.12


def _encombrement_fp(fp) -> tuple:
    """Etendue (largeur, hauteur) d un footprint — COURTYARD d abord.

    ⚠️ Le corps d un boitier deborde largement ses pastilles. Mesure du
    2026-08-27, ESP32-WROOM :

        etendue des pastilles : 17,5 x 17,8 mm
        courtyard reel        : 41,3 x 48,1 mm

    En prenant les pastilles, `_ecarter_des_dominants` poussait les passifs hors
    d une boite DEUX FOIS trop petite : ils retombaient sur le module, et les
    `courtyards_overlap` subsistaient jusque dans le meilleur de trois tirages.

    Le courtyard est la surface que le fabricant reserve, et c est celle que le
    DRC compare. On ne retient QUE lui : la serigraphie deborde souvent, et la
    prendre gonflerait l emprise sans raison.

    Sans courtyard declare, on retombe sur les pastilles — rendre 0 ferait
    perdre toute protection.
    """
    x0, y0, x1, y1 = _boite_locale_fp(fp)
    return x1 - x0, y1 - y0


def _boite_locale_fp(fp) -> tuple:
    """Boite du footprint DANS SON REPERE : ``(x0, y0, x1, y1)``.

    ⚠️ `_encombrement_fp` n en rendait que la TAILLE, et jetait le decalage.
    Or c est le decalage qui manquait. Courtyard reel de l ESP32-WROOM, lu
    dans un board du banc :

        x local : de -24,00 a +24,00      (centre sur l origine)
        y local : de -30,74 a +10,51      (decale de 10 mm)

    L origine d un module est sur sa pastille 1, pas au milieu de son corps —
    c est vrai de l ESP32, des en-tetes Arduino et des connecteurs Nucleo.
    Raisonner en demi-taille de part et d autre de la position fait donc
    tomber un cote de la couronne EN PLEIN dans le module : cinq
    `courtyards_overlap` mesures le 2026-08-27.

    ⚠️ Pastilles et courtyard sont l un comme l autre en coordonnees LOCALES
    (verifie sur un board reel) : la boite se ramene en absolu en ajoutant
    simplement `fp.position`.
    """
    xs, ys = [], []
    for g in getattr(fp, "graphics", []) or []:
        if str(getattr(g, "layer", "")) not in ("F.CrtYd", "B.CrtYd"):
            continue
        for point in (getattr(g, "start", None), getattr(g, "end", None)):
            if point is None:
                continue
            try:
                xs.append(float(point[0]))
                ys.append(float(point[1]))
            except (TypeError, IndexError, ValueError):
                continue
    if not xs:
        xs = [p.position[0] for p in getattr(fp, "pads", []) or []]
        ys = [p.position[1] for p in getattr(fp, "pads", []) or []]
    if not xs:
        return 0.0, 0.0, 0.0, 0.0
    return min(xs), min(ys), max(xs), max(ys)


def _boitiers_dominants(pcb) -> list:
    """Refs des boitiers occupant une part notable de la carte.

    ⚠️ Le critere porte sur la SURFACE RELATIVE, pas sur le nombre de broches.
    `_dense_part_refs` (>= 16 pads) repond a une autre question — le canal
    d escape — et ne convient pas ici : un LQFP-48 de 9 x 9 mm sur une carte
    de 100 mm n a rien de dominant, et l ancrer priverait l optimiseur d un
    degre de liberte utile.

    Mesure du 2026-08-26 : meme sur une carte de 93 x 70 mm ou son courtyard
    de 41 x 48 tient largement, l ESP32-WROOM recevait 9 chevauchements —
    `OptimizationWorkflow` empile les passifs par-dessus et `PlacementFixer`
    n y parvient pas, deplacer un boitier de 2000 mm2 demandant de deplacer
    tout le reste.

    Sans taille de carte connue, « dominant » n a pas de sens : on ne devine
    pas, on rend une liste vide.
    """
    try:
        l_carte, h_carte = pcb.board_size
    except Exception:
        return []
    aire = float(l_carte) * float(h_carte)
    if aire <= 0:
        return []
    dominants = []
    for fp in pcb.footprints:
        if not fp.reference:
            continue
        l, h = _encombrement_fp(fp)
        if l * h >= _PART_DOMINANTE * aire:
            dominants.append(fp.reference)
    return dominants


# Marge ajoutee quand on pousse un mobile hors d un boitier ancre : de quoi
# loger sa propre demi-taille plus un degagement de routage.
_MARGE_ECARTEMENT_MM = 2.0


def _placer_en_couronne(pcb, dominants: list) -> int:
    """Place le boitier dominant au centre et les autres en couronne autour.

    ⚠️ Mesure du 2026-08-27, ESP32 du banc : les QUATRE tirages de
    `OptimizationWorkflow` produisent des conflits de courtyard. Ce n est pas
    de la malchance, c est structurel — un genetique optimise une longueur de
    fil totale qu un boitier de 2000 mm2 domine entierement, et les 19 passifs
    deviennent du bruit dans sa fonction de cout.

    Un concepteur ne procede pas ainsi : il pose le module, puis dispose les
    passifs autour. Deterministe, sans tirage, donc REPRODUCTIBLE — c est tout
    l interet face au genetique.

    ⚠️ Ne remplace PAS l optimiseur. Sur une carte sans boitier dominant, le
    genetique fait mieux : il groupe les decouplages avec leur IC, ce qu une
    grille ignore. On ne bascule que sur le cas ou il echoue.
    """
    try:
        l_carte, h_carte = (float(v) for v in pcb.board_size)
    except Exception:
        return 0
    if l_carte <= 0 or h_carte <= 0:
        return 0

    cx, cy = l_carte / 2.0, h_carte / 2.0
    modules = [f for f in pcb.footprints if f.reference in set(dominants)]
    autres = [f for f in pcb.footprints
              if f.reference and f.reference not in set(dominants)]
    if not modules:
        return 0

    principal = modules[0]
    # ⚠️ On centre le CORPS, pas l ORIGINE. L origine d un module est sur sa
    # pastille 1 ; la poser au milieu de la carte y decale le corps d autant.
    bx0, by0, bx1, by1 = _boite_locale_fp(principal)
    principal.position = (cx - (bx0 + bx1) / 2.0, cy - (by0 + by1) / 2.0)
    px, py = principal.position
    # Boite ABSOLUE du corps : c est elle que la couronne doit contourner.
    mx0, my0 = px + bx0, py + by0
    mx1, my1 = px + bx1, py + by1

    # Anneaux successifs autour de cette boite. Le pas vaut la plus grande
    # piece a loger, pour qu aucune ne deborde sur sa voisine.
    pas = max([max(_encombrement_fp(f)) for f in autres] or [2.0]) + 1.5
    places, anneau = 0, 1
    restants = list(autres)
    while restants and anneau < 40:
        marge = anneau * pas
        gx0, gy0 = mx0 - marge, my0 - marge
        gx1, gy1 = mx1 + marge, my1 + marge
        # Positions sur le rectangle de cet anneau, dans un ordre stable.
        cases = []
        nx = max(2, int((gx1 - gx0) / pas))
        ny = max(2, int((gy1 - gy0) / pas))
        for i in range(nx + 1):
            x = gx0 + i * (gx1 - gx0) / nx
            cases.append((x, gy0))
            cases.append((x, gy1))
        for j in range(1, ny):
            y = gy0 + j * (gy1 - gy0) / ny
            cases.append((gx0, y))
            cases.append((gx1, y))
        for x, y in cases:
            if not restants:
                break
            fx0, fy0, fx1, fy1 = _boite_locale_fp(restants[0])
            # Hors contour : un passif dehors est inroutable. La boite du
            # passif, pas sa demi-taille — meme raison que pour le module.
            if not (0.0 <= x + fx0 and x + fx1 <= l_carte
                    and 0.0 <= y + fy0 and y + fy1 <= h_carte):
                continue
            restants.pop(0).position = (x, y)
            places += 1
        anneau += 1

    if restants:
        logger.warning(
            "auto_place: %d composant(s) sans place en couronne — laisses ou ils sont",
            len(restants))
    return places

def _ecarter_dans_le_fichier(pcb_path: Path, dominants: list) -> int:
    """Recharge le board, ecarte les mobiles des ancres, et resauve.

    Le raffinement CMA-ES et l Inspecteur travaillent sur le FICHIER : il
    faut donc repasser dessus, pas sur l objet en memoire d avant.
    """
    try:
        from kicad_tools.schema.pcb import PCB

        pcb = PCB.load(str(pcb_path))
        n = _ecarter_des_dominants(pcb, dominants)
        if n:
            pcb.save(str(pcb_path))
            logger.info(
                "auto_place: %d composant(s) ecarte(s) de l emprise des "
                "boitiers dominants (apres raffinement)", n)
        return n
    except Exception as exc:
        logger.warning("auto_place: ecartement final impossible (%s)", exc)
        return 0


def _ecarter_des_dominants(pcb, dominants: list) -> int:
    """Pousse les composants MOBILES hors de l emprise des boitiers ancres.

    ⚠️ Mesure du 2026-08-27, ESP32 du banc : apres avoir centre et ancre le
    module, il restait trois `courtyards_overlap`, tous entre U1 et un passif
    pose PAR-DESSUS. `PlacementFixer` ne les ecarte pas — sa reparation locale
    deplace de proche en proche, et un boitier de 2000 mm2 ne lui laisse aucun
    voisinage libre ou glisser.

    Un composant ancre occupe une surface INTERDITE aux autres. On pousse donc
    chaque mobile dans la direction qui l en sort le plus vite.

    ⚠️ On ne deplace QUE les mobiles : pousser un ancre annulerait l ancrage,
    et deux ancres qui se chevauchent relevent de
    `_position_libre_pour_ancrage`.

    ⚠️ Le composant pousse reste DANS la carte. Le sortir du contour
    echangerait un chevauchement contre un defaut pire — ses nets seraient
    inroutables.
    """
    try:
        l_carte, h_carte = (float(v) for v in pcb.board_size)
    except Exception:
        l_carte = h_carte = 0.0
    fixes = set(dominants)
    # ⚠️ Des BOITES absolues, pas des centres et des demi-tailles. L origine
    # d un module est sur sa pastille 1 : `position ± demi-taille` rend une
    # emprise trop PETITE du cote long et trop GRANDE du cote court. Sur le
    # courtyard de l ESP32, decale de 10 mm, un passif pose en plein dans le
    # module tombait hors de cette emprise fausse et n etait pas ecarte.
    boites = []
    for ref in dominants:
        fp = next((f for f in pcb.footprints if f.reference == ref), None)
        if fp is None:
            continue
        bx0, by0, bx1, by1 = _boite_locale_fp(fp)
        px, py = fp.position
        boites.append((px + bx0, py + by0, px + bx1, py + by1))
    if not boites:
        return 0

    ecartes = 0
    for fp in pcb.footprints:
        if not fp.reference or fp.reference in fixes:
            continue
        x, y = fp.position
        # Le mobile n est pas un POINT non plus : sa propre boite compte.
        fx0, fy0, fx1, fy1 = _boite_locale_fp(fp)
        for mx0, my0, mx1, my1 in boites:
            if (x + fx1 <= mx0 or mx1 <= x + fx0
                    or y + fy1 <= my0 or my1 <= y + fy0):
                continue  # deja dehors, son courtyard compris
            # Sortir par le cote le plus proche : c est le trajet le plus court,
            # donc celui qui derange le moins le reste du placement. On raisonne
            # en DEPLACEMENT, seul moyen d etre juste sur une boite decalee.
            m = _MARGE_ECARTEMENT_MM
            sorties = [
                (mx0 - m - (x + fx1), lambda d: (x + d, y)),   # vers la gauche
                (mx1 + m - (x + fx0), lambda d: (x + d, y)),   # vers la droite
                (my0 - m - (y + fy1), lambda d: (x, y + d)),   # vers le haut
                (my1 + m - (y + fy0), lambda d: (x, y + d)),   # vers le bas
            ]
            sorties.sort(key=lambda s: abs(s[0]))
            for delta, deplacer in sorties:
                nx, ny = deplacer(delta)
                # ⚠️ Le contour se verifie sur la BOITE, pas sur la position :
                # un composant pousse le corps dehors est inroutable — le
                # defaut meme que cet ecartement dit vouloir eviter.
                if l_carte > 0 and not (0.0 <= nx + fx0 and nx + fx1 <= l_carte
                                        and 0.0 <= ny + fy0 and ny + fy1 <= h_carte):
                    continue
                fp.position = (nx, ny)
                ecartes += 1
                break
            break
    return ecartes

def _centrer(pcb, refs: list) -> None:
    """Pose les refs au centre de la carte, en les ecartant les unes des autres.

    ⚠️ Ancrer un boitier LA OU `gen_pcb` l a laisse figerait un mauvais
    placement — la grille de depart n a aucune intention. Un module dominant
    va au milieu, et les passifs s organisent autour : c est ce que fait un
    concepteur.
    """
    try:
        l_carte, h_carte = pcb.board_size
    except Exception:
        return
    cx, cy = float(l_carte) / 2.0, float(h_carte) / 2.0
    for i, ref in enumerate(refs):
        fp = next((f for f in pcb.footprints if f.reference == ref), None)
        if fp is None:
            continue
        # ⚠️ Le CORPS au centre, pas l ORIGINE. L origine d un module est sur
        # sa pastille 1 : centrer l origine decale le corps de tout le
        # decalage du courtyard — 10 mm sur l ESP32-WROOM.
        x0, y0, x1, y1 = _boite_locale_fp(fp)
        l = x1 - x0
        # Plusieurs dominants : on les decale de leur propre largeur.
        fp.position = (cx + i * (l + 5.0) - (x0 + x1) / 2.0, cy - (y0 + y1) / 2.0)

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


# Tirages de placement avant de renoncer. Le placement coute 2 a 4 minutes,
# le routage 25 : re-tirer un placement casse est DIX FOIS moins cher que
# router un board que le DRC refusera. Borne, pour qu une carte reellement
# impossible ne bloque pas le pipeline.
_MAX_TIRAGES_PLACEMENT = 4


def _dominants_du_b64(kicad_pcb_b64: str) -> list:
    """Boitiers dominants du board RECU, avant tout placement.

    Sert a decider du nombre de tirages : la reponse doit etre connue AVANT de
    payer dix minutes de genetique. Rend une liste vide si le board est
    illisible — on retombe alors sur la serie complete, jamais sur un raccourci
    decide par une erreur.
    """
    import base64 as _b64

    try:
        from kicad_tools.schema.pcb import PCB

        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "b.kicad_pcb"
            f.write_bytes(_b64.b64decode(kicad_pcb_b64))
            return _boitiers_dominants(PCB.load(str(f)))
    except Exception as exc:
        logger.debug("dominants non lisibles avant placement (%s)", exc)
        return []


def _tirages_utiles(dominants: list) -> int:
    """Nombre de tirages du genetique qui vaut la peine d etre paye.

    ⚠️ Chronologie mesuree le 2026-08-27 sur `arduino-uno`, 35 composants :

        19:27:11  tirage 1 demarre
        19:27:33  tirage 1 fini          22 s de travail journalise
        19:37:15  tirage 2 demarre       9 min 42 de SILENCE entre les deux

    Le silence est `OptimizationWorkflow`, qui ne journalise qu a la fin. Son
    budget est FIXE — 100 generations x 50 individus, plus 1000 iterations de
    raffinement — et ne diminue pas pour une carte simple.

    Or ces tirages ne divergent pas quand un boitier domine : 1 et 1 sur
    l Arduino, 17/16/16/22 sur l ESP32. L echec est STRUCTUREL, comme le dit
    deja `_placer_en_couronne` — le genetique optimise une longueur de fil que
    le boitier ecrase, et les passifs deviennent du bruit dans sa fonction de
    cout. On payait trente minutes pour quatre fois le meme echec, avant que la
    couronne deterministe ne reprenne la main en 0,1 s.

    ⚠️ Sans boitier dominant, on garde la serie complete : la variance est
    alors reelle (8/0/3/0/5 conflits mesures sur le board STM32) et le
    genetique est le bon outil. On ne reduit que la ou l on a mesure que les
    tirages n apportent rien.

    Garde : tests/test_tirages_selon_le_cas.py.
    """
    return 1 if dominants else _MAX_TIRAGES_PLACEMENT


def auto_place(kicad_pcb_b64: str, board_width_mm: float,
               board_height_mm: float) -> dict:
    """Place, et RE-TIRE tant que des conflits subsistent.

    ⚠️ `OptimizationWorkflow` n a pas de seed fixe. Mesure du 2026-08-27 sur
    le meme board ESP32, sans qu une ligne change :

        tirage A : 0 conflit     tirage B : 13 conflits

    Le second partait quand meme au routage — 25 minutes — pour produire un
    board que le DRC refusait de toute facon.

    On garde le MEILLEUR, pas le dernier : un tirage tardif peut etre pire.
    """
    meilleur = None
    tirages = _tirages_utiles(_dominants_du_b64(kicad_pcb_b64))
    for essai in range(tirages):
        r = _auto_place_une_fois(kicad_pcb_b64, board_width_mm, board_height_mm)
        n_conflits = r.get("conflits_restants", 0)
        if meilleur is None or n_conflits < meilleur.get("conflits_restants", 10**6):
            meilleur = r
        if n_conflits == 0:
            if essai:
                logger.info("auto_place: placement propre au tirage %d", essai + 1)
            break
        logger.warning(
            "auto_place: %d conflit(s) au tirage %d/%d — on re-tire plutot que "
            "de router un board casse", n_conflits, essai + 1, tirages)
    if meilleur.get("conflits_restants"):
        # ⚠️ L optimiseur a echoue a TOUS ses tirages : ce n est pas de la
        # malchance, c est structurel. Mesure du 2026-08-27 sur l ESP32 —
        # quatre tirages, quatre echecs. Un genetique optimise une longueur
        # de fil qu un boitier dominant ecrase ; les passifs deviennent du
        # bruit dans sa fonction de cout.
        #
        # On bascule alors sur un placement DETERMINISTE — module au centre,
        # passifs en couronne — qui ne depend d aucun tirage.
        secours = _couronne_de_secours(kicad_pcb_b64, meilleur)
        if secours is not None:
            return secours
        logger.error(
            "auto_place: %d conflit(s) apres %d tirages — board livre en l etat",
            meilleur["conflits_restants"], tirages)
    return meilleur


def _couronne_de_secours(kicad_pcb_b64: str, meilleur: dict):
    """Placement deterministe, essaye quand l optimiseur a echoue partout.

    ⚠️ Rend None si la couronne ne fait pas MIEUX. Elle ignore les grappes
    fonctionnelles que le genetique sait grouper — la preferer sans gain
    serait une regression.
    """
    import base64 as _b64

    try:
        from kicad_tools.schema.pcb import PCB

        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "b.kicad_pcb"
            f.write_bytes(_b64.b64decode(kicad_pcb_b64))
            pcb = PCB.load(str(f))
            dominants = _boitiers_dominants(pcb)
            if not dominants:
                return None
            _placer_en_couronne(pcb, dominants)
            pcb.save(str(f))
            _resolve_remaining_conflicts(f, dominants)
            _rendre_lisible(f)
            n = _compter_conflits_erreur(f)
            if n >= meilleur.get("conflits_restants", 10**6):
                logger.info(
                    "auto_place: couronne deterministe %d conflit(s) — pas mieux "
                    "que l optimiseur (%d), on garde l optimiseur",
                    n, meilleur.get("conflits_restants"))
                return None
            logger.info(
                "auto_place: couronne deterministe retenue — %d conflit(s) "
                "contre %d pour l optimiseur", n, meilleur.get("conflits_restants"))
            fps = PCB.load(str(f)).footprints
            return {
                "kicad_pcb_b64": _b64.b64encode(f.read_bytes()).decode(),
                "placed_count": len(fps),
                "conflits_restants": n,
                "positions": [
                    {"ref": fp.reference, "x_mm": fp.position[0],
                     "y_mm": fp.position[1]}
                    for fp in fps if fp.reference
                ],
            }
    except Exception as exc:
        logger.warning("auto_place: couronne de secours impossible (%s)", exc)
        return None


def _auto_place_une_fois(kicad_pcb_b64: str, board_width_mm: float,
                         board_height_mm: float) -> dict:
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
        # ⚠️ Les boitiers DOMINANTS rejoignent les ancrages, apres avoir ete
        # centres. Un module qui occupe un quart de la carte ne se place pas
        # par tirage genetique : mesure du 2026-08-26, l ESP32-WROOM recevait
        # 9 chevauchements de courtyard meme avec la place necessaire.
        dominants = _boitiers_dominants(pcb)
        if dominants:
            logger.info("auto_place: boitier(s) dominant(s) centre(s) et ancre(s) : %s",
                        ", ".join(dominants))
            _centrer(pcb, dominants)
            conn = conn + [r for r in dominants if r not in conn]
        _clamp_fixed_refs_to_outline(pcb, conn, exempts=dominants)

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
        # Correctif B — normalisation du repère APRÈS write_to_pcb().
        # Sans lui, l'Architecte livre 15-16 composants sur 17 hors carte
        # (mesuré 3 tirages sur 3, 2026-07-31), et tout ce qui suit — Inspecteur,
        # CMA-ES, halo — travaille sur un board déjà faux.
        n_norm = _normalize_origin_after_write(pcb, skip=conn)

        # ⚠️ Ecarter les MOBILES poses sur un boitier ancre. L optimiseur les
        # y depose, et `PlacementFixer` ne les en sort pas : sa reparation
        # locale deplace de proche en proche, et un boitier de 2000 mm2 ne
        # lui laisse aucun voisinage libre. Mesure du 2026-08-27 : trois
        # `courtyards_overlap` residuels sur l ESP32, tous contre U1.
        if dominants:
            n_ecartes = _ecarter_des_dominants(pcb, dominants)
            if n_ecartes:
                logger.info(
                    "auto_place: %d composant(s) ecarte(s) de l emprise des "
                    "boitiers dominants", n_ecartes)

        logger.info(
            "auto_place natif (hybrid+cluster): %d composants écrits, wirelength=%.1fmm, %d connecteurs ancrés%s",
            updated,
            getattr(result, "wire_length_mm", 0.0) or getattr(result, "wire_length", 0.0),
            len(conn),
            f", {n_norm} repère(s) normalisé(s)" if n_norm else "",
        )

        pcb.save(str(out))

        # write_to_pcb() peut écrire en sheet-absolute selon la version de
        # kicad-tools (régression 0.18.0, issue #72) : on ramène en repère board
        # AVANT toute analyse de conflits, sinon l'Inspecteur travaille sur des
        # positions fausses et le routeur refuse le placement.
        _normalize_to_board_frame(out)

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
                # ⚠️ Journaliser le SUCCÈS, pas seulement les échecs.
                #
                # Toutes les autres branches du Géomètre écrivent un warning ou
                # une exception ; le succès, lui, était MUET. Un succès
                # silencieux est indistinguable d'une étape jamais exécutée —
                # et c'est exactement la condition qui a masqué pendant des
                # semaines le fait que le Géomètre ne tournait JAMAIS en
                # production (`signal.signal` hors thread principal).
                #
                # Le verdict seul ne suffit pas : sans le déplacement mesuré, on
                # ne peut pas distinguer un micro-raffinement d'une dérive.
                # Garde : tests/test_placement_geometre_observable.py.
                logger.info(
                    _LOG_GEOMETRE_OK,
                    refine.get("elapsed_s", 0.0), max_disp, _CMAES_MAX_DISPLACEMENT_MM,
                )
        else:
            # Sauté ou indisponible : le board reste celui de l'Architecte, ce
            # qui est valide — mais il faut le DIRE plutôt que le laisser
            # déduire d'une absence de trace.
            logger.info(_LOG_GEOMETRE_SAUTE, refine.get("elapsed_s", 0.0))

        # ── Brique 1 : halo d'escape — dégage le canal de routage des boîtiers
        # denses (fine-pitch) en écartant leurs voisins mobiles. No-op sur une
        # carte sans composant dense. Dernière étape placement : ni le GA ni le
        # CMA-ES ne peuvent re-tasser les voisins ensuite.
        n_halo = _reserve_escape_halos(out, conn)
        if n_halo:
            logger.info(
                "auto_place: halo d'escape — %d voisin(s) écarté(s) du périmètre "
                "des composants denses (fine-pitch)", n_halo)

        # ── Brique 2 : snap bypass — APRES le Geometre et APRES le halo.
        #
        # Le GA laisse les decouplages a 13-28 mm de leur IC (mesure du
        # 2026-06-18) : sa fonction de cout est une longueur de fil globale
        # que les rails GND dominent, et aucun reglage ne l en fera devier.
        # Le CMA-ES en reprend 2-3 mm. Le reste est une REGLE, pas un
        # optimum : `FunctionalCluster.max_distance_mm`, applique par saut.
        #
        # ⚠️ L ordre est contraint des deux cotes. Avant le CMA-ES, le snap
        # serait defait — l optimiseur renverrait la capa au loin. Avant le
        # halo, il serait defait aussi — le halo ecarte les voisins des
        # boitiers fine-pitch. Il vient donc en dernier, et connait le halo :
        # sur une ancre dense il garde les 5 mm du canal d escape au lieu de
        # le reboucher.
        #
        # ⚠️ La distance se mesure entre les CORPS. L origine d un module est
        # sur sa pastille 1 (courtyard ESP32-WROOM : y de -30,74 a +10,51) ;
        # snapper « a 3 mm de l origine » poserait la capa DANS le module.
        pcb_snap = PCB.load(str(out))
        n_snap = snap_cluster_members(
            pcb_snap, figes=conn, denses=_dense_part_refs(pcb_snap))
        if n_snap:
            pcb_snap.save(str(out))
            _normalize_to_board_frame(out)
            logger.info(
                "auto_place: snap bypass — %d membre(s) de cluster ramene(s) "
                "a portee de leur ancre", n_snap)
            # L Inspecteur est le filet du snap : un saut peut poser la capa
            # sur un pad de l ancre. Il ecarte, le membre reste pres.
            _resolve_remaining_conflicts(out, conn)

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
        # ── Angles de pads : le writer en ajoute un que la source ne déclare
        # pas, ce qui fait basculer le grand axe des pads et les fait se
        # recouvrir. 204 erreurs DRC mesurées sur un board sans une seule
        # piste ; 0 après restauration (cf. restore_pad_angles).
        # AVANT le filet hors-carte, dont la détection est géométrique : elle
        # lirait sinon l'encombrement de boîtiers aux pads mal orientés.
        texte_final, n_pads = restore_pad_angles(
            src.read_text(encoding="utf-8", errors="replace"),
            out.read_text(encoding="utf-8", errors="replace"))
        if n_pads:
            out.write_text(texte_final, encoding="utf-8")
            logger.info(
                "auto_place: angle restauré sur %d pad(s) — le writer en ajoute "
                "un que la source ne déclare pas, et les formes se recouvrent",
                n_pads)

        # ── Filet hors-carte. Le GA peut parquer des composants au-delà du
        # bord : leurs nets deviennent inroutables et `kct route` refuse le
        # board (« placement invalid »). L'Inspecteur ne peut pas le résoudre —
        # PlacementFixer n'a aucun traitement de OFF_BOARD. On répare, puis on
        # le relance en ANCRANT les refs réparées, sinon il les ressort.
        repares = _repair_off_board(out, conn)
        if repares:
            logger.warning(
                "auto_place: %d composant(s) hors carte réparé(s) (%s)",
                len(repares), ", ".join(repares))
            _resolve_remaining_conflicts(out, conn + repares)

        # ⚠️ Repasser l ecartement APRES le raffinement et l Inspecteur : le
        # CMA-ES ne connait pas nos ancrages dominants et peut y ramener des
        # mobiles. Un ecartement fait AVANT eux ne survit pas.
        if dominants:
            _ecarter_dans_le_fichier(out, dominants)

        n_hors = _outside_outline_refs(out)
        if n_hors:
            logger.error(
                "auto_place: %d composant(s) LIVRÉ(S) HORS CONTOUR — leurs nets "
                "sont inroutables et kct route refusera le board ; réparation "
                "non implémentée", n_hors)

        # ⚠️ Compter ce qu on n a PAS su reparer, et le dire. Mesure du
        # 2026-08-26, ESP32 du banc : 9 `courtyards_overlap`, 8
        # `shorting_items` et 2 `pth_inside_courtyard` livres SANS un mot.
        # L appelant routait un board deja casse et decouvrait les degats
        # au DRC, trois etapes plus loin, sans pouvoir les imputer.
        #
        # On ne LEVE pas : un board imparfait vaut mieux qu aucun board, et
        # l orchestrateur sait deja re-tirer. Mais on ne ment plus par
        # omission.
        _rendre_lisible(out)
        conflits_restants = _compter_conflits_erreur(out)
        if conflits_restants:
            logger.error(
                "auto_place: %d conflit(s) de placement NON RESOLU(S) — le "
                "board est livre en l etat, le DRC les signalera",
                conflits_restants)

        footprints = PCB.load(str(out)).footprints
        return {
            "kicad_pcb_b64": base64.b64encode(out.read_bytes()).decode(),
            "placed_count": len(footprints),
            "conflits_restants": conflits_restants,
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
