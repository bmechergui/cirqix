"""Placement « pro » : connecteurs couchés au bord, zones interdites, marge au bord.

D-2026-09-26-a, validée par l'utilisateur le 2026-09-26 (« oui »), sur ses
propres mots à propos de nucleo-f401 : « il ne faut pas […] faire des
composants en dessous ou dans le bord ». Trois règles, pour toutes les cartes :

1. un connecteur est COUCHÉ le long de son bord — grand axe parallèle — puis
   collé à `MARGE_CONNECTEUR_BORD_MM`. Mesure du 2026-09-26 sur les 15 boards
   de la campagne : 48 connecteurs sur 48 à 2 mm d'un bord, mais 35 DEBOUT,
   plongeant de 6 à 11 mm dans la carte (52 mm pour un 2×20).
   `_position_au_bord` translate et ne tourne jamais : c'était le trou ;
2. rien sous ni autour d'un connecteur : bande de `BANDE_CONNECTEUR_MM` ;
3. rien contre le bord : le corps de tout autre composant reste à
   `MARGE_BORD_MM` du contour.

Les distances se mesurent sur le CORPS orienté (`_boite_orientee_fp`), jamais
sur l'origine — leçon du 2026-09-21 : l'origine d'un en-tête est sur sa broche 1.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

logger = logging.getLogger(__name__)

MARGE_BORD_MM: float = 1.5            # corps–bord, tout composant hors connecteurs
BANDE_CONNECTEUR_MM: float = 1.5      # zone interdite autour d'un connecteur
# Un connecteur collé à son bord. La proposition disait 1 mm ; mesuré le
# 2026-09-26 : à 1 mm, `PlacementAnalyzer` le compte HORS CARTE et le filet
# `_repair_off_board` le repousse — deux règles qui se combattent. On garde
# donc la marge du clamp existant, 2 mm : le connecteur reste AU BORD.
MARGE_CONNECTEUR_BORD_MM: float = 2.0
_PAS_MM: float = 0.5                  # pas de la grille de placement
_RAYON_MAX_MM: float = 40.0
_CARRE_MM: float = 0.5                # en dessous, un corps n'a pas de grand axe


def _P():
    from tools import placement as P  # import tardif : placement importe ce module
    return P


def boite_absolue(fp) -> tuple:
    """Corps orienté du footprint, en coordonnées board."""
    b = _P()._boite_orientee_fp(fp)
    x, y = fp.position
    return (x + b[0], y + b[1], x + b[2], y + b[3])


def _bord_le_plus_proche(boite: tuple, bornes: tuple) -> str:
    x0, x1, y0, y1 = bornes
    distances = {"gauche": boite[0] - x0, "droite": x1 - boite[2],
                 "haut": boite[1] - y0, "bas": y1 - boite[3]}
    return min(distances, key=distances.get)


def _parallele(boite: tuple, bord: str) -> bool:
    largeur, hauteur = boite[2] - boite[0], boite[3] - boite[1]
    if abs(largeur - hauteur) < _CARRE_MM:
        return True
    return largeur >= hauteur if bord in ("haut", "bas") else hauteur >= largeur


def parallele_a_son_bord(pcb, ref: str) -> bool:
    """Le grand axe du corps de `ref` longe-t-il le bord le plus proche ?"""
    bornes = _P()._outline_bounds(pcb)
    fp = next(f for f in pcb.footprints if f.reference == ref)
    if bornes is None:
        return True
    boite = boite_absolue(fp)
    return _parallele(boite, _bord_le_plus_proche(boite, bornes))


def _tourner(fp, delta: float) -> None:
    """Tourne le boîtier ET l'angle absolu de chaque pastille du même pas —
    le 3ᵉ terme de `(at x y a)` d'une pastille est absolu (kicad-tools #3902)."""
    fp.rotation = (float(fp.rotation or 0.0) + delta) % 360.0
    for pad in fp.pads:
        pad.rotation = (float(pad.rotation or 0.0) + delta) % 360.0


