"""La couture ne repose pas de via dans un ilot DEJA relie a l autre face.

⚠️ RELEVE LE 2026-09-19, en relisant a l oeil les dix cartes du banc. Chacune
porte une rangee de 9 a 20 vias GND au pas de 1,8 mm, le long du bord haut —
116 au total. carte-01 (5 composants) : 9 de ses 12 vias sont dans la rangee.
Le board place n en porte aucun : c est le routage qui les ajoute.

CAUSE. `_stitch_zones` pose un via dans chaque ilot, a CHAQUE passe, sans
regarder s il en porte deja un qui l atteint en face. GND vivant sur deux
couches, `_faut_coudre` repond oui meme pour un plan d un seul tenant. Le
centre de l ilot est occupe, la grille part du coin haut gauche, la regle
anti-doublon decale chaque nouveau via de 1,8 mm : d ou la rangee, a raison de
5 passes par appel et de plusieurs appels par routage.

La regle generale de masse dit « AU MOINS un via vers la face opposee ». Un
ilot qui en a un est en regle : lui en ajouter un n est pas coudre, c est
percer pour rien — un trou facture et un obstacle de plus au routage.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from tools import routing_pcbnew_runner as RUN  # noqa: E402

BANC = RACINE / "examples" / "carte-01-diviseur" / "expected" / "final.kicad_pcb"


def _contient(table):
    """`contient(ilot, point)` depuis une table {ilot: {points}}."""
    return lambda k, p: p in table.get(k, set())


class TestRegle:
    """Relie = dans la MEME composante que le plus grand ilot du net, par des
    traversants (vias, pastilles traversantes). Pas « un via qui atteint du
    cuivre en face » : ce premier critere, essaye le 2026-09-19, a laisse
    carte-09 a 2 ruptures GND — deux PAIRES de petits ilots cousus entre eux,
    chacun se croyant relie, aucune n atteignant le plan."""

    AIRES = {"F_plan": 11070.0, "B_plan": 11285.0, "F_petit": 4.8, "B_petit": 5.6}

    def test_un_ilot_cousu_au_plan_est_relie(self):
        relies = RUN._ilots_relies_au_principal(
            self.AIRES, ["v_plans", "v1"],
            _contient({"F_plan": {"v_plans"}, "B_plan": {"v_plans", "v1"},
                       "F_petit": {"v1"}}))
        assert {"F_plan", "B_plan", "F_petit"} <= relies
        assert "B_petit" not in relies

    def test_une_paire_cousue_entre_elle_n_est_pas_reliee(self):
        # La mesure de carte-09 : F.Cu#1 <-> B.Cu#1 par un via, rien d autre.
        relies = RUN._ilots_relies_au_principal(
            self.AIRES, ["v_plans", "v_paire"],
            _contient({"F_plan": {"v_plans"}, "B_plan": {"v_plans"},
                       "F_petit": {"v_paire"}, "B_petit": {"v_paire"}}))
        assert relies == {"F_plan", "B_plan"}

    def test_sans_traversant_seul_le_principal_est_relie(self):
        assert RUN._ilots_relies_au_principal(
            self.AIRES, [], _contient({})) == {"B_plan"}

    def test_un_predicat_qui_leve_ne_vaut_pas_relie(self):
        # Au doute, on coud : on retombe sur le comportement d avant.
        def boum(_k, _p):
            raise RuntimeError("polygone illisible")
        assert RUN._ilots_relies_au_principal(self.AIRES, ["v"], boum) == {"B_plan"}

    def test_aucun_ilot(self):
        assert RUN._ilots_relies_au_principal({}, ["v"], _contient({})) == set()


class TestCablage:
    SOURCE = (RACINE / "tools" / "routing_pcbnew_runner.py").read_text(encoding="utf-8")

    def test_la_couture_consulte_la_regle_avant_de_chercher_un_point(self):
        corps = self.SOURCE[self.SOURCE.index("def _stitch_zones("):]
        corps = corps[: corps.index("\ndef ")]
        assert "_ilots_relies_au_principal_du_net(" in corps
        assert (corps.index("_ilots_relies_au_principal_du_net(")
                < corps.index("_candidats_par_preference("))


pcbnew = pytest.importorskip("pcbnew", reason="pcbnew absent : se lance dans le conteneur")


class TestSurUnVraiBoard:
    def test_un_board_livre_n_appelle_aucun_via_de_plus(self, tmp_path):
        """carte-01 livree : chaque ilot de GND est deja relie. La couture
        rendait « stitched: 1 » ou plus a chaque appel — la rangee grandissait
        d un via par passe."""
        if not BANC.is_file():
            pytest.skip("board du banc absent de l image")
        entree = tmp_path / "in.kicad_pcb"
        shutil.copy(BANC, entree)
        resultat = tmp_path / "r.json"
        RUN._stitch_zones(pcbnew, {
            "pcb": str(entree),
            "output": str(tmp_path / "out.kicad_pcb"),
            "result": str(resultat),
            "nets": json.dumps(["GND"]),
        })
        assert json.loads(resultat.read_text(encoding="utf-8"))["stitched"] == 0
