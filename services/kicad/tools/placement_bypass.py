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
import os
import re
from typing import Iterable, Optional


def _reglage(nom: str, defaut):
    """Reglage du banc (`/tmp/cirqix-reglages.json`), relu a chaque appel ;
    la valeur par defaut si le module des reglages est absent."""
    try:
        from tools.reglages_banc import reglage
        return reglage(nom, defaut)
    except Exception:  # noqa: BLE001
        return defaut

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
    clusters = detect_functional_clusters(copie)
    return _reattribuer_les_decouplages(clusters, composants)


def _reattribuer_les_decouplages(clusters, composants):
    """Rattache chaque condensateur de decouplage au CI LE PLUS PROCHE sur son
    rail — pas au premier CI que la detection a parcouru.

    ⚠️ MESURE DU 2026-09-10 sur `carte-05`. `detect_power_clusters` garde un
    `processed_caps` : le PREMIER IC parcouru rafle toutes les capas de son
    rail. `U2` (le regulateur) passe avant `U1` (le MCU) et prend les DIX capas
    de +3V3 — dont `C10`..`C15`, qui decouplent le MCU a 3-6 mm de lui et se
    retrouvent mesurees a 12-28 mm de `U2`. Sur la reference humaine, `C49` est
    ancree a 48 mm de `U5` : elle decouple evidemment un autre CI.

    Le snap herite de cet appariement et COLLE LES DECOUPLAGES DU MCU SUR LE
    REGULATEUR. C est ce que les captures de l utilisateur montraient — pas une
    distance mal reglee, un mauvais partenaire.

    Regle generale, pas un correctif par carte : une capa decouple le CI qu elle
    TOUCHE. Sur un rail partage par plusieurs CI, on la donne au plus proche.
    On ne touche pas au fork ; on recompose les clusters POWER cote Cirqix.
    """
    # ⚠️ Tout ce qui n est pas une liste de clusters passe INTACT. Une garde
    # monkeypatche `detect_functional_clusters` pour rendre un entier et ne
    # verifier que l appel ; iterer dessus la faisait tomber en TypeError.
    if not isinstance(clusters, (list, tuple)):
        return clusters
    par_ref = {getattr(c, "ref", None): c for c in composants if getattr(c, "ref", None)}
    power = [c for c in clusters
             if str(getattr(c, "cluster_type", "")).upper().endswith("POWER")]
    if len(power) < 2 and not any(len(c.members) > 1 for c in power):
        return clusters
    autres = [c for c in clusters if c not in power]

    # ⚠️ LES ANCRES SONT TOUS LES CI QUI ONT UNE BROCHE SUR UN RAIL, pas
    # seulement ceux a qui la detection a laisse des capas. Mesure du
    # 2026-09-10 : `U1` (LQFP-48, broches 1 et 24 sur +3V3) n avait AUCUN
    # cluster POWER — `processed_caps` avait tout donne a `U2`, parcouru avant.
    # Sans lui dans la liste, aucune reattribution n est possible.
    rails_de = {}
    for ref, c in par_ref.items():
        if len(getattr(c, "pins", None) or []) < 8:
            continue  # un CI, pas un passif
        r = set()
        for pin in c.pins or []:
            n = getattr(pin, "net_name", "") or ""
            if n and not n.upper().startswith(("GND", "AGND", "DGND")):
                nk = _nom_kicad_du_rail(n)
                if _RE_RAIL_DECIMAL.match(nk) or nk.upper().startswith(("V", "P", "+", "-")):
                    r.add(nk)
        if r:
            rails_de[ref] = r
    ancres = list(dict.fromkeys([c.anchor for c in power] + list(rails_de)))

    def _pos(ref):
        c = par_ref.get(ref)
        return (getattr(c, "x", None), getattr(c, "y", None)) if c else (None, None)

    def _rails(ref):
        c = par_ref.get(ref)
        out = set()
        for pin in getattr(c, "pins", None) or []:
            n = getattr(pin, "net_name", "") or ""
            if n and not n.upper().startswith(("GND", "AGND", "DGND")):
                out.add(_nom_kicad_du_rail(n))
        return out

    # UNE CAPA PAR BROCHE DE RAIL, LES PLUS PROCHES D ABORD. Mesure du
    # 2026-09-10 sur carte-05 : « au CI le plus proche » laissait C10..C15
    # groupees autour du regulateur, parce que le GA (qui herite de
    # `processed_caps`) les y avait deja rassemblees — le plus proche lisait
    # l erreur qu il devait corriger. Chaque CI RECLAME autant de capas de son
    # rail qu il a de broches sur ce rail (capacite), le CI le plus dote
    # d abord ; ce qui reste va au plus proche. C est la regle de l industrie
    # (« une 100 nF par broche VDD », docs/methodologie-routage.md), pas une
    # heuristique de plus.
    membres = []
    for c in power:
        for m in c.members:
            if m not in membres:
                membres.append(m)
    origine = {m: c.anchor for c in power for m in c.members}

    def _capacite(ref, rail):
        """Broches de l ancre `ref` sur CE rail — pas sur tous ses rails : un
        regulateur a six broches VIN et une seule sur +3V3, et c est la
        seule qui compte pour les capas de +3V3."""
        c = par_ref.get(ref)
        n = 0
        for pin in getattr(c, "pins", None) or []:
            nom = getattr(pin, "net_name", "") or ""
            if nom and _nom_kicad_du_rail(nom) == rail:
                n += 1
        return n

    def _distance(m, a):
        mx, my = _pos(m)
        ax, ay = _pos(a)
        if mx is None or ax is None:
            return None
        return ((mx - ax) ** 2 + (my - ay) ** 2) ** 0.5

    nouveaux = {a: [] for a in ancres}
    libres = list(membres)
    paires = [(a, rail) for a in ancres for rail in sorted(rails_de.get(a) or _rails(a))]
    for a, rail in sorted(paires, key=lambda ar: _capacite(*ar), reverse=True):
        candidats = []
        for m in libres:
            d = _distance(m, a)
            if d is not None and rail in _rails(m):
                candidats.append((d, m))
        candidats.sort()
        for _, m in candidats[:_capacite(a, rail)]:
            nouveaux[a].append(m)
            libres.remove(m)
    for m in libres:
        meilleur, dmin = origine.get(m), float("inf")
        for a in ancres:
            if not (_rails(m) & (rails_de.get(a) or _rails(a))):
                continue
            d = _distance(m, a)
            if d is not None and d < dmin:
                meilleur, dmin = a, d
        nouveaux.setdefault(meilleur, []).append(m)

    resultat = list(autres)
    modele = power[0] if power else None
    for a in ancres:
        membres = nouveaux.get(a, [])
        if not membres:
            continue
        existant = next((c for c in power if c.anchor == a), None)
        if existant is not None:
            try:
                existant.members = membres
            except Exception:
                pass
            resultat.append(existant)
        elif modele is not None:
            # Un CI que la detection avait laisse vide recoit un cluster POWER
            # de meme forme que les autres (meme plafond de 3 mm).
            c = copy.copy(modele)
            try:
                c.anchor = a
                c.members = membres
            except Exception:
                continue
            resultat.append(c)
    return resultat

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
                 ecart_actuel: Optional[float] = None,
                 marge_voisins: Optional[float] = None):
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
    # ⚠️ DEUX MARGES, ET ELLES NE PROTEGENT PAS LA MEME CHOSE.
    #
    # `marge` est l ecart radial a l ANCRE : sur un boitier fine-pitch c est le
    # halo d escape, 5 mm, et il ne doit pas etre rebouche.
    #
    # `marge_voisins` est le degagement exige des AUTRES composants. Rien ne
    # justifie d y imposer le halo : entre deux 0603 la marge normale est
    # `_MARGE_MM` = 0,3 mm. En imposant 5 mm, l anneau proche de l ancre
    # devenait inhabitable des qu un autre membre du cluster s y trouvait — et
    # ils y sont tous, par construction. La recherche partait au large.
    #
    # Mesure du 2026-09-08, `carte-04-mcu-minimal` : les cinq decouplages du
    # cluster POWER restaient a 3,4 / 5,5 / 6,1 / 9,5 / 11,4 mm, sur une carte
    # occupee a 30 %.
    #
    # Le defaut reste `marge` : un appelant qui ne distingue pas les deux
    # obtient exactement le comportement anterieur.
    marge_v = marge if marge_voisins is None else marge_voisins
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
                        and _libre(boite, obstacles, marge_v)):
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


