"""Le GA recoit UNE contrainte native par CI : ses condensateurs de decouplage
a portee de lui. Sans elle, le GA range les capas ou bon lui semble et le
snap, en dernier, ne trouve plus de place contre les broches — mesure du
2026-09-11 sur carte-09 (62 composants) : decouplage 19 mm, capas en paquet
sous le MCU. Etape 2 du pipeline « placement structure ».
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))
sys.path.insert(0, str(_SERVICE / "kicad-tools" / "src"))

from tools import placement_contraintes as C  # noqa: E402


_NETS = {}


class _Pad:
    def __init__(self, number, net_name, x, y):
        self.number, self.net_name, self.position = number, net_name, (x, y)
        # La detection native apparie par NUMERO de net : un vrai board en a.
        self.net_number = _NETS.setdefault(net_name, len(_NETS) + 1)


class _Fp:
    def __init__(self, ref, x, y, pads):
        self.reference, self.position, self.pads, self.rotation = ref, (x, y), pads, 0.0
        self.layer = "F.Cu"


class _Pcb:
    def __init__(self, fps):
        self.footprints = fps


def _carte():
    u1 = _Fp("U1", 40.0, 0.0, [_Pad(str(i), "+3V3" if i in (1, 24) else ("GND" if i in (8, 23) else "SIG%d" % i),
                               -3.5 + 0.5 * (i % 12), -3.5 if i < 25 else 3.5) for i in range(1, 49)])
    u2 = _Fp("U2", 0.0, 0.0, [_Pad(str(i), "+3V3" if i == 2 else ("GND" if i == 1 else "VIN"), 0.5 * i, 0) for i in range(1, 9)])
    caps = [_Fp("C%d" % i, 20.0 + i, 5.0, [_Pad("1", "+3V3", -0.5, 0), _Pad("2", "GND", 0.5, 0)]) for i in range(10, 14)]
    c1 = _Fp("C1", 2.0, 1.0, [_Pad("1", "+3V3", -0.5, 0), _Pad("2", "GND", 0.5, 0)])
    return _Pcb([u1, u2, c1] + caps)


class TestContraintes:
    def test_une_contrainte_par_CI_avec_ses_capas(self):
        cs = C.contraintes_de_decouplage(_carte())
        par_nom = {c.name: c for c in cs}
        assert any("U1" in n for n in par_nom), par_nom.keys()
        u1 = next(c for n, c in par_nom.items() if "U1" in n)
        assert "U1" in u1.members and len([m for m in u1.members if m.startswith("C")]) >= 2

    def test_l_ancre_est_le_CI_et_le_rayon_est_court(self):
        cs = C.contraintes_de_decouplage(_carte())
        for c in cs:
            sc = c.constraints[0]
            assert sc.parameters.get("anchor", "").startswith("U")
            assert 2.0 <= sc.parameters.get("radius_mm", 0) <= 12.0, sc.parameters

    def test_un_board_sans_CI_ne_rend_rien_et_ne_leve_pas(self):
        assert C.contraintes_de_decouplage(_Pcb([_Fp("R1", 0, 0, [_Pad("1", "A", 0, 0), _Pad("2", "B", 1, 0)])])) == []

    def test_contraintes_du_board_les_inclut(self):
        code = "\n".join(l.split("#")[0] for l in inspect.getsource(C.contraintes_du_board).splitlines())
        assert "contraintes_de_decouplage(" in code
