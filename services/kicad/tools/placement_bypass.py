"""Snap bypass — coller les membres d'un cluster fonctionnel a leur ancre.

Etape ③ du placement, entre le Geometre (CMA-ES) et l'Inspecteur.

POURQUOI une etape separee. Le GA minimise une longueur de fil GLOBALE que
les rails d'alimentation dominent : un decouplage tire par GND (ressort ~75)
ne remonte pas vers son IC (ressort ~50). Mesure du 2026-06-18 : les capas
finissent a 13-28 mm de leur MCU. Le CMA-ES ameliore de 2-3 mm, pas plus.
Aucun reglage du GA ne corrige cela — c'est sa fonction de cout qui le veut.

Le snap n'est donc PAS un optimiseur : il applique une REGLE METIER que
`FunctionalCluster.max_distance_mm` exprime deja (5 mm par defaut). On ne
re-detecte rien — la detection reste `detect_functional_clusters`, native.
Le membre est TELEPORTE, pas glisse : c'est ce qui le distingue du CMA-ES.

⚠️ APRES le Geometre, jamais avant. Snapper d'abord puis lancer le CMA-ES
rendrait le snap inutile — l'optimiseur reprend sa fonction de cout et
renvoie la capa au loin.

⚠️ La distance se mesure entre les CORPS, pas entre les origines. L'origine
d'un module est sur sa pastille 1 : le courtyard de l'ESP32-WROOM va de
-30,74 a +10,51 en y. « 3 mm de l'origine » y poserait la capa EN PLEIN
DANS le module. `_boite_locale_fp` porte deja ce decalage ; on s'en sert.

⚠️ Le halo d'escape (`_reserve_escape_halos`, 5 mm autour des boitiers
fine-pitch) tourne AVANT. Ramener une capa dans ce halo reboucherait le
canal de sortie qu'il vient de degager — deux correctifs qui se combattent.
La marge appliquee a une ancre dense est donc celle du halo, pas la marge
courante : les deux regles se composent au lieu de s'annuler.
"""

from __future__ import annotations

import copy
import logging
import math
import re
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

# La detection native est importee au niveau du module pour qu'un test puisse
# la remplacer, et pour que `_clusters_natifs` reste le SEUL point de passage.
try:  # pragma: no cover - depend de l'environnement
    from kicad_tools.optim.clustering import detect_functional_clusters
except Exception:  # pragma: no cover
    detect_functional_clusters = None  # type: ignore[assignment]

# `+3.3V` -> `+3V3`. Ancre aux DEUX bouts : on ne bricole pas un nom quelconque
# qui contiendrait un rail (`VDD_3.3V_SENSE` reste intact).
_RE_RAIL_DECIMAL = re.compile(r"^([+-]?)(\d+)\.(\d+)V$")


def _nom_kicad_du_rail(nom: str) -> str:
    """Rend le nom d'un rail dans la convention KiCad : `+3.3V` -> `+3V3`.

    ⚠️ Mesure du 2026-09-02, `nucleo-f401`. Le motif natif de `kicad-tools`
    est ``r"^(\\+|\\-)?\\d+V"`` : il exige des chiffres IMMEDIATEMENT suivis
    d'un `V`. Notre generateur ecrit `+3.3V`, et le point decimal fait echouer
    le motif — le rail principal de la carte n'etait donc pas reconnu comme
    une alimentation, aucun cluster POWER n'etait construit, et les huit
    condensateurs de decouplage restaient a 24-68 mm du MCU, sans contrainte.

    `+3V3` est LA convention KiCad, concue precisement pour eviter ce point.

    Tout autre nom est rendu tel quel.
    """
    m = _RE_RAIL_DECIMAL.match(nom or "")
    if m is None:
        return nom
    return "%s%sV%s" % (m.group(1), m.group(2), m.group(3))


