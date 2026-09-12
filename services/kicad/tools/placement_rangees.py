"""Rangees de paires (LED + resistance serie) le long du bord le plus libre.

Etape 8 du pipeline « placement structure » (2026-09-11). Mesure sur carte-09
(62 composants) apres la contrainte de decouplage ET la graine hierarchique
native : le decouplage est bon (4,2-4,5 mm) mais les quinze paires LED/R
restent EPARPILLEES sur toute la carte, a 35 mm de moyenne entre elles,
chacune a un endroit different — le GA les reordonne a chaque generation et
defait la graine. Un humain les met EN RANGEE le long d un bord : lisible,
pistes courtes, LED visibles.

⚠️ CE N EST PAS UNE HEURISTIQUE DE DETECTION : les paires viennent de
`paires_du_board` (deja en production pour le snap), le bord est mesure, et
la geometrie des boitiers vient de `_centre_et_demi`. On ne fait ici que
POSER, en dernier des deplacements (avant la grille), comme le snap.

Regle :
  1. le bord retenu est celui qui a la plus grande profondeur LIBRE devant
     lui (distance du bord au premier CI ou connecteur) ;
  2. les paires sont triees selon leur position actuelle le long de ce bord
     (l ordre du GA, qui reflete grossierement l ordre des broches du CI) ;
  3. chaque LED est posee a `_MARGE_BORD_MM` du bord, sa resistance juste
     derriere elle, alignee ; le pas est celui du plus large des deux
     boitiers + `_ESPACE_MM` ; les rangees se suivent vers l interieur ;
  4. rien n est pose si la profondeur libre ne suffit pas a une rangee.

Reglage `rangees_paires` (defaut : vrai) pour l A/B.
"""
from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

_MARGE_BORD_MM: float = 4.0    # du bord au centre de la LED
_ESPACE_MM: float = 1.5        # entre deux paires d une rangee
_ESPACE_LED_R_MM: float = 1.0  # entre la LED et sa resistance
_PADS_CI: int = 8              # un CI a au moins 8 pastilles


def _actif() -> bool:
    try:
        from tools.reglages_banc import reglage
        return bool(reglage("rangees_paires", True))
    except Exception:  # noqa: BLE001
        return True


def _profondeurs_libres(pcb, figes, largeur, hauteur) -> dict:
    """Profondeur libre devant chaque bord, mesuree sur les CI et les figes."""
    from tools.placement_bypass import _boite_absolue
    haut, bas, gauche, droite = hauteur, hauteur, largeur, largeur
    for fp in pcb.footprints:
        ref = getattr(fp, "reference", None)
        if not ref:
            continue
        if ref not in figes and len(getattr(fp, "pads", None) or []) < _PADS_CI:
            continue
        x0, y0, x1, y1 = _boite_absolue(fp)
        haut, bas = min(haut, y0), min(bas, hauteur - y1)
        gauche, droite = min(gauche, x0), min(droite, largeur - x1)
    return {"haut": haut, "bas": bas, "gauche": gauche, "droite": droite}


def ranger_les_paires(pcb, paires, figes, largeur_mm: float, hauteur_mm: float) -> int:
    """Pose les paires en rangee(s) le long du bord le plus libre.
    Rend le nombre de footprints deplaces. Modifie `pcb` en place."""
    if not _actif() or not paires:
        return 0
    from tools.placement_bypass import _centre_et_demi
    figes = set(figes or ())
    par_ref = {f.reference: f for f in pcb.footprints if getattr(f, "reference", None)}
    retenues = [(a, b) for _, a, b in paires
                if a in par_ref and b in par_ref and a not in figes and b not in figes]
    if not retenues:
        return 0
    # Geometrie commune : demi-largeur max le long du bord, demi-hauteur des
    # deux boitiers en profondeur.
    demi_l = demi_p_led = demi_p_r = 0.0
    for a, b in retenues:
        _, _, hwa, hha = _centre_et_demi(par_ref[a])
        _, _, hwb, hhb = _centre_et_demi(par_ref[b])
        demi_l = max(demi_l, hwa, hwb)
        demi_p_led = max(demi_p_led, hha)
        demi_p_r = max(demi_p_r, hhb)
    pas = 2.0 * demi_l + _ESPACE_MM
    profondeur_rangee = 2.0 * (demi_p_led + demi_p_r) + _ESPACE_LED_R_MM + _ESPACE_MM
    prof = _profondeurs_libres(pcb, figes, largeur_mm, hauteur_mm)
    bord = max(prof, key=prof.get)
    if prof[bord] < _MARGE_BORD_MM + profondeur_rangee:
        logger.info("rangees : aucun bord assez libre (%.1f mm au mieux, %.1f requis) "
                    "— paires laissees en place", prof[bord], _MARGE_BORD_MM + profondeur_rangee)
        return 0
    horizontal = bord in ("haut", "bas")
    longueur = largeur_mm if horizontal else hauteur_mm
    par_rangee = max(1, int((longueur - 2.0 * _MARGE_BORD_MM) // pas))

    def _le_long(ref):
        cx, cy, _, _ = _centre_et_demi(par_ref[ref])
        return cx if horizontal else cy

    retenues.sort(key=lambda ab: _le_long(ab[0]))
    deplaces = 0
    for k, (led, res) in enumerate(retenues):
        rangee, col = divmod(k, par_rangee)
        n_dans_rangee = min(par_rangee, len(retenues) - rangee * par_rangee)
        depart = (longueur - (n_dans_rangee - 1) * pas) / 2.0
        u = depart + col * pas                       # le long du bord
        v_led = _MARGE_BORD_MM + rangee * profondeur_rangee   # profondeur LED
        v_res = v_led + demi_p_led + _ESPACE_LED_R_MM + demi_p_r
        for ref, v in ((led, v_led), (res, v_res)):
            fp = par_ref[ref]
            if bord == "haut":
                cible, rot = (u, v), 0.0
            elif bord == "bas":
                cible, rot = (u, hauteur_mm - v), 0.0
            elif bord == "gauche":
                cible, rot = (v, u), 90.0
            else:
                cible, rot = (largeur_mm - v, u), 90.0
            # `_centre_et_demi` rend le centre du CORPS ; on deplace l ORIGINE
            # du meme vecteur, pour que le corps tombe sur la cible.
            cx, cy, _, _ = _centre_et_demi(fp)
            px, py = fp.position
            nx, ny = cible[0] - (cx - px), cible[1] - (cy - py)
            if math.hypot(nx - px, ny - py) > 1e-6 or abs((getattr(fp, "rotation", 0.0) or 0.0) - rot) > 1e-6:
                fp.position = (nx, ny)
                try:
                    fp.rotation = rot
                except Exception:  # noqa: BLE001
                    pass
                deplaces += 1
    logger.info("rangees : %d paire(s) posee(s) le long du bord %s, %d par rangee, "
                "pas %.1f mm", len(retenues), bord, par_rangee, pas)
    return deplaces
