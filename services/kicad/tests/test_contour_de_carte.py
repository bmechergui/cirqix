"""Le contour de carte ne se lit QUE dans les objets Edge.Cuts.

⚠️ Mesure du 2026-09-01, board `nucleo-f401` apres coulee des plans :

    _board_outline  : (-6.10, -6.10, 209.75, 150.95)
    pcbnew          : (87.20, 59.00, 209.80, 151.00)

Les MAXIMA concordent, les MINIMA sont absurdes — 93 mm d ecart.

CAUSE. `_board_outline` decoupait le texte sur `(gr_` et cherchait
« Edge.Cuts » dans le morceau. Or un morceau s etend jusqu au `(gr_` SUIVANT :
il avale donc tout ce qui se trouve entre les deux, y compris les
`(polygon (pts (xy ...)))` de nos propres zones de masse. Le contour se
contaminait lui-meme.

CONSEQUENCE VISIBLE, signalee par l utilisateur sur une capture KiCad : le plan
de masse part de (-6.1, -6.1) et deborde largement la carte, au lieu de suivre
son contour comme dans `stm32-validation` :

    reference   (xy 100.3 100.3) ... (xy 159.7 ...)   = le contour
    le notre    (xy  -6.1  -6.1) ... (xy 209.15 ...)  = n importe quoi

⚠️ TROISIEME CAS DU MEME PIEGE dans la journee : une lecture qui suppose qu un
bloc s arrete la ou l on croit. Les deux precedents etaient le keepout
fine-pitch (87 mm a cote) et la regex de segment (`(uuid)` intercale). On
delimite desormais chaque bloc par ses PROPRES parentheses.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402

LF = chr(10)


class TestLectureDuContour:
    def test_un_contour_simple_est_lu(self):
        b = (
            "(kicad_pcb" + LF
            + '  (gr_line (start 10 10) (end 100 10) (layer "Edge.Cuts"))' + LF
            + '  (gr_line (start 100 100) (end 10 100) (layer "Edge.Cuts"))' + LF
            + ")"
        ).encode("utf-8")
        assert R._board_outline(b) == (10.0, 10.0, 100.0, 100.0)

    def test_une_zone_qui_SUIT_le_contour_ne_le_pollue_pas(self):
        """⚠️ LE DEFAUT EXACT : le polygone de zone etait avale par le morceau."""
        b = (
            "(kicad_pcb" + LF
            + '  (gr_line (start 100 100) (end 160 100) (layer "Edge.Cuts"))' + LF
            + '  (gr_line (start 160 160) (end 100 160) (layer "Edge.Cuts"))' + LF
            + '  (zone (net 1) (net_name "GND") (layer "F.Cu")' + LF
            + "    (polygon (pts (xy -6.1 -6.1) (xy 209.1 -6.1)"
            + " (xy 209.1 150.3) (xy -6.1 150.3)))" + LF
            + "  )" + LF + ")"
        ).encode("utf-8")
        assert R._board_outline(b) == (100.0, 100.0, 160.0, 160.0)

    def test_un_trace_sur_une_AUTRE_couche_est_ignore(self):
        b = (
            "(kicad_pcb" + LF
            + '  (gr_line (start 1 1) (end 500 500) (layer "F.SilkS"))' + LF
            + '  (gr_line (start 10 10) (end 100 100) (layer "Edge.Cuts"))' + LF
            + ")"
        ).encode("utf-8")
        assert R._board_outline(b) == (10.0, 10.0, 100.0, 100.0)

    def test_sans_contour_on_ne_devine_pas(self):
        assert R._board_outline(b"(kicad_pcb)") is None
