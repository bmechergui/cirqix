"""L'auto-correction ERC corrige ce que kicad-cli DÉSIGNE — au bon endroit.

Mesure du 2026-09-15 : régénérées avec l'ERC bloquant (#191), neuf cartes du
banc sur onze s'arrêtaient à l'ERC. Trois défauts, tous vérifiés sur le
rapport brut de kicad-cli :

1. **Les positions sont cent fois trop petites.** `kicad-cli sch erc` annonce
   `coordinate_units: mm` mais rend U1.44 (BOOT0) à (0.3048, 0.4826) pour une
   broche posée à (30.48, 48.26). Les `(no_connect)` de l'auto-correction
   tombaient près de l'origine : 78 broches libres restaient en erreur.
2. **PWR_FLAG sur un rail déjà piloté** (#192) : un drapeau posé sur la sortie
   `VO` d'un régulateur donne « Pins of type Power output and Power output are
   connected ».
3. **Rail d'alimentation sans pilote** : « Input Power pin not driven ».

Expérience, sur le schéma régénéré par le service : carte-02 3 erreurs -> 0,
carte-04 45 erreurs -> 0, en corrigeant ces trois points à partir du rapport.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from tools import erc as E  # noqa: E402
from tools import erc_autofix as A  # noqa: E402
from tools import pwr_flag as P  # noqa: E402

_DEFINITION = (
    '(symbol "power:PWR_FLAG" (power global)\n'
    '  (symbol "PWR_FLAG_0_0" (pin power_out line (at 0 0 90) (length 0)))\n'
    ')'
)


def _rapport(*violations: dict) -> str:
    return json.dumps({"coordinate_units": "mm", "sheets": [{"path": "/", "violations": list(violations)}]})


def _item(description: str, x: float, y: float) -> dict:
    return {"description": description, "uuid": "u-" + description[:12], "pos": {"x": x, "y": y}}


def _flag(ref: str, x: float, y: float) -> str:
    return P._instance_pwr_flag(x, y, ref)


def _sch(*corps: str) -> str:
    return (
        '(kicad_sch\n\t(version 20240108)\n\t(lib_symbols\n\t\t' + _DEFINITION + '\n\t)\n'
        + "".join(corps) + ')\n'
    )


class TestPositions:
    def test_les_positions_du_rapport_sont_remises_en_millimetres(self):
        v = E.parse_erc_report(_rapport({
            "type": "pin_not_connected", "severity": "error", "description": "Pin not connected",
            "items": [_item("Symbol U1 Pin 44 [BOOT0, Input, Line]", 0.3048, 0.4826)],
        }))
        assert v[0]["x_mm"] == 30.48 and v[0]["y_mm"] == 48.26


class TestCorrections:
    def test_broche_libre_une_croix_au_BON_endroit(self):
        violations = [{"type": "pin_not_connected", "severity": "error", "ref": "U1", "pin": "44",
                       "message": "Pin not connected", "x_mm": 30.48, "y_mm": 48.26}]
        out, n = A.corriger_erc(_sch(), violations)
        assert n == 1 and "(no_connect (at 30.48 48.26)" in out

    def test_drapeau_en_conflit_avec_une_sortie_d_alimentation_est_RETIRE(self):
        sch = _sch(_flag("#FLG01", 50.8, 30.48), _flag("#FLG02", 76.2, 40.64))
        violations = [
            {"type": "pin_to_pin", "severity": "error", "ref": "#FLG02", "pin": "1",
             "message": "Pins of type Power output and Power output are connected", "x_mm": 76.2, "y_mm": 40.64},
            {"type": "pin_to_pin", "severity": "error", "ref": "U1", "pin": "2",
             "message": "Pins of type Power output and Power output are connected", "x_mm": 76.2, "y_mm": 40.64},
        ]
        out, n = A.corriger_erc(sch, violations)
        assert n == 1
        assert '"#FLG02"' not in out and '"#FLG01"' in out
        assert out.count("(") == out.count(")")

    def test_un_conflit_SANS_drapeau_n_est_pas_touche(self):
        # Deux vraies sorties d'alimentation reliées : une faute de schéma, pas
        # un drapeau à retirer. On ne la maquille pas.
        sch = _sch()
        violations = [{"type": "pin_to_pin", "severity": "error", "ref": "U1", "pin": "2",
                       "message": "Pins of type Power output and Power output are connected"}]
        assert A.corriger_erc(sch, violations) == (sch, 0)

    def test_rail_sans_pilote_recoit_un_drapeau_sur_la_broche(self):
        violations = [{"type": "power_pin_not_driven", "severity": "error", "ref": "U1", "pin": "3",
                       "message": "Input Power pin not driven by any Output Power pins",
                       "x_mm": 30.48, "y_mm": 30.48}]
        out, n = A.corriger_erc(_sch(), violations, racine_symboles="/inexistant")
        assert n == 1
        assert '(lib_id "power:PWR_FLAG")' in out and "(at 30.48 30.48 0)" in out
        assert out.count("(") == out.count(")")

    def test_deux_violations_au_meme_point_un_seul_drapeau(self):
        v = {"type": "power_pin_not_driven", "severity": "error", "message": "x", "x_mm": 30.48, "y_mm": 30.48}
        out, n = A.corriger_erc(_sch(), [v, dict(v)], racine_symboles="/inexistant")
        assert n == 1 and out.count('(lib_id "power:PWR_FLAG")') == 1

    def test_les_autres_erreurs_ne_sont_jamais_corrigees(self):
        sch = _sch()
        violations = [{"type": "pin_not_driven", "severity": "error", "message": "Input pin not driven",
                       "x_mm": 1.0, "y_mm": 2.0},
                      {"type": "power_pin_not_driven", "severity": "error", "message": "sans position"}]
        assert A.corriger_erc(sch, violations) == (sch, 0)


class TestCablage:
    """Une règle jamais appelée est indistinguable d'une règle absente."""

    def test_la_boucle_de_l_erc_appelle_la_correction(self):
        from routers import erc as R
        assert "corriger_erc(" in inspect.getsource(R.run_erc)