def _clusters_natifs(composants):
    """`detect_functional_clusters`, sur des noms de rails NORMALISES.

    ⚠️ AUCUNE heuristique maison : la detection reste native, on lui donne
    seulement le nom que KiCad emploie lui-meme. Precedent exact dans le
    projet : `kct_route.py::_VCC_RENAME` renomme deja `+3.3V` en `P3V3` pour
    contourner une classification de la meme lib.

    ⚠️ SUR UNE COPIE, IMPERATIVEMENT. Renommer les pins du modele charge
    renommerait les nets du board ecrit derriere, et un board dont les nets
    changent de nom est un board casse. La normalisation ne sert qu'a la
    DETECTION ; les clusters rendus ne portent que des references.

    Effet mesure sur `nucleo-f401`, meme board :
        sans : 4 clusters, aucun POWER
        avec : 5 clusters — POWER, ancre U1, plafond 3,0 mm, les 8 capas
    """
    if detect_functional_clusters is None:
        return []
    copie = copy.deepcopy(list(composants))
    for c in copie:
        for pin in getattr(c, "pins", None) or []:
            try:
                pin.net_name = _nom_kicad_du_rail(getattr(pin, "net_name", ""))
            except Exception:
                continue  # une pin en lecture seule ne doit pas tuer la detection
    return detect_functional_clusters(copie)

# Degagement laisse entre les deux courtyards apres le saut. Assez pour que
# l'Inspecteur n'ait rien a ecarter dans le cas nominal, assez petit pour que
# « colle » veuille dire quelque chose.
_MARGE_MM: float = 0.3


def _boite_absolue(fp) -> tuple[float, float, float, float]:
    """Boite du footprint en coordonnees board : ``(x0, y0, x1, y1)``."""
    from tools.placement import _boite_locale_fp

    x0, y0, x1, y1 = _boite_locale_fp(fp)
    px, py = fp.position
    return px + x0, py + y0, px + x1, py + y1


# Demi-extension plancher. `_boite_locale_fp` derive la boite des POSITIONS de
# pastilles quand aucun courtyard n est declare — pas de leur taille. La boite
# d un 0402 dont les deux pastilles sont alignees a donc une hauteur NULLE, et
# deux boites plates ne se recouvrent jamais : l evitement devient aveugle et
# le snap empile. Un plancher rend la detection sure sans surestimer un vrai
# courtyard, toujours plus grand que cela.
_DEMI_MINIMUM_MM: float = 0.35


def _centre_et_demi(fp) -> tuple[float, float, float, float]:
    """Centre du CORPS (absolu) et demi-extensions ``(cx, cy, hw, hh)``."""
    x0, y0, x1, y1 = _boite_absolue(fp)
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0,
            max((x1 - x0) / 2.0, _DEMI_MINIMUM_MM),
            max((y1 - y0) / 2.0, _DEMI_MINIMUM_MM))


def _portee(hw: float, hh: float, ux: float, uy: float) -> float:
    """Distance du centre de la boite a son bord, dans la direction ``u``."""
    tx = hw / abs(ux) if abs(ux) > 1e-9 else math.inf
    ty = hh / abs(uy) if abs(uy) > 1e-9 else math.inf
    port = min(tx, ty)
    return 0.0 if port is math.inf else port


def _composants(pcb) -> list:
    """Modele `optim.Component` du board — broches en coordonnees ABSOLUES.

    ⚠️ `fp.pads[].position` est LOCAL (verifie sur un board reel) ; `Pin`
    attend de l'absolu. Sans l'addition, l'index net/broche reste juste mais
    toute lecture geometrique en aval serait fausse.
    """
    from kicad_tools.optim.components import Component, Pin

    comps = []
    for fp in pcb.footprints:
        if not fp.reference:
            continue
        px, py = fp.position
        pins = [
            Pin(
                number=str(getattr(p, "number", "")),
                x=px + p.position[0],
                y=py + p.position[1],
                net=int(getattr(p, "net_number", 0) or 0),
                net_name=str(getattr(p, "net_name", "") or ""),
            )
            for p in (getattr(fp, "pads", None) or [])
        ]
        comps.append(
            Component(ref=fp.reference, x=px, y=py,
                      rotation=float(getattr(fp, "rotation", 0.0) or 0.0),
                      pins=pins)
        )
    return comps


