"""Graine EN ÉTOILE — un placement CALCULÉ, pas tiré. RÉGLAGE DE BANC, DÉSARMÉ.

## Le constat (2026-09-21, banc des dix cartes)

La stratégie `hybrid` de kicad-tools tire une population au hasard. Sur le
MÊME circuit, cinq placements de carte-10 rendent 601, 501, 351, 681 et 561
croisements du chevelu ; 72 à 100 % de ces croisements impliquent un net de
connecteur, et les connexions qui manquent après routage sont les signaux qui
partent du boîtier central. Des forces locales ne démêlent jamais un chevelu
déjà croisé : plus de couches, une carte plus grande, un rejeu du routeur,
trois variantes de placement — tout a été mesuré et réfuté le même jour.

Un concepteur ne tire rien au sort : il pose le boîtier central, met chaque
connecteur du côté des broches qu'il relie, et range chaque périphérique sur
le rayon de SA broche. Le chevelu part en étoile et ne se croise presque plus.

    croisements   carte-08  406 → 73    carte-09  483 → 109    carte-10  564 → 119
    routage GELÉ de la graine brute : 07, 08, 09 et 10 à 100 %, 0 erreur,
    0 connexion manquante (placement actuel, même jour : 2, 8 et 11 manquantes ;
    carte-10 sur 6 couches contre 2 avec la graine)

## La règle — aucune carte nommée

- **centre** : tout boîtier non connecteur d'au moins `_BROCHES_D_UN_CENTRE`
  pastilles. Ce n'est pas un seuil calibré sur le banc : c'est le plus petit
  boîtier de circuit intégré (SOIC-8). Plusieurs centres : une étoile chacun,
  le plus gros au milieu, les autres sur le rayon des broches qui les relient ;
- **connecteur** : contre le bord que vise le rayon de ses broches (règle de
  l'utilisateur : « toujours les connecteurs à l'extrémité ») ;
- **périphérique** : sur le rayon des broches du centre qu'il relie ; un
  découplage, sur celui de la broche de rail la plus proche ;
- **suivant** (la LED derrière sa résistance) : derrière celui qu'il prolonge ;
- un circuit SANS centre n'est pas touché — le placement habituel s'applique.

Les pas de recherche (0,5 mm, 5°) sont des résolutions, pas des seuils.
"""
from __future__ import annotations

import collections
import logging
import math
from typing import Optional

logger = logging.getLogger(__name__)

# Le plus petit boîtier de circuit intégré (SOIC-8, DIP-8). En dessous : un
# transistor, un régulateur 3 broches, une diode — rien ne « rayonne » autour.
_BROCHES_D_UN_CENTRE: int = 8
_MARGE_BORD_MM: float = 2.0      # celle du clamp et du collage au bord
_JEU_MM: float = 0.4             # entre courtyards, au-dessus de `_MARGE_ENTRE_COURTYARDS_MM`
_PAS_RAYON_MM: float = 0.5
_PAS_ANGLE_DEG: float = 5.0
# Regles de trace du depot : piste 0,25 mm (`_TRONCON_LARGEUR_MM`), degagement 0,2 mm.
_PAS_DE_ROUTAGE_MM: float = 0.25 + 0.2
_DEGAGEMENT_MM: float = 0.2


def armee() -> bool:
    """Réglage de banc `graine_etoile` — faux par défaut, relu à chaque appel."""
    from tools.reglages_banc import reglage
    return bool(reglage("graine_etoile", False))


def couloir_mm(fp) -> float:
    """Couloir de sortie a laisser autour d un centre : signaux a sortir PAR COTE
    x pas de routage, plus un degagement.

    ⚠️ Regression du 2026-09-21 : carte-03 (centre de 8 broches) sortait a
    3 erreurs et 7 connexions manquantes, tous les tirages figes a 12 % ou
    moins — les peripheriques etaient colles au boitier, rien ne pouvait en
    SORTIR. Deduit des regles de trace, pas d une carte : ~0,65 mm pour un
    8 broches, ~4,3 mm pour un LQFP-48 a 36 signaux (le halo existant en
    reserve 5 aux boitiers de 16 broches et plus : meme ordre de grandeur).
    """
    signaux = {pad.net_name for pad in fp.pads if _est_route(pad.net_name)}
    return math.ceil(len(signaux) / 4.0) * _PAS_DE_ROUTAGE_MM + _DEGAGEMENT_MM


def _est_signal(net: Optional[str]) -> bool:
    from kicad_tools.explain.mistakes import is_power_net
    from tools.placement import _NETS_DE_PLAN
    return bool(net) and net not in _NETS_DE_PLAN and not is_power_net(net)


