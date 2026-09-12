"""Le snap POWER approche la capa par l EXTERIEUR de la broche d alimentation
(normale sortante du CI), pas depuis sa position courante.

Mesure du 2026-09-12 (carte-08, carte-09 livrees) : decouplages a 13-32 mm de
leur broche alors que la broche etait bien visee. La direction « du GA » (de
la broche vers la capa) traverse le boitier quand la capa est de l autre
cote : chaque candidat proche est occupe par le corps du CI et la recherche
finit 6-20 mm plus loin.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))
sys.path.insert(0, str(_SERVICE / "kicad-tools" / "src"))

from kicad_tools.schema.pcb import PCB  # noqa: E402
from tools.placement_bypass import snap_cluster_members  # noqa: E402
from tests.test_placement_bypass_snap import _board_ic_and_far_bypass, _xy  # noqa: E402


def test_la_capa_finit_du_cote_de_sa_broche(tmp_path):
    # U1 : broche VCC a (-1.9, -2.54) du centre, C1 a +20 mm a DROITE (cote oppose).
    pcb = PCB.load(str(_board_ic_and_far_bypass(tmp_path)))
    assert snap_cluster_members(pcb) >= 1
    ux, uy = _xy(pcb, "U1")
    cx, cy = _xy(pcb, "C1")
    vx, vy = cx - ux, cy - uy
    # produit scalaire avec la normale sortante de la broche VCC : POSITIF
    assert vx * (-1.9) + vy * (-2.54) > 0, "C1 (%.1f, %.1f) n est pas du cote de sa broche" % (vx, vy)
    assert math.hypot(vx + 1.9, vy + 2.54) <= 3.5, "C1 trop loin de la broche VCC"


def test_le_snap_passe_la_normale_sortante_a_la_recherche():
    src = (_SERVICE / "tools" / "placement_bypass.py").read_text(encoding="utf-8")
    assert "sortant or (ux, uy)" in src
