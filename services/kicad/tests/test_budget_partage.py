"""Le budget de routage se PARTAGE entre les essais, il ne se donne pas au premier.

⚠️ Mesure du 2026-08-29, carte a 100 composants, budget 1800 s :

    palier 2 couches -> 59%
    escalade interrompue avant 2 couches — budget epuise

Un seul tirage a consomme les 1800 secondes. Il n y a donc eu ni re-tirage ni
escalade : les 59 % sont le PREMIER essai, garde faute de mieux. Le passage
precedent avait rendu 96 % — la chance d un bon premier tirage, pas une
propriete de la chaine.

Chaque essai recevait `max(restant, _MIN_LEVEL_BUDGET_S)`, c est-a-dire TOUT le
temps disponible. La methode — tirer plusieurs fois a chaque palier, escalader,
garder le meilleur — ne peut pas s exercer si le premier essai epuise le budget.

⚠️ Un plancher reste indispensable : un essai trop court ne rend qu un routage
tronque, et douze essais tronques valent moins qu un essai complet. Quand la
part descend sous le plancher, on prefere donc faire MOINS d essais mais
entiers — c est le comportement actuel, conserve.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestPart:
    def test_le_budget_se_divise_entre_les_essais_restants(self):
        assert R._part_de_budget(1200, 4) == 300

    def test_le_dernier_essai_prend_tout_ce_qui_reste(self):
        # Rien ne sert de reserver pour un essai qui n aura pas lieu.
        assert R._part_de_budget(1200, 1) == 1200

    def test_la_part_ne_descend_jamais_sous_le_plancher(self):
        # ⚠️ Ce test divisait 600 par 12 et attendait le plancher. 600 // 12
        # vaut 50, au-dessus des 30 s du plancher : il testait le mauvais cas
        # et echouait sur un code juste. On prend une division qui MORD.
        assert R._part_de_budget(120, 12) == R._MIN_LEVEL_BUDGET_S
        # Et une qui ne mord pas, pour que la borne reste une borne.
        assert R._part_de_budget(600, 12) == 50

    def test_un_budget_epuise_reste_epuise(self):
        assert R._part_de_budget(0, 4) == R._MIN_LEVEL_BUDGET_S


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")
    BOUCLE = SOURCE[SOURCE.index("essais = _paliers_avec_tirages("):]

    def test_la_boucle_partage_son_budget(self):
        assert "_part_de_budget(" in self.BOUCLE[:4000], (
            "sans partage, le premier essai peut consommer tout le temps")

    def test_le_nombre_d_essais_restants_est_connu(self):
        # Impossible de partager sans savoir combien d essais suivent.
        assert "enumerate(" in self.BOUCLE[:600]
