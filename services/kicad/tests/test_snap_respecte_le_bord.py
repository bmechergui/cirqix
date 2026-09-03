"""Le snap ignorait le BORD DE LA CARTE, et y poussait un composant.

⚠️ Mesure du 2026-09-02, `nucleo-f401`, par le chemin réel `auto_place` avec
la recherche élargie :

    médiane  58,5 -> 14,7 mm      max  68,7 -> 15,1 mm     ← excellent
    DRC      0 erreur -> 1 ERREUR                          ← inacceptable

L'erreur unique :

    copper_edge_clearance
    Board edge clearance violation (constraint 0,5000 mm; actual 0,4474 mm)
       Rectangle on Edge.Cuts
       Pad 1 [LED26] of D26 on F.Cu

CAUSE. `_cible_libre` teste ses candidats contre les BOÎTES DES COMPOSANTS
(`_boites_absolues`) et contre rien d'autre. Le contour de la carte n'a jamais
fait partie de ses obstacles. Tant que la recherche ne dépassait pas 4,5 mm,
elle ne pouvait pas atteindre le bord ; en l'élargissant, je le lui ai permis.

⚠️ Le défaut était donc LATENT, et c'est mon élargissement qui l'a réveillé.
Ce n'est pas une raison de revenir en arrière : c'est une raison de poser la
contrainte manquante. Un correctif qui découvre un défaut voisin doit le
traiter, pas le remettre sous le tapis.

⚠️ Les 0,5 mm ne sont PAS un seuil de réglage : c'est la contrainte que le DRC
applique lui-même (`board setup constraints edge clearance`). La reproduire
n'est pas une décision produit, c'est obéir au juge.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import placement_bypass as PB  # noqa: E402


CONTOUR = (0.0, 0.0, 100.0, 60.0)   # min_x, min_y, max_x, max_y


class TestDansLeContour:
    def test_une_boite_bien_au_centre_est_acceptee(self):
        assert PB._dans_le_contour((40, 25, 45, 30), CONTOUR, marge=0.5)

    def test_le_cas_mesure_est_REFUSE(self):
        # D26 dépassait de 0,05 mm : la boîte affleure le bord droit.
        assert not PB._dans_le_contour((99.55, 25, 100.05, 30), CONTOUR,
                                       marge=0.5)

    def test_une_boite_qui_touche_EXACTEMENT_le_bord_est_refusee(self):
        # Toucher n'est pas respecter un isolement de 0,5 mm.
        assert not PB._dans_le_contour((99.5, 25, 100.0, 30), CONTOUR, marge=0.5)

    def test_juste_au_dela_de_la_marge_c_est_bon(self):
        assert PB._dans_le_contour((99.0, 25, 99.5, 30), CONTOUR, marge=0.5)

    def test_les_quatre_bords_sont_gardes(self):
        assert not PB._dans_le_contour((-0.1, 25, 5, 30), CONTOUR, marge=0.5)
        assert not PB._dans_le_contour((40, -0.1, 45, 5), CONTOUR, marge=0.5)
        assert not PB._dans_le_contour((40, 55, 45, 60.1), CONTOUR, marge=0.5)
        assert not PB._dans_le_contour((99.9, 25, 100.1, 30), CONTOUR, marge=0.5)

    def test_sans_contour_connu_on_n_INTERDIT_rien(self):
        # ⚠️ Une carte dont on ne sait pas lire le contour ne doit pas voir son
        # snap éteint : on ne remplace pas une contrainte par un refus global.
        assert PB._dans_le_contour((40, 25, 45, 30), None, marge=0.5)


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "placement_bypass.py").read_text(
        encoding="utf-8")

    def _corps(self, nom: str) -> str:
        i = self.SOURCE.index("def %s(" % nom)
        j = self.SOURCE.find(chr(10) + "def ", i + 1)
        return self.SOURCE[i:j if j != -1 else len(self.SOURCE)]

    def test_la_recherche_consulte_REELLEMENT_le_contour(self):
        # ⚠️ Une contrainte correcte jamais appelée est indistinguable d'une
        # contrainte absente.
        assert "_dans_le_contour(" in self._corps("_cible_libre")

    def test_le_contour_est_lu_NATIVEMENT(self):
        # Règle du projet : vérifier ce que kicad-tools offre avant d'écrire
        # une extraction maison. `placement.py` l'utilise déjà.
        assert "extract_board_outline" in self.SOURCE
