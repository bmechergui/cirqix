"""A l escalade, les pistes protegees sont LIBEREES autour des pastilles que le
meilleur board n a pas reliees — sinon deux couches de plus ne debloquent pas
une pastille encerclee (carte-08 : 96 % de 2 a 6 couches, 2026-09-11).
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
  (net 4 "GND")
  (segment (start 10 20) (end 12 20) (width 0.25) (layer "F.Cu") (uuid "a") (net 3))
  (via (at 12 20) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (uuid "b") (net 3))
  (segment (start 50 50) (end 60 50) (width 0.25) (layer "F.Cu") (uuid "c") (net 4))
)"""

_RAPPORT = {"unconnected_items": [
    {"description": "x", "items": [
        {"description": "Pad 1 [SIG] of R1", "pos": {"x": 11.0, "y": 21.0}},
        {"description": "Pad 2 [SIG] of U1", "pos": {"x": 40.0, "y": 40.0}},
    ]},
]}


class TestPositions:
    def test_lues_dans_le_rapport(self):
        assert R._positions_non_reliees(_RAPPORT) == [(11.0, 21.0), (40.0, 40.0)]

    def test_un_item_sans_position_est_ignore(self):
        assert R._positions_non_reliees({"unconnected_items": [{"items": [{"description": "x"}]}]}) == []


class TestLiberation:
    def test_les_pistes_pres_d_une_pastille_non_reliee_ne_sont_pas_protegees(self):
        bloc = R._bloc_wiring_pistes(_BOARD, liberer=[(11.0, 21.0)])
        assert "(net SIG)" not in bloc          # segment + via a moins de 2,5 mm : liberes
        assert bloc.count("(net GND)") == 1     # la piste lointaine reste protegee

    def test_sans_zone_tout_est_protege(self):
        bloc = R._bloc_wiring_pistes(_BOARD)
        assert bloc.count("(type protect)") == 3

    def test_le_rayon_est_court(self):
        assert 1.0 <= R._RAYON_LIBERATION_MM <= 4.0


class TestCablage:
    def test_le_changement_de_palier_calcule_les_zones(self):
        code = "\n".join(l.split("#")[0] for l in inspect.getsource(R.route_auto).splitlines())
        i_prot = code.find("_PISTES_A_PROTEGER = [base64.b64decode(meilleur.kicad_pcb_b64)]")
        i_zone = code.find("_ZONES_LIBEREES = _positions_non_reliees(")
        assert i_prot != -1 and i_zone != -1 and i_prot < i_zone

    def test_l_injection_transmet_les_zones(self):
        code = "\n".join(l.split("#")[0] for l in inspect.getsource(R._injecter_wiring).splitlines())
        assert "liberer=_ZONES_LIBEREES" in code

    def test_les_zones_sont_remises_a_zero_a_chaque_appel(self):
        code = "\n".join(l.split("#")[0] for l in inspect.getsource(R.route_auto).splitlines())
        assert "_ZONES_LIBEREES = []" in code
