"""Familles rangées : les paires LED + résistance en matrice, là où elles sont.

D-2026-09-26-a, phase C (validée par l'utilisateur le 2026-09-26 : « phase C,
fais-le »). Mesure du 2026-09-26 sur les boards placés de la campagne : les
LED de carte-07 à 10 sont entassées, sans orientation commune, leurs repères
superposés.

⚠️ `placement_rangees.ranger_les_paires` existait, et ne se déclenchait plus :
elle range contre le bord le PLUS LIBRE, or depuis la phase A chaque bord
porte un connecteur — « aucun bord assez libre (6,0 mm au mieux, 12,4
requis) » sur 22 tirages de la campagne. Ici on ne cherche pas un bord : la
matrice est posée au plus près de l'endroit où l'optimiseur a mis la famille,
c'est-à-dire près du circuit qu'elle sert.

Règle :
  1. les paires viennent de `paires_du_board` (déjà en production) ;
  2. chaque cellule = la LED, sa résistance juste dessous, toutes à 0° —
     orientation et polarité communes ;
  3. chaque cellule réserve la place de DEUX repères lisibles, à plat : celui
     de la LED au-dessus d'elle, celui de la résistance en dessous. Pas =
     max(corps, repère) + 0,5 mm. ⚠️ Mesuré le 2026-09-26 : au pas « corps
     + 0,5 mm » de la proposition, la matrice était propre mais les repères
     n'avaient plus de place — carte-08, 6 -> 45 avertissements de
     sérigraphie. La règle de lisibilité (D-2026-09-26-a, 5) interdit de les
     réduire ou de les masquer : c'est donc la cellule qui leur fait place ;
  4. les cellules suivent l'ordre des broches cibles (la pastille qui pilote
     la résistance), colonne par colonne : peu de croisements ajoutés ;
  5. plusieurs formes (1 à 4 rangées) et la place libre la plus proche du
     centre actuel de la famille ; rien n'est posé si aucune ne tient —
     jamais contre le bord ni sur un connecteur (mêmes zones qu'en phase A).

Le garde-fou (erreurs, croisements) vit chez l'appelant, comme pour la grille.
"""
from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

_ESPACE_MM: float = 0.5          # entre deux corps de la matrice
_ECART_REPERE_MM: float = 0.2    # entre un repère et son corps
_PAS_RECHERCHE_MM: float = 0.5
_RAYON_MAX_MM: float = 30.0
_RANGEES_MAX: int = 4
_PAIRES_MIN: int = 3             # une « famille » compte au moins trois paires
_LIEN_MM: float = 15.0           # au-delà, deux paires sont deux groupes distincts


def _Z():
    from tools import placement_zones as Z
    return Z


def _cible(pcb, led: str, res: str, net_commun: str):
    """Point de la pastille qui PILOTE la résistance (l'autre bout du couple),
    ou None si elle ne mène nulle part d'identifiable."""
    from tools.serigraphie import _tourne
    fps = {f.reference: f for f in pcb.footprints}
    r = fps[res]
    autre = next((p.net_name for p in r.pads
                  if getattr(p, "net_name", None) and p.net_name != net_commun), None)
    if not autre:
        return None
    for f in pcb.footprints:
        if f.reference in (led, res):
            continue
        for p in f.pads:
            if getattr(p, "net_name", None) == autre:
                return _tourne(f, *p.position)
    return None


def _formes(n: int):
    for rangees in range(1, min(_RANGEES_MAX, n) + 1):
        yield rangees, math.ceil(n / rangees)


_DECALAGES: list = []


def _anneaux(rayon_max: float):
    """Décalages du plus proche au plus loin, en distance VRAIE — pas par
    anneau carré, dont le coin est plus loin que le côté de l'anneau suivant
    (revue du 2026-09-26)."""
    if not _DECALAGES:
        n = int(round(_RAYON_MAX_MM / _PAS_RECHERCHE_MM))
        _DECALAGES.extend(sorted(
            ((i * _PAS_RECHERCHE_MM, j * _PAS_RECHERCHE_MM)
             for i in range(-n, n + 1) for j in range(-n, n + 1)
             if math.hypot(i, j) * _PAS_RECHERCHE_MM <= _RAYON_MAX_MM),
            key=lambda d: (math.hypot(*d), d)))
    return (d for d in _DECALAGES if math.hypot(*d) <= rayon_max)


