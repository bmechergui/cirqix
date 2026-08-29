"""Snap bypass : honorer FunctionalCluster.max_distance_mm (5 mm).

Le clustering natif groupe IC + capa, mais le GA hybrid laisse les springs
molles (mesure 13-28 mm). On applique le plafond du cluster, on n'invente
pas une autre détection.
"""
from __future__ import annotations

import math
from pathlib import Path

from kicad_tools.schema.pcb import PCB

from tools.placement_bypass import snap_cluster_members

_BOARD_W_MM, _BOARD_H_MM = 60.0, 40.0


def _ic_sexp(ref: str, uuid: str, x_abs: float, y_abs: float) -> str:
    return f"""\
  (footprint "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
    (layer "F.Cu")
    (uuid "{uuid}")
    (at {x_abs} {y_abs})
    (property "Reference" "{ref}" (at 0 -3 0) (layer "F.SilkS")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Value" "MCU" (at 0 3 0) (layer "F.Fab")
      (effects (font (size 1 1) (thickness 0.15))))
    (pad "VCC" smd rect (at -1.9 -2.54) (size 0.6 1.5) (layers "F.Cu" "F.Paste" "F.Mask")
      (net 1 "VCC"))
    (pad "GND" smd rect (at 1.9 -2.54) (size 0.6 1.5) (layers "F.Cu" "F.Paste" "F.Mask")
      (net 2 "GND"))
    (pad "1" smd rect (at -1.9 0) (size 0.6 1.5) (layers "F.Cu" "F.Paste" "F.Mask")
      (net 3 "SIG"))
  )
"""


def _cap_sexp(ref: str, uuid: str, x_abs: float, y_abs: float) -> str:
    return f"""\
  (footprint "Capacitor_SMD:C_0402_1005Metric"
    (layer "F.Cu")
    (uuid "{uuid}")
    (at {x_abs} {y_abs})
    (property "Reference" "{ref}" (at 0 -2 0) (layer "F.SilkS")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Value" "100nF" (at 0 2 0) (layer "F.Fab")
      (effects (font (size 1 1) (thickness 0.15))))
    (pad "1" smd roundrect (at -0.5 0) (size 0.6 0.6) (layers "F.Cu" "F.Paste" "F.Mask")
      (net 1 "VCC"))
    (pad "2" smd roundrect (at 0.5 0) (size 0.6 0.6) (layers "F.Cu" "F.Paste" "F.Mask")
      (net 2 "GND"))
  )
"""


def _resistor_sexp(ref: str, uuid: str, x_abs: float, y_abs: float) -> str:
    return f"""\
  (footprint "Resistor_SMD:R_0402_1005Metric"
    (layer "F.Cu")
    (uuid "{uuid}")
    (at {x_abs} {y_abs})
    (property "Reference" "{ref}" (at 0 -2 0) (layer "F.SilkS")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Value" "10k" (at 0 2 0) (layer "F.Fab")
      (effects (font (size 1 1) (thickness 0.15))))
    (pad "1" smd roundrect (at -0.5 0) (size 0.6 0.6) (layers "F.Cu" "F.Paste" "F.Mask")
      (net 3 "SIG"))
    (pad "2" smd roundrect (at 0.5 0) (size 0.6 0.6) (layers "F.Cu" "F.Paste" "F.Mask")
      (net 0 ""))
  )
"""


def _board_ic_and_far_bypass(tmp_path: Path) -> Path:
    """U1 au centre, C1 100nF à 20 mm (même VCC/GND), R1 loin sur SIG."""
    pcb = PCB.create(width=_BOARD_W_MM, height=_BOARD_H_MM, layers=2)
    ox, oy = pcb.board_origin
    path = tmp_path / "bypass.kicad_pcb"
    pcb.save(str(path))
    text = path.read_text(encoding="utf-8")
    close_idx = text.rstrip().rfind(")")
    inject = _ic_sexp("U1", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1", ox + 20.0, oy + 20.0)
    inject += _cap_sexp("C1", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2", ox + 40.0, oy + 20.0)
    inject += _resistor_sexp("R1", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa3", ox + 10.0, oy + 10.0)
    path.write_text(text[:close_idx] + inject + text[close_idx:], encoding="utf-8")
    return path


def _xy(pcb: PCB, ref: str) -> tuple[float, float]:
    fp = next(f for f in pcb.footprints if f.reference == ref)
    return fp.position[0], fp.position[1]


def test_snap_pulls_bypass_within_five_mm(tmp_path):
    path = _board_ic_and_far_bypass(tmp_path)
    pcb = PCB.load(str(path))
    u1 = _xy(pcb, "U1")
    c1 = _xy(pcb, "C1")
    assert math.hypot(c1[0] - u1[0], c1[1] - u1[1]) > 15.0

    moved = snap_cluster_members(pcb)
    assert moved >= 1

    u1 = _xy(pcb, "U1")
    c1 = _xy(pcb, "C1")
    dist = math.hypot(c1[0] - u1[0], c1[1] - u1[1])
    assert dist <= 5.0, f"C1 encore à {dist:.1f} mm de U1"


def test_snap_does_not_move_unrelated_resistor(tmp_path):
    path = _board_ic_and_far_bypass(tmp_path)
    pcb = PCB.load(str(path))
    r1_before = _xy(pcb, "R1")
    snap_cluster_members(pcb)
    assert _xy(pcb, "R1") == r1_before


def test_snap_is_noop_when_already_close(tmp_path):
    pcb = PCB.create(width=_BOARD_W_MM, height=_BOARD_H_MM, layers=2)
    ox, oy = pcb.board_origin
    path = tmp_path / "close.kicad_pcb"
    pcb.save(str(path))
    text = path.read_text(encoding="utf-8")
    close_idx = text.rstrip().rfind(")")
    inject = _ic_sexp("U1", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1", ox + 20.0, oy + 20.0)
    inject += _cap_sexp("C1", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2", ox + 23.0, oy + 20.0)
    path.write_text(text[:close_idx] + inject + text[close_idx:], encoding="utf-8")
    pcb = PCB.load(str(path))
    before = _xy(pcb, "C1")
    moved = snap_cluster_members(pcb)
    assert moved == 0
    assert _xy(pcb, "C1") == before
