"""Le keepout fine-pitch doit tomber SUR le boitier, pas a 60 mm de la.

⚠️ Trouve le 2026-09-01 par l UTILISATEUR, a l oeil, sur une capture KiCad :
trois rectangles vides flottant hors de la carte, en haut a gauche. Aucun
compteur, aucun test, aucun rapport DRC ne l avait signale en trois mois.

CAUSE, mesuree sur `nucleo-f401`, MEME board, MEMES boitiers :

    boitier                kicad-tools          pcbnew
    LQFP-64_10x10mm     ( 67.02,  59.24)   (154.27, 118.29)
    SOT-223-3_TabPin2   (102.89,  82.48)   (190.14, 141.53)
    PinHeader_1x02      ( 35.00,   5.00)   (122.25,  64.05)
    PinHeader_2x19      ( 50.00,   5.00)   (137.25,  64.05)

Ecart CONSTANT : (87.25, 59.05) — le coin du contour de carte.

`kicad-tools` rend les positions RELATIVES a l origine de la carte ; le format
`.kicad_pcb`, lui, les ecrit ABSOLUES. `_dense_footprint_boxes` lisait les
premieres et les ecrivait comme les secondes : chaque keepout atterrissait a
60-90 mm de son boitier, donc hors carte sur 7 boards sur 8.

⚠️ CE QUE CELA SIGNIFIE. Le keepout fine-pitch existe pour EMPECHER le plan de
masse de pretendre couvrir les pastilles d un boitier au pas de 0,5 mm — le
mecanisme documente comme cause des broches GND « couvertes mais non
reliees ». Il n a JAMAIS protege un seul boitier.

On lit donc les coordonnees directement dans le fichier, ou elles sont
absolues par construction : `(footprint ... (at X Y))` pour le boitier,
`(pad ... (at x y))` en relatif. Un seul referentiel, celui du fichier.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402

LF = chr(10)


def _board(x, y, pads):
    """Un board minimal : un boitier a (x, y) avec `pads` pastilles."""
    l = ["(kicad_pcb", '  (footprint "LQFP"', "    (at %s %s)" % (x, y)]
    for i, (px, py) in enumerate(pads, start=1):
        l.append('    (pad "%d" smd rect (at %s %s) (size 0.3 1.5))' % (i, px, py))
    l += ["  )", ")"]
    return LF.join(l).encode("utf-8")


class TestReferentiel:
    def test_la_boite_est_absolue_comme_le_fichier(self):
        # Boitier a (150, 100), pastilles a +-5 : la boite doit encadrer 150/100,
        # jamais 5 ou -5.
        pads = [(-5, -5), (5, -5), (5, 5), (-5, 5)] * 4  # 16 pads
        boites = R._boites_fine_pitch(_board(150, 100, pads))
        assert len(boites) == 1
        x1, y1, x2, y2 = boites[0]
        assert 140 < x1 < 146 and 154 < x2 < 160, (x1, x2)
        assert 90 < y1 < 96 and 104 < y2 < 110, (y1, y2)

    def test_la_marge_est_appliquee(self):
        pads = [(-5, -5), (5, 5)] * 8
        x1, y1, x2, y2 = R._boites_fine_pitch(_board(100, 100, pads))[0]
        assert abs((95 - x1) - R._KEEPOUT_MARGIN_MM) < 0.01
        assert abs((x2 - 105) - R._KEEPOUT_MARGIN_MM) < 0.01

    def test_un_boitier_peu_dense_est_ignore(self):
        # Une resistance n a pas besoin de keepout : le plan l atteint.
        assert R._boites_fine_pitch(_board(150, 100, [(-1, 0), (1, 0)])) == []

    def test_un_board_vide_ne_rend_rien(self):
        assert R._boites_fine_pitch(b"(kicad_pcb)") == []


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_le_keepout_utilise_la_lecture_absolue(self):
        i = self.SOURCE.index("def _add_ground_planes(")
        corps = self.SOURCE[i:i + 8000]
        assert "_boites_fine_pitch(" in corps, (
            "le keepout lit encore des coordonnees relatives a l origine carte")

    def test_kicad_tools_n_est_plus_la_source_des_boites(self):
        # ⚠️ C est le MELANGE de referentiels qui a coute trois mois de keepouts
        # inutiles. Une garde sur le nom de la fonction ne suffirait pas ; on
        # verifie que l ancien chemin a disparu.
        assert "def _dense_footprint_boxes" not in self.SOURCE
