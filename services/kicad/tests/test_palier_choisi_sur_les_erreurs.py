"""A pourcentage egal, le palier qui porte MOINS d erreurs gagne.

⚠️ Regression introduite le 2026-08-28 par l arret anticipe de l escalade, et
mesuree des le banc suivant sur `stm32-baseline` :

    avant :  6 couches   93 % route   1 manquante   0 erreur
    apres :  2 couches   93 % route   1 manquante   1 ERREUR

L arret anticipe n etait pas faux en soi ; c est le CRITERE de comparaison qui
l etait deja, et qui ne se voyait pas tant qu on essayait tous les paliers.
`route_auto` classait les paliers sur le seul `routed_percent`. Deux paliers a
93 % etaient donc juges equivalents alors que l un passe le DRC et l autre non.

Le pourcentage route et la fabricabilite sont deux questions distinctes : une
carte complete mais refusee par le fabricant ne vaut pas mieux qu une carte
incomplete. On classe donc sur le couple, le pourcentage d abord.

⚠️ Un palier qui n ameliore NI le pourcentage NI les erreurs ne compte pas comme
un gain : sans quoi l arret anticipe ne se declencherait jamais.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestClassement:
    def test_un_meilleur_pourcentage_l_emporte(self):
        assert R._palier_meilleur((95, 4), (90, 0)) is True

    def test_a_pourcentage_egal_le_moins_d_erreurs_gagne(self):
        assert R._palier_meilleur((93, 0), (93, 1)) is True
        assert R._palier_meilleur((93, 1), (93, 0)) is False

    def test_un_palier_identique_n_est_pas_un_gain(self):
        # Sinon l arret anticipe ne se declencherait jamais.
        assert R._palier_meilleur((93, 1), (93, 1)) is False

    def test_le_pourcentage_prime_sur_les_erreurs(self):
        # Une carte incomplete n est pas rattrapee par un DRC propre : les
        # erreurs departagent, elles ne renversent pas.
        assert R._palier_meilleur((80, 0), (95, 3)) is False


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def _corps(self):
        """Le corps de la boucle d escalade, borne par son propre retour."""
        debut = self.SOURCE.index("essais = _paliers_avec_tirages(")
        corps = self.SOURCE[debut:]
        return corps[:corps.index("return meilleur")]

    def test_la_boucle_classe_sur_le_couple(self):
        # ⚠️ On bornait la lecture a 8000 caracteres. Les commentaires ajoutes
        # le 2026-08-29 ont pousse le code au-dela, et le test a echoue sur un
        # code juste. On borne sur la FIN REELLE de la boucle.
        corps = self._corps()
        assert "_palier_meilleur(" in corps

    def test_les_erreurs_du_palier_sont_mesurees(self):
        corps = self._corps()
        assert "_compte_erreurs(" in corps, (
            "on ne peut pas classer sur les erreurs sans les compter")
