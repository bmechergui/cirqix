"""Une broche GND dont le DRC decrit la rupture par son TRONCON est une
orpheline du plan comme les autres.

Mesure du 2026-09-12 (stm32-100, quatre tirages a 96 %) : U1-8 portait un
troncon de 1,2 mm vers un via que le retrait des ilots flottants avait
emporte. Le DRC ecrivait « Track [GND] <-> Via [GND] », jamais « Pad 8 » :
`_pads_isolees_du_plan` ne voyait aucune pastille, le repli GND cible ne
se declenchait pas, et la carte restait a 96 % tirage apres tirage.
Un item GND pose SUR une pastille designe cette pastille.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as routing_router  # noqa: E402

_BOARD = b'''(kicad_pcb (version 20240108) (generator "pcbnew")
  (net 0 "")
  (net 2 "GND")
  (footprint "Package_QFP:LQFP-48_7x7mm_P0.5mm" (layer "F.Cu")
    (at 157.3375 111.75)
    (property "Reference" "U1" (at 0 0 0) (layer "F.SilkS"))
    (pad "8" smd roundrect (at -4 0) (size 1.5 0.3) (layers "F.Cu") (net 2 "GND"))
    (pad "9" smd roundrect (at -4 0.5) (size 1.5 0.3) (layers "F.Cu") (net 0 ""))
  )
)
'''

_RAPPORT = {
    "unconnected_items": [
        {
            "items": [
                {"description": "Track [GND] on F.Cu, length 1.2000 mm",
                 "pos": {"x": 153.3375, "y": 111.75}},
                {"description": "Via [GND] on F.Cu - B.Cu",
                 "pos": {"x": 150.5, "y": 112.42}},
            ]
        },
        {
            "items": [
                {"description": "Track [GPIO26] on F.Cu, length 0.1177 mm",
                 "pos": {"x": 168.9, "y": 105.3}},
                {"description": "Pad 29 [GPIO26] of U1 on F.Cu",
                 "pos": {"x": 161.66, "y": 111.75}},
            ]
        },
    ]
}


def test_le_troncon_pose_sur_la_pastille_designe_la_pastille(monkeypatch):
    monkeypatch.setattr(routing_router, "_NETS_CONFIES_AU_PLAN", ("GND",))
    assert routing_router._pads_isolees_du_plan(_RAPPORT, _BOARD) == [("U1", "8")]


def test_sans_board_le_comportement_reste_celui_d_avant(monkeypatch):
    monkeypatch.setattr(routing_router, "_NETS_CONFIES_AU_PLAN", ("GND",))
    assert routing_router._pads_isolees_du_plan(_RAPPORT) == []


def test_le_site_du_repli_transmet_le_board():
    src = (_SERVICE / "routers" / "routing.py").read_text(encoding="utf-8")
    assert "orphelines = _pads_isolees_du_plan(rap_final, final)" in src