class _PaireEnSerie:
    """Une paire a deux bornes, presentee comme un cluster.

    ⚠️ MESURE DU 2026-09-08. Le snap ne traite que les clusters de
    `detect_functional_clusters` — POWER, TIMING, DRIVER, INTERFACE. Une LED
    et sa resistance serie n appartiennent a AUCUN de ces types : elles
    n etaient jamais regardees, et finissaient a **101 mm** l une de l autre
    sur `carte-09`, pour un net qui ne touche qu ELLES DEUX.

    Les contraintes natives passees au workflow le meme jour ont ramene la
    moyenne de 55 a 36 mm — un vrai gain, mais ce sont des FORCES, et le depot
    mesure deja que les ressorts de groupe sont domines par les rails GND.
    Le serrage DUR de fin de chaine reste necessaire.

    On ne reecrit pas le snap : il porte deja tout ce qui compte — recherche
    de place libre, garde « ne peut qu ameliorer », refus de degrader une
    autre attache. La boucle ne lit que trois attributs d un cluster ; on les
    fournit. Ajouter un chemin parallele aurait duplique ces trois gardes, et
    c est ainsi qu elles divergent.
    """

    __slots__ = ("anchor", "members", "max_distance_mm", "cluster_type")

    def __init__(self, ancre: str, membre: str, plafond_mm: float) -> None:
        self.anchor = ancre
        self.members = [membre]
        self.max_distance_mm = plafond_mm
        self.cluster_type = "PAIRE"


