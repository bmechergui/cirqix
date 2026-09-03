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


class TestOrdre:
    """⚠️ Le retrait doit venir APRÈS le dernier remplissage de zones.

    Mesure du 2026-09-02 : placé avant `_reparer_reliefs_affames`, le retrait
    rendait « 0 îlot flottant » alors que `stm32-60` en portait un de 4,9 mm²,
    mesuré à 1 via et 0 reliant. Cette étape **recoule les zones**, et le
    remplissage régénère les îlots qu'on venait d'enlever.

    Même faute que le clamp contre le centrage des dominants (2026-08-27) et
    le snap contre le Géomètre (2026-08-29) : deux correctifs justes qui
    s'annulent. **L'ordre fait partie du correctif.**
    """

    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_le_retrait_vient_APRES_la_reparation_thermique(self):
        # Celle-ci recoule les zones : tout retrait qui la précède est annulé.
        retrait = self.SOURCE.rindex("final = _retirer_ilots_flottants(final)")
        thermique = self.SOURCE.rindex("final = _reparer_reliefs_affames(final)")
        assert retrait > thermique, (
            "le retrait precede un remplissage qui regenere les ilots")

    def test_le_retrait_vient_APRES_la_couture(self):
        # Un îlot qu'on aurait pu coudre ne doit pas être retiré.
        retrait = self.SOURCE.rindex("final = _retirer_ilots_flottants(final)")
        couture = self.SOURCE.rindex("_recoudre_les_zones")
        assert retrait > couture

    def test_le_board_retire_est_bien_CELUI_QUI_EST_RENDU(self):
        # Un retrait dont le resultat n'est pas encodé serait inerte.
        retrait = self.SOURCE.rindex("final = _retirer_ilots_flottants(final)")
        rendu = self.SOURCE.index("res.kicad_pcb_b64 = base64.b64encode(final)",
                                  retrait)
        assert rendu > retrait


class TestIlotAvecPastille:
    """Un îlot qui porte une pastille ne se supprime pas — il se RELIE.

    ⚠️ Mesure du 2026-09-02, `stm32-60`. La dernière rupture, annoncée par le
    DRC comme `Zone GND B.Cu ↔ Zone GND F.Cu`, vient d'un îlot de 4,9 mm² :

        1 via dedans · 0 reliant · contient la PASTILLE GND de C4

    Ce n'est pas du cuivre flottant : c'est le cuivre local de la pastille de
    masse de `C4`, isolé du reste du plan. Le retirer **déconnecterait C4**.

    Et le fanout ne la vise jamais : le DRC ne la déclare pas isolée, puisqu'elle
    EST reliée — à son petit îlot. C'est l'îlot qui n'atteint pas le plan.

    Or `C4` est CMS, large de 0,56 mm, et **surplombe le cuivre de masse de
    B.Cu**. Un via dans sa pastille la relie directement, comme pour `D1`,
    `D3` et `C5`.

    La règle : îlot sans pastille et sans via reliant → on retire. Îlot AVEC
    pastille et sans via reliant → on tente le via dans la pastille.
    """

    def test_un_ilot_avec_pastille_et_sans_reliant_appelle_le_VIA_EN_PASTILLE(self):
        assert RUN._ilot_a_relier_par_sa_pastille(
            vias_reliants=0, pastilles_dedans=1) is True

    def test_un_ilot_SANS_pastille_ne_le_declenche_pas(self):
        # Celui-là se retire — il n'y a rien à relier.
        assert RUN._ilot_a_relier_par_sa_pastille(
            vias_reliants=0, pastilles_dedans=0) is False

    def test_un_ilot_DEJA_relie_ne_le_declenche_pas(self):
        assert RUN._ilot_a_relier_par_sa_pastille(
            vias_reliants=2, pastilles_dedans=1) is False

    def test_les_deux_regles_sont_EXCLUSIVES(self):
        # ⚠️ Un îlot ne peut pas être à la fois retiré et relié.
        for vr in (0, 1, 3):
            for pd in (0, 1, 2):
                a = RUN._ilot_est_flottant(1, vr, pd)
                b = RUN._ilot_a_relier_par_sa_pastille(vr, pd)
                assert not (a and b), (vr, pd)