def coucher_les_connecteurs(pcb, conn: list, exempts=()) -> dict:
    """Couche chaque connecteur debout le long du bord le plus proche de son
    corps. Rend {référence tournée: angle ajouté}. Un connecteur qui, couché, ne tiendrait
    plus dans la carte, ou ne serait toujours pas parallèle à son bord, garde
    son orientation : on ne dégrade jamais un ancrage pour l'y forcer."""
    bornes = _P()._outline_bounds(pcb)
    if bornes is None:
        return []
    x0, x1, y0, y1 = bornes
    ignores = set(exempts or ())
    tournes = {}
    for fp in pcb.footprints:
        if fp.reference not in conn or fp.reference in ignores:
            continue
        boite = boite_absolue(fp)
        if _parallele(boite, _bord_le_plus_proche(boite, bornes)):
            continue
        for delta in (90.0, 270.0):
            _tourner(fp, delta)
            b = boite_absolue(fp)
            tient = (b[2] - b[0] <= x1 - x0 - 2 * MARGE_CONNECTEUR_BORD_MM
                     and b[3] - b[1] <= y1 - y0 - 2 * MARGE_CONNECTEUR_BORD_MM)
            if tient and _parallele(b, _bord_le_plus_proche(b, bornes)):
                tournes[fp.reference] = delta
                logger.info("placement : connecteur %s couché le long du bord %s",
                            fp.reference, _bord_le_plus_proche(b, bornes))
                break
            _tourner(fp, -delta)
    return tournes


def redresser_les_conflits(pcb, tournes: dict) -> list:
    """Rend son orientation d'origine à tout connecteur couché qui, une fois
    collé, recouvre un autre connecteur. Les connecteurs sont figés pour
    l'optimiseur, et la réparation DRC ne sépare jamais deux figés : un tel
    recouvrement ne serait rattrapé par personne (revue du 2026-09-26). Le
    contrôle vient APRÈS le collage — avant, deux en-têtes voisins debout se
    recouvriraient une fois couchés sur place, alors que le collage les écarte.
    Rend les références redressées ; l'appelant les recolle."""
    marge = _P()._MARGE_ENTRE_COURTYARDS_MM
    conn = {f.reference: f for f in pcb.footprints}
    redresses = []
    for ref, delta in tournes.items():
        fp = conn.get(ref)
        if fp is None:
            continue
        b = boite_absolue(fp)
        autres = [r for r in conn if r != ref and r in _P()._connector_refs(pcb)]
        if any(_P()._boites_se_recouvrent(b, boite_absolue(conn[r]), marge) for r in autres):
            _tourner(fp, -delta)
            redresses.append(ref)
            logger.warning("placement : connecteur %s laissé debout — couché, il "
                           "recouvrait un autre connecteur", ref)
    return redresses


def _gonfler(boite: tuple, marge: float) -> tuple:
    return (boite[0] - marge, boite[1] - marge, boite[2] + marge, boite[3] + marge)


def _dedans(boite: tuple, cadre: tuple) -> bool:
    return (boite[0] >= cadre[0] - 1e-6 and boite[2] <= cadre[1] + 1e-6
            and boite[1] >= cadre[2] - 1e-6 and boite[3] <= cadre[3] + 1e-6)


def _chevauche(a: tuple, b: tuple) -> bool:
    return a[0] < b[2] - 1e-6 and b[0] < a[2] - 1e-6 and a[1] < b[3] - 1e-6 and b[1] < a[3] - 1e-6


