"""Les pistes protegees emportent leurs VIAS, et les vias injectes portent le
padstack du DSN — pas la constante a deux couches.

Mesure du 2026-09-11, 09:08, carte-10, palier 4 couches : « via padstack not
found », 673 pistes protegees sans leurs vias, 88 % a 2 couches -> 79 % a 4.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402

_BOARD = b"""(kicad_pcb (version 20240108) (generator "pcbnew")
  (net 0 "")
  (net 3 "SIG")
  (segment (start 10 20) (end 12 20) (width 0.25) (layer "F.Cu") (uuid "a") (net 3))
  (via (at 12 20) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (uuid "b") (net 3))
  (segment (start 12 20) (end 12 25) (width 0.25) (layer "B.Cu") (uuid "c") (net 3))
)"""

_DSN_4C = """(pcb x (structure (layer F.Cu) (layer In1.Cu) (layer In2.Cu) (layer B.Cu))
  (library (padstack "Via[0-3]_600:300_um" (shape (circle F.Cu 600))))
  (network (net SIG (pins U1-1 U1-2)) (class kicad_default "" SIG (circuit (use_via "Via[0-3]_600:300_um"))))
  (wiring )
)"""


class TestPadstack:
    def test_lu_dans_le_dsn(self):
        assert R._padstack_via_du_dsn(_DSN_4C) == "Via[0-3]_600:300_um"

    def test_deux_couches_par_defaut(self):
        assert R._padstack_via_du_dsn("(pcb x)") == R._PADSTACK_VIA == "Via[0-1]_600:300_um"


class TestPistesProtegees:
    def test_les_vias_du_board_sont_proteges_avec_les_segments(self):
        bloc = R._bloc_wiring_pistes(_BOARD)
        assert bloc.count("(wire") == 2
        assert bloc.count("(via") == 1
        assert '(via "%s" 12000.0 -20000.0 (net SIG) (type protect))' % R._PADSTACK_VIA in bloc

    def test_l_injection_pose_le_padstack_du_dsn(self):
        dsn = R._injecter_wiring(_DSN_4C, [], "GND", pistes=_BOARD)
        assert "Via[0-3]_600:300_um" in dsn
        assert "Via[0-1]_600:300_um" not in dsn, "le placeholder a deux couches a survecu a l injection"
        assert dsn.count("(type protect)") == 3

    def test_un_via_sans_net_est_ecarte(self):
        board = _BOARD.replace(b'(uuid "b") (net 3)', b'(uuid "b") (net 0)')
        assert R._bloc_wiring_pistes(board).count("(via") == 0


def test_le_bloc_des_vias_reserves_passe_aussi_par_le_padstack_du_dsn():
    code = "\n".join(l.split("#")[0] for l in inspect.getsource(R._injecter_wiring).splitlines())
    assert "_padstack_via_du_dsn(dsn_text)" in code
