"""Garde : les valeurs de propriété purement numériques doivent rester quotées.

Bug trouvé le 2026-07-27 en validant le pipeline complet (LED blinker, R3=330Ω).

`kicad_tools/sexp/parser.py` ne quote un atome chaîne que s'il a été *lu* depuis
un token quoté (`_originally_quoted`) ou s'il ne ressemble pas à un nombre. Or ce
drapeau vaut False pour les atomes construits PROGRAMMATIQUEMENT — exactement le
cas d'une valeur de composant injectée depuis notre schéma JSON. Résultat pour
une valeur purement numérique :

    (property "Value" 330          ← atome nu : S-expression invalide

KiCad 10.0.4 refuse alors le fichier entier (`Failed to load board`), aussi bien
via kicad-cli que via pcbnew.LoadBoard (qui renvoie None). Conséquence mesurée :
le board se place et se route (kicad-tools a son propre parseur, plus permissif),
puis DRC et export échouent — sur un board pourtant routé à 100 %.

Les valeurs numériques sont la norme en électronique (330, 100, 4700, 10…), donc
tout schéma contenant une résistance notée sans unité était affecté.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools.pcb import _quote_bare_property_values  # noqa: E402


def test_quotes_a_bare_numeric_value():
    src = '(footprint "R_0805"\n\t(property "Value" 330\n\t\t(at 0 0 0)\n\t)\n)'
    out, n = _quote_bare_property_values(src)
    assert '(property "Value" "330"' in out
    assert n == 1


def test_leaves_already_quoted_values_untouched():
    src = '(property "Value" "10k"\n)\n(property "Reference" "R1"\n)'
    out, n = _quote_bare_property_values(src)
    assert out == src
    assert n == 0


def test_quotes_every_bare_property_not_just_value():
    # Le bug n'est pas propre au champ "Value" : toute propriété dont le contenu
    # ressemble à un nombre est concernée (ex. un champ custom "Tolerance" 5).
    src = '(property "Value" 330\n)\n(property "Tolerance" 5\n)'
    out, n = _quote_bare_property_values(src)
    assert '(property "Value" "330"' in out
    assert '(property "Tolerance" "5"' in out
    assert n == 2


def test_handles_decimal_and_negative_atoms():
    src = '(property "Value" 4.7\n)\n(property "Offset" -12\n)'
    out, _ = _quote_bare_property_values(src)
    assert '(property "Value" "4.7"' in out
    assert '(property "Offset" "-12"' in out


def test_does_not_touch_non_property_numeric_atoms():
    # (at 0 0 0), (size 1 1), (thickness 1.6)… doivent rester des nombres nus :
    # ce sont de vrais atomes numériques attendus par KiCad.
    src = '(at 133.5 95)\n(size 1.7 1.7)\n(thickness 1.6)\n(version 20260206)'
    out, n = _quote_bare_property_values(src)
    assert out == src
    assert n == 0


def test_is_idempotent():
    src = '(property "Value" 330\n)'
    once, _ = _quote_bare_property_values(src)
    twice, n = _quote_bare_property_values(once)
    assert twice == once
    assert n == 0


def test_real_board_shape_stays_loadable_by_a_strict_parser():
    """Reproduit la forme exacte trouvée dans le board généré (4_gen.kicad_pcb)."""
    src = (
        '\t(footprint "R_0805_2012Metric"\n'
        '\t\t(version 20260206)\n'
        '\t\t(at 120 100)\n'
        '\t\t(property "Reference" "R3"\n'
        '\t\t\t(at 0 -1.43 0)\n'
        '\t\t)\n'
        '\t\t(property "Value" 330\n'
        '\t\t\t(at 0 1.43 0)\n'
        '\t\t)\n'
        '\t)\n'
    )
    out, n = _quote_bare_property_values(src)
    assert n == 1
    assert '(property "Value" "330"' in out
    assert '(property "Reference" "R3"' in out
    # Les atomes numériques légitimes sont préservés.
    assert '(version 20260206)' in out
    assert '(at 0 1.43 0)' in out
