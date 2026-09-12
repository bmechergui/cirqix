"""Dégager les références de sérigraphie qui se chevauchent.

## Le reproche

Les captures de l'utilisateur du 2026-09-08 sont illisibles : « 33R6 »,
« 100C2 », « LED D2 » superposés. Ce n'est pas une impression — `carte-07`,
pourtant livrée à 100 % routé et **zéro erreur DRC**, porte 118 violations :

    silk_over_copper : 82      le texte est posé sur du cuivre exposé
    silk_overlap     : 36      deux textes se recouvrent

⚠️ Aucune n'est une erreur de fabrication — ce sont des avertissements, et le
board est fabricable. Mais c'est la première chose qu'un relecteur humain voit,
et c'est ce qui a fait dire « placement d'amateur ».

## Ce qu'on déplace, et ce qu'on ne déplace pas

**On déplace le TEXTE, jamais le composant.** C'est ce qui rend cette
correction sans risque pour le routage, contrairement à tout le reste du lot
placement : la sérigraphie ne porte aucun signal.

⚠️ **On ne réduit PAS la taille du texte.** C'est la première suggestion de
`kicad-tools` (`_suggest_silk_overlap`), et elle se retourne contre le but : une
référence illisible sur la carte fabriquée ne vaut pas mieux qu'une référence
superposée. Le repérage manuel des composants en dépend.

⚠️ **On ne le passe pas non plus en `F.Fab`.** La couche de fabrication ne
s'imprime pas : le chevauchement disparaîtrait du DRC en emportant l'information
avec lui. Faire taire une garde n'est pas la satisfaire.

## Le levier est natif

`PCB.move_reference(ref, absolute=(x, y))` — public, documenté, **jamais
appelé** par Cirqix. Quatrième levier natif inutilisé trouvé cette semaine,
après `FunctionalCluster.max_distance_mm`, `WorkflowConfig.grid` et
`constraints=`.

⚠️ `absolute` est relatif à l'ORIGINE DU BOÎTIER, pas à la carte. Confondre les
deux enverrait chaque référence à l'autre bout du board.
"""
from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

# Marge entre une référence et ce qu'elle doit éviter, en millimètres.
_MARGE_MM = 0.15

# Largeur d'un caractère, en fraction de la hauteur de police. KiCad dessine
# ses glyphes dans un carré dont la largeur utile vaut environ 0,72 de la
# hauteur, plus l'épaisseur du trait de part et d'autre.
# ⚠️ MESURE, pas estime : `kicad-cli pcb export svg` ecrit « C60 » avec
# textLength=3,15 mm pour une hauteur de 1 mm, soit 1,05 mm par caractere.
# A 0,72 la boite etait trop courte d un tiers et la sonde annoncait
# « 8 sur cuivre » la ou le DRC en comptait 95 (carte-10, 2026-09-12).
_LARGEUR_PAR_CARACTERE = 1.05

# Rayons d'essai, du plus proche au plus lointain. On s'éloigne le moins
# possible : une référence à 5 mm de son composant ne le désigne plus.
_RAYONS_MM = (0.0, 0.8, 1.6, 2.4, 3.2, 4.0)
_ANGLES = (90, 270, 0, 180, 45, 135, 225, 315)


def _boite_texte(cx: float, cy: float, texte: str, hauteur: float,
                 rot_deg: float) -> tuple[float, float, float, float]:
    """La boîte englobante d'un texte centré en (cx, cy).

    ⚠️ Une rotation de 90° échange largeur et hauteur. L'ignorer sous-estimerait
    la boîte des références verticales — c'est-à-dire précisément celles qui
    longent les rangées de passifs, là où ça se chevauche le plus.
    """
    l = max(len(texte), 1) * hauteur * _LARGEUR_PAR_CARACTERE
    h = hauteur
    if abs(math.sin(math.radians(rot_deg))) > 0.5:
        l, h = h, l
    return (cx - l / 2, cy - h / 2, cx + l / 2, cy + h / 2)


def _chevauche(a: tuple, b: tuple, marge: float = _MARGE_MM) -> bool:
    return not (a[2] + marge < b[0] or b[2] + marge < a[0]
                or a[3] + marge < b[1] or b[3] + marge < a[1])


