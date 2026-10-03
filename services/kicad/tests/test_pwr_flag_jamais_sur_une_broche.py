"""Un `PWR_FLAG` se pose sur un RAIL, jamais sur une broche nue.

⚠️ Mesuré le 2026-09-24 sur `carte-10-maximale`, et reproduit à la main par la
vraie route `/erc` :

    schéma généré     2 PWR_FLAG, chacun SUR un symbole d'alimentation
    après réparation  6 PWR_FLAG — les 4 ajoutés sont SUR DES BROCHES NUES

    netlist AVANT     VIN = J1.1 C2.1 U2.3 C1.1
    netlist APRÈS     VIN = J1.1 C2.1 C1.1          <- U2.3 arrachée
                      PWR_FLAG = U1.9 U1.48 U1.36 U2.3

Un `PWR_FLAG` est un symbole d'alimentation `(power global)` : il NOMME le net
où il se pose. Sur le symbole d'un rail, le nom du rail l'emporte — rien ne
change. Sur une broche NUE, rien ne l'emporte : le net s'appelle `PWR_FLAG`, et
ce nom étant global, tous les drapeaux ainsi posés fusionnent en UN net.

Le routeur relie ensuite ce net en cuivre, correctement selon le netlist : sur
`carte-05`, 22 pistes et vias relient +3V3, GND, SDA et VIN. **Un court-circuit
des rails d'alimentation**, sur un board déclaré 100 % routé, 0 erreur,
fabricable — et aucun juge ne pouvait le voir, puisque le DRC compare le board
à SON netlist.

⚠️ La réparation désarmait aussi un filet existant. Avant elle, U1.36, U1.48 et
U2.2 étaient ORPHELINES — un défaut visible, que `_patch_floating_nets`
reconnecte sur le board à leur net du schéma. Fusionnées, elles ne sont plus
orphelines, donc plus réparées. Un remède faisait disparaître le symptôme que
l'autre savait soigner.

Le docstring d'`erc_autofix` énonçait déjà la règle : « une entrée non pilotée
est une faute de schéma, et la maquiller rendrait l'ERC aveugle ». La réparation
la violait deux lignes plus bas.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from tools import erc_autofix as A  # noqa: E402
from tools import pwr_flag as P  # noqa: E402

_DEFINITION = (
    '(symbol "power:PWR_FLAG" (power global)\n'
    '  (symbol "PWR_FLAG_0_0" (pin power_out line (at 0 0 90) (length 0)))\n'
    ')'
)


def _symbole_alim(rail: str, x: float, y: float, ref: str = "#PWR01") -> str:
    """Une instance de symbole d'alimentation `power:<rail>` en (x, y)."""
    return (
        "\t(symbol\n"
        f'\t\t(lib_id "power:{rail}")\n'
        f"\t\t(at {x} {y} 0)\n"
        f'\t\t(property "Reference" "{ref}")\n'
        f'\t\t(property "Value" "{rail}")\n'
        "\t)\n"
    )


def _sch(*corps: str) -> str:
    return ('(kicad_sch\n\t(version 20240108)\n\t(lib_symbols\n\t\t' + _DEFINITION
            + '\n\t)\n' + "".join(corps) + ')\n')


def _non_pilotee(x: float, y: float, ref: str = "U1") -> dict:
    return {"type": "power_pin_not_driven", "severity": "error", "ref": ref,
            "message": "Input Power pin not driven by any Output Power pins",
            "x_mm": x, "y_mm": y}


class TestLaRegle:
    def test_un_drapeau_n_est_JAMAIS_pose_sur_une_broche_nue(self):
        """Le cas de carte-10 : la broche d'un composant, sans symbole de rail."""
        sch = _sch(_symbole_alim("+3V3", 10.0, 10.0))
        out, n = A.corriger_erc(sch, [_non_pilotee(30.48, 30.48)], racine_symboles="/inexistant")
        assert n == 0, "un drapeau sur une broche nue nomme le net PWR_FLAG"
        assert out.count('(lib_id "power:PWR_FLAG")') == 0

    def test_sur_le_symbole_d_un_rail_le_drapeau_est_pose(self):
        """Le cas d'origine (#PWR001.1, 2026-09-14) : là, le rail garde son nom."""
        sch = _sch(_symbole_alim("+3V3", 30.48, 30.48))
        out, n = A.corriger_erc(sch, [_non_pilotee(30.48, 30.48, "#PWR01")],
                                racine_symboles="/inexistant")
        assert n == 1
        assert '(lib_id "power:PWR_FLAG")' in out and "(at 30.48 30.48 0)" in out

    def test_un_PWR_FLAG_existant_ne_compte_pas_comme_rail(self):
        """Sinon un drapeau fautif légitimerait le suivant au même point."""
        sch = _sch(P._instance_pwr_flag(30.48, 30.48, "#FLG01"))
        out, n = A.corriger_erc(sch, [_non_pilotee(30.48, 30.48)], racine_symboles="/inexistant")
        assert n == 0

    def test_la_position_tolere_l_arrondi_du_rapport(self):
        """Le rapport arrondit à 4 décimales, le schéma écrit 2 : 30.4800 == 30.48."""
        sch = _sch(_symbole_alim("GND", 30.48, 66.04))
        out, n = A.corriger_erc(sch, [_non_pilotee(30.4801, 66.0399, "#PWR02")],
                                racine_symboles="/inexistant")
        assert n == 1


class TestLesRails:
    def test_les_symboles_d_alimentation_sont_des_rails(self):
        sch = _sch(_symbole_alim("+3V3", 1.0, 2.0), _symbole_alim("GND", 3.0, 4.0, "#PWR02"))
        assert P.positions_des_rails(sch) == {(1.0, 2.0), (3.0, 4.0)}

    def test_un_PWR_FLAG_n_est_pas_un_rail(self):
        sch = _sch(_symbole_alim("+3V3", 1.0, 2.0), P._instance_pwr_flag(5.0, 6.0, "#FLG01"))
        assert P.positions_des_rails(sch) == {(1.0, 2.0)}

    def test_un_schema_illisible_n_a_aucun_rail(self):
        """Au doute, aucun drapeau : un schéma refusé par l'ERC se voit, un
        court-circuit ne se voit pas."""
        assert P.positions_des_rails("") == set()
        assert P.positions_des_rails("(kicad_sch") == set()
