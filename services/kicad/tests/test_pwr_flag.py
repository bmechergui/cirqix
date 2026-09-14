"""Un `PWR_FLAG` par rail d'alimentation, sinon l'ERC de KiCad refuse le schema.

Mesure du 2026-09-14 sur le schema NE555, par la vraie route `/erc` : apres le
passage des labels en globaux il restait DEUX erreurs, toutes deux
`power_pin_not_driven` sur `#PWR001.1` et `#PWR006.1`. Un symbole `power:VCC`
porte une broche `power_in` que rien ne pilote tant qu'aucune `power_out` ne
touche le net ; l'usage etabli est le `PWR_FLAG`.

La pose est sure par GEOMETRIE : la broche de `PWR_FLAG` est a (0, 0) de son
symbole, exactement comme celle de `power:VCC` — le drapeau pose aux memes
coordonnees a donc sa broche au meme point, sans fil a tracer.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from tools import pwr_flag as P  # noqa: E402
from tools import schematic as S  # noqa: E402

# Une definition minimale mais de la BONNE forme : broche `power_out` a (0, 0).
_DEFINITION = (
    '(symbol "power:PWR_FLAG" (power global)\n'
    '  (property "Reference" "#FLG" (at 0 1.905 0))\n'
    '  (symbol "PWR_FLAG_0_0" (pin power_out line (at 0 0 90) (length 0)))\n'
    ')'
)


def _sch(*rails: tuple[str, float, float]) -> str:
    corps = "".join(
        f'\t(symbol\n\t\t(lib_id "power:{nom}")\n\t\t(at {x} {y} 0)\n\t\t(unit 1)\n'
        f'\t\t(uuid "u-{nom}-{x}")\n\t\t(property "Reference" "#PWR00{i}"\n\t\t\t(at {x} {y} 0)\n\t\t)\n'
        f'\t\t(property "Value" "{nom}"\n\t\t\t(at {x} {y} 0)\n\t\t)\n\t)\n'
        for i, (nom, x, y) in enumerate(rails)
    )
    return (
        '(kicad_sch\n\t(version 20240108)\n\t(generator "eeschema")\n'
        '\t(lib_symbols\n'
        '\t\t(symbol "power:VCC" (power global)\n'
        '\t\t\t(symbol "VCC_0_0" (pin power_in line (at 0 0 90) (length 0)))\n\t\t)\n'
        '\t)\n' + corps + ')\n'
    )


class TestRails:
    def test_chaque_rail_est_trouve_avec_la_position_de_son_symbole(self):
        sch = _sch(("VCC", 76.2, 31.75), ("GND", 50.8, 60.96), ("VCC", 30.48, 35.56))
        assert P.rails_sans_drapeau(sch) == {"VCC": (76.2, 31.75), "GND": (50.8, 60.96)}

    def test_un_schema_sans_alimentation_ne_rend_rien(self):
        assert P.rails_sans_drapeau('(kicad_sch (version 20240108))') == {}

    def test_les_symboles_de_la_BIBLIOTHEQUE_ne_comptent_pas_pour_des_instances(self):
        # `lib_symbols` contient `(symbol "power:VCC" …)` : le confondre avec une
        # instance poserait un drapeau dans le vide.
        sch = _sch()
        assert P.rails_sans_drapeau(sch) == {}


class TestPose:
    def test_un_drapeau_par_rail_a_la_POSITION_du_symbole(self):
        sch = _sch(("VCC", 76.2, 31.75), ("GND", 50.8, 60.96))
        out = P.poser_pwr_flags(sch, racine_symboles="/inexistant")
        # Sans bibliotheque, rien n est pose : on ne fabrique pas un symbole.
        assert out is sch

    def test_avec_la_definition_deja_presente_le_drapeau_est_pose(self):
        sch = _sch(("VCC", 76.2, 31.75), ("GND", 50.8, 60.96)).replace(
            "\t)\n\t(symbol", "\t\t" + _DEFINITION + "\n\t)\n\t(symbol", 1)
        out = P.poser_pwr_flags(sch, racine_symboles="/inexistant")
        assert out.count('(lib_id "power:PWR_FLAG")') == 2
        assert "(at 76.2 31.75 0)" in out and "(at 50.8 60.96 0)" in out
        assert '"#FLG01"' in out and '"#FLG02"' in out

    def test_idempotente(self):
        sch = _sch(("VCC", 76.2, 31.75)).replace(
            "\t)\n\t(symbol", "\t\t" + _DEFINITION + "\n\t)\n\t(symbol", 1)
        une = P.poser_pwr_flags(sch, racine_symboles="/inexistant")
        assert P.poser_pwr_flags(une, racine_symboles="/inexistant") is une

    def test_le_fichier_reste_equilibre(self):
        sch = _sch(("VCC", 76.2, 31.75), ("GND", 50.8, 60.96)).replace(
            "\t)\n\t(symbol", "\t\t" + _DEFINITION + "\n\t)\n\t(symbol", 1)
        out = P.poser_pwr_flags(sch, racine_symboles="/inexistant")
        assert out.count("(") == out.count(")")

    def test_une_entree_vide_ou_illisible_est_rendue_TELLE_QUELLE(self):
        assert P.poser_pwr_flags("") == ""
        assert P.poser_pwr_flags("pas du kicad") == "pas du kicad"


class TestCablage:
    """Une regle jamais appelee est indistinguable d une regle absente."""

    def test_le_generateur_pose_les_drapeaux_avant_de_rendre(self):
        corps = inspect.getsource(S._generate_with_cs_lib)
        assert "poser_pwr_flags(" in corps
        # Et APRES la globalisation : le drapeau se pose sur le schema final.
        assert corps.index("globaliser_les_labels_hierarchiques(") <= corps.rindex("poser_pwr_flags(")