def _angle_texte(t: Any) -> float:
    """L angle du TEXTE, tel que KiCad le dessine — jamais celui du boitier.

    ⚠️ MESURE DU 2026-09-12 (carte-10, `kicad-cli pcb export svg`) : la
    reference d une 0603 tournee de 90 degres est ecrite `(at 0 -1.43 0)` et
    KiCad la dessine A PLAT (aucun `rotate` dans le SVG, textLength 3,15 mm en
    x). L angle de la propriete est celui du rendu ; notre generateur ecrit 0
    partout. En tournant la boite avec le boitier, la sonde voyait un texte
    vertical de 1 mm de large a 0,4 mm des pastilles — « libre » — quand le
    DRC voyait un texte horizontal de 3 mm qui les recouvrait : 95 violations
    invisibles a la sonde, et une regle jamais appelee par ailleurs.
    """
    for nom in ("rotation", "angle", "orientation"):
        v = getattr(t, nom, None)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0


def _absolu(fp: Any, dx: float, dy: float) -> tuple[float, float]:
    """Une position locale du boîtier, ramenée au repère de la carte.

    ⚠️ La rotation du BOÎTIER s'applique à l'offset de son texte. L'oublier
    place correctement les références des boîtiers à 0° et déplace toutes les
    autres — un défaut qui ne se voit que sur les cartes denses.
    """
    return _tourne(fp, dx, dy)


def _tourne(fp: Any, dx: float, dy: float) -> tuple[float, float]:
    """Offset local -> absolu, dans la convention de KiCad.

    ⚠️ KiCad : y vers le BAS, rotation positive ANTIHORAIRE a l ecran — donc
    x = dx·cos + dy·sin, y = -dx·sin + dy·cos (meme formule que
    `_positions_des_pastilles` du routage). La convention mathematique
    inverse (dx·cos - dy·sin) MIROITE chaque offset des boitiers tournes :
    mesure du 2026-09-12, C60 a 90 degres, texte local (0, -1,43), le DRC le
    voit a x - 1,43 quand la sonde le mettait a x + 1,43. Sur carte-10, 51
    boitiers sur 70 sont tournes : la sonde ne regardait pas les bons
    endroits, et ses deplacements posaient les textes sur les pastilles des
    voisins (14 -> 49 `silk_over_copper` avec les contours en obstacles).
    """
    a = math.radians(getattr(fp, "rotation", 0.0) or 0.0)
    ox, oy = fp.position
    return (ox + dx * math.cos(a) + dy * math.sin(a),
            oy - dx * math.sin(a) + dy * math.cos(a))


def _reference_visible(fp: Any):
    for t in getattr(fp, "texts", []) or []:
        if (getattr(t, "text_type", "") == "reference"
                and not getattr(t, "hidden", False)
                and "Silk" in (getattr(t, "layer", "") or "")):
            return t
    return None


def _hauteur(t: Any) -> float:
    h = getattr(t, "font_height", None) or getattr(t, "font_size", None)
    if isinstance(h, (tuple, list)):
        h = h[1] if len(h) > 1 else h[0]
    return float(h) if h else 1.0


def _obstacles_cuivre(pcb: Any) -> list[tuple]:
    """Les pastilles, en absolu. C'est ce que `silk_over_copper` mesure."""
    out = []
    for fp in pcb.footprints:
        a = math.radians(getattr(fp, "rotation", 0.0) or 0.0)
        ox, oy = fp.position
        for pad in getattr(fp, "pads", []) or []:
            px, py = getattr(pad, "position", (0.0, 0.0))
            sx, sy = getattr(pad, "size", (0.0, 0.0)) or (0.0, 0.0)
            x, y = _tourne(fp, px, py)
            if abs(math.sin(a)) > 0.5:
                sx, sy = sy, sx
            out.append((x - sx / 2, y - sy / 2, x + sx / 2, y + sy / 2))
    return out