def _familles(pcb, paires: list) -> list:
    """Les paires regroupées en familles : même couple d'empreintes, et
    proches les unes des autres (lien simple sous `_LIEN_MM`).

    ⚠️ Revue du 2026-09-26 : une seule matrice pour TOUTES les paires du board
    rassemblait au centre global deux groupes posés loin l'un de l'autre.
    Et un composant n'appartient qu'à une paire : `paires_du_board` ne garantit
    que l'unicité du couple, pas du composant.
    """
    from tools import placement_zones as Z
    fps = {f.reference: f for f in pcb.footprints}
    vus, uniques = set(), []
    for net, d, r in paires:
        if d in vus or r in vus:
            continue
        vus |= {d, r}
        uniques.append((net, d, r))

    def centre(p):
        b = Z.boite_absolue(fps[p[1]])
        return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)

    groupes = []
    par_empreinte = {}
    for p in uniques:
        par_empreinte.setdefault((fps[p[1]].name, fps[p[2]].name), []).append(p)
    for membres in par_empreinte.values():
        restants = list(membres)
        while restants:
            groupe = [restants.pop(0)]
            ajoute = True
            while ajoute:
                ajoute = False
                for q in list(restants):
                    if any(math.dist(centre(q), centre(g)) <= _LIEN_MM for g in groupe):
                        groupe.append(q)
                        restants.remove(q)
                        ajoute = True
            groupes.append(groupe)
    return [g for g in groupes if len(g) >= _PAIRES_MIN]


def _poser_les_reperes(pcb, led, res, S) -> None:
    """Repère de la LED au-dessus d'elle, celui de la résistance dessous, à
    plat — la place que la cellule leur a réservée."""
    for fp, dessus in ((led, True), (res, False)):
        t = S._reference_visible(fp)
        if t is None:
            continue
        x0, y0, x1, y1 = Z_boite(fp)
        _, h0, _, h1 = S._boite_texte(0.0, 0.0, fp.reference, S._hauteur(t), 0.0)
        demi = (h1 - h0) / 2
        cy = y0 - _ECART_REPERE_MM - demi if dessus else y1 + _ECART_REPERE_MM + demi
        S._poser_reference(pcb, fp.reference, S._vers_local(fp, (x0 + x1) / 2, cy), 0.0)


def Z_boite(fp):
    return _Z().boite_absolue(fp)


def ranger_les_familles(pcb, figes=()) -> list:
    """Pose chaque famille de paires LED + R en matrice près de son centre
    actuel. Modifie `pcb` en place ; rend les références déplacées (vide si
    aucune famille ne tient)."""
    from tools.placement_contraintes import paires_du_board
    from tools.reglages_banc import reglage
    if not reglage("familles_rangees", True):
        # Réglage de BANC (A/B), jamais produit : désarme l'étape pour
        # produire un témoin. Nucleo, 2026-09-27 : 6, 6 et 8 couches avec
        # les familles, 2 avant — il faut le bras sans pour conclure.
        logger.info("familles : desarmees par le reglage de banc `familles_rangees`")
        return []
    Z = _Z()
    figes = set(figes or ())
    fps = {f.reference: f for f in pcb.footprints if f.reference}
    paires = [(net, d, r) for net, d, r in paires_du_board(pcb)
              if d in fps and r in fps and d not in figes and r not in figes]
    ctx = Z._contexte(pcb, figes)
    if ctx is None:
        return []
    deplaces = []
    for famille in _familles(pcb, paires):
        deplaces += _ranger_une_famille(pcb, fps, famille, ctx)
    return deplaces


