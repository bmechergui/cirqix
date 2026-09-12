"""La carte est-elle assez grande pour ses composants ? Vérifier AVANT de placer.

## Le défaut, et pourquoi corriger une carte ne suffisait pas

Mesure du 2026-09-09 sur `carte-11-croisements`. Le schéma demandait deux
connecteurs 2×20 verticaux — 48,3 mm chacun — sur une carte de 90 × 60 mm.

    reparation hors-carte : J1 (encombrement 51,1 mm) ne tient pas dans le contour

Aucune position n'existait : sur 60 mm de haut, la plage valide valait
`60 − 2 × 51,1 = −42 mm`, une **plage négative**. Le placement renonçait — à
juste titre — `J1` sortait de 43,3 mm, et Freerouting n'avait rien à router.
La carte sortait à **3 % routé, 42 erreurs**, depuis des semaines.

J'ai cherché du côté du routeur, de l'escalade de couches, du nombre de tirages.
Six tirages perdus avant de mesurer la géométrie.

⚠️ **AGRANDIR CETTE CARTE-LÀ NE CORRIGE RIEN.** La prochaine carte trop petite
échouera identiquement, et le dimensionnement vient d'un modèle de langage : il
sera plausible et faux aussi souvent qu'on le lui demandera. C'est la remarque
de l'utilisateur — « je veux toujours une solution générale, pas une solution
de bricolage liée à chaque carte ».

## Ce que ce module fait

Avant toute génération, il additionne l'encombrement des composants et le
compare au contour demandé. Trois issues :

    ça tient                    on ne touche à rien
    ça ne tient pas             on AGRANDIT, et on le dit
    un seul composant est
    plus grand que la carte     on AGRANDIT pour lui, et on le dit fort

⚠️ **ON AGRANDIT, ON NE REFUSE PAS.** Une carte trop petite produit un board
inutilisable qui traverse tout le pipeline sans que rien ne le signale — c'est
ce qui vient de coûter des semaines. Une carte agrandie reste fabricable ; elle
coûte seulement un peu plus de substrat.

⚠️ **ET ON NE RÉTRÉCIT JAMAIS.** Le dimensionnement peut porter une intention
que nous ignorons — un boîtier, un connecteur à un emplacement précis. On ne
retire que l'impossible.
"""
from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

# Marge de bord, en millimètres. Reprend `_OFF_BOARD_MARGIN_MM` du placement :
# c'est la même contrainte, il ne faut pas qu'elles divergent.
_MARGE_BORD_MM = 2.0

# Facteur de remplissage praticable. Un placeur ne remplit jamais 100 % d'une
# carte : il faut des canaux de routage entre les composants. 0,45 est la valeur
# usuelle pour une carte à deux couches ; au-delà, le routeur étouffe.
_REMPLISSAGE = 0.45

# Pas de la grille d'arrondi, en millimètres. Une carte de 137,3 mm n'a pas de
# sens en fabrication ; on arrondit au multiple supérieur.
_PAS_MM = 10.0


def _boite(fp) -> tuple[float, float]:
    """Les dimensions RÉELLES d'une empreinte, en millimètres.

    ⚠️ ON MESURE UNE BOÎTE, PAS UN RAYON. Première version de ce module :
    surface estimée par `π × portée²`, la portée venant de
    `_footprint_reach_mm`. Pour un connecteur 2×20 — 48 × 5 mm — cela rend un
    disque de 49 mm de rayon, soit **7500 mm² au lieu de 240**, trente fois
    trop. `carte-11`, qui route à 100 % en 140 × 120, se voyait réclamer
    190 × 190.

    Une carte inutilement agrandie coûte du substrat et éloigne les composants,
    donc allonge les pistes. Sur-estimer n'est pas « prudent », c'est faux.
    """
    pads = list(getattr(fp, "pads", []) or [])
    if not pads:
        return (4.0, 4.0)
    xs, ys = [], []
    for pad in pads:
        px, py = getattr(pad, "position", (0.0, 0.0))
        sx, sy = getattr(pad, "size", (0.0, 0.0)) or (0.0, 0.0)
        xs += [px - sx / 2, px + sx / 2]
        ys += [py - sy / 2, py + sy / 2]
    a = math.radians(getattr(fp, "rotation", 0.0) or 0.0)
    l, h = max(xs) - min(xs), max(ys) - min(ys)
    if abs(math.sin(a)) > 0.5:
        l, h = h, l
    return (max(l, 1.0), max(h, 1.0))