def _contexte(pcb, figes):
    P = _P()
    bornes = P._outline_bounds(pcb)
    if bornes is None:
        return None
    # La plus stricte des deux marges validées : 1,5 mm (D-2026-09-26-a) et
    # 2 mm courtyard–bord (D-2026-09-15-a), que `_repair_off_board` applique.
    m = max(MARGE_BORD_MM, P._MARGE_COURTYARD_BORD_MM)
    cadre = (bornes[0] + m, bornes[1] - m, bornes[2] + m, bornes[3] - m)
    connecteurs = set(P._connector_refs(pcb))
    zones = {fp.reference: _gonfler(boite_absolue(fp), BANDE_CONNECTEUR_MM)
             for fp in pcb.footprints if fp.reference in connecteurs}
    # Les zones sont figées ici : les connecteurs sont exemptés, donc jamais
    # déplacés par `respecter_les_zones`.
    exemptes = connecteurs | set(figes or ())
    return cadre, zones, exemptes


def _raisons(boite: tuple, cadre: tuple, zones: dict) -> list:
    raisons = [] if _dedans(boite, cadre) else ["bord"]
    raisons += ["connecteur " + r for r, z in zones.items() if _chevauche(boite, z)]
    return raisons


def violations_de_zones(pcb, figes=()) -> list:
    """(référence, raison) de chaque composant qui touche le bord ou la zone
    d'un connecteur. Liste vide = les deux règles tiennent."""
    ctx = _contexte(pcb, figes)
    if ctx is None:
        return []
    cadre, zones, exemptes = ctx
    return [(fp.reference, r) for fp in pcb.footprints if fp.reference not in exemptes
            for r in _raisons(boite_absolue(fp), cadre, zones)]


def _anneau(rayon: float):
    """Décalages sur le carré de demi-côté `rayon`, du plus proche au plus loin."""
    n = int(round(rayon / _PAS_MM))
    pts = {(i * _PAS_MM, j * _PAS_MM) for i in range(-n, n + 1) for j in (-n, n)}
    pts |= {(i * _PAS_MM, j * _PAS_MM) for j in range(-n, n + 1) for i in (-n, n)}
    return sorted(pts, key=lambda d: (math.hypot(*d), d))


def respecter_les_zones(pcb_path: Path, figes=()) -> list:
    """Écarte du bord et des connecteurs tout composant qui y touche, vers la
    place libre la plus proche (pas de la grille, aucun chevauchement créé).
    Rend les références déplacées. `figes` n'est jamais déplacé."""
    from kicad_tools.schema.pcb import PCB

    pcb = PCB.load(str(pcb_path))
    ctx = _contexte(pcb, figes)
    if ctx is None:
        return []
    cadre, zones, exemptes = ctx
    boites = {fp.reference: boite_absolue(fp) for fp in pcb.footprints}
    marge = _P()._MARGE_ENTRE_COURTYARDS_MM
    deplaces = []
    for fp in sorted(pcb.footprints, key=lambda f: f.reference):
        ref = fp.reference
        if ref in exemptes or not _raisons(boites[ref], cadre, zones):
            continue
        x, y = fp.position
        b = boites[ref]
        trouve = None
        rayon = _PAS_MM
        while trouve is None and rayon <= _RAYON_MAX_MM:
            for dx, dy in _anneau(rayon):
                nb = (b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy)
                if _raisons(nb, cadre, zones):
                    continue
                if any(_P()._boites_se_recouvrent(nb, o, marge)
                       for r, o in boites.items() if r != ref):
                    continue
                trouve = (dx, dy, nb)
                break
            rayon += _PAS_MM
        if trouve is None:
            logger.warning("placement : %s touche %s, aucune place libre à %.0f mm",
                           ref, ", ".join(_raisons(b, cadre, zones)), _RAYON_MAX_MM)
            continue
        dx, dy, nb = trouve
        fp.position = (x + dx, y + dy)
        boites[ref] = nb
        deplaces.append(ref)
    if deplaces:
        pcb.save(str(pcb_path))
        logger.info("placement : %d composant(s) écarté(s) du bord ou d'un connecteur (%s)",
                    len(deplaces), ", ".join(deplaces))
    return deplaces