def _ranger_une_famille(pcb, fps: dict, paires: list, ctx) -> list:
    Z = _Z()
    P = Z._P()
    cadre, zones, _ = ctx
    membres = {x for _, d, r in paires for x in (d, r)}

    # Orientation commune d'abord : les dimensions de la cellule en dépendent.
    rotations = {ref: fps[ref].rotation for ref in membres}
    for ref in membres:
        delta = (0.0 - float(fps[ref].rotation or 0.0)) % 360.0
        if delta:
            Z._tourner(fps[ref], delta)
    boites = {ref: Z.boite_absolue(fps[ref]) for ref in membres}
    from tools import serigraphie as S
    repere = [S._boite_texte(0.0, 0.0, ref, S._hauteur(S._reference_visible(fps[ref])), 0.0)
              for ref in membres if S._reference_visible(fps[ref]) is not None]
    l_rep = max((b[2] - b[0] for b in repere), default=0.0)
    h_rep = max((b[3] - b[1] for b in repere), default=0.0) + _ECART_REPERE_MM
    lg = max(max(b[2] - b[0] for b in boites.values()), l_rep) + _ESPACE_MM
    h_led = max(boites[d][3] - boites[d][1] for _, d, _ in paires)
    h_res = max(boites[r][3] - boites[r][1] for _, _, r in paires)
    ht = h_rep + h_led + _ESPACE_MM + h_res + h_rep + _ESPACE_MM

    cibles = {d: _cible(pcb, d, r, net) for net, d, r in paires}
    # D-2026-09-27-b (validee) : la matrice vise le barycentre des broches
    # CIBLES (celles qui pilotent les résistances), plus le centre des paires.
    # Sur les cartes à module, les LED finissaient loin du module.
    points = [c for c in cibles.values() if c is not None]
    if points:
        cx = sum(x for x, _ in points) / len(points)
        cy = sum(y for _, y in points) / len(points)
    else:
        cx = sum((b[0] + b[2]) / 2 for b in boites.values()) / len(boites)
        cy = sum((b[1] + b[3]) / 2 for b in boites.values()) / len(boites)
    obstacles = [Z.boite_absolue(f) for ref, f in fps.items() if ref not in membres]
    marge = P._MARGE_ENTRE_COURTYARDS_MM

    meilleur = None
    for rangees, colonnes in _formes(len(paires)):
        w, h = colonnes * lg - _ESPACE_MM, rangees * ht - _ESPACE_MM
        for dx, dy in _anneaux(_RAYON_MAX_MM):
            x0, y0 = cx - w / 2 + dx, cy - h / 2 + dy
            bloc = (x0, y0, x0 + w, y0 + h)
            if Z._raisons(bloc, cadre, zones):
                continue
            if any(P._boites_se_recouvrent(bloc, o, marge) for o in obstacles):
                continue
            dist = math.hypot(dx, dy)
            if meilleur is None or dist < meilleur[0]:
                meilleur = (dist, rangees, colonnes, x0, y0)
            break
    if meilleur is None:
        for ref, rot in rotations.items():
            Z._tourner(fps[ref], (float(rot or 0.0) - float(fps[ref].rotation or 0.0)) % 360.0)
        logger.info("familles : aucune place pour %d paires en matrice — laissées en place",
                    len(paires))
        return []

    _, rangees, colonnes, x0, y0 = meilleur
    ordre = sorted(paires, key=lambda p: (cibles[p[1]] or (cx, cy))[0])
    deplaces = []
    for i, (_, d, r) in enumerate(ordre):
        col, lig = divmod(i, rangees)
        gauche, haut = x0 + col * lg, y0 + lig * ht
        largeur = lg - _ESPACE_MM
        for ref, top in ((d, haut + h_rep), (r, haut + h_rep + h_led + _ESPACE_MM)):
            b = Z.boite_absolue(fps[ref])
            px, py = fps[ref].position
            # corps centré dans sa colonne : le repère, plus large, déborde
            # également des deux côtés
            dx = gauche + (largeur - (b[2] - b[0])) / 2 - b[0]
            fps[ref].position = (px + dx, py + top - b[1])
            deplaces.append(ref)
        _poser_les_reperes(pcb, fps[d], fps[r], S)
    logger.info("familles : %d paires LED + R en %d rangée(s) de %d, à %.1f mm de leur centre",
                len(paires), rangees, colonnes, meilleur[0])
    return deplaces
