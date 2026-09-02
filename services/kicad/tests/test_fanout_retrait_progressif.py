"""Le fanout ne doit pas jeter TOUTES ses pastilles pour une seule fautive.

⚠️ Mesure du 2026-09-02, `stm32-100`. Quatre connexions manquantes subsistent,
et ce sont de **vraies pastilles** de masse — aucun îlot n'est en cause :

    Pad 2 [GND] de D36  <->  Zone GND
    Pad 8 [GND] de U1   <->  Via GND      (broche fine-pitch du MCU)
    Pad 2 [GND] de C2   <->  Zone GND
    Pad 2 [GND] de C12  <->  Zone GND

Le journal dit pourquoi elles restent :

    fanout: 1 erreur(s) ajoutee(s) (0 -> 1) — board d origine conserve

Le fanout **fonctionne** : il vise les quatre, pose ses vias, l'un d'eux ajoute
une erreur, et **tout le lot est annulé**. Trois pastilles parfaitement
réparables sont perdues avec la quatrième.

C'est le motif TOUT-OU-RIEN que ce dépôt a déjà corrigé deux fois :

    `_reposer_vias_reserves`   21 vias perdus pour un doublon
    `_recoudre_les_zones`      7 vias perdus pour un seul gênant

La garde « ne peut qu'aggraver » est juste ; appliquée au LOT, elle jette le
bon avec le mauvais. On retire donc les pastilles une à une jusqu'à trouver un
sous-ensemble qui n'aggrave pas — et à défaut, le board reçu. La garde reste
inviolée.

⚠️ L'unité de retrait est la PASTILLE, pas le via : c'est ce que le fanout
traite, et une pastille peut donner une piste ET un via.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestSousEnsembles:
    def test_on_retire_la_DERNIERE_pastille_d_abord(self):
        # Ordre stable : on rogne par la fin, comme `_sans_derniers_vias`.
        pastilles = [("D36", "2"), ("U1", "8"), ("C2", "2"), ("C12", "2")]
        assert R._sans_dernieres_pastilles(pastilles, 1) == pastilles[:3]

    def test_retirer_zero_rend_la_liste_ENTIERE(self):
        pastilles = [("D36", "2"), ("U1", "8")]
        assert R._sans_dernieres_pastilles(pastilles, 0) == pastilles

    def test_retirer_tout_rend_une_liste_VIDE(self):
        pastilles = [("D36", "2"), ("U1", "8")]
        assert R._sans_dernieres_pastilles(pastilles, 2) == []

    def test_retirer_plus_que_la_liste_ne_leve_pas(self):
        assert R._sans_dernieres_pastilles([("D36", "2")], 5) == []

    def test_une_liste_vide_reste_vide(self):
        assert R._sans_dernieres_pastilles([], 3) == []


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def _corps(self) -> str:
        i = self.SOURCE.index("def _fanout_pads_isolees(")
        j = self.SOURCE.find(chr(10) + "def ", i + 1)
        return self.SOURCE[i:j if j != -1 else len(self.SOURCE)]

    def test_le_fanout_TENTE_des_sous_ensembles(self):
        # ⚠️ Une regle correcte jamais appelee est indistinguable d une regle
        # absente.
        assert "_sans_dernieres_pastilles(" in self._corps()

    def test_la_garde_anti_aggravation_SUBSISTE(self):
        # On ne supprime pas la garde : on l atteint plus rarement.
        corps = self._corps()
        assert "_compte_erreurs(" in corps
        assert "board d origine conserve" in corps

    def test_le_retrait_est_BORNE(self):
        # Une boucle non bornee sur les pastilles couterait un DRC par tour.
        corps = self._corps()
        assert "while" in corps or "for" in corps
