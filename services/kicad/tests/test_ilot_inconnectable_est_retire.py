"""Un îlot de plan qu'aucun via ne relie est du cuivre FLOTTANT — on le retire.

⚠️ Mesure du 2026-09-02, `stm32-60`, board réparé. Comptage des vias GND par
îlot, et de ceux qui atteignent réellement du cuivre de masse en face :

    F.Cu  12792,2 mm²   40 vias dedans   40 reliants
    F.Cu    328,5 mm²   20 vias          20 reliants
    F.Cu    207,7 mm²   20 vias          20 reliants
    F.Cu      6,6 mm²    5 vias           5 reliants
    F.Cu      4,9 mm²    1 via            **0 reliant**

Un seul îlot reste : 4,9 mm², percé une fois, et ce via ne touche aucun cuivre
de masse sur la face opposée. Du cuivre percé pour rien.

⚠️ LA SUPPRESSION NATIVE DE KiCad NE PEUT RIEN ICI. `ISLAND_REMOVAL_MODE_ALWAYS`
est déjà actif et retire les îlots sans connexion — mais celui-ci **a** un via,
donc KiCad le croit connecté. Le via, lui, ne relie rien. Mesuré : régler le
mode et recouler ne change aucune connexion manquante sur les quatre cartes.

## Pourquoi retirer plutôt que relier ou laisser

Question posée à Grok le 2026-09-02, qui tranche pour la suppression :

    « C'est du cuivre flottant, pas un îlot de référence mal cousu. Plus
      aucune liaison : ce n'est plus une référence, c'est une plaque. »

    « Le laisser est le pire des trois : 24 mm² à 0,2 mm des pistes, c'est une
      antenne et un condensateur de couplage pile sur les signaux qui l'ont
      isolé. »

    « Élargir l'isolement de la zone est trop large : cela mange aussi le
      cuivre GND utile autour. »

Et il met en garde contre trois raccourcis : forcer un via hors isolement,
coudre jusqu'à un seul îlot, ou laisser du flottant sous prétexte que la carte
est déjà à 98 %.

⚠️ **CHIRURGICAL, PAS UN SEUIL.** On ne retire pas « les îlots de moins de
N mm² » — un petit plan encore relié est utile, et le projet a mesuré qu'une
carte livrée à 100 % portait six îlots. On retire ceux dont AUCUN via
n'atteint le cuivre d'en face, quelle que soit leur taille.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import routing_pcbnew_runner as RUN  # noqa: E402


class TestQuelIlotRetirer:
    def test_un_ilot_sans_via_reliant_est_retire(self):
        # Le cas mesuré : 4,9 mm², un via, zéro reliant.
        assert RUN._ilot_est_flottant(vias_dedans=1, vias_reliants=0,
                                      pastilles_dedans=0) is True

    def test_un_ilot_SANS_AUCUN_via_est_retire(self):
        assert RUN._ilot_est_flottant(vias_dedans=0, vias_reliants=0,
                                      pastilles_dedans=0) is True

    def test_un_ilot_avec_UN_SEUL_via_reliant_est_GARDE(self):
        # ⚠️ Un via reliant suffit : l'îlot est une référence valide.
        assert RUN._ilot_est_flottant(vias_dedans=3, vias_reliants=1,
                                      pastilles_dedans=0) is False

    def test_un_ilot_qui_porte_une_PASTILLE_du_net_est_garde(self):
        # ⚠️ Même sans via, un îlot relié à une pastille GND sur la MÊME face
        # reste une référence — Grok le souligne explicitement.
        assert RUN._ilot_est_flottant(vias_dedans=0, vias_reliants=0,
                                      pastilles_dedans=2) is False

    def test_la_TAILLE_n_entre_pas_dans_la_decision(self):
        # ⚠️ Pas de seuil d'aire : le projet a mesuré qu'une carte livrée à
        # 100 % portait six îlots, dont de tout petits, tous connectés.
        # ⚠️ Sur le CODE, docstring exclue : elle cite légitimement la mesure
        # « 4,9 mm² » qui a motivé la règle. Une garde qui lit la prose ne
        # mesure pas la décision.
        import inspect
        src = inspect.getsource(RUN._ilot_est_flottant)
        corps = src.split('"""')[-1]
        assert "aire" not in corps.lower() and "mm2" not in corps.lower(), corps
        # Et la signature ne reçoit aucune surface.
        assert "aire" not in str(inspect.signature(RUN._ilot_est_flottant))


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(
        encoding="utf-8")

    def test_l_operation_de_retrait_existe_et_est_declaree(self):
        assert '"retirer_ilots_flottants"' in self.SOURCE

    def test_le_retrait_utilise_la_REGLE(self):
        i = self.SOURCE.index("def _retirer_ilots_flottants(")
        j = self.SOURCE.find(chr(10) + "def ", i + 1)
        assert "_ilot_est_flottant(" in self.SOURCE[i:j]

    def test_le_retrait_COMPTE_ce_qu_il_enleve(self):
        # Un retrait silencieux serait indistinguable d'un retrait absent.
        i = self.SOURCE.index("def _retirer_ilots_flottants(")
        j = self.SOURCE.find(chr(10) + "def ", i + 1)
        assert '"retires"' in self.SOURCE[i:j]
