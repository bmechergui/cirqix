"""Le plafond de temps devait attraper un routeur MUET. Il coupe un lent.

⚠️ Mesure du 2026-08-31, `stm32-100`, DEUX tirages independants, meme ligne :

    Freerouting fige (42 passes sans progres, 3 non routes, plafond de temps)

42 passes, pas 150. Ce n est pas le compteur de passes qui a coupe — c est
l horloge, sur un board a TROIS nets du but (96 %).

⚠️ Le plafond est AVEUGLE A LA TAILLE, et c est la faute :

    stm32-100 (100 composants)   300 s  =   42 passes
    carte simple                 300 s  =  des centaines de passes

La patience effective est donc INVERSEMENT proportionnelle a la taille de la
carte — la plus courte exactement la ou le routeur en a le plus besoin. Le
compteur de passes, lui, s adapte tout seul : 150 passes valent 22 s sur une
carte rapide et 17 min sur stm32-100. C est la bonne unite.

⚠️ Reference : sur les 461 jobs du journal Freerouting, le plus grand ecart
entre deux progres est de 144 passes. Couper a 42 revient a declarer mort un
job dont la cadence est parfaitement normale.

⚠️ On ne SUPPRIME pas le garde-fou : sans lui, un routeur reellement bloque
tiendrait le budget entier. On le ramene a son role — detecter le SILENCE
(aucune passe nouvelle), pas la lenteur. Et son seuil s adapte a la cadence
observee, sans quoi on recreerait le defaut de la Nucleo : un tirage abandonne
apres UNE passe sur un board ou une passe dure plusieurs minutes.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestSilence:
    def test_un_routeur_qui_parle_n_est_pas_muet(self):
        # Le cas mesure : passes qui defilent, board a 96 %. Ne pas couper.
        assert R._routeur_muet(silence_s=5.0, cadence_s=7.0, passes_vues=42) is False

    def test_un_routeur_silencieux_est_coupe(self):
        assert R._routeur_muet(silence_s=400.0, cadence_s=7.0, passes_vues=42) is True

    def test_le_seuil_s_adapte_a_une_cadence_LENTE(self):
        """⚠️ Defaut de la Nucleo, deja paye : un tirage abandonne apres UNE
        passe sur un board ou une passe dure plusieurs minutes."""
        # Cadence de 200 s : 400 s de silence, c est DEUX passes — normal.
        assert R._routeur_muet(silence_s=400.0, cadence_s=200.0,
                               passes_vues=3) is False
        # Au-dela de la marge, c est un vrai silence.
        assert R._routeur_muet(silence_s=900.0, cadence_s=200.0,
                               passes_vues=3) is True

    def test_sans_cadence_mesurable_on_ne_coupe_pas(self):
        """⚠️ « Je n ai pas pu mesurer » n est pas « il est mort ». Une seule
        passe vue ne permet aucune estimation de cadence."""
        assert R._routeur_muet(silence_s=9999.0, cadence_s=0.0, passes_vues=1) is False
        assert R._routeur_muet(silence_s=9999.0, cadence_s=7.0, passes_vues=1) is False

    def test_la_marge_est_bornee_par_le_bas(self):
        # Sur une carte tres rapide, 3 x cadence serait ridicule : le plancher
        # de 300 s evite de couper un job qui reflechit un instant.
        assert R._routeur_muet(silence_s=100.0, cadence_s=0.5,
                               passes_vues=50) is False


class TestDecision:
    def test_les_passes_coupent_quand_la_fenetre_est_atteinte(self):
        assert R._faut_couper(plat=150, fenetre=150, muet=False) is True

    def test_les_passes_ne_coupent_pas_avant_la_fenetre(self):
        # Le cas mesure : 42 passes plates, fenetre a 150.
        assert R._faut_couper(plat=42, fenetre=150, muet=False) is False

    def test_une_fenetre_nulle_signifie_NE_JAMAIS_COUPER(self):
        """⚠️ `_fenetre_stagnation` rend 0 pour dire « presque fini, ou compte
        inconnu : n abandonne pas ». L ancienne condition coupait quand meme
        par l horloge — l intention de la fonction etait annulee par la ligne
        qui l utilisait."""
        assert R._faut_couper(plat=9999, fenetre=0, muet=False) is False

    def test_le_silence_coupe_meme_une_fenetre_nulle(self):
        # Le garde-fou survit : un routeur muet ne doit pas tenir le budget.
        assert R._faut_couper(plat=0, fenetre=0, muet=True) is True


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_la_boucle_utilise_la_decision(self):
        assert "_faut_couper(" in self.SOURCE

    def test_la_boucle_mesure_le_SILENCE_et_pas_le_temps_sans_progres(self):
        # ⚠️ Ancrer sur le DEPART DU JOB, pas sur `_freerouting_input_payload` :
        # son premier occurrent est la DEFINITION de la fonction, loin de la
        # boucle d attente. Une garde mal ancree verifie autre chose que ce
        # qu elle croit.
        # ⚠️ Ancrer sur L URL, pas sur le nom de l appelant : celui-ci est
        # passe de `_api` a `_appel` le 2026-08-31, quand `_api` a du etre
        # sortie au niveau module — et la garde s est mise a lever
        # `ValueError` au lieu de mesurer. Ce qu elle verifie n a pas change.
        i = self.SOURCE.index('f"{pre}/jobs/{job_id}/start"')
        corps = self.SOURCE[i:i + 12000]
        assert "_routeur_muet(" in corps

    def test_le_numero_de_passe_est_suivi(self):
        # Sans lui, impossible de distinguer « lent » de « muet ».
        assert "_numero_de_passe(" in self.SOURCE
