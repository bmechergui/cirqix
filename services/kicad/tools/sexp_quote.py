"""Requotage des valeurs de propriété sérialisées en atome nu.

Le sérialiseur de `kicad_tools` (`sexp/parser.py`) ne quote un atome chaîne que
s'il a été LU depuis un token quoté (`_originally_quoted`) ou s'il ne ressemble
pas à un nombre. Ce drapeau vaut False pour tout atome construit
programmatiquement — c'est-à-dire pour chaque valeur de composant injectée
depuis notre schéma JSON. Une valeur purement numérique ressort donc nue :

    (property "Value" 330          ← S-expression invalide

KiCad 10.0.4 refuse alors le fichier ENTIER. Les valeurs numériques sans unité
sont la norme (330, 100, 4700, 10…), donc le défaut n'a rien d'exotique.

Ce module existe pour que le PCB et le SCHÉMA partagent la MÊME règle. Ils ne la
partageaient pas : le garde côté PCB date du 2026-07-27
(`pcbnew.LoadBoard` → None, « Failed to load board », mesuré sur R3 = 330 Ω du
cas led-blinker), tandis que le schéma n'en avait aucun. Résultat, le
2026-08-20 : `kicad-cli sch erc` répondait `rc=3: Failed to load schematic` et
l'ERC d'autorité ne rendait aucun verdict — le repli TypeScript travaillait
seul. Deux copies d'une même règle finissent toujours par diverger ; une seule
ne le peut pas.

⚠️ Le message de kicad-cli est GÉNÉRIQUE : un fichier absent produit exactement
le même « Failed to load schematic ». Il ne suffit jamais à diagnostiquer.

Le fix appartient à `kicad_tools` (le défaut d'`_originally_quoted` est inadapté
à la construction programmatique) ; ce garde vit ici en attendant, le submodule
suivant la procédure fork/rebase de DEPENDENCIES.md.

Garde : tests/test_erc_bare_property_quoting.py.
"""
from __future__ import annotations

import re

# Ne touche QUE la valeur d'un `(property "…" …)`. Les atomes numériques
# légitimes — `(at …)`, `(size …)`, `(version …)` — sont préservés : les quoter
# casserait le fichier aussi sûrement que de ne pas quoter les valeurs.
_BARE_PROPERTY_RE = re.compile(
    r'(\(property\s+"[^"]*"\s+)(-?\d+(?:\.\d+)?)(?=[\s()])'
)


def quote_bare_property_values(text: str) -> tuple[str, int]:
    """Renvoie ``(texte_corrigé, nombre_de_valeurs_requotées)``."""
    return _BARE_PROPERTY_RE.subn(r'\1"\2"', text)