# Balayage d evitement : on essaie la direction voulue, puis on s en ecarte par
# pas de 12 degres jusqu a un demi-tour de part et d autre, en elargissant le
# rayon si aucun angle ne convient. Bornes volontairement courtes — le but est
# de rester PRES de l ancre, pas de trouver une place a tout prix.
_PAS_ANGULAIRE_DEG: float = 12.0
_ESSAIS_ANGULAIRES: int = 15
_ESSAIS_RADIAUX: int = 4
_PAS_RADIAL_MM: float = 1.5
# Plafond ABSOLU de la recherche radiale, pour borner le temps de calcul.
# 80 pas x 1,5 mm = 120 mm : au-dela de la diagonale de nos plus grandes
# cartes, donc jamais atteint par un cas legitime. Le pire ecart mesure sur
# `nucleo-f401` est 68,7 mm, soit 43 pas.
_ESSAIS_RADIAUX_MAX: int = 80


def _essais_radiaux(ecart_actuel: Optional[float], marge: float) -> int:
    """Combien de pas radiaux explorer, DEDUIT de la situation.

    ⚠️ Mesure du 2026-09-02, `nucleo-f401` : les huit condensateurs de
    decouplage n etaient jamais deplaces, le journal rendant « aucune place
    libre » pour chacun. Avec `_ESSAIS_RADIAUX = 4` et un pas de 1,5 mm, la
    recherche n explorait que 4,5 mm au-dela de la marge — soit, sur une ancre
    dense (marge 5 mm), l anneau d ecart libre 5,0 a 9,5 mm. Or les resistances
    occupent precisement cet anneau (13,7 mm d entraxe, ~6,2 mm d ecart libre
    au corps du LQFP-64). L anneau etait plein, la recherche echouait.

    ⚠️ J avais d abord conclu a une contradiction entre le plafond POWER (3 mm)
    et la marge du halo (5 mm). C etait FAUX : le plafond decide seulement s il
    faut ESSAYER ; le deplacement est accepte des qu il AMELIORE l ecart. Un
    point a 5 mm remplacait parfaitement un point a 58 mm.

    La borne naturelle est l ecart ou le membre se trouve DEJA : au-dela, la
    garde « ne peut qu ameliorer » refuserait le point de toute facon. Aucun
    seuil n est donc choisi — il est deduit.
    """
    if ecart_actuel is None:
        return _ESSAIS_RADIAUX
    besoin = (float(ecart_actuel) - marge) / _PAS_RADIAL_MM
    return max(1, min(_ESSAIS_RADIAUX_MAX, int(math.ceil(besoin))))


def _boites_absolues(pcb, sauf: str) -> list:
    """Boites des autres footprints, en coordonnees board."""
    boites = []
    for fp in pcb.footprints:
        if not fp.reference or fp.reference == sauf:
            continue
        cx, cy, hw, hh = _centre_et_demi(fp)
        boites.append((cx - hw, cy - hh, cx + hw, cy + hh))
    return boites


def _libre(boite: tuple, obstacles: list, marge: float) -> bool:
    x0, y0, x1, y1 = boite
    for o0, p0, o1, p1 in obstacles:
        if x0 - marge < o1 and o0 < x1 + marge and y0 - marge < p1 and p0 < y1 + marge:
            return False
    return True


# Isolement exige entre le cuivre et le bord de la carte. Ce n est PAS un
# reglage : c est la contrainte que le DRC applique lui-meme
# (`board setup constraints edge clearance`, 0,5 mm par defaut chez KiCad).
# La reproduire, c est obeir au juge, pas choisir un seuil.
_MARGE_BORD_MM: float = 0.5


