"""Un repli GND refuse a 2 couches ne dit RIEN de ce qu il donnerait a 4 ou 6.

La memoire « pas deux fois la meme chose » retient les jeux de broches dont le
repli a echoue pendant l appel. Mesure du 2026-09-14, carte-10 : le repli
CIBLE sur U1.8 est refuse au palier 2 couches — Freerouting n a qu une face
de signal pour tirer une piste de masse entre les sorties d un LQFP — puis
« DEJA tente sans succes » au palier 4, ou deux couches internes lui auraient
donne un chemin. L escalade montait pour rien : la seule reparation possible
etait interdite par un souvenir pris a un autre palier.

La signature d un echec porte donc le NOMBRE DE COUCHES ; sans couches, la
regle historique (broches seules) est conservee.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402


class TestMemoire:
    def setup_method(self):
        R._replis_gnd_echoues.clear()

    def test_un_echec_a_2_couches_n_interdit_pas_le_palier_4(self):
        R._noter_repli_echoue([("U1", "8")], couches=2)
        assert R._repli_deja_tente([("U1", "8")], couches=2)
        assert not R._repli_deja_tente([("U1", "8")], couches=4)
        assert not R._repli_deja_tente([("U1", "8")], couches=6)

    def test_le_meme_palier_reste_interdit_quel_que_soit_l_ordre(self):
        R._noter_repli_echoue([("U1", "8"), ("C3", "2")], couches=4)
        assert R._repli_deja_tente([("C3", "2"), ("U1", "8")], couches=4)

    def test_sans_couches_la_regle_historique_tient(self):
        R._noter_repli_echoue([("U1", "8")])
        assert R._repli_deja_tente([("U1", "8")])
        assert not R._repli_deja_tente([("U1", "8")], couches=2)


class TestCablage:
    def test_route_auto_passe_le_nombre_de_couches_du_board(self):
        corps = inspect.getsource(R.route_auto)
        assert "_repli_deja_tente(orphelines, couches=" in corps
        assert "_noter_repli_echoue(orphelines, couches=" in corps
        assert "_noter_repli_echoue(orphelines)" not in corps