def _est_route(net: Optional[str]) -> bool:
    from tools.placement import _NETS_DE_PLAN
    return bool(net) and net not in _NETS_DE_PLAN


def _pastille_absolue(fp, pad, position: tuple) -> tuple:
    """Sens de KiCad (y descend) — même convention que `_boite_orientee_fp`."""
    a = math.radians(float(getattr(fp, "rotation", 0.0) or 0.0))
    px, py = pad.position
    return (position[0] + px * math.cos(a) + py * math.sin(a),
            position[1] - px * math.sin(a) + py * math.cos(a))


class _Etoile:
    """État d'un calcul : positions posées, boîtes occupées, pastilles des centres."""

    def __init__(self, fps: list, connecteurs: list, contour: tuple) -> None:
        from tools.placement import _boite_orientee_fp
        self.fps = {fp.reference: fp for fp in fps if getattr(fp, "reference", None)}
        self.conn = [r for r in connecteurs if r in self.fps]
        self.contour = contour
        self.bornes = (contour[0] + _MARGE_BORD_MM, contour[1] - _MARGE_BORD_MM,
                       contour[2] + _MARGE_BORD_MM, contour[3] - _MARGE_BORD_MM)
        self.boites = {r: _boite_orientee_fp(fp) for r, fp in self.fps.items()}
        self.pos: dict = {}
        self.occupees: dict = {}
        self.pads_centre: dict = {}          # centre -> {net: [pastilles absolues]}
        self.sans_place: list = []           # refs qu on n a PAS su poser — jamais en silence

    # -- géométrie ---------------------------------------------------------
    def boite_a(self, ref: str, pos: tuple) -> tuple:
        b = self.boites[ref]
        return (pos[0] + b[0], pos[1] + b[1], pos[0] + b[2], pos[1] + b[3])

    def milieu(self, ref: str) -> tuple:
        b, p = self.boites[ref], self.pos[ref]
        return (p[0] + (b[0] + b[2]) / 2.0, p[1] + (b[1] + b[3]) / 2.0)

    def demi_diagonale(self, ref: str) -> float:
        b = self.boites[ref]
        return math.hypot(b[2] - b[0], b[3] - b[1]) / 2.0

    def libre(self, boite: tuple) -> bool:
        from tools.placement import _boites_se_recouvrent
        dedans = (self.bornes[0] <= boite[0] and boite[2] <= self.bornes[1]
                  and self.bornes[2] <= boite[1] and boite[3] <= self.bornes[3])
        return dedans and not any(_boites_se_recouvrent(boite, o, _JEU_MM)
                                  for o in self.occupees.values())

    def fixer_ou_avouer(self, ref: str, pos: Optional[tuple], couloir: float = 0.0) -> None:
        """Pose `ref`, ou le laisse ou il etait ET LE NOTE : un composant reste a sa
        place d origine se lit, sinon, exactement comme un composant bien pose."""
        if pos is None:
            self.sans_place.append(ref)
            pos = tuple(self.fps[ref].position)
        self.fixer(ref, pos, couloir)

    def fixer(self, ref: str, pos: tuple, couloir: float = 0.0) -> None:
        """`couloir` elargit la boite OCCUPEE d un centre : rien ne s y pose."""
        self.pos[ref] = pos
        b = self.boite_a(ref, pos)
        marge = max(0.0, couloir - _JEU_MM)      # `libre` ajoute deja `_JEU_MM`
        self.occupees[ref] = (b[0] - marge, b[1] - marge, b[2] + marge, b[3] + marge)

    def le_long_du_rayon(self, ref: str, origine: tuple, angle: float, r0: float) -> Optional[tuple]:
        """Première place libre sur le rayon, puis sur les rayons voisins."""
        b = self.boites[ref]
        dx, dy = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0
        portee = math.hypot(self.contour[1] - self.contour[0], self.contour[3] - self.contour[2])
        pas_a = math.radians(_PAS_ANGLE_DEG)
        for k in range(int(math.pi / pas_a) + 1):
            for sens in ((0,) if k == 0 else (1, -1)):
                a, r = angle + sens * k * pas_a, r0
                while r < portee:
                    pos = (origine[0] + math.cos(a) * r - dx, origine[1] + math.sin(a) * r - dy)
                    if self.libre(self.boite_a(ref, pos)):
                        return pos
                    r += _PAS_RAYON_MM
        return None

    # -- liens -------------------------------------------------------------
    def relever_les_pastilles(self, centre: str) -> None:
        nets = collections.defaultdict(list)
        fp = self.fps[centre]
        for pad in fp.pads:
            if _est_route(pad.net_name):
                nets[pad.net_name].append(_pastille_absolue(fp, pad, self.pos[centre]))
        self.pads_centre[centre] = nets

    def lien(self, ref: str, centre: str, signaux: bool) -> list:
        """Pastilles du centre reliées à `ref` — signaux, ou rails si `signaux` est faux."""
        nets = self.pads_centre.get(centre, {})
        return [q for pad in self.fps[ref].pads
                if pad.net_name in nets and _est_signal(pad.net_name) == signaux
                for q in nets[pad.net_name]]

    def centre_de(self, ref: str, centres: list, signaux: bool) -> Optional[str]:
        scores = [(len(self.lien(ref, c, signaux)), -i, c) for i, c in enumerate(centres)]
        n, _, c = max(scores) if scores else (0, 0, None)
        return c if n else None

    def angle_vers(self, ref: str, centre: str, signaux: bool) -> float:
        pts = self.lien(ref, centre, signaux)
        if not signaux:
            # Un découplage vise LA broche de rail la plus proche, pas leur moyenne.
            x, y = self.fps[ref].position
            pts = [min(pts, key=lambda q: math.hypot(q[0] - x, q[1] - y))]
        gx = sum(q[0] for q in pts) / len(pts)
        gy = sum(q[1] for q in pts) / len(pts)
        ox, oy = self.milieu(centre)
        return math.atan2(gy - oy, gx - ox)


