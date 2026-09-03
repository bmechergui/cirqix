"""La couture ne doit pas TOUT jeter parce qu UN via gene.

⚠️ Mesure du 2026-09-01, `nucleo-f401`, journal du run :

    couture : 7 via(s) poses dans les ilots de plan
    couture de zones : erreurs ajoutees — board d origine conserve

Sept vias poses, un seul mauvais, et les SEPT sont perdus. Le board livre
garde donc ses quatre ruptures `Zone [GND] <-> Zone [GND]`, que ces vias
etaient precisement charges de refermer.

C est le meme « tout-ou-rien » que celui deja corrige pour la repose des vias
reserves : une garde « ne peut qu aggraver » est juste, mais appliquee au LOT
elle jette le bon avec le mauvais.

LA REGLE. On garde le meilleur des deux essais, et si le lot entier degrade on
retente SANS le dernier via pose — jusqu a trouver un sous-ensemble qui
n aggrave pas. A defaut, on rend le board recu : la garde reste inviolee.

⚠️ Le critere de comparaison compte les ERREURS, pas les avertissements : une
erreur de fabricabilite fait refuser la carte, un avertissement non.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestChoix:
    def test_un_lot_qui_n_aggrave_pas_est_garde(self):
        assert R._couture_acceptable(erreurs_avant=3, erreurs_apres=3) is True

    def test_un_lot_qui_ameliore_est_garde(self):
        assert R._couture_acceptable(erreurs_avant=5, erreurs_apres=2) is True

    def test_un_lot_qui_aggrave_est_refuse(self):
        assert R._couture_acceptable(erreurs_avant=3, erreurs_apres=4) is False


class TestRetraitProgressif:
    def test_on_retire_le_dernier_via_pose(self):
        # Le board porte 3 vias de couture ; on doit pouvoir en rendre une
        # version qui n en garde que 2, puis 1, puis 0.
        board = R._sans_derniers_vias(
            b'(kicad_pcb (via (at 1 1)) (via (at 2 2)) (via (at 3 3)))', 1)
        assert board.count(b"(via ") == 2
        assert b"(at 3 3)" not in board

    def test_retirer_plus_que_present_rend_un_board_sans_via(self):
        board = R._sans_derniers_vias(b'(kicad_pcb (via (at 1 1)))', 5)
        assert b"(via " not in board

    def test_ne_touche_a_rien_d_autre(self):
        b = (b'(kicad_pcb (segment (start 1 1)) (via (at 2 2))'
             b' (zone (net 1) (net_name "GND")))')
        s = R._sans_derniers_vias(b, 1)
        assert b"(segment" in s and b'(net_name "GND")' in s
        assert b"(via " not in s


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_la_couture_retente_avant_de_tout_jeter(self):
        i = self.SOURCE.index("def _recoudre_les_zones(")
        j = self.SOURCE.index("\ndef ", i + 10)
        corps = self.SOURCE[i:j]
        assert "_sans_derniers_vias(" in corps, (
            "la couture jette encore les sept vias parce qu un seul gene")
        assert "_couture_acceptable(" in corps