def _obstacles_serigraphie(pcb: Any) -> list[tuple]:
    """Les traits de serigraphie des empreintes (contours), en absolu.

    ⚠️ C est ce que `silk_overlap` mesure entre un texte et un contour : sur
    carte-10 (2026-09-12), 16 des 24 chevauchements restants opposaient la
    reference d une LED au contour de la resistance voisine, a 4 mm. Sans ces
    obstacles, la sonde jugeait la place « libre » et y laissait le texte.
    """
    out = []
    for fp in pcb.footprints:
        a = math.radians(getattr(fp, "rotation", 0.0) or 0.0)
        ox, oy = fp.position
        for g in getattr(fp, "graphics", []) or []:
            if "Silk" not in (getattr(g, "layer", "") or ""):
                continue
            pts = []
            for nom in ("start", "end"):
                v = getattr(g, nom, None)
                if v:
                    pts.append(v)
            pts.extend(getattr(g, "points", []) or [])
            if not pts:
                continue
            xs, ys = [], []
            for px, py in pts:
                x, y = _tourne(fp, px, py)
                xs.append(x)
                ys.append(y)
            e = (getattr(g, "stroke_width", 0.12) or 0.12) / 2
            out.append((min(xs) - e, min(ys) - e, max(xs) + e, max(ys) + e))
    return out


def boites_des_references(pcb: Any) -> dict[str, tuple]:
    """La boîte absolue de chaque référence visible sur la sérigraphie."""
    out = {}
    for fp in pcb.footprints:
        t = _reference_visible(fp)
        if t is None or not fp.reference:
            continue
        dx, dy = getattr(t, "position", (0.0, 0.0))
        cx, cy = _absolu(fp, dx, dy)
        out[fp.reference] = _boite_texte(cx, cy, fp.reference, _hauteur(t),
                                         _angle_texte(t))
    return out


def compter_chevauchements(pcb: Any) -> tuple[int, int]:
    """(references sur du cuivre, paires de references qui se recouvrent).

    ⚠️ Ce compte est une APPROXIMATION géométrique, pas le DRC. Il sert à
    itérer sans conteneur ; le verdict reste `kicad-cli pcb drc`. Les deux ne
    donneront pas le même nombre, et c'est normal — l'un compte des boîtes, and
    l'autre les vraies formes des glyphes.
    """
    boites = boites_des_references(pcb)
    cuivre = _obstacles_cuivre(pcb) + _obstacles_serigraphie(pcb)
    sur_cuivre = sum(1 for b in boites.values()
                     if any(_chevauche(b, c) for c in cuivre))
    refs = sorted(boites)
    entre_eux = sum(1 for i, r in enumerate(refs) for s in refs[i + 1:]
                    if _chevauche(boites[r], boites[s]))
    return sur_cuivre, entre_eux


def degager_references(pcb: Any) -> int:
    """Déplace les références qui chevauchent. Rend le nombre de déplacements.

    ⚠️ ON NE DÉPLACE QUE CE QUI CHEVAUCHE. Une référence déjà bien placée qu'on
    « améliore » est une régression déguisée — même règle que le snap, pour la
    même raison.

    ⚠️ ET SEULEMENT SI ON TROUVE MIEUX. Si aucun essai n'est libre, on laisse en
    place : un texte déplacé au hasard chevauche autant et ne désigne plus son
    composant.
    """
    cuivre = _obstacles_cuivre(pcb) + _obstacles_serigraphie(pcb)
    boites = boites_des_references(pcb)
    par_ref = {fp.reference: fp for fp in pcb.footprints if fp.reference}
    deplaces = 0

    for ref in sorted(boites):
        fp = par_ref.get(ref)
        t = _reference_visible(fp) if fp else None
        if t is None:
            continue
        autres = [b for r, b in boites.items() if r != ref]
        genes = cuivre + autres
        if not any(_chevauche(boites[ref], o) for o in genes):
            continue

        haut = _hauteur(t)
        rot = _angle_texte(t)
        dx0, dy0 = getattr(t, "position", (0.0, 0.0))
        trouve = None
        for rayon in _RAYONS_MM:
            for ang in _ANGLES:
                if rayon == 0.0 and ang != _ANGLES[0]:
                    continue
                ndx = dx0 + rayon * math.cos(math.radians(ang))
                ndy = dy0 + rayon * math.sin(math.radians(ang))
                cx, cy = _absolu(fp, ndx, ndy)
                b = _boite_texte(cx, cy, ref, haut, rot)
                if not any(_chevauche(b, o) for o in genes):
                    trouve = (ndx, ndy, b)
                    break
            if trouve:
                break

        if trouve is None:
            logger.debug("serigraphie: %s — aucune place libre, non deplacee", ref)
            continue

        ndx, ndy, b = trouve
        if pcb.move_reference(ref, absolute=(ndx, ndy)):
            boites[ref] = b
            deplaces += 1

    if deplaces:
        logger.info("serigraphie: %d reference(s) degagee(s)", deplaces)
    return deplaces
