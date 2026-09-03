"""Une pastille ne doit etre reservee qu UNE fois.

⚠️ `_VIAS_RESERVES` concatene TROIS reservations calculees independamment :

    _vias_a_reserver        les pastilles que le DRC declare isolees du plan
    _vias_signaux_a_reserver les pastilles SIGNAL des boitiers fine-pitch
    _vias_gnd_preventifs     les pastilles GND des boitiers fine-pitch

Les deux premieres sont disjointes par construction (signal contre plan), mais
la premiere et la TROISIEME se recouvrent : une pastille GND d un LQFP-48 que
le DRC signale isolee figure dans les deux. `escape_pads` y poserait alors
DEUX fois la meme piste et le meme via, superposes.

⚠️ Ce n est pas cosmetique. Deux vias au meme point font une violation
`hole_to_hole`, et `_reposer_vias_reserves` est TOUT-OU-RIEN : une seule erreur
ajoutee et le board d origine est rendu — les vingt et un vias partent d un
coup, GND compris, sans que le journal nomme GND. Le doublon ne se contente
donc pas d ajouter du cuivre : il peut annuler toute la repose.

On garde la PREMIERE occurrence : l ordre de concatenation place en tete les
pastilles que le DRC a effectivement vues isolees, c est-a-dire le besoin
avere plutot que le besoin preventif.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestDedoublonnage:
    def test_la_meme_pastille_n_est_gardee_qu_une_fois(self):
        vias = [
            {"ref": "U2", "pad": "8", "via_x": 100, "via_y": 200},
            {"ref": "U2", "pad": "8", "via_x": 999, "via_y": 999},
        ]
        sortie = R._sans_doublons(vias)
        assert len(sortie) == 1
        # La PREMIERE l emporte : c est le besoin avere, pas le preventif.
        assert sortie[0]["via_x"] == 100

    def test_deux_pastilles_du_meme_boitier_sont_gardees(self):
        vias = [{"ref": "U2", "pad": "8", "via_x": 1, "via_y": 1},
                {"ref": "U2", "pad": "23", "via_x": 2, "via_y": 2}]
        assert len(R._sans_doublons(vias)) == 2

    def test_deux_boitiers_avec_le_meme_numero_de_pastille(self):
        vias = [{"ref": "U1", "pad": "1", "via_x": 1, "via_y": 1},
                {"ref": "U2", "pad": "1", "via_x": 2, "via_y": 2}]
        assert len(R._sans_doublons(vias)) == 2

    def test_une_liste_vide_reste_vide(self):
        assert R._sans_doublons([]) == []

    def test_l_ordre_est_conserve(self):
        # L ordre porte la priorite : le dedoublonnage ne doit pas le brouiller.
        vias = [{"ref": "A", "pad": "1"}, {"ref": "B", "pad": "1"},
                {"ref": "A", "pad": "1"}, {"ref": "C", "pad": "1"}]
        assert [v["ref"] for v in R._sans_doublons(vias)] == ["A", "B", "C"]


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_les_trois_reservations_sont_dedoublonnees_avant_usage(self):
        # ⚠️ Un dedoublonnage correct que personne n appelle est indistinguable
        # d un dedoublonnage absent.
        # La fenetre va de la PREMIERE reservation jusqu a la fin du
        # nommage : le dedoublonnage doit tomber entre les deux, ou que son
        # appel soit ecrit.
        debut = self.SOURCE.index("_VIAS_RESERVES = _vias_a_reserver(")
        fin = self.SOURCE.index("_VIAS_RESERVES = _nommer_les_nets(")
        bloc = self.SOURCE[debut:fin + 300]
        assert "_sans_doublons(" in bloc, (
            "les trois reservations sont concatenees sans dedoublonnage")