# ⚠️ DECISION PRODUIT `D-2026-09-08-c`, EN ATTENTE. Desarme par defaut.
# Armer avec `CIRQIX_ABANDON_ATTACHES_IMPOSSIBLES=1`.
_ABANDONNER_IMPOSSIBLES = os.environ.get(
    "CIRQIX_ABANDON_ATTACHES_IMPOSSIBLES", "") not in ("", "0", "false")


def _elaguer_attaches_impossibles(attaches: dict, plafonds: dict,
                                  par_ref: dict) -> int:
    """Retire les attaches qu AUCUNE position ne peut satisfaire.

    ⚠️ MESURE DU 2026-09-08. `detect_functional_clusters` attache un meme
    composant a PLUSIEURS ancres, et ces ancres sont incompatibles entre elles :

        carte-07   15 composants a plusieurs ancres — les 15 insatisfiables
        carte-09   19 sur 19        carte-10   19 sur 19        carte-04   3 sur 3

        D10 (carte-09) appartient a SEPT clusters : J1, J10..J14 et U1
        D6  tenu par J7 et J1, distants de 123 mm pour 16 mm de plafonds cumules

    Aucune position ne satisfait « a 8 mm de J1 » ET « a 8 mm de J7 » quand les
    deux sont a 123 mm l un de l autre.

    CONSEQUENCE : LE GEL COMPLET. La garde « ne peut qu ameliorer » refuse tout
    mouvement, puisque se rapprocher d une ancre eloigne d une autre. Elle fait
    exactement son travail — et RIEN ne bouge :

        snap R10 -> D10 : eloignerait une autre ancre, ignore
        snap R11 -> D11 : eloignerait une autre ancre, ignore   (les seize)

    C est l explication de fond du reproche « placement d amateur » : le serrage
    ne manque pas, il est systematiquement refuse.

    LA REGLE. On garde l ancre la PLUS PROCHE, et on abandonne toute autre ancre
    prouvablement incompatible avec elle : `dist(A, B) > plafond(A) + plafond(B)`
    signifie qu aucun point n est a portee des deux. Ce n est pas un arbitrage
    de gout — c est de la geometrie.

    ⚠️ ON N ABANDONNE QUE CE QUI EST PROUVE. Deux ancres compatibles restent
    toutes deux en vigueur : la garde continue de proteger ce qui peut l etre.

    ⚠️ Le risque assume : une attache abandonnee peut correspondre a une
    adjacence que le routage utilisait. C est pourquoi la regle est desarmee par
    defaut et journalise ce qu elle retire.

    Rend le nombre d attaches retirees. Modifie `attaches` sur place.
    """
    retirees = 0
    for ref, ancres in list(attaches.items()):
        if len(ancres) < 2 or ref not in par_ref:
            continue
        cx, cy, _, _ = _centre_et_demi(par_ref[ref])
        connues = [a for a in dict.fromkeys(ancres) if a in par_ref]
        if len(connues) < 2:
            continue

        def _dist(a: str) -> float:
            ax, ay, _, _ = _centre_et_demi(par_ref[a])
            return math.hypot(ax - cx, ay - cy)

        proche = min(connues, key=_dist)
        px, py, _, _ = _centre_et_demi(par_ref[proche])
        gardees = [proche]
        for a in connues:
            if a == proche:
                continue
            ax, ay, _, _ = _centre_et_demi(par_ref[a])
            ecart = math.hypot(ax - px, ay - py)
            if ecart > plafonds.get(proche, 0.0) + plafonds.get(a, 0.0):
                logger.debug("snap: %s — attache %s abandonnee "
                             "(%.0f mm de %s pour %.0f mm de plafonds)",
                             ref, a, ecart, proche,
                             plafonds.get(proche, 0.0) + plafonds.get(a, 0.0))
                retirees += 1
            else:
                gardees.append(a)
        attaches[ref] = gardees
    return retirees


