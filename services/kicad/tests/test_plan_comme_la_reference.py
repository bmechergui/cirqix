"""Le plan de masse doit ressembler a celui de `stm32-validation`.

⚠️ DEMANDE DE L UTILISATEUR le 2026-09-01, capture KiCad a l appui : « je ne
veux pas le plan de masse comme ca, en rouge plein — je le veux comme le
propose KiCad, comme dans l exemple stm32-validation ».

COMPARAISON des deux boards, zone GND :

    reference   (connect_pads (clearance 0.3))    -> reliefs thermiques
                (priority 1)
                polygone = le contour de carte

    le notre    (connect_pads yes (clearance 0.25)) -> cuivre PLEIN, sans relief
                pas de priorite
                polygone = (-6.1, -6.1) ... hors carte

Trois ecarts, deux corriges ici, un ailleurs :

1. `connect_pads yes` soude le plan en plein sur chaque pastille. C est
   electriquement meilleur pour une masse, mais ce n est pas le rendu demande
   ni la pratique courante : KiCad fait des reliefs par defaut. On retire le
   `yes` et on GARDE l isolement de 0,25 mm, lui MESURE — a 0,5 mm le cuivre
   entre les pattes d un LQFP-48 disparait (6 connexions manquantes contre 3).

2. `(priority 1)` sur GND, comme la reference : quand plusieurs plans se
   recouvrent, la masse doit gagner.

3. Le polygone hors carte est corrige separement dans `_board_outline`
   (tests/test_contour_de_carte.py) : il venait d une lecture qui avalait les
   polygones de zone.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402

SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")


class TestFormeDeLaZone:
    def test_les_reliefs_thermiques_sont_actifs(self):
        assert "(connect_pads yes" not in SOURCE, (
            "le plan se soude en plein sur les pastilles, sans relief")
        assert "(connect_pads (clearance" in SOURCE

    def test_l_isolement_mesure_est_conserve(self):
        # ⚠️ 0,25 mm, mesure le 2026-08-21 sur un LQFP-48 au pas de 0,5 :
        # a 0,5 mm d isolement le cuivre entre les pattes disparait et il reste
        # 6 connexions manquantes, contre 3 a 0,25. Ne pas reprendre le 0,3 de
        # la reference sans remesurer.
        assert "(connect_pads (clearance 0.25))" in SOURCE

    def test_la_masse_est_prioritaire(self):
        assert "(priority 1)" in SOURCE
