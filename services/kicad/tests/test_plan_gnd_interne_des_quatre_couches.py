"""D-2026-09-12-b : a partir de 4 couches, le plan GND vit aussi sur In1.Cu —
SOUS REGLAGE DE BANC `plan_gnd_interne` seulement, la mesure ayant refute le
defaut (carte-08 : 100 % a 4 couches sans, jamais 100 % de 2 a 8 couches avec).

Mesure du 2026-09-12 (carte-10, stm32-100) : les vias d echappement GND du
LQFP atterrissaient sur B.Cu dans des ilots de 1 mm2 isoles par les pistes ;
les couches internes n avaient aucun plan et un via traversant n y trouvait
rien. Un plan interne est continu : tout via GND le rejoint.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

import pytest  # noqa: E402

from routers import routing as R  # noqa: E402
from tools import reglages_banc  # noqa: E402
from tests.test_ground_planes_avant_routage import RECT, _board  # noqa: E402


@pytest.fixture
def plan_interne_active(monkeypatch):
    monkeypatch.setattr(reglages_banc, "reglage", lambda nom, defaut: True if nom == "plan_gnd_interne" else defaut)


def test_par_defaut_les_faces_seulement_meme_en_quatre_couches():
    assert R._couches_du_plan(R._expand_stackup(_board(RECT), 4)) == ("F.Cu", "B.Cu")


def test_deux_couches_les_faces_seulement():
    assert R._couches_du_plan(_board(RECT)) == ("F.Cu", "B.Cu")


def test_quatre_couches_ajoutent_in1(plan_interne_active):
    assert R._couches_du_plan(R._expand_stackup(_board(RECT), 4)) == ("F.Cu", "In1.Cu", "B.Cu")


def test_six_couches_toujours_un_seul_plan_interne(plan_interne_active):
    assert R._couches_du_plan(R._expand_stackup(_board(RECT), 6)) == ("F.Cu", "In1.Cu", "B.Cu")


def test_un_board_sans_bloc_layers_reste_sur_les_faces():
    assert R._couches_du_plan(b"(kicad_pcb (net 3 \"GND\"))") == ("F.Cu", "B.Cu")


def test_la_coulee_lit_les_couches_du_board():
    src = (_SERVICE / "routers" / "routing.py").read_text(encoding="utf-8")
    assert "for c in _couches_du_plan(pcb_bytes) if c not in existantes" in src