def _pastille_partagee(ancre_fp, membre_fp, exclure=()) -> tuple[float, float] | None:
    """La pastille de l ANCRE qui porte un net d alimentation partage avec le membre.

    ⚠️ MESURE DU 2026-09-10, sur les onze cartes du banc — distance entre un
    condensateur de decouplage et la broche d alimentation qu il decouple :

        carte-05     9,2 mm   max 12,9
        carte-09    16,6 mm   max 24,0
        carte-10    18,5 mm   max 27,6

    La regle de l industrie (Hartley, Bogatin, IPC) : « au plus pres des broches
    d alimentation », soit 1 a 3 mm. AUCUNE carte n y etait. Un condensateur a
    18 mm de sa broche ne decouple rien — sa boucle est trop grande.

    ⚠️ LA CAUSE : le snap POWER visait le CENTRE DU CORPS de l ancre
    (`_centre_et_demi`). « A 3 mm du corps » d un LQFP-48 de 7 mm de cote laisse
    la capa n importe ou sur un perimetre de 40 mm — jamais contre la broche.
    La bibliotheque le dit elle-meme (`FunctionalCluster.anchor_pin`, docstring :
    « immediately adjacent to the IC power pins ») et ne le remplit pas ; et
    CLAUDE.md l annoncait depuis le 2026-08-29 : « `anchor_pin`, deja expose,
    jamais lu ». C est le SEPTIEME levier natif inutilise trouve cette semaine.

    On ne devine rien : le net est SUR les pastilles. Rend la position absolue
    de la pastille d alimentation de l ancre, ou `None` si le membre n en
    partage aucune (il n est alors pas un decouplage, on retombe sur le corps).
    """
    def _nets(fp):
        out = {}
        for pad in getattr(fp, "pads", []) or []:
            n = getattr(pad, "net_name", None)
            if n:
                out.setdefault(n, []).append(pad)
        return out

    nets_membre = _nets(membre_fp)
    nets_ancre = _nets(ancre_fp)
    # Un decouplage partage UN rail (pas GND) avec le CI.
    from tools.placement_contraintes import _est_alimentation
    communs = [n for n in nets_membre if n in nets_ancre and _est_alimentation(n)
               and n.upper() not in ("GND", "AGND", "DGND", "PGND")]
    if not communs:
        return None
    net = communs[0]
    a = math.radians(getattr(ancre_fp, "rotation", 0.0) or 0.0)
    ox, oy = ancre_fp.position
    # ⚠️ Plusieurs pastilles du meme rail sur un LQFP (VDD x4) : on prend la
    # plus proche de la position ACTUELLE du membre, pour ne pas envoyer une
    # capa a l autre bout du boitier alors qu une broche est deja a cote.
    mx, my = membre_fp.position
    # UNE CAPA PAR PASTILLE : `exclure` porte les pastilles deja servies par
    # une autre capa de la meme ancre. Sans cela, deux capas se collent a la
    # meme broche VDD et les autres broches restent nues (mesure carte-05,
    # 2026-09-10). Si toutes sont prises, on retombe sur la plus proche.
    prises = {(round(x, 3), round(y, 3)) for x, y in (exclure or ())}
    candidates = []
    for pad in nets_ancre[net]:
        px, py = pad.position
        ax = ox + px * math.cos(a) - py * math.sin(a)
        ay = oy + px * math.sin(a) + py * math.cos(a)
        candidates.append((math.hypot(ax - mx, ay - my), (ax, ay)))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    for _, pos in candidates:
        if (round(pos[0], 3), round(pos[1], 3)) not in prises:
            return pos
    return candidates[0][1]


