"""`_poser_via_dans_pastille` doit vérifier ce que `_escape_pads` vérifie.

⚠️ Mesure du 2026-09-02, `stm32-100` livrée à 99 % avec UNE connexion
manquante — un îlot du plan F.Cu séparé du reste. L'opération de production
qui répare ce cas rend :

    {"retires": 0, "vias_retires": 0, "relies": 1}
    avant  manquantes=1 erreurs=0
    apres  manquantes=1 erreurs=1

Elle relie bien un îlot par sa pastille, mais son via **ajoute une erreur** et
ne ferme pas la connexion. La garde « ne peut qu'améliorer » de la chaîne l'a
donc rejeté — correctement.

CAUSE. `_poser_via_dans_pastille` contrôle trois choses : le via tient dans la
pastille, le perçage respecte le minimum KiCad, le trou est libre. Il ne
contrôle **jamais le dégagement sur les couches que la pastille ne couvre
pas** — une pastille CMS n'existe que sur une face, le via traverse jusqu'à
l'autre, et y pose du cuivre que rien ne vouche.

C'est le défaut corrigé le matin même dans `_escape_pads`, resté intact dans sa
sœur. Sa docstring affirme pourtant :

    « Reutilise exactement les regles du fanout »

Cette phrase était vraie quand elle a été écrite ; le renforcement du fanout
l'a rendue fausse **sans que rien ne le signale**. Une garde qui compare les
deux fonctions l'aurait dit.

⚠️ Le prédicat de gêne est EXTRAIT pour être mesurable : inline dans deux
fonctions, il ne pouvait être teste que par leurs effets.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import routing_pcbnew_runner as RUN  # noqa: E402

MM = 1_000_000


class TestPredicatDeGene:
    """Un via est gêné si son cuivre approche un obstacle de trop près."""

    OBSTACLE = ("segment", 0, 0, 0, 10 * MM, 0.25 * MM)

    def test_un_via_LOIN_de_tout_n_est_pas_gene(self):
        assert RUN._via_gene_par(5 * MM, 5 * MM, 0.6 * MM, 0.2 * MM,
                                 [self.OBSTACLE]) is False

    def test_le_cas_mesure_a_0_048_mm_est_GENE(self):
        # Le via touche presque la piste : 0,048 mm pour 0,2 mm exiges.
        obs = ("segment", 0, 0, 0, 10 * MM, 0.25 * MM)
        assert RUN._via_gene_par(0.35 * MM, 5 * MM, 0.6 * MM, 0.2 * MM,
                                 [obs]) is True

    def test_sans_obstacle_rien_ne_gene(self):
        assert RUN._via_gene_par(0, 0, 0.6 * MM, 0.2 * MM, []) is False

    def test_le_DEGAGEMENT_entre_dans_la_decision(self):
        # ⚠️ Le meme via, au meme endroit : seule la regle change.
        obs = ("segment", 0, 0, 0, 10 * MM, 0.0)
        loin = RUN._via_gene_par(0.5 * MM, 5 * MM, 0.6 * MM, 0.05 * MM, [obs])
        pres = RUN._via_gene_par(0.5 * MM, 5 * MM, 0.6 * MM, 0.5 * MM, [obs])
        assert (loin, pres) == (False, True)


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(
        encoding="utf-8")

    def _corps(self, nom: str) -> str:
        i = self.SOURCE.index("def %s(" % nom)
        j = self.SOURCE.find(chr(10) + "def ", i + 1)
        return self.SOURCE[i:j if j != -1 else len(self.SOURCE)]

    def test_la_pose_en_pastille_VERIFIE_les_couches_nues(self):
        assert "_couches_traversees_hors_pastille(" in self._corps(
            "_poser_via_dans_pastille")

    def test_les_DEUX_fonctions_partagent_le_predicat(self):
        # ⚠️ LA GARDE QUI MANQUAIT. Les deux poses de via en pastille doivent
        # appliquer la MEME regle ; c est leur divergence silencieuse qui a
        # laisse `stm32-100` a une connexion du but.
        for nom in ("_escape_pads", "_poser_via_dans_pastille"):
            assert "_via_gene_par(" in self._corps(nom), nom

    def test_la_pose_recoit_un_DEGAGEMENT(self):
        # Sans lui, la fonction ne peut pas mesurer ce qu elle doit refuser.
        entete = self._corps("_poser_via_dans_pastille").split(")")[0]
        assert "clearance" in entete, entete

    def test_le_TROU_reste_verifie(self):
        # On ajoute une regle, on n en retire aucune.
        assert "_trou_libre(" in self._corps("_poser_via_dans_pastille")

    def test_l_APPELANT_transmet_le_degagement(self):
        # ⚠️ LA GARDE DECISIVE. `clearance` a une valeur par defaut de 0, et la
        # verification des couches nues est sautee quand elle vaut 0. Un
        # appelant qui l omettrait rendrait la regle INERTE — indistinguable
        # d une regle absente, la faute la plus repetee de ce depot.
        corps = self._corps("_retirer_ilots_flottants")
        assert "clearance_mm" in corps, "l operation ne lit aucun degagement"
        i = corps.index("_poser_via_dans_pastille(")
        j = corps.index(")", corps.index("trous", i))
        assert "clearance" in corps[i:j + 1], corps[i:j + 1]
