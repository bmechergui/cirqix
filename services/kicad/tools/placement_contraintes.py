"""Les contraintes de groupement que le placement n'a jamais reçues.

## Le reproche, chiffré

Mesure du 2026-09-08 sur les onze cartes du banc. Une LED et sa résistance
série partagent un net qui ne touche qu'**elles deux** — la paire la plus
serrable qui existe sur une carte :

    carte-09   D10 ↔ R10   87,1 mm
    carte-10   D1  ↔ R1    71,6 mm
    carte-08   D12 ↔ R12   67,6 mm

Moyenne par carte : 5 mm à 5 composants, **45 mm à 70**. La dispersion suit la
taille de la carte — le GA disperse d'autant plus qu'il a de place.

## Pourquoi le snap existant ne les voyait pas

`tools/placement_bypass.py` ne traite que les clusters rendus par
`detect_functional_clusters` : POWER, TIMING, DRIVER, INTERFACE. Une paire
résistance-LED n'appartient à AUCUN de ces types. Elle n'est jamais regardée,
donc jamais serrée. Le snap fonctionne ; il ne regarde pas là.

## Le levier était natif, et personne ne l'appelait

⚠️ `OptimizationWorkflow` — celui que nous appelons déjà — accepte un argument
`constraints=[GroupingConstraint]` (`optim/workflow.py:244`) qu'il transmet à
`optimizer.add_grouping_constraints` (ligne 333). Ces contraintes ne sont pas
décoratives : `PlacementOptimizer.compute_constraint_forces`
(`optim/placement.py:1297`) produit des forces de rappel intégrées à l'étape 5
du calcul de forces (ligne 1783). Nous ne l'avons jamais passé.

De même `WorkflowConfig.grid` (`optim/workflow.py:187`, défaut `0.0` = pas de
snap) déclenche `optimizer.snap_to_grid(grid, 90.0)` en fin d'optimisation
(ligne 348). Jamais passé non plus — d'où des positions au centième de
millimètre et **0 composant sur 55** aligné sur `nucleo-f401`.

C'est la troisième fois que ce dépôt paie la même erreur, après
`FunctionalCluster.max_distance_mm` et `anchor_pin` : **le levier existait,
public, calculé à chaque appel, et personne ne lisait ce que la lib rendait.**

## Ce que ce module fait, et ce qu'il ne fait pas

Il CONSTRUIT des `GroupingConstraint` à partir de la netlist. Il n'invente
aucune heuristique de valeur ni de nom : un net à deux bornes est un fait
topologique, pas une devinette. La règle de ce dépôt — vérifier le natif avant
d'écrire — est respectée : la détection est arithmétique, la contrainte et son
application sont natives.

⚠️ Ce sont des FORCES, pas des contraintes dures. Le dépôt mesure déjà que les
ressorts de cluster (~50) sont dominés par les rails GND (~75) : une contrainte
peut donc être perdue. Elle ne remplace pas le snap dur de fin de chaîne, elle
le précède et lui laisse moins à rattraper.

⚠️ On ne contraint QUE les paires à deux boîtiers. Un net à trois bornes ou
plus n'a pas de « bonne » distance évidente, et le forcer reviendrait à
inventer une intention que la netlist n'exprime pas.

⚠️ Les nets d'ALIMENTATION sont exclus, même à deux bornes. `GND` et `+3V3`
relient tout à tout : les traiter comme une adjacence tirerait la carte entière
vers un point. `is_power_net` de `kicad-tools` fait cette détection — on ne la
réécrit pas.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Rayon de rappel d'une paire à deux bornes, en millimètres.
#
# ⚠️ SEUIL CHIFFRÉ QUI CHANGE LE COMPORTEMENT LIVRÉ — décision produit, à
# valider par l'utilisateur avant d'être considérée comme acquise.
#
# La valeur se déduit de ce qu'un ingénieur fait à la main : une résistance
# série et sa LED se posent côte à côte, corps à corps, soit 2 à 3 mm entre
# ORIGINES pour des boîtiers 0603/0805. On prend 5 mm, qui laisse au routeur
# la place de passer entre les deux sans annuler l'intention.
#
# Ce n'est pas une distance de courtyard : `max_distance` de kicad-tools se
# mesure entre positions de composants, pas entre corps. Le snap dur, lui,
# mesure entre CORPS (`_boite_locale_fp`) — les deux ne sont pas comparables,
# et confondre les deux est une erreur déjà commise dans ce dépôt.
# ⚠️ Pilotable par `CIRQIX_RAYON_PAIRE_MM` — une valeur NULLE desactive la
# contrainte. C est ce qui permet le TEMOIN : sans moyen de desarmer une
# regle sans editer le code, on ne peut pas prouver qu elle est en cause,
# et ce depot a deja failli reverter un correctif innocent faute de temoin.
_RAYON_PAIRE_MM = 5.0


def _rayon_paire_mm() -> float:
    """Relu A CHAQUE APPEL — voir `tools/reglages_banc`."""
    from tools.reglages_banc import reglage
    return float(reglage("rayon_paire_mm", _RAYON_PAIRE_MM))

# Au-dela de ce nombre de pastilles, un boitier est un NOEUD du circuit et non
# un element de chaine : on ne le contraint pas.
#
# 4 couvre les passifs (2), les diodes (2), les quartz (2 a 4) et les reseaux
# a deux elements. Un LQFP-48 en a 48, un connecteur 4 a 40 — aucun des deux
# n a de « bonne » distance a un voisin en particulier.
_PADS_MAX_PAIRE = 4


def _est_alimentation(nom: str) -> bool:
    """Vrai si ce net est un rail d'alimentation — détection NATIVE."""
    try:
        from kicad_tools.explain.mistakes import is_power_net
        return bool(is_power_net(nom))
    except Exception:
        # ⚠️ Un repli qui ratisse LARGE : rater un rail ferait tirer la carte
        # entière vers un point, alors qu'écarter un net de signal ne coûte
        # qu'une contrainte non posée. On échoue du côté qui ne casse rien.
        h = nom.upper()
        return (h.startswith(("+", "-", "VCC", "VDD", "VSS", "VIN", "VBUS"))
                or h in {"GND", "AGND", "DGND", "PGND", "GROUND"})


