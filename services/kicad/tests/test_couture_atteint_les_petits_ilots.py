"""Les petits îlots de plan ne recevaient AUCUN via — la grille les sautait.

⚠️ Mesure du 2026-09-02, boards finaux. Nombre de vias GND tombant DANS chaque
îlot du plan :

    nucleo-f401   11002 · 1480 · 238 · 128 · 75 · 60 · 50 mm²   1 à 23 vias
                      8,4 mm²                                   **0 via**

    stm32-30       4059 · 338 · 71 mm²                          4 à 20 vias
                     23,9 · 21,2 · 12,4 mm²                     **0 via**

    stm32-60      12792 · 329 · 208 mm²                         5 à 21 vias
                      6,6 · 4,9 mm²                             **0 via**

Le compte des îlots sans via correspond exactement aux ruptures `plan ↔ plan`
signalées par le DRC. Tous les îlots plus grands sont reliés.

CAUSE. `_stitch_zones` échantillonne ses candidats avec

    _points_dans_boite(..., pas=via_d * 3)      soit 1,8 mm

Sur un îlot de 5 mm² — typiquement une languette étroite entre deux pistes —
aucun point de cette grille ne tombe à l'intérieur. L'îlot n'est pas refusé :
il n'est **jamais visité**.

⚠️ Ce n'est donc NI un problème de cuivre en face, NI un besoin de pont entre
îlots. J'avais conclu aux deux, sur une sonde qui ne testait que le CENTRE de
la boîte englobante — un point qui tombe dans un trou dès que le polygone est
concave. Elle déclarait même le plan principal de 32012 mm² « sans cuivre en
face », ce qui est absurde. Mesurer par échantillonnage a corrigé les deux
conclusions.

REMÈDE — le pas se DÉDUIT de l'îlot, il n'est pas choisi. Il doit être assez
fin pour que la plus petite dimension de la boîte reçoive plusieurs points, et
jamais plus fin que le via qu'on y posera : échantillonner sous cette taille
ne ferait que payer des essais sans gain.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import routing_pcbnew_runner as RUN  # noqa: E402

MM = 1_000_000


class TestPasAdapte:
    def test_un_grand_ilot_garde_le_pas_large(self):
        # Rien ne change là où la couture fonctionnait déjà.
        pas = RUN._pas_d_echantillonnage(largeur=60 * MM, hauteur=40 * MM,
                                         via_d=0.6 * MM)
        assert pas == 1.8 * MM

    def test_une_languette_ETROITE_recoit_un_pas_fin(self):
        # Le cas mesuré : un îlot de ~5 mm², large de 0,5 mm.
        pas = RUN._pas_d_echantillonnage(largeur=0.5 * MM, hauteur=10 * MM,
                                         via_d=0.6 * MM)
        assert pas < 1.8 * MM

    def test_le_pas_ne_descend_JAMAIS_sous_le_via(self):
        # ⚠️ Échantillonner plus fin que le via qu'on pose ne fait que payer
        # des essais sans gain : deux points distants de moins d'un diamètre
        # donnent le même verdict.
        pas = RUN._pas_d_echantillonnage(largeur=0.05 * MM, hauteur=0.05 * MM,
                                         via_d=0.6 * MM)
        assert pas >= 0.6 * MM

    def test_la_petite_dimension_commande(self):
        # Une languette longue mais fine doit être traitée comme fine.
        etroit = RUN._pas_d_echantillonnage(0.8 * MM, 50 * MM, 0.6 * MM)
        large = RUN._pas_d_echantillonnage(50 * MM, 50 * MM, 0.6 * MM)
        assert etroit < large

    def test_une_boite_degeneree_ne_casse_rien(self):
        assert RUN._pas_d_echantillonnage(0, 0, 0.6 * MM) >= 0.6 * MM

    def test_le_pas_reste_STRICTEMENT_positif(self):
        # Un pas nul ferait boucler `_points_dans_boite` indéfiniment.
        for l, h in ((0, 10 * MM), (10 * MM, 0), (0, 0), (-5, -5)):
            assert RUN._pas_d_echantillonnage(l, h, 0.6 * MM) > 0


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(
        encoding="utf-8")

    def _stitch(self) -> str:
        i = self.SOURCE.index("def _stitch_zones(")
        j = self.SOURCE.find(chr(10) + "def ", i + 1)
        return self.SOURCE[i:j if j != -1 else len(self.SOURCE)]

    def test_la_couture_UTILISE_le_pas_adapte(self):
        # ⚠️ Une règle correcte jamais appelée est indistinguable d'une règle
        # absente.
        assert "_pas_d_echantillonnage(" in self._stitch()

    def test_le_pas_FIXE_a_disparu_de_la_couture(self):
        # `via_d * 3` en dur était précisément le défaut.
        code = [l for l in self._stitch().split(chr(10))
                if not l.strip().startswith("#")]
        assert not [l for l in code if "via_d * 3" in l], (
            "le pas fixe de 3 diametres est toujours la")
