"""Le keepout ne doit PAS partir dans le DSN : il bloquerait le routage.

⚠️ REGRESSION QUE J AI INTRODUITE le 2026-09-01, mesuree dans l heure.

Le correctif 5c759c0 a remis les keepouts fine-pitch sur leur boitier — ils
etaient poses 87 mm a cote depuis toujours. Effet immediat sur `nucleo-f401` :

    tirage fige a ~0% au palier 2 couches   (x3)
    tirage fige a ~0% au palier 4 couches   (x2)

CINQ tirages, zero pour cent. Pas de la dispersion : le routeur ne route plus
RIEN.

CAUSE, mesuree sur le DSN reellement exporte :

    keepouts dans le board : 3
    (keepout ...) dans le DSN : 3

En Specctra, un `(keepout)` NU bloque TOUT — pistes ET vias — la ou nos zones
KiCad ne declarent que `(copperpour not_allowed)`, tracks et vias autorises.
L export perd la nuance. Le routeur se voyait donc interdire toute la surface
du LQFP-64, c est-a-dire l endroit meme ou sortent ses 64 broches.

Tant que les keepouts etaient HORS CARTE, ils ne bloquaient que du vide : le
defaut de coordonnees masquait le defaut d export. Corriger le premier a
revele le second.

LA REGLE. Le keepout sert a empecher la COULEE, pas le ROUTAGE — et la coulee
a deja eu lieu quand on exporte. Il n a donc rien a faire dans le DSN. Il reste
dans le board livre, ou KiCad le respecte au remplissage.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402

LF = chr(10)

_AVEC = (
    "(kicad_pcb" + LF
    + '  (net 1 "GND")' + LF
    + '  (footprint "R"' + LF + "    (at 10 10)" + LF
    + '    (pad "1" smd rect (at 0 0) (size 1 1))' + LF + "  )" + LF
    + '  (zone (net 1) (net_name "GND") (layer "F.Cu")' + LF
    + "    (fill yes)" + LF + "  )" + LF
    + '  (zone (net 0) (net_name "") (layer "F.Cu")' + LF
    + "    (keepout (tracks allowed) (vias allowed) (pads allowed)" + LF
    + "      (copperpour not_allowed) (footprints allowed))" + LF
    + "    (polygon (pts (xy 1 1) (xy 2 1) (xy 2 2) (xy 1 2)))" + LF
    + "  )" + LF + ")"
).encode("utf-8")


class TestRetrait:
    def test_les_keepouts_partent(self):
        assert b"(keepout" not in R._sans_keepouts(_AVEC)

    def test_la_zone_de_masse_RESTE(self):
        # ⚠️ Retirer le plan avec le keepout serait catastrophique : le routeur
        # ne verrait plus le cuivre de masse et routerait comme sur une carte
        # vide — exactement le defaut mesure le 2026-08-29 (68 % contre 94 %).
        sortie = R._sans_keepouts(_AVEC)
        assert b'(net_name "GND")' in sortie
        assert b"(fill yes)" in sortie

    def test_le_reste_du_board_est_intact(self):
        sortie = R._sans_keepouts(_AVEC)
        assert b'(footprint "R"' in sortie
        assert b'(pad "1" smd rect' in sortie
        assert b'(net 1 "GND")' in sortie
        assert sortie.count(b"(") == sortie.count(b")")

    def test_un_board_sans_keepout_est_rendu_INCHANGE(self):
        nu = b'(kicad_pcb (net 1 "GND"))'
        assert R._sans_keepouts(nu) is nu


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_l_export_specctra_retire_les_keepouts(self):
        i = self.SOURCE.index("def _export_specctra(")
        j = self.SOURCE.index("\ndef ", i + 10)
        assert "_sans_keepouts(" in self.SOURCE[i:j], (
            "le keepout part encore dans le DSN et bloquera tout le routage")