def paires_a_deux_bornes(connexions: list[Any]) -> list[tuple[str, str, str]]:
    """Les nets qui ne touchent QUE deux boîtiers, hors alimentation.

    Rend une liste de `(nom_du_net, ref_a, ref_b)`, `ref_a < ref_b`.

    ⚠️ On compte les BOÎTIERS, pas les broches : un net reliant `R1.1` à `R1.2`
    n'est pas une adjacence, c'est un composant bouclé sur lui-même.
    """
    paires: list[tuple[str, str, str]] = []
    vues: set[tuple[str, str]] = set()
    for net in connexions or []:
        nom = getattr(net, "name", None)
        if not nom or _est_alimentation(nom):
            continue
        refs = sorted({getattr(p, "ref", None) for p in getattr(net, "pins", [])
                       if getattr(p, "ref", None)})
        if len(refs) != 2:
            continue
        cle = (refs[0], refs[1])
        if cle in vues:
            # Deux nets entre les mêmes boîtiers : une seule contrainte suffit,
            # deux ne serreraient pas davantage et fausseraient le compte.
            continue
        vues.add(cle)
        paires.append((nom, refs[0], refs[1]))
    return paires


def contraintes_de_paires(connexions: list[Any],
                          refs_ancrees: list[str] | None = None,
                          rayon_mm: float | None = None) -> list[Any]:
    """Construit les `GroupingConstraint` natives des paires à deux bornes.

    ⚠️ L'ANCRE EST CELLE QUI NE BOUGE PAS. `SpatialConstraint.max_distance`
    prend un `anchor` : si on ancrait sur un composant libre, la contrainte
    serait satisfaite en déplaçant les DEUX, ce qui n'aide en rien. Quand l'un
    des deux est déjà ancré (connecteur, boîtier dominant), c'est lui l'ancre ;
    sinon on prend le premier par ordre alphabétique, qui est stable d'un
    tirage à l'autre — un ancrage instable rendrait le placement irreproductible
    pour une raison sans rapport avec le GA.
    """
    try:
        from kicad_tools.optim.constraints import (GroupingConstraint,
                                                   SpatialConstraint)
    except Exception:
        logger.warning("contraintes de paires indisponibles : kicad_tools.optim."
                       "constraints introuvable — placement non contraint")
        return []

    ancrees = set(refs_ancrees or [])
    out = []
    for nom, a, b in paires_a_deux_bornes(connexions):
        ancre = a if a in ancrees else (b if b in ancrees else a)
        out.append(GroupingConstraint(
            name="paire-%s" % nom,
            members=[a, b],
            constraints=[SpatialConstraint.max_distance(anchor=ancre,
                                                        radius_mm=rayon_mm)],
        ))
    if out:
        logger.info("placement: %d paire(s) a deux bornes contrainte(s) a %.1f mm",
                    len(out), rayon_mm)
    else:
        logger.info("placement: aucune paire a deux bornes a contraindre")
    return out