def snap_cluster_members(
    pcb,
    *,
    marge_mm: float = _MARGE_MM,
    figes: Optional[Iterable[str]] = None,
    denses: Optional[Iterable[str]] = None,
    marge_dense_mm: float = 5.0,
    paires: Optional[Iterable] = None,
    plafond_paire_mm: float = 5.0,
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
    clusters = list(_clusters_natifs(_composants(pcb)))

    # ⚠️ LES PAIRES EN SERIE REJOIGNENT LES CLUSTERS, elles ne forment pas
    # un second passage. Deux passages successifs se defont l un l autre : le
    # depot a deja mesure ce piege entre le clamp et le centrage des dominants,
    # puis entre le halo et le snap. Un seul parcours, une seule table
    # d attaches, une seule garde « ne peut qu ameliorer ».
    #
    # ⚠️ L ANCRE EST CELLE QUI A D AUTRES ATTACHES, et ce choix decide de
    # tout. Premiere version, mesuree sur `carte-09` : ancre = la premiere par
    # ordre alphabetique, donc `D10` pour la paire `(D10, R10)`. Resultat :
    #
    #     snap R10 -> D10 : eloignerait une autre ancre, ignore
    #     ... les SEIZE paires refusees, sans exception
    #
    # La raison est juste : chaque `R<n>` appartient deja au cluster de `U1`.
    # Le rapprocher de sa LED l eloignerait du MCU, et la garde « ne peut
    # qu ameliorer » refuse — elle fait exactement son travail.
    #
    # C est l ancre qui etait fausse. La resistance est tenue par le MCU ; la
    # LED, elle, n a AUCUNE autre attache. C est donc elle qui doit venir. On
    # ancre sur le membre le plus contraint, et on deplace le plus libre :
    # les deux intentions sont alors satisfaites au lieu d une seule.
    #
    # ⚠️ Ce choix se fait APRES la construction des clusters natifs, parce
    # qu il a besoin de savoir qui y appartient. Le faire avant reviendrait a
    # deviner ce qu on peut lire.
    figes_init = set(figes or ())
    membres_de_clusters = {m for c in clusters for m in c.members}
    membres_de_clusters |= {c.anchor for c in clusters}

    def _ancre_de_paire(a: str, b: str) -> tuple[str, str]:
        # 1. Un composant fige ne bouge pas : il est l ancre, sans discussion.
        if a in figes_init and b not in figes_init:
            return a, b
        if b in figes_init and a not in figes_init:
            return b, a
        # 2. Celui qui porte d autres attaches ancre l autre.
        a_tenu, b_tenu = a in membres_de_clusters, b in membres_de_clusters
        if a_tenu and not b_tenu:
            return a, b
        if b_tenu and not a_tenu:
            return b, a
        # 3. A egalite, l ordre alphabetique — stable d un tirage a l autre.
        #    Un ancrage instable rendrait le placement irreproductible pour une
        #    raison sans rapport avec le GA.
        return (a, b) if a < b else (b, a)

    for _nom, _a, _b in (paires or ()):
        ancre_p, membre_p = _ancre_de_paire(_a, _b)
        clusters.append(_PaireEnSerie(ancre_p, membre_p, plafond_paire_mm))

    if not clusters:
        return 0

    par_ref = {fp.reference: fp for fp in pcb.footprints if fp.reference}
    # ⚠️ Un membre appartient parfois a PLUSIEURS clusters — R2 est a la fois
    # dans `J1 INTERFACE` et dans `U2 DRIVER`. Une garantie « ne peut
    # qu ameliorer » verifiee sur le seul cluster traite est donc trompeuse :
    # mesure du 2026-08-29, rapprocher R2 de U2 (7,1 -> 6,5 mm) l eloignait de
    # J1 de 12,6 a 17,6. On tient la liste de TOUTES ses attaches.
    attaches: dict = {}
    plafonds: dict = {}
    for c in clusters:
        plafonds[c.anchor] = min(plafonds.get(c.anchor, 1e9), c.max_distance_mm)
        for m in c.members:
            attaches.setdefault(m, []).append(c.anchor)

    if _ABANDONNER_IMPOSSIBLES:
        abandons = _elaguer_attaches_impossibles(attaches, plafonds, par_ref)
        if abandons:
            logger.info("snap: %d attache(s) PROUVABLEMENT insatisfiable(s) "
                        "abandonnee(s)", abandons)

    immobiles = set(figes or ())
    # Une ancre ne se deplace pas : elle est le repere de son propre cluster.
    immobiles |= {c.anchor for c in clusters}
    denses = set(denses or ())

    deplaces = 0
    # Pastilles de rail deja servies, par ancre : une capa par broche VDD.
    pads_prises: dict = {}
    for cluster in clusters:
        ancre = par_ref.get(cluster.anchor)
        if ancre is None:
            continue
        acx, acy, ahw, ahh = _centre_et_demi(ancre)
        est_power = str(getattr(cluster, "cluster_type", "")).upper().endswith("POWER")
        # Marge du halo si l'ancre est fine-pitch : sinon on reboucherait le
        # canal d'escape que `_reserve_escape_halos` vient de degager.
        marge = max(marge_mm, marge_dense_mm) if cluster.anchor in denses else marge_mm
        # ⚠️ UN DECOUPLAGE N EST PAS UN SIGNAL. Le halo de 5 mm protege le canal
        # d ECHAPPEMENT des signaux d un boitier fine-pitch ; un condensateur de
        # decouplage, lui, DOIT etre dans ce halo, contre sa broche — c est la
        # regle de l industrie (« immediately adjacent to the IC power pins »).
        #
        # Mesure du 2026-09-10 : avec le halo impose aux capas, le decouplage
        # plafonne a 4,6-4,7 mm sur carte-05 et carte-09, quand la regle vise
        # 1 a 3 mm. Le halo et la regle ne sont pas en conflit sur le fond ;
        # c est notre code qui appliquait le halo a TOUT membre indistinctement.
        #
        # Le canal d echappement n en souffre pas : une capa 0603 collee a une
        # broche VDD occupe UN cote du boitier sur 1,6 mm, elle ne bouche pas les
        # trois autres ni les 36 signaux qui en sortent.
        # ⚠️ A/B du 2026-09-10 (soir) : depuis que les decouplages entrent dans
        # le halo, carte-11 exige 4 couches (2 auparavant) et esp32-baseline
        # monte a 6 sans atteindre 100 % (100 % sur 2 le 2026-09-03). Reglage
        # `decouplage_dans_le_halo` (defaut : vrai) pour mesurer sur le meme
        # board avant de trancher.
        if est_power and _reglage("decouplage_dans_le_halo", True):
            marge = marge_mm

        for ref in cluster.members:
            fp = par_ref.get(ref)
            if fp is None or ref in immobiles:
                continue
            mcx, mcy, mhw, mhh = _centre_et_demi(fp)
            # ⚠️ DECOUPLAGE : on vise la BROCHE, pas le corps. Voir
            # `_pastille_partagee`. Le rayon d ancre devient celui d une pastille
            # (quasi nul) : « a 3 mm » signifie alors 3 mm de la broche.
            if est_power:
                cible = _pastille_partagee(ancre, fp, exclure=pads_prises.get(cluster.anchor, ()))
                if cible is not None:
                    acx, acy = cible
                    ahw = ahh = _DEMI_MINIMUM_MM
                    pads_prises.setdefault(cluster.anchor, set()).add(cible)
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
            # ⚠️ La marge du HALO ne vaut que pour l ancre. Les voisins gardent
            # la marge ordinaire : imposer 5 mm entre deux 0603 rendait
            # l anneau proche inhabitable et poussait la recherche au large.
            place = _cible_libre(pcb, fp, (acx, acy), (ahw, ahh), (ux, uy),
                                 marge, ref, ecart_actuel=dist - portee,
                                 marge_voisins=marge_mm)
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
