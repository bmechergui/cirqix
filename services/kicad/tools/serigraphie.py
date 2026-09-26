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

# Marge entre une référence et le bord de la carte. `silk_edge_clearance`
# (« Silkscreen clipped by board edge ») tombe dès que le texte touche le contour.
_MARGE_BORD_MM = 0.25


def _contour(pcb: Any) -> tuple[float, float, float, float] | None:
    """Le contour Edge.Cuts dans le repère des positions, ou None s'il est illisible.

    ⚠️ Mesure du 2026-09-15 : 2 runs sur 5 du prompt « diviseur de tension »
    livraient la référence de R2 au-delà du bord haut (texte y 92,22 pour un
    bord à 92,45). Le bord n'était pas un obstacle : une place hors carte était
    « libre ». Sans contour lisible, on garde l'ancien comportement.
    """
    try:
        from tools.contour_et_bords import _contour_repere_board
        return _contour_repere_board(pcb)
    except Exception:  # noqa: BLE001 — un faux board de test n'a pas de contour
        return None


def _deborde(boite: tuple, contour: tuple | None, marge: float = _MARGE_BORD_MM) -> bool:
    if contour is None:
        return False
    x0, y0, x1, y1 = contour
    return (boite[0] < x0 + marge or boite[1] < y0 + marge
            or boite[2] > x1 - marge or boite[3] > y1 - marge)


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
                                         _angle(pcb, fp, t))
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
    contour = _contour(pcb)
    deplaces = 0

    for ref in sorted(boites):
        fp = par_ref.get(ref)
        t = _reference_visible(fp) if fp else None
        if t is None:
            continue
        autres = [b for r, b in boites.items() if r != ref]
        genes = cuivre + autres
        # Une référence coupée par le bord est aussi mal placée qu'une référence
        # posée sur du cuivre.
        if not any(_chevauche(boites[ref], o) for o in genes) and not _deborde(boites[ref], contour):
            continue

        haut = _hauteur(t)
        rot = _angle(pcb, fp, t)
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
                if not any(_chevauche(b, o) for o in genes) and not _deborde(b, contour):
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


# ── D-2026-09-26-a, phase B : repère TOURNÉ dans l axe du boîtier, posé AUTOUR
# de son corps. Campagne du 2026-09-26, carte-07 : 9 repères en conflit, et la
# recherche ci-dessus (texte à plat, 4 mm autour de sa position d origine) n en
# plaçait AUCUN — « aucune place libre » pour les 9. Les deux leviers
# manquants : tourner le texte (une 0603 verticale porte un repère vertical,
# 1 mm de large au lieu de 3), et chercher contre les quatre côtés et les quatre
# coins du CORPS plutôt qu autour d une origine posée sur une pastille.
#
# ⚠️ Rien de natif : `kct fix-silkscreen` ne corrige que les épaisseurs et les
# hauteurs, `SilkscreenGenerator` rend visibles des repères cachés. Et le
# modèle `FootprintText` ne lit pas l angle du texte : on le lit et on
# l écrit dans l arbre S-expr, troisième terme de `(at x y a)`, ABSOLU.
#
# ⚠️ Toujours ni réduction, ni masquage (D-2026-09-26-a : NON autorisés).

# Écarts au corps, du plus serré au plus lâche : au-delà de 1,4 mm un repère
# ne désigne plus clairement son composant dans un amas.
_ECARTS_CORPS_MM = (0.2, 0.7, 1.4)
# Passes : placer un repère libère parfois la place d un autre.
_PASSES = 3
_GLISSEMENTS_MM = (0.0, 0.6, -0.6, 1.2, -1.2, 2.0, -2.0)


def _noeud_reference(pcb: Any, ref: str):
    """Le nœud `at` du repère de `ref` dans l arbre, ou None."""
    arbre = getattr(pcb, "_sexp", None)
    if arbre is None:
        return None
    for fp in arbre.iter_children():
        if fp.tag != "footprint" or pcb._get_footprint_reference(fp) != ref:
            continue
        for tag, cle in (("property", "Reference"), ("fp_text", "reference")):
            for t in fp.find_all(tag):
                if t.get_string(0) == cle:
                    return t.find("at")
    return None


def _angle(pcb: Any, fp: Any, t: Any) -> float:
    """L angle du repère tel qu il est ÉCRIT dans le fichier, seul lecteur.

    ⚠️ Revue du 2026-09-26 : `_angle_texte` lit le modèle `FootprintText`, qui
    ne parse aucun angle — il rend 0 pour un texte que `reorienter_et_degager`
    vient de tourner. Rejouée après le resserrage du contour, la recherche
    à plat calculait alors des boîtes horizontales pour des textes verticaux.
    """
    if _noeud_reference(pcb, fp.reference) is not None:
        return _angle_reference(pcb, fp.reference)
    return _angle_texte(t)


def _angle_reference(pcb: Any, ref: str) -> float:
    at = _noeud_reference(pcb, ref)
    if at is None:
        return 0.0
    try:
        return float(at.get_float(2) or 0.0)
    except (IndexError, TypeError, ValueError):
        return 0.0


