"""Le repli GND ne peut jamais etre retenu s il DECONNECTE la carte.

⚠️ Mesure du 2026-09-01, `nucleo-f401`, journal du banc :

    repli GND retenu : (3 erreur, 11 manquante) -> (0 erreur, 73 manquante)

Le repli a ete RETENU en multipliant les connexions manquantes par 6,6.

CAUSE. `_secours_est_meilleur` classait les couples `(erreurs, manquantes)`
par ordre lexicographique — `return apres < avant`. Or

    (0, 73) < (3, 11)   est VRAI, parce que 0 < 3

L ordre lexicographique traite UNE erreur comme infiniment pire que N
connexions manquantes, quel que soit N. Trois erreurs de fabricabilite ont
donc ete echangees contre soixante-deux liaisons absentes.

⚠️ Cela contredit l objet meme du repli, ecrit trois lignes au-dessus de son
appel : « Une carte non connectée ne part pas en fabrication — on refait alors
le routage en INCLUANT GND, qui relie tout par des pistes. » Le repli existe
POUR reduire les connexions manquantes. Un repli qui les augmente a manque son
objet, et son compte d erreurs ne le rachete pas : 73 liaisons absentes, ce
n est plus une carte.

⚠️ Le classement erreurs-d abord reste juste PARTOUT AILLEURS, et on n y touche
pas : on ajoute une seule condition d irrecevabilite, en amont du classement.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestLeCasMesure:
    def test_le_repli_de_nucleo_f401_est_REFUSE(self):
        # (3 erreur, 11 manquante) -> (0 erreur, 73 manquante)
        assert R._secours_est_meilleur((3, 11), (0, 73)) is False

    def test_un_echange_qui_empire_le_TOTAL_est_irrecevable(self):
        # 1 defaut echange contre 20 : le total passe de 6 a 21.
        assert R._secours_est_meilleur((1, 5), (0, 21)) is False

    def test_une_petite_augmentation_qui_AMELIORE_le_total_reste_acceptee(self):
        # ⚠️ Garde anti-sur-correction. Interdire TOUTE augmentation aurait
        # casse ce cas, deja documente par `test_repli_gnd_ne_degrade_pas` :
        # cinq erreurs pour une liaison, c est un bon echange.
        assert R._secours_est_meilleur((5, 10), (0, 11)) is True


class TestCeQueLeRepliDoitEncoreAccepter:
    """Garde anti-sur-correction : la regle ne doit pas eteindre le repli."""

    def test_moins_d_erreurs_a_connexions_egales_est_retenu(self):
        assert R._secours_est_meilleur((3, 11), (0, 11)) is True

    def test_moins_de_tout_est_retenu(self):
        assert R._secours_est_meilleur((3, 11), (0, 5)) is True

    def test_moins_de_manquantes_a_erreurs_egales_est_retenu(self):
        # Le cas nominal : le repli relie les broches GND orphelines.
        assert R._secours_est_meilleur((0, 6), (0, 0)) is True

    def test_a_EGALITE_on_refuse(self):
        # Comportement d origine, conserve : le repli coute du cuivre en plus,
        # sans gain mesure on garde l existant.
        assert R._secours_est_meilleur((0, 5), (0, 5)) is False

    def test_plus_d_erreurs_reste_refuse(self):
        assert R._secours_est_meilleur((2, 20), (5, 3)) is False


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_le_site_d_appel_passe_bien_par_la_regle(self):
        # ⚠️ Une regle correcte jamais appelee est indistinguable d une regle
        # absente. On verifie que le remplacement du board est GARDE par elle.
        # ⚠️ `rindex` et non `index` : la phrase apparait AUSSI dans la
        # docstring de la regle, plus haut dans le fichier. Une garde ancree
        # sur la premiere occurrence mesurait le commentaire, pas le code.
        i = self.SOURCE.rindex("repli GND retenu")
        avant = self.SOURCE[:i]
        assert "_secours_est_meilleur(" in avant[-600:], (
            "le board est remplace sans passer par la comparaison")