def paires_du_board(pcb) -> list[tuple[str, str, str]]:
    """Les paires a deux bornes lues sur le BOARD, pas sur le schema.

    ⚠️ LE CODE LIT LE BOARD, donc la regle se calibre sur le board.
    Ce depot a deja paye deux fois d avoir mesure sur une source VOISINE de
    celle que le code utilise : le plancher d echappement calibre sur
    `circuit.json` quand le code lisait le board (43 signaux contre 36), et le
    banc de dogbones calibre sur `expected/` quand le conteneur lit `output/`.

    Et c est aussi plus JUSTE : le board porte ce qui existe reellement, y
    compris les nets qu une etape amont aurait perdus.
    """
    par_net: dict[str, set] = {}
    for fp in getattr(pcb, "footprints", []) or []:
        ref = getattr(fp, "reference", None)
        if not ref:
            continue
        for pad in getattr(fp, "pads", []) or []:
            nom = getattr(pad, "net_name", None)
            if not nom or nom in ("", "~"):
                continue
            par_net.setdefault(nom, set()).add(ref)

    # ⚠️ UN CONCENTRATEUR NE PEUT PAS ETRE ADJACENT A TOUT LE MONDE.
    # Premiere version de cette regle, mesuree sur `carte-09` : 38 paires,
    # dont 20 de la forme `R<n>-U1`. Contraindre le MCU a 5 mm de VINGT
    # resistances est insatisfiable, et le solveur aurait arbitre au hasard
    # entre des ressorts qui se contredisent — un placement pire, pas meilleur.
    #
    # La regle retenue est TOPOLOGIQUE, pas nominale : on ne contraint que
    # deux petits boitiers en serie. Un boitier a plus de `_PADS_MAX_PAIRE`
    # pastilles est un noeud du circuit, pas un element de chaine.
    #
    # On n ecrit AUCUNE heuristique de valeur ni de prefixe de reference : le
    # nombre de pastilles se lit sur le board, il ne se devine pas.
    pastilles = {getattr(fp, "reference", None): len(getattr(fp, "pads", []) or [])
                 for fp in getattr(pcb, "footprints", []) or []}

    paires, vues = [], set()
    for nom, refs in sorted(par_net.items()):
        if _est_alimentation(nom):
            continue
        if len(refs) != 2:
            continue
        a, b = sorted(refs)
        if (a, b) in vues:
            continue
        if max(pastilles.get(a, 99), pastilles.get(b, 99)) > _PADS_MAX_PAIRE:
            continue
        vues.add((a, b))
        paires.append((nom, a, b))
    return paires


def contraintes_du_board(pcb, refs_ancrees=None, rayon_mm=None):
    """`contraintes_de_paires`, mais alimentee par le board."""
    try:
        from kicad_tools.optim.constraints import (GroupingConstraint,
                                                   SpatialConstraint)
    except Exception:
        logger.warning("contraintes de paires indisponibles : kicad_tools.optim."
                       "constraints introuvable — placement non contraint")
        return []

    if rayon_mm is None:
        rayon_mm = _rayon_paire_mm()
    if rayon_mm <= 0:
        # Temoin : la regle est desarmee, et on le DIT — un silence se
        # confondrait avec « aucune paire trouvee ».
        logger.info("placement: contraintes de paires DESARMEES (rayon=0)")
        return []

    ancrees = set(refs_ancrees or [])
    out = []
    for nom, a, b in paires_du_board(pcb):
        ancre = a if a in ancrees else (b if b in ancrees else a)
        out.append(GroupingConstraint(
            name="paire-%s" % nom,
            members=[a, b],
            constraints=[SpatialConstraint.max_distance(anchor=ancre,
                                                        radius_mm=rayon_mm)],
        ))
    if out:
        logger.info("placement: %d paire(s) a deux bornes contrainte(s) a %.1f mm "
                    "(lues sur le board)", len(out), rayon_mm)
    else:
        logger.info("placement: aucune paire a deux bornes sur ce board")
    return out

