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

import logging
import math
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

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


def _centre_et_demi(fp) -> tuple[float, float, float, float]:
    """Centre du CORPS (absolu) et demi-extensions ``(cx, cy, hw, hh)``."""
    x0, y0, x1, y1 = _boite_absolue(fp)
    return (x0 + x1) / 2.0, (y0 + y1) / 2.0, (x1 - x0) / 2.0, (y1 - y0) / 2.0


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
    from kicad_tools.optim.clustering import detect_functional_clusters

    clusters = detect_functional_clusters(_composants(pcb))
    if not clusters:
        return 0

    par_ref = {fp.reference: fp for fp in pcb.footprints if fp.reference}
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

            cible = portee + marge
            ncx, ncy = acx + ux * cible, acy + uy * cible
            fp.position = (fp.position[0] + (ncx - mcx),
                           fp.position[1] + (ncy - mcy))
            deplaces += 1
            logger.debug("snap %s -> %s : %.1fmm libre -> %.1fmm",
                         ref, cluster.anchor, dist - portee, marge)

    return deplaces