def _poser_les_centres(e: _Etoile, centres: list, mobiles: list) -> None:
    """Le plus gros au milieu ; les autres sur le rayon des broches qui les relient,
    assez loin pour laisser à chacun la couronne de ses périphériques."""
    premier = centres[0]
    b = e.boites[premier]
    cx, cy = (e.contour[0] + e.contour[1]) / 2.0, (e.contour[2] + e.contour[3]) / 2.0
    e.fixer(premier, (cx - (b[0] + b[2]) / 2.0, cy - (b[1] + b[3]) / 2.0),
            couloir_mm(e.fps[premier]))
    e.relever_les_pastilles(premier)
    couronne = 2.0 * max((max(e.boites[r][2] - e.boites[r][0], e.boites[r][3] - e.boites[r][1])
                          for r in mobiles if r not in centres), default=0.0)
    for c in centres[1:]:
        poses = [p for p in centres if p in e.pos]
        parent = e.centre_de(c, poses, True) or e.centre_de(c, poses, False) or premier
        relie = e.lien(c, parent, True) or e.lien(c, parent, False)
        angle = e.angle_vers(c, parent, bool(e.lien(c, parent, True))) if relie else 0.0
        r0 = e.demi_diagonale(parent) + e.demi_diagonale(c) + couronne
        pos = e.le_long_du_rayon(c, e.milieu(parent), angle, r0)
        e.fixer_ou_avouer(c, pos, couloir_mm(e.fps[c]))
        e.relever_les_pastilles(c)


def _poser_les_connecteurs(e: _Etoile, centres: list) -> None:
    """Chaque connecteur contre le bord que vise le rayon de ses broches."""
    from tools.placement import _position_au_bord
    lies = [(len(e.lien(r, c, True)), r, c) for r in e.conn
            for c in [e.centre_de(r, centres, True)] if c]
    a_leur_place = [r for r in e.conn if r not in {x[1] for x in lies}]
    for r in a_leur_place:                       # sans lien : ils restent, et font obstacle
        e.fixer(r, tuple(e.fps[r].position))
    for _, r, c in sorted(lies, key=lambda x: (-x[0], x[1])):
        a, (ox, oy), b = e.angle_vers(r, c, True), e.milieu(c), e.boites[r]
        # Où le rayon sort du contour : le plus court des deux franchissements.
        t = min(((haut if d > 0 else bas) - o) / d
                for d, o, bas, haut in ((math.cos(a), ox, e.contour[0], e.contour[1]),
                                        (math.sin(a), oy, e.contour[2], e.contour[3]))
                if abs(d) > 1e-9)
        depart = (ox + math.cos(a) * t - (b[0] + b[2]) / 2.0, oy + math.sin(a) * t - (b[1] + b[3]) / 2.0)
        # TOUT ce qui est deja pose fait obstacle — centres et leur couloir compris :
        # sur une carte basse, le bord vise peut etre a quelques mm du boitier.
        autres = list(e.occupees.values())
        pos = _position_au_bord(depart, b, e.bornes, autres)
        e.fixer_ou_avouer(r, pos if pos != depart else None)