def aligner_sur_grille(chemin, pas_mm: float, figes=None) -> int:
    """Arrondit les positions des footprints MOBILES au pas donne.

    Rend le nombre de footprints deplaces. Modifie le fichier en place.

    ⚠️ CETTE ETAPE VIENT EN DERNIER, et c est tout son interet.

    `WorkflowConfig.grid` fait deja un snap natif — mais A LA FIN DE
    L OPTIMISATION, alors que notre chaine enchaine ensuite le Geometre
    (CMA-ES), le halo d escape, le snap des clusters et l Inspecteur. Chacun
    deplace. Mesure du 2026-09-08 sur `carte-09` avec `grid=0.5` transmis :

        grille 0,5 mm   2/62 avant   ->   2/62 apres

    Aucun changement. Le natif avait bien aligne ; les quatre etapes suivantes
    avaient tout defait. C est exactement le piege deja inscrit dans ce depot :
    « l ordre fait partie du correctif, pas de son emballage. »

    ⚠️ On ne touche PAS aux composants figes. Un connecteur est ancre a une
    position choisie, souvent clampee dans le contour : l arrondir pourrait le
    faire sortir.

    ⚠️ L arrondi peut creer un chevauchement — il deplace de moins d un
    demi-pas, mais deux boitiers a la limite peuvent se toucher. L appelant
    repasse l Inspecteur derriere, et revient en arriere si le compte d erreurs
    monte : meme filet que le snap, pour la meme raison.
    """
    import re as _re
    from pathlib import Path
    if pas_mm <= 0:
        return 0

    immobiles = set(figes or ())
    texte = Path(chemin).read_text(encoding="utf-8", errors="replace")
    deplaces = 0
    morceaux, i = [], 0
    while True:
        j = texte.find("(footprint ", i)
        if j < 0:
            morceaux.append(texte[i:])
            break
        morceaux.append(texte[i:j])
        prof, k = 0, j
        while k < len(texte):
            if texte[k] == "(":
                prof += 1
            elif texte[k] == ")":
                prof -= 1
                if prof == 0:
                    break
            k += 1
        bloc = texte[j:k + 1]
        i = k + 1

        # ⚠️ Le `(at ...)` du FOOTPRINT est le premier du bloc ; ceux des
        # pastilles et des textes sont RELATIFS a lui et ne doivent pas bouger.
        ref = _re.search(chr(92) + '(property "Reference" "([^"]+)"', bloc)
        if ref and ref.group(1) in immobiles:
            morceaux.append(bloc)
            continue
        m = _re.search(r'\(at ([-\d.]+) ([-\d.]+)((?:\s+[-\d.]+)?)\)', bloc)
        if not m:
            morceaux.append(bloc)
            continue
        x, y = float(m.group(1)), float(m.group(2))
        nx = round(x / pas_mm) * pas_mm
        ny = round(y / pas_mm) * pas_mm
        if abs(nx - x) < 1e-9 and abs(ny - y) < 1e-9:
            morceaux.append(bloc)
            continue
        remplace = "(at %s %s%s)" % (_fmt(nx), _fmt(ny), m.group(3))
        morceaux.append(bloc[:m.start()] + remplace + bloc[m.end():])
        deplaces += 1

    if deplaces:
        Path(chemin).write_text("".join(morceaux), encoding="utf-8")
        logger.info("placement: %d footprint(s) alignes sur la grille de %.2f mm",
                    deplaces, pas_mm)
    return deplaces


def _fmt(v: float) -> str:
    """Ecrit un nombre comme KiCad : sans zeros inutiles."""
    t = ("%.4f" % v).rstrip("0").rstrip(".")
    return t if t not in ("", "-0") else "0"
