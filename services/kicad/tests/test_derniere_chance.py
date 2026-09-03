"""Quand TOUS les tirages figent, on ne rend rien — alors que le routeur, lui,
continue et finit.

⚠️ Mesure du 2026-08-31, `nucleo-f401` au banc final, six tirages d affilee :

    2 couches   43 %   79 %   (3e)
    4 couches   77 %   77 %   62 %

Aucun n a ete conserve. `RoutageFige` ne transporte que des compteurs, jamais
le board, et le job abandonne CONTINUE de tourner dans la JVM — `cancel`
repond 501, on ne peut pas le tuer. Le cuivre existe donc, dans un job vivant,
et personne ne va le chercher.

Meme scenario la nuit precedente sur `stm32-100` : « Tous les routeurs ont
echoue » alors que des tirages avaient atteint 96 %.

⚠️ La detection de stagnation reste JUSTE : elle evite 44 minutes de politesse
sur un job condamne, et c est elle qui a rendu l escalade rapide. Ce qui
manquait est le cas limite — quand elle a tout abandonne et qu il ne reste
RIEN, mieux vaut attendre un tirage jusqu au bout que rendre une carte vide.

On ne desarme donc pas le detecteur : on lui ajoute une DERNIERE CHANCE, une
seule, au palier de depart, et seulement si le budget le permet. Le detecteur
de SILENCE, lui, reste actif — un routeur muet ne doit jamais tenir le budget.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestDrapeau:
    def test_l_abandon_est_autorise_par_defaut(self):
        # Le comportement normal ne change pas : la stagnation coupe.
        assert R._ABANDON_AUTORISE is True

    def test_desarme_la_fenetre_de_passes_ne_coupe_plus(self):
        assert R._fenetre_effective(150, autorise=False) == 0

    def test_arme_la_fenetre_est_celle_calculee(self):
        assert R._fenetre_effective(150, autorise=True) == 150

    def test_le_SILENCE_coupe_meme_desarme(self):
        """⚠️ Un routeur muet ne doit JAMAIS tenir le budget, derniere chance
        ou non : c est une panne, pas une lenteur."""
        assert R._faut_couper(plat=999, fenetre=0, muet=True) is True
        assert R._faut_couper(plat=999, fenetre=0, muet=False) is False


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def _boucle(self) -> str:
        i = self.SOURCE.index("essais = _paliers_avec_tirages(")
        return self.SOURCE[i:i + 5000]

    def test_la_derniere_chance_est_CABLEE(self):
        assert "derniere_chance" in self._boucle()

    def test_elle_ne_se_declenche_QUE_sans_resultat(self):
        """⚠️ Ancrer sur la GARDE, pas sur la premiere occurrence du mot.

        Premiere version : chercher « meilleur is None » a +/- 400 caracteres
        du premier « derniere_chance ». Or ce premier est l initialisation du
        drapeau, tout en haut de la boucle — loin de la condition. Une garde
        qui vise le mauvais endroit ne verifie rien.
        """
        corps = self._boucle()
        i = corps.index("derniere_chance_donnee" + chr(10))
        garde = corps[max(0, i - 300):i + 300]
        assert "meilleur is not None" in garde or "meilleur is None" in garde, (
            "la derniere chance doit etre reservee au cas ou RIEN n a ete garde")

    def test_elle_n_est_donnee_QU_UNE_FOIS(self):
        # Sinon une carte reellement impossible bouclerait sans fin.
        assert "derniere_chance_donnee" in self._boucle()

    def test_le_drapeau_est_ARME_A_L_ENTREE(self):
        """⚠️ Armer a l entree, et non restaurer a la sortie.

        Premiere version de cette garde : exiger un `finally`. Mais un
        `finally` ne protege que le chemin qui a desarme le drapeau, alors
        qu armer a l ENTREE repare en plus une fuite laissee par un appel
        precedent. `_ABANDON_AUTORISE` est un etat de MODULE partage par tout
        le worker : le laisser desarme ferait disparaitre la detection de
        stagnation sans que rien ne le dise — le pire des defauts silencieux.
        """
        i = self.SOURCE.index("def route_auto(")
        corps = self.SOURCE[i:i + 6000]
        assert "_armer_abandon(True)" in corps
        assert corps.index("_armer_abandon(True)") < corps.index(
            "essais = _paliers_avec_tirages("), (
            "le drapeau doit etre arme AVANT la boucle des paliers")

    def test_la_fenetre_effective_est_UTILISEE_dans_l_attente(self):
        # ⚠️ Meme correction que dans test_plafond_muet : s ancrer sur L URL,
        # pas sur le nom de l appelant. `_api` a du sortir au niveau module le
        # 2026-08-31 — elle etait imbriquee et `_recuperer_jobs_abandonnes`
        # levait `NameError` a chaque appel — et l appel local s appelle
        # desormais `_appel`.
        i = self.SOURCE.index('f"{pre}/jobs/{job_id}/start"')
        assert "_fenetre_effective(" in self.SOURCE[i:i + 12000]
