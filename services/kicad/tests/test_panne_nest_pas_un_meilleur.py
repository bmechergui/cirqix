"""Une PANNE ne peut pas etre retenue comme « le meilleur resultat ».

⚠️ Mesure du 2026-09-01, banc final, `stm32-100` :

    7 tirages, TOUS figes   73, 54, 25, 57 % (2 couches) · 25, 73, 52 % (4)
    dernier essai           API en timeout, kicad-tools sans budget
                            -> « palier 6 couches -> 0% (aucun moteur) »
    verdict rendu           ECHEC [routage] Tous les routeurs ont echoue

Un board a 73 % existait dans la JVM, et `_recuperer_jobs_abandonnes` — repare
la nuit meme — n a JAMAIS ete appele. Raison : la boucle ecrit

    if meilleur is None or _palier_meilleur(...):

Le PREMIER resultat devient donc « le meilleur », quel qu il soit. Les tirages
figes ne rendent rien (ils levent `RoutageFige`), si bien que le seul resultat
de tout le run fut la PANNE finale — `skipped`, 0 %, sans board. Elle a pris la
place du meilleur, `meilleur is None` est devenu faux, et le dernier recours a
ete saute.

La doctrine est pourtant ecrite dans CLAUDE.md depuis le 2026-08-29 :
« NEVER lire un 0 % comme un verdict de routage. "0 % (aucun moteur)" est une
panne — moteur injoignable, budget epuise avant le repli. » Le code ne
l appliquait pas a CET endroit.

Une panne n est pas un mauvais resultat : c est l ABSENCE de resultat. Elle ne
peut donc ni etre livree, ni empecher un vrai board d etre recupere.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


def _rep(pct=0, skipped=False, board="AAAA"):
    return R.RouteAutoResponse(
        kicad_pcb_b64=board, routed_percent=pct, layers=2, skipped=skipped)


class TestPanne:
    def test_un_resultat_skipped_est_une_panne(self):
        assert R._est_une_panne(_rep(pct=0, skipped=True)) is True

    def test_un_zero_pour_cent_sans_board_est_une_panne(self):
        assert R._est_une_panne(_rep(pct=0, board="")) is True

    def test_un_routage_partiel_N_EST_PAS_une_panne(self):
        # 52 % est un mauvais resultat, pas une absence de resultat : il doit
        # pouvoir etre retenu et livre.
        assert R._est_une_panne(_rep(pct=52)) is False

    def test_un_zero_pour_cent_AVEC_board_n_est_pas_une_panne(self):
        # Un board reellement route a 0 % reste un board : le distinguer d une
        # panne est tout l enjeu — « mesure a zero » contre « jamais mesure ».
        assert R._est_une_panne(_rep(pct=0, board="AAAA")) is False


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_la_boucle_ecarte_les_pannes(self):
        # ⚠️ Garde de CABLAGE : la fonction seule ne sert a rien si la boucle
        # continue d accepter le premier resultat venu.
        i = self.SOURCE.index("meilleur, meilleur_note = res")
        avant = self.SOURCE[max(0, i - 900):i]
        assert "_est_une_panne(" in avant, (
            "la boucle retient encore une panne comme meilleur resultat")

    def test_le_dernier_recours_reste_atteignable(self):
        # C est lui que la panne empechait de jouer.
        assert "_recuperer_jobs_abandonnes(pcb_bytes)" in self.SOURCE