def _contour_de_carte(pcb) -> Optional[tuple]:
    """(min_x, min_y, max_x, max_y) du contour, en coordonnees de footprint.

    Lecture NATIVE — `extract_board_outline`, la meme que `tools/placement.py`.
    Rend ``None`` si le contour est illisible : on ne remplace pas une
    contrainte qu on ne sait pas evaluer par un refus global.
    """
    try:
        from kicad_tools.optim.board_outline import extract_board_outline
        outline = extract_board_outline(pcb)
        if outline is None or not outline.vertices:
            return None
        ox, oy = pcb.board_origin
        xs = [v.x - ox for v in outline.vertices]
        ys = [v.y - oy for v in outline.vertices]
        return (min(xs), min(ys), max(xs), max(ys))
    except Exception:
        return None


def _dans_le_contour(boite: tuple, contour: Optional[tuple],
                     marge: float = _MARGE_BORD_MM) -> bool:
    """La boite tient-elle dans le contour, isolement du bord compris ?

    ⚠️ Mesure du 2026-09-02, `nucleo-f401` : la recherche elargie a pousse
    `D26` a 0,4474 mm du bord pour 0,5000 exiges — une erreur
    `copper_edge_clearance`, seule erreur du board. `_cible_libre` testait ses
    candidats contre les BOITES DES COMPOSANTS et contre rien d autre ; le
    contour n a jamais fait partie de ses obstacles. Tant que la recherche ne
    depassait pas 4,5 mm elle ne pouvait pas atteindre le bord : le defaut
    etait LATENT, et l elargissement l a reveille.

    Contour inconnu : on n interdit rien.
    """
    if not contour:
        return True
    x1, y1, x2, y2 = boite
    cx1, cy1, cx2, cy2 = contour
    return (x1 >= cx1 + marge and y1 >= cy1 + marge
            and x2 <= cx2 - marge and y2 <= cy2 - marge)


def _cible_libre(pcb, fp, centre_ancre: tuple, demi_ancre: tuple,
                 direction: tuple, marge: float, ref: str,
                 ecart_actuel: Optional[float] = None):
    """Premier point libre pour le CENTRE du corps de `fp`, ou ``None``.

    ⚠️ Sans cette recherche, deux membres de directions voisines atterrissent
    au MEME point. Mesure du 2026-08-29, board STM32 : 0 conflit avant le
    snap, 1 ERROR / 3 conflits apres 8 deplacements ; 202 ERROR sur l Arduino
    et ses 44 deplacements — assez pour forcer un re-tirage complet du
    placement, seize minutes a chaque fois.

    On garde la direction du GA comme PREMIER choix : elle porte l information
    de placement qu on ne veut pas jeter. On ne s en ecarte que si la place
    est prise, et par le plus petit ecart qui convient.
    """
    acx, acy = centre_ancre
    ahw, ahh = demi_ancre
    ux, uy = direction
    _, _, mhw, mhh = _centre_et_demi(fp)
    obstacles = _boites_absolues(pcb, ref)
    # ⚠️ Le CONTOUR est un obstacle au meme titre que les voisins. Sans lui,
    # la recherche elargie pousse un composant hors carte ou trop pres du bord.
    contour = _contour_de_carte(pcb)
    angle0 = math.atan2(uy, ux)
    pas = math.radians(_PAS_ANGULAIRE_DEG)
    # ⚠️ Portee DEDUITE de l ecart actuel, pas constante. Une fenetre de
    # 4,5 mm ne pouvait pas depasser l anneau de voisins d une ancre dense.
    for k_r in range(_essais_radiaux(ecart_actuel, marge)):
        supplement = k_r * _PAS_RADIAL_MM
        for k_a in range(_ESSAIS_ANGULAIRES):
            for signe in ((1,) if k_a == 0 else (1, -1)):
                a = angle0 + signe * k_a * pas
                vx, vy = math.cos(a), math.sin(a)
                rayon = (_portee(ahw, ahh, vx, vy) + _portee(mhw, mhh, vx, vy)
                         + marge + supplement)
                cx, cy = acx + vx * rayon, acy + vy * rayon
                boite = (cx - mhw, cy - mhh, cx + mhw, cy + mhh)
                # ⚠️ Le degagement exige est la MARGE, pas zero. Deux boites
                # qui se touchent passent un test de recouvrement et echouent
                # l analyseur, dont les regles portent sur un ecart reel.
                if (_dans_le_contour(boite, contour)
                        and _libre(boite, obstacles, marge)):
                    return cx, cy
    return None


