"""Carte de DÉPART dimensionnée sur la surface réelle des composants.

## Le constat (relecture du banc, 2026-09-19)

carte-09 : 62 composants sur 130 × 100 mm. Leurs courtyards couvrent
662 mm², soit **5 %** de la carte ; carte-10 4,7 %, carte-08 5,4 %. Le reste
est vide, et c'est la première chose qu'un relecteur voit.

Le resserrage du contour (D-2026-09-13-c A) ne rattrape rien : il s'arrête à
la boîte des composants, et le placement les a déjà étalés sur toute la
surface reçue — même hors connecteurs, la boîte de carte-09 fait 127 × 97 mm.
Ce n'est pas le contour final qui est trop grand, c'est la surface de DÉPART.

## Ce que ce module fait — derrière un réglage de banc, DÉSARMÉ

Quand la taille n'est pas imposée (`auto_size_board`) et que le réglage
`occupation_cible` est posé, la carte de départ est ramenée à la surface
`somme des courtyards / occupation`, aux proportions de la carte demandée, et
les composants mobiles sont renvoyés hors carte pour que `place_unplaced`
(natif) les rapatrie dans ce contour compact avant l'optimisation. Les
connecteurs, ancrés, sont ramenés dans le contour par le clamp existant.

⚠️ Mesure A/B d'abord : ce dépôt a mesuré que la SURFACE aide le routage
(carte-08, 216 connexions manquantes → 0 en l'agrandissant, 2026-09-07). Le
taux d'occupation est une décision produit, pas un réglage technique.
"""
from __future__ import annotations

import base64
import logging
import math
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Hors carte : sous le seuil que `_auto_place_une_fois` traite comme « non
# placé » (< -100 mm) et rapatrie par `place_unplaced`.
_HORS_CARTE_MM = -1000.0


def occupation_cible() -> float:
    """Taux visé (0 = règle désarmée, le défaut). Relu à chaque appel."""
    from tools.reglages_banc import reglage
    try:
        return float(reglage("occupation_cible", 0.0))
    except (TypeError, ValueError):
        logger.error("carte compacte : occupation_cible illisible — regle desarmee")
        return 0.0


def taille_compacte(surface_mm2: float, largeur: float, hauteur: float,
                    occupation: float) -> Optional[tuple[float, float]]:
    """(largeur, hauteur) visées, aux proportions de la carte ; None si rien à gagner.

    On ne fait que RÉDUIRE : une carte déjà plus petite que la cible garde sa
    taille (la vérification de taille minimale l'agrandira si besoin).
    """
    if surface_mm2 <= 0 or largeur <= 0 or hauteur <= 0 or not 0 < occupation < 1:
        return None
    visee = surface_mm2 / occupation
    if visee >= largeur * hauteur:
        return None
    ratio = largeur / hauteur
    l = math.sqrt(visee * ratio)
    return (round(l, 1), round(visee / l, 1))


def compacter_la_carte_de_depart(kicad_pcb_b64: str, largeur: float, hauteur: float,
                                 occupation: float) -> tuple[str, float, float]:
    """Board de départ réduit à `taille_compacte`, composants mobiles hors carte.

    Rend `(board_b64, largeur, hauteur)` — inchangés si rien à gagner ou en
    cas de panne (on le DIT : la carte est seulement restée grande).
    """
    from kicad_tools.schema.pcb import PCB
    from tools.placement import (_boite_locale_fp, _connector_refs,
                                 _redimensionner_contour)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "b.kicad_pcb"
            f.write_bytes(base64.b64decode(kicad_pcb_b64))
            pcb = PCB.load(str(f))
            surface = 0.0
            for fp in pcb.footprints:
                x0, y0, x1, y1 = _boite_locale_fp(fp)
                surface += (x1 - x0) * (y1 - y0)
            taille = taille_compacte(surface, largeur, hauteur, occupation)
            if taille is None:
                return kicad_pcb_b64, largeur, hauteur
            ancres = set(_connector_refs(pcb))
            for fp in pcb.footprints:
                if fp.reference not in ancres:
                    fp.position = (_HORS_CARTE_MM, _HORS_CARTE_MM)
            pcb.save(str(f))
            if not _redimensionner_contour(f, *taille):
                return kicad_pcb_b64, largeur, hauteur
            logger.warning(
                "carte compacte : %.0fx%.0f -> %.0fx%.0f mm (courtyards %.0f mm2, "
                "occupation visee %.0f %%) — REGLAGE DE BANC",
                largeur, hauteur, taille[0], taille[1], surface, occupation * 100)
            return base64.b64encode(f.read_bytes()).decode(), taille[0], taille[1]
    except Exception as exc:  # noqa: BLE001
        logger.error("carte compacte : non appliquee (%s) — carte de depart inchangee", exc)
        return kicad_pcb_b64, largeur, hauteur
