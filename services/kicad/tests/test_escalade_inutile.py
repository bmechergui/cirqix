"""Quand le ROUTEUR annonce 100 %, ajouter des couches ne peut rien apporter.

⚠️ Mesure du 2026-08-31, `arduino-uno` au banc final :

    2 couches -> 93 %      moteur : 100 %,  1 net incomplet : GND
    4 couches -> 93 %      idem
    6 couches -> 93 %      idem
    duree 2654 s contre 1909 s au banc precedent

Douze minutes entierement consommees a escalader vers 4 puis 6 couches, pour
la meme valeur a chaque palier — et une carte 6 couches proposee la ou 2
suffisent.

L explication est dans le journal : « 100 % annonce par le moteur, mais le DRC
voit 1 net incomplet sur 15 ». Le routeur a TOUT relie par des pistes. L ecart
vient de notre verification, qui regarde le board LIVRE et compte un net confie
au PLAN — GND, qui n est pas route mais COULE.

Du cuivre supplementaire n y change donc rien, par construction. L escalade
existe pour donner de la place a un routeur qui n y arrive pas ; elle n a aucun
sens face a un routeur qui a fini.

⚠️ On n arrete PAS si le board porte des erreurs DRC : une violation de
fabricabilite (clearance, largeur de piste) peut, elle, se resoudre avec plus
d espace. Le critere est « le routeur a fini ET le board est propre ».
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestRegle:
    def test_un_moteur_a_100_pourcent_et_zero_erreur_arrete_l_escalade(self):
        # LE CAS MESURE : arduino-uno, moteur 100 %, 1 net GND, 0 erreur.
        assert R._escalade_peut_aider(100, erreurs=0) is False

    def test_un_moteur_incomplet_laisse_escalader(self):
        # C est la raison d etre de l escalade : donner de la place.
        assert R._escalade_peut_aider(93, erreurs=0) is True
        assert R._escalade_peut_aider(70, erreurs=0) is True

    def test_des_erreurs_DRC_laissent_escalader_meme_a_100_pourcent(self):
        """⚠️ Une violation de fabricabilite peut se resoudre avec plus
        d espace — contrairement a une pastille de plan orpheline."""
        assert R._escalade_peut_aider(100, erreurs=1) is True

    def test_un_zero_laisse_escalader(self):
        # « 0 % (aucun moteur) » est une panne ; l escalade ne la traite pas,
        # mais ce n est pas ici qu on l arrete.
        assert R._escalade_peut_aider(0, erreurs=0) is True


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def _boucle(self) -> str:
        """Tout ce qui suit le debut de `route_auto`.

        ⚠️ Deux versions fausses avant celle-ci, et toutes deux mesuraient la
        MISE EN PAGE plutot que le cablage :
          - `SOURCE[i:i + 7000]` depuis la boucle des paliers, alors que
            l appel se trouve 18 000 caracteres plus bas ;
          - le corps borne par le `def` suivant, alors que `route_auto` est la
            DERNIERE fonction du fichier et n en a aucun apres elle.
        """
        return self.SOURCE[self.SOURCE.index("def route_auto("):]

    def test_la_regle_est_APPELEE(self):
        assert "_escalade_peut_aider(" in self._boucle()

    def test_le_pourcentage_du_MOTEUR_est_conserve(self):
        """⚠️ `_percent_verifie` ECRASE `res.routed_percent`. Sans copie
        prealable, la regle lirait le pourcentage corrige (93 %) au lieu de
        celui du moteur (100 %) — et ne se declencherait jamais."""
        assert "percent_moteur" in self.SOURCE
        i = self.SOURCE.index("res.routed_percent = _percent_verifie(")
        assert "percent_moteur" in self.SOURCE[max(0, i - 500):i]