def _ecart_libre(centre_a: tuple, demi_a: tuple, centre_m: tuple,
                 demi_m: tuple) -> float:
    """Espace LIBRE entre deux corps, le long de la droite qui les joint."""
    dx, dy = centre_m[0] - centre_a[0], centre_m[1] - centre_a[1]
    d = math.hypot(dx, dy)
    if d < 1e-9:
        return 0.0
    u = (dx / d, dy / d)
    return d - _portee(*demi_a, *u) - _portee(*demi_m, *u)


def _degrade_une_autre_attache(par_ref: dict, attaches: dict, ref: str,
                               ancre_traitee: str, avant: tuple,
                               apres: tuple) -> bool:
    """Le deplacement eloigne-t-il `ref` d une AUTRE de ses ancres ?

    Sans ce controle, la garantie « ne peut qu ameliorer » ne vaut que pour le
    cluster en cours de traitement — et un membre partage se fait eloigner de
    son autre ancre sans que rien ne le signale.
    """
    fp = par_ref.get(ref)
    if fp is None:
        return False
    _, _, mhw, mhh = _centre_et_demi(fp)
    for autre in attaches.get(ref, ()):
        if autre == ancre_traitee:
            continue
        fa = par_ref.get(autre)
        if fa is None:
            continue
        acx, acy, ahw, ahh = _centre_et_demi(fa)
        av = _ecart_libre((acx, acy), (ahw, ahh), avant, (mhw, mhh))
        ap = _ecart_libre((acx, acy), (ahw, ahh), apres, (mhw, mhh))
        if ap > av:
            return True
    return False


