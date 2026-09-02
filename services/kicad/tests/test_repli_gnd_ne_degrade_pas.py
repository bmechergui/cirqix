"""Le repli GND remplacait le board SANS JAMAIS COMPARER.

⚠️ Mesure du 2026-08-31. Le meme board `stm32-60`, repris hors du banc, passe
de 98 % a 100 % — 0 manquante, 0 erreur, 2 couches, 950 s — et le journal nomme
le mecanisme qui l a resolu :

    plan de masse : 1 broche GND non reliee — repli sur un routage incluant GND

Au banc, sur ce meme board, le repli s est declenche aussi... et la carte est
sortie a 98 %. Il reussit isolement, il echoue au banc.

L explication tient en deux lignes :

    secours = _router_en_incluant_gnd(etendu, req, restant)
    if secours is not None:
        final = secours          # <- remplacement INCONDITIONNEL

`_router_en_incluant_gnd` etait le SEUL mecanisme de la chaine sans garde
« ne peut qu ameliorer ». Ses quatre voisines l ont :

    _recoudre_les_zones      OUI
    _recoudre_les_ilots      OUI
    _fanout_pads_isolees     OUI
    _reposer_vias_reserves   OUI  (ajoutee le 2026-08-31)
    _router_en_incluant_gnd  NON

Un repli qui echoue rend deja None, et l appelant garde son board — c est
documente. Mais un repli qui REUSSIT MOINS BIEN ecrasait un meilleur resultat
sans que rien ne le dise.

⚠️ On classe sur (erreurs, connexions manquantes) : une erreur de
fabricabilite fait REFUSER la carte, une connexion manquante se voit au DRC.
La premiere prime — meme ordre que partout ailleurs dans le projet.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestRegle:
    def test_un_secours_MEILLEUR_est_retenu(self):
        # Le cas mesure : 1 manquante -> 0 manquante, sans erreur ajoutee.
        assert R._secours_est_meilleur(
            avant=(0, 1), apres=(0, 0)) is True

    def test_un_secours_PIRE_est_refuse(self):
        assert R._secours_est_meilleur(avant=(0, 1), apres=(0, 3)) is False

    def test_un_secours_EGAL_est_refuse(self):
        """A egalite on garde l existant : le repli coute du cuivre en plus
        (GND route par des pistes au lieu d etre coule)."""
        assert R._secours_est_meilleur(avant=(0, 1), apres=(0, 1)) is False

    def test_une_ERREUR_ajoutee_fait_refuser_meme_si_plus_complet(self):
        """⚠️ Une carte complete mais non fabricable ne part pas en production.
        La connexion manquante bloque au DRC ; l erreur, elle, peut passer."""
        assert R._secours_est_meilleur(avant=(0, 2), apres=(1, 0)) is False

    def test_une_erreur_RETIREE_fait_accepter(self):
        assert R._secours_est_meilleur(avant=(2, 0), apres=(0, 1)) is True


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_le_remplacement_n_est_plus_INCONDITIONNEL(self):
        # ⚠️ Le bloc REEL, pas une tranche de longueur fixe. Les 900
        # caracteres d origine ont ete depasses le 2026-09-02 par l ajout du
        # « repli deja tente » : la garde a cesse de mesurer ce qu elle visait,
        # alors que son intention — comparer avant de remplacer — etait
        # intacte. Troisieme ancrage fragile repare dans cette session.
        i = self.SOURCE.index("secours = _router_en_incluant_gnd(")
        fin = self.SOURCE.index("_reparer_reliefs_affames", i)
        bloc = self.SOURCE[i:fin]
        assert "_secours_est_meilleur(" in bloc, (
            "le repli remplace le board sans comparer")

    def test_le_refus_est_DIT(self):
        # Un refus silencieux ferait croire que le repli a ete applique.
        # ⚠️ Fenetre elargie : le refus se journalise apres tout le bloc de
        # comparaison. Une garde trop etroite mesurerait la mise en page.
        i = self.SOURCE.index("secours = _router_en_incluant_gnd(")
        bloc = self.SOURCE[i:i + 1800]
        assert "repli GND REFUSE" in bloc and "logger.warning" in bloc

    def test_toutes_les_etapes_qui_remplacent_le_board_comparent(self):
        """⚠️ Invariant de la chaine, verifie sur les CINQ mecanismes."""
        for nom in ("_recoudre_les_zones", "_recoudre_les_ilots",
                    "_fanout_pads_isolees", "_reposer_vias_reserves"):
            i = self.SOURCE.index("def %s(" % nom)
            j = self.SOURCE.index(chr(10) + "def ", i + 5)
            assert "_compte_erreurs" in self.SOURCE[i:j], nom