def _poser_reference(pcb: Any, ref: str, local: tuple, angle: float) -> bool:
    if not pcb.move_reference(ref, absolute=local):
        return False
    at = _noeud_reference(pcb, ref)
    if at is not None:
        at.set_value(2, angle)
    return True


def _vers_local(fp: Any, x: float, y: float) -> tuple[float, float]:
    """Inverse de `_tourne` : absolu -> offset local du boîtier."""
    a = math.radians(getattr(fp, "rotation", 0.0) or 0.0)
    ox, oy = fp.position
    u, v = x - ox, y - oy
    return (u * math.cos(a) - v * math.sin(a), u * math.sin(a) + v * math.cos(a))


def _corps(fp: Any) -> tuple:
    from tools.placement import _boite_orientee_fp
    b = _boite_orientee_fp(fp)
    x, y = fp.position
    return (x + b[0], y + b[1], x + b[2], y + b[3])


def _candidats(corps: tuple, texte: str, hauteur: float, angle_actuel: float):
    """(angle, boîte) à essayer, du meilleur au pire : texte dans l axe du
    corps d abord, contre ses grands côtés, puis ses petits côtés, puis ses
    coins ; chaque place glisse ensuite le long de son côté."""
    x0, y0, x1, y1 = corps
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    horizontal = (x1 - x0) >= (y1 - y0)
    axe = 0.0 if horizontal else 90.0
    # Les boîtes ne savent traiter que 0 et 90 : un angle quelconque est
    # ramené au cardinal le plus proche.
    actuel = (round(angle_actuel / 90.0) * 90.0) % 180.0
    angles = [axe] + [a for a in (actuel, 90.0 - axe) if a != axe]
    vus = set()
    for g, angle in ((g, a) for g in _ECARTS_CORPS_MM for a in dict.fromkeys(angles)):
        l0, h0, l1, h1 = _boite_texte(0.0, 0.0, texte, hauteur, angle)
        w, h = l1 - l0, h1 - h0
        haut, bas = (cx, y0 - g - h / 2), (cx, y1 + g + h / 2)
        gauche, droite = (x0 - g - w / 2, cy), (x1 + g + w / 2, cy)
        cotes_x = [(haut, True), (bas, True)]          # glisse le long de x
        cotes_y = [(gauche, False), (droite, False)]   # glisse le long de y
        coins = [((x0 - g - w / 2, y0 - g - h / 2), True), ((x1 + g + w / 2, y0 - g - h / 2), True),
                 ((x0 - g - w / 2, y1 + g + h / 2), True), ((x1 + g + w / 2, y1 + g + h / 2), True)]
        places = (cotes_x + cotes_y if horizontal else cotes_y + cotes_x) + coins
        for (px, py), le_long_de_x in places:
            for d in _GLISSEMENTS_MM:
                qx, qy = (px + d, py) if le_long_de_x else (px, py + d)
                cle = (angle, round(qx, 3), round(qy, 3))
                if cle in vus:
                    continue
                vus.add(cle)
                yield angle, (qx, qy), _boite_texte(qx, qy, texte, hauteur, angle)


def reorienter_et_degager(pcb: Any) -> int:
    """Seconde chance pour les repères que `degager_references` n a pas su
    placer : texte tourné dans l axe du boîtier, posé contre son corps.

    Mêmes règles : on ne touche QUE ce qui chevauche encore, et seulement si
    une place libre existe ; sinon le repère reste où il est.
    """
    cuivre = _obstacles_cuivre(pcb) + _obstacles_serigraphie(pcb)
    par_ref = {fp.reference: fp for fp in pcb.footprints if fp.reference}
    contour = _contour(pcb)
    boites = {}
    for ref, fp in par_ref.items():
        t = _reference_visible(fp)
        if t is None:
            continue
        dx, dy = getattr(t, "position", (0.0, 0.0))
        cx, cy = _absolu(fp, dx, dy)
        boites[ref] = _boite_texte(cx, cy, ref, _hauteur(t), _angle(pcb, fp, t))
    deplaces = 0
    for ref in sorted(boites) * _PASSES:
        fp = par_ref[ref]
        genes = cuivre + [b for r, b in boites.items() if r != ref]
        if not any(_chevauche(boites[ref], o) for o in genes) and not _deborde(boites[ref], contour):
            continue
        t = _reference_visible(fp)
        trouve = None
        for angle, (qx, qy), b in _candidats(_corps(fp), ref, _hauteur(t), _angle_reference(pcb, ref)):
            if not any(_chevauche(b, o) for o in genes) and not _deborde(b, contour):
                trouve = (angle, (qx, qy), b)
                break
        if trouve is None:
            logger.debug("serigraphie: %s — aucune place autour du corps", ref)
            continue
        angle, (qx, qy), b = trouve
        if _poser_reference(pcb, ref, _vers_local(fp, qx, qy), angle):
            boites[ref] = b
            deplaces += 1
    if deplaces:
        logger.info("serigraphie: %d reference(s) reorientee(s) contre leur corps", deplaces)
    return deplaces