def snap_cluster_members(
    pcb,
    *,
    marge_mm: float = _MARGE_MM,
    figes: Optional[Iterable[str]] = None,
    denses: Optional[Iterable[str]] = None,
    marge_dense_mm: float = 5.0,
) -> int:
    """Ramene chaque membre de cluster a portee de son ancre. Modifie ``pcb``.

    Ne bouge un membre que s'il est REELLEMENT trop loin : l'ecart mesure est
    l'espace LIBRE entre les deux corps, compare au plafond du cluster. Un
    membre deja proche n'est pas touche — un snap qui « corrige » un placement
    correct est une regression deguisee.

    Renvoie le nombre de footprints deplaces.
    """
    # ⚠️ `_clusters_natifs` et non la detection brute : le nom de rail doit
    # etre normalise avant, sinon `+3.3V` n'est pas reconnu comme une
    # alimentation et AUCUN cluster POWER n'est construit.
    clusters = _clusters_natifs(_composants(pcb))
    if not clusters:
        return 0

    par_ref = {fp.reference: fp for fp in pcb.footprints if fp.reference}
    # ⚠️ Un membre appartient parfois a PLUSIEURS clusters — R2 est a la fois
    # dans `J1 INTERFACE` et dans `U2 DRIVER`. Une garantie « ne peut
    # qu ameliorer » verifiee sur le seul cluster traite est donc trompeuse :
    # mesure du 2026-08-29, rapprocher R2 de U2 (7,1 -> 6,5 mm) l eloignait de
    # J1 de 12,6 a 17,6. On tient la liste de TOUTES ses attaches.
    attaches: dict = {}
    for c in clusters:
        for m in c.members:
            attaches.setdefault(m, []).append(c.anchor)
    immobiles = set(figes or ())
    # Une ancre ne se deplace pas : elle est le repere de son propre cluster.
    immobiles |= {c.anchor for c in clusters}
    denses = set(denses or ())

    deplaces = 0
    for cluster in clusters:
        ancre = par_ref.get(cluster.anchor)
        if ancre is None:
            continue
        acx, acy, ahw, ahh = _centre_et_demi(ancre)
        # Marge du halo si l'ancre est fine-pitch : sinon on reboucherait le
        # canal d'escape que `_reserve_escape_halos` vient de degager.
        marge = max(marge_mm, marge_dense_mm) if cluster.anchor in denses else marge_mm

        for ref in cluster.members:
            fp = par_ref.get(ref)
            if fp is None or ref in immobiles:
                continue
            mcx, mcy, mhw, mhh = _centre_et_demi(fp)
            dx, dy = mcx - acx, mcy - acy
            dist = math.hypot(dx, dy)
            if dist < 1e-6:
                # Deja superpose : l'Inspecteur s'en charge, pas nous — on ne
                # sait pas dans quelle direction pousser.
                continue
            ux, uy = dx / dist, dy / dist
            portee = _portee(ahw, ahh, ux, uy) + _portee(mhw, mhh, ux, uy)
            if dist - portee <= cluster.max_distance_mm:
                continue

            # ⚠️ TRANSMETTRE l ecart actuel : sans lui, la recherche retombe
            # sur sa fenetre d origine de 4,5 mm et le correctif serait inerte.
            place = _cible_libre(pcb, fp, (acx, acy), (ahw, ahh), (ux, uy),
                                 marge, ref, ecart_actuel=dist - portee)
            if place is None:
                # ⚠️ Mieux vaut laisser un membre LOIN que le poser sur un
                # voisin : un court-circuit coute plus cher qu un decouplage
                # mal place, et l Inspecteur ne repare pas toujours.
                logger.debug("snap %s -> %s : aucune place libre, non deplace",
                             ref, cluster.anchor)
                continue
            ncx, ncy = place
            # ⚠️ LE SNAP NE PEUT QU AMELIORER — meme garde que le reasoner de
            # routage. La recherche de place libre s ecarte de la direction
            # voulue et elargit le rayon : elle peut donc poser un membre PLUS
            # LOIN qu il n etait. Mesure du 2026-08-29 sur le board STM32 :
            # J1-R2 passait de 12,6 a 17,6 mm et U2-D1 de 6,4 a 8,0. Un
            # correctif qui degrade ce qu il pretend corriger est pire que pas
            # de correctif : on ne bouge que si l ecart LIBRE diminue.
            ndx, ndy = ncx - acx, ncy - acy
            ndist = math.hypot(ndx, ndy)
            nu = (ndx / ndist, ndy / ndist) if ndist > 1e-9 else (ux, uy)
            necart = ndist - _portee(ahw, ahh, *nu) - _portee(mhw, mhh, *nu)
            if necart >= dist - portee:
                logger.debug("snap %s -> %s : place libre plus lointaine, ignoree",
                             ref, cluster.anchor)
                continue
            if _degrade_une_autre_attache(par_ref, attaches, ref, cluster.anchor,
                                          (mcx, mcy), (ncx, ncy)):
                logger.debug("snap %s -> %s : eloignerait une autre ancre, ignore",
                             ref, cluster.anchor)
                continue
            fp.position = (fp.position[0] + (ncx - mcx),
                           fp.position[1] + (ncy - mcy))
            deplaces += 1
            logger.debug("snap %s -> %s : %.1fmm -> %.1fmm libre",
                         ref, cluster.anchor, dist - portee, necart)

    return deplaces
