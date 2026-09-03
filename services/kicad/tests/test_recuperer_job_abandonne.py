"""Le job abandonne CONTINUE dans la JVM et finit seul. On va chercher son cuivre.

⚠️ Mesure du 2026-08-31, `stm32-100` au banc final :

    12:35  tirage fige a 68 %
    12:39  tirage fige a 54 %
    13:10  tirage fige a 72 %
    13:42  escalade interrompue — budget epuise
           ECHEC : tous les routeurs ont echoue

Un board a 72 % A EXISTE. Son cuivre etait dans un job encore vivant — la JVM
n a pas de `cancel` (501), le job finit seul — et la chaine a rendu « aucun
routage ».

⚠️ La « DERNIERE CHANCE » livree le matin meme (`ae75892`) n a PAS pu jouer :
elle est conditionnee par `_budget_suffisant(...)`, or des tirages qui figent
consomment TOUT le budget (80 min mesurees pour 60 alloues). Un filet de
securite qui exige les ressources que la situation vient d epuiser ne sert a
rien. Relancer un routage etait la mauvaise reponse : il n y a plus de temps
pour router, mais le cuivre est deja la.

⚠️ NOTE DE COLLABORATION : ce mecanisme a ete ecrit par une AUTRE session
travaillant sur le meme worktree. J en avais commence un second, en doublon,
avant de m en apercevoir — le sien etait deja complet ET cable, le mien restait
mort, masque par sa declaration posee plus bas. Doublon retire, sa version
conservee, et ce fichier garde SA version.

Voir la memoire `sessions-paralleles-meme-worktree` : verifier ce qui existe
avant d ecrire, ne jamais ecraser du travail non commite.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestMemoire:
    def test_l_exception_porte_le_pourcentage_atteint(self):
        # C est la PREUVE d echec du palier, et le seul chiffre qui survive a
        # l abandon. Le board, lui, se recupere par le job.
        assert R.RoutageFige(unrouted=5, nets=100).routed_percent == 95

    def test_la_liste_des_jobs_abandonnes_existe(self):
        assert isinstance(R._JOBS_ABANDONNES, list)


class TestRecuperation:
    def test_aucun_job_abandonne_rend_None(self):
        R._JOBS_ABANDONNES.clear()
        assert R._recuperer_jobs_abandonnes(b"(kicad_pcb)") is None

    def test_un_job_injoignable_ne_LEVE_pas(self):
        """⚠️ Le job peut avoir disparu, la JVM avoir redemarre, la sortie
        etre vide. Aucun de ces cas ne doit remplacer un echec franc par une
        exception — on rend None, l appelant garde son echec."""
        R._JOBS_ABANDONNES.clear()
        R._JOBS_ABANDONNES.append({"job_id": "ZZZ", "pre": "http://127.0.0.1:1/v1"})
        try:
            assert R._recuperer_jobs_abandonnes(b"(kicad_pcb)") is None
        finally:
            R._JOBS_ABANDONNES.clear()


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_la_levee_MEMORISE_le_job(self):
        i = self.SOURCE.index("raise RoutageFige(")
        avant = self.SOURCE[max(0, i - 1200):i]
        assert "_JOBS_ABANDONNES.append(" in avant, (
            "on abandonne le job sans garder de quoi le retrouver")

    def test_la_liste_est_VIDEE_a_chaque_appel(self):
        """⚠️ Etat de module : sans remise a zero, on recupererait le cuivre
        d une carte PRECEDENTE. Livrer le board d une autre carte comme le sien
        serait le pire defaut imaginable."""
        corps = self.SOURCE[self.SOURCE.index("def route_auto("):]
        assert "_JOBS_ABANDONNES.clear()" in corps
        assert corps.index("_JOBS_ABANDONNES.clear()") < corps.index(
            "essais = _paliers_avec_tirages(")

    def test_la_recuperation_n_a_lieu_QUE_sans_resultat(self):
        corps = self.SOURCE[self.SOURCE.index("def route_auto("):]
        i = corps.index("_recuperer_jobs_abandonnes(")
        assert "meilleur is None" in corps[max(0, i - 900):i], (
            "un board recupere ne doit jamais primer sur un routage abouti")

    def test_il_n_y_a_QU_UNE_implementation(self):
        """⚠️ J en avais commence une seconde, en doublon, sans voir celle
        d une autre session. Elle etait morte, masquee par la sienne — un
        doublon silencieux est exactement ce que ce projet traque."""
        assert self.SOURCE.count("def _recuperer_jobs_abandonnes") == 1
        assert self.SOURCE.count("_JOBS_ABANDONNES: list[dict] = []") == 1