def _poser_les_peripheriques(e: _Etoile, centres: list, mobiles: list) -> None:
    """Signaux d'abord (ils fixent la topologie), découplages ensuite, puis les
    suivants en largeur, enfin les isolés."""
    reste = [r for r in mobiles if r not in centres]
    file: collections.deque = collections.deque()
    for signaux in (True, False):
        directs = [(r, c) for r in reste if r not in e.pos
                   for c in [e.centre_de(r, centres, signaux)] if c]
        for r, c in sorted(directs, key=lambda x: (-len(e.fps[x[0]].pads), x[0])):
            pos = e.le_long_du_rayon(r, e.milieu(c), e.angle_vers(r, c, signaux),
                                     e.demi_diagonale(c) * 0.75)
            e.fixer_ou_avouer(r, pos)
            file.append((r, c))
    voisins = collections.defaultdict(set)
    par_net = collections.defaultdict(set)
    for r in reste:
        for pad in e.fps[r].pads:
            if _est_signal(pad.net_name):
                par_net[pad.net_name].add(r)
    for refs in par_net.values():
        for r in refs:
            voisins[r] |= refs - {r}
    while file:
        parent, c = file.popleft()
        for r in sorted(voisins[parent] - set(e.pos)):
            (ox, oy), (px, py) = e.milieu(c), e.milieu(parent)
            pos = e.le_long_du_rayon(r, (ox, oy), math.atan2(py - oy, px - ox),
                                     math.hypot(px - ox, py - oy))
            e.fixer_ou_avouer(r, pos)
            file.append((r, c))
    for r in [x for x in reste if x not in e.pos]:
        pos = e.le_long_du_rayon(r, e.milieu(centres[0]), 0.0, e.demi_diagonale(centres[0]))
        e.fixer_ou_avouer(r, pos)


def calculer(fps: list, connecteurs: list, contour: tuple, avec_echecs: bool = False) -> tuple:
    """``({ref: (x, y)}, [centres])`` — fonction PURE. ``({}, [])`` sans centre.
    Avec ``avec_echecs`` : un troisieme element, les refs restees SANS PLACE.

    ``contour`` : ``(min_x, max_x, min_y, max_y)`` dans le repère de
    ``fp.position``. Seules les positions qui CHANGENT sont rendues.
    """
    e = _Etoile(fps, connecteurs, contour)
    mobiles = [r for r in e.fps if r not in e.conn]
    centres = sorted((r for r in mobiles if len(e.fps[r].pads) >= _BROCHES_D_UN_CENTRE),
                     key=lambda r: (-len(e.fps[r].pads), r))
    if not centres:
        return ({}, [], []) if avec_echecs else ({}, [])
    _poser_les_centres(e, centres, mobiles)
    _poser_les_connecteurs(e, centres)
    _poser_les_peripheriques(e, centres, mobiles)
    positions = {r: p for r, p in e.pos.items()
                 if r not in e.sans_place and tuple(e.fps[r].position) != p}
    return (positions, centres, list(e.sans_place)) if avec_echecs else (positions, centres)


def poser_sur(pcb, connecteurs: list) -> list:
    """Pose la graine dans ``pcb``. Rend les centres (liste vide : rien n'a été fait,
    et on le DIT — une graine silencieusement absente fausserait la mesure)."""
    from tools.placement import _outline_bounds
    try:
        contour = _outline_bounds(pcb)
        if contour is None:
            logger.error("graine en etoile : contour illisible — NON posee")
            return []
        positions, centres, sans_place = calculer(list(pcb.footprints), list(connecteurs),
                                                   contour, avec_echecs=True)
        if not centres:
            logger.warning("graine en etoile : aucun boitier central — placement habituel")
            return []
        par_ref = {fp.reference: fp for fp in pcb.footprints}
        for ref, pos in positions.items():
            par_ref[ref].position = pos
        logger.warning("graine en etoile : %d position(s) posee(s) autour de %s, contour "
                       "%.1fx%.1f mm, %s en (%.1f, %.1f) — REGLAGE DE BANC",
                       len(positions), ", ".join(centres), contour[1] - contour[0],
                       contour[3] - contour[2], centres[0], *par_ref[centres[0]].position)
        if sans_place:
            logger.error("graine en etoile : %d composant(s) SANS PLACE, laisse(s) ou ils etaient "
                         "(%s) — les filets de la chaine devront les reprendre",
                         len(sans_place), ", ".join(sorted(sans_place)))
        return centres
    except Exception as exc:  # noqa: BLE001 — une panne ici rend la main au placement habituel
        logger.error("graine en etoile : NON posee (%s) — placement habituel", exc)
        return []
