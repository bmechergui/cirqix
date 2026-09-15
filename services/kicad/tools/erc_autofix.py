"""Auto-correction ERC : ne corrige que ce que kicad-cli DÉSIGNE, là où il le désigne.

Mesure du 2026-09-15 : avec l'ERC bloquant (#191), neuf cartes du banc sur
onze s'arrêtaient à l'ERC. Trois familles d'erreurs se corrigent à partir du
rapport lui-même, et l'ERC d'autorité REJUGE ensuite le schéma corrigé :

| violation                                   | correction                                |
|---------------------------------------------|-------------------------------------------|
| `pin_not_connected`                         | `(no_connect)` sur la broche              |
| `pin_to_pin` « Power output and Power output », dont un `#FLG` | ce drapeau est retiré |
| `power_pin_not_driven`                      | un `PWR_FLAG` sur la broche               |

Expérience sur les schémas régénérés par le service : carte-02 3 -> 0 erreur,
carte-04 45 -> 0.

⚠️ Tout le reste est laissé tel quel. Deux VRAIES sorties d'alimentation
reliées, une entrée non pilotée, un symbole inconnu : ce sont des fautes de
schéma, et les maquiller rendrait l'ERC aveugle — exactement ce que #191 a
voulu empêcher. Garde : tests/test_erc_autocorrection.py.
"""
from __future__ import annotations

from typing import Any, Optional

from tools.erc import apply_no_connect_fixes
from tools.pwr_flag import ajouter_pwr_flag, retirer_pwr_flag

__all__ = ["corriger_erc"]

_CONFLIT_DE_SORTIES = "Power output and Power output"


def _position(v: dict[str, Any]) -> Optional[tuple[float, float]]:
    x, y = v.get("x_mm"), v.get("y_mm")
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        return round(float(x), 4), round(float(y), 4)
    return None


def corriger_erc(
    sch_content: str,
    violations: list[dict[str, Any]],
    racine_symboles: Optional[str] = None,
) -> tuple[str, int]:
    """Applique les corrections désignées par le rapport. Rend (contenu, nombre)."""
    sortie, corrigees = sch_content, 0

    # 1. Un drapeau posé sur un rail qu'une sortie d'alimentation pilote déjà.
    drapeaux = sorted({
        str(v["ref"]) for v in violations
        if v.get("type") == "pin_to_pin"
        and _CONFLIT_DE_SORTIES in str(v.get("message", ""))
        and str(v.get("ref", "")).startswith("#FLG")
    })
    for reference in drapeaux:
        sortie, retire = retirer_pwr_flag(sortie, reference)
        corrigees += int(retire)

    # 2. Un rail d'alimentation que rien ne pilote : un drapeau sur la broche.
    points: list[tuple[float, float]] = []
    for v in violations:
        p = _position(v) if v.get("type") == "power_pin_not_driven" else None
        if p is not None and p not in points:
            points.append(p)
    for x, y in points:
        avec_drapeau = ajouter_pwr_flag(sortie, x, y, racine_symboles)
        if avec_drapeau is not None:
            sortie, corrigees = avec_drapeau, corrigees + 1

    # 3. Une broche libre : la croix, à la position remise en millimètres.
    sortie, croix = apply_no_connect_fixes(
        sortie, [v for v in violations if v.get("type") == "pin_not_connected"]
    )
    return sortie, corrigees + croix
