"""La boite d encombrement tourne avec le composant. carte-09, 2026-09-12 :
une 0402 a 90 degres etait testee couchee, deux capas « libres » se
chevauchaient (courtyards_overlap C35/C65, C36/C37) et le retrait cible les
renvoyait a 17-50 mm de leur broche."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from tools.placement_bypass import _boite_absolue, _centre_et_demi  # noqa: E402


def _fp(rotation: float):
    seg = SimpleNamespace(layer="F.CrtYd", start=(-1.0, -0.5), end=(1.0, 0.5))
    return SimpleNamespace(reference="C1", position=(10.0, 20.0), rotation=rotation, graphics=[seg], pads=[])


def test_sans_rotation_la_boite_est_celle_du_courtyard():
    assert _boite_absolue(_fp(0.0)) == (9.0, 19.5, 11.0, 20.5)


def test_a_90_degres_largeur_et_hauteur_s_echangent():
    x0, y0, x1, y1 = _boite_absolue(_fp(90.0))
    assert abs(x0 - 9.5) < 1e-6 and abs(x1 - 10.5) < 1e-6
    assert abs(y0 - 19.0) < 1e-6 and abs(y1 - 21.0) < 1e-6
    cx, cy, hw, hh = _centre_et_demi(_fp(90.0))
    assert abs(hw - 0.5) < 1e-6 and abs(hh - 1.0) < 1e-6


def test_a_180_degres_rien_ne_change():
    x0, y0, x1, y1 = _boite_absolue(_fp(180.0))
    assert abs(x0 - 9.0) < 1e-6 and abs(x1 - 11.0) < 1e-6 and abs(y0 - 19.5) < 1e-6