def _encombrement(fp) -> float:
    """L'encombrement TEL QUE LE PLACEMENT LE MESURE.

    ⚠️ ON APPELLE LA MÊME FONCTION QUE `_repair_off_board`, et c'est tout
    l'intérêt. Première version : demi-diagonale de la boîte, soit 24,3 mm pour
    un connecteur 2×20. Le placement, lui, lit `_footprint_reach_mm` et obtient
    **49,1 mm** — le double. Ma règle validait donc `carte-11` en 90 × 60, la
    dimension exacte où le placement renonçait.

    Une vérification calibrée sur une source VOISINE de celle que le code lit
    laisse passer précisément le cas qu'elle doit attraper. Ce dépôt l'a déjà
    payé deux fois — le plancher d'échappement calibré sur `circuit.json` quand
    le code lisait le board, et le banc de dogbones calibré sur `expected/`
    quand le conteneur lit `output/`.
    """
    try:
        from tools.placement import _footprint_reach_mm
        return float(_footprint_reach_mm(fp))
    except Exception:  # noqa: BLE001
        # ⚠️ Repli LARGE : la diagonale entière, pas la moitié. Sous-estimer
        # rend la garde inutile ; sur-estimer coûte du substrat.
        l, h = _boite(fp)
        return math.hypot(l, h)


def taille_minimale(pcb) -> tuple[float, float, str]:
    """La taille minimale que la carte doit avoir. Rend `(largeur, hauteur, raison)`.

    Deux contraintes, et c'est **la plus forte des deux** qui décide :

    1. **La surface.** La somme des surfaces d'encombrement, divisée par le
       facteur de remplissage praticable.
    2. **Le plus gros composant.** ⚠️ C'est celle qui manquait, et c'est celle
       qui a fait échouer `carte-11` : un connecteur de 49 mm de rayon exige
       `2 × (49 + marge)` dans CHAQUE dimension, quelle que soit la surface
       totale. Une carte peut avoir dix fois la surface nécessaire et rester
       inutilisable parce qu'un seul boîtier n'y entre pas.
    """
    fps = [f for f in getattr(pcb, "footprints", []) or [] if getattr(f, "reference", None)]
    if not fps:
        return (0.0, 0.0, "aucun composant")

    portees = [(f.reference, _encombrement(f)) for f in fps]
    # ⚠️ La surface d une empreinte est celle de sa BOITE, pas d un disque de
    # rayon egal a sa demi-diagonale — voir `_boite`.
    surface = sum(l * h for l, h in (_boite(f) for f in fps)) / _REMPLISSAGE
    cote_surface = math.sqrt(surface)

    ref_max, portee_max = max(portees, key=lambda x: x[1])
    cote_composant = 2 * (portee_max + _MARGE_BORD_MM)

    if cote_composant >= cote_surface:
        raison = ("le plus gros composant, %s (encombrement %.1f mm), exige "
                  "%.0f mm dans chaque dimension" % (ref_max, portee_max, cote_composant))
        cote = cote_composant
    else:
        raison = ("la surface des %d composants exige %.0f mm de cote a %.0f %% "
                  "de remplissage" % (len(fps), cote_surface, _REMPLISSAGE * 100))
        cote = cote_surface

    arrondi = math.ceil(cote / _PAS_MM) * _PAS_MM
    return (arrondi, arrondi, raison)


def verifier_et_agrandir(pcb, largeur: float, hauteur: float) -> tuple[float, float]:
    """Rend `(largeur, hauteur)` — agrandies si la carte demandée est trop petite.

    ⚠️ On agrandit CHAQUE dimension separement : une carte peut etre assez large
    et trop courte, comme `carte-11` (90 x 60, il fallait 110 dans les deux).
    """
    mini_l, mini_h, raison = taille_minimale(pcb)
    if mini_l <= 0:
        return (largeur, hauteur)

    nl, nh = max(largeur, mini_l), max(hauteur, mini_h)
    if nl <= largeur and nh <= hauteur:
        return (largeur, hauteur)

    logger.warning(
        "taille de carte: %.0fx%.0f mm INSUFFISANTE — agrandie a %.0fx%.0f mm ; %s",
        largeur, hauteur, nl, nh, raison)
    return (nl, nh)
