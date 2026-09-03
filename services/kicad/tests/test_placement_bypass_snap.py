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


# ---------------------------------------------------------------------------
# ⚠️ Le snap ne doit pas EMPILER ce qu il rapproche.
#
# Premiere version : chaque membre etait teleporte a distance fixe DANS SA
# DIRECTION ACTUELLE, sans regarder si la place etait libre. Deux membres de
# directions voisines atterrissaient au meme endroit.
#
# Mesure du 2026-08-29, board STM32 du banc :
#     avant snap : 0 ERROR / 0 conflit
#     apres snap : 1 ERROR / 3 conflits   (8 membres deplaces)
# Sur l Arduino, 44 deplacements donnaient 202 ERROR — l Inspecteur les
# resorbait presque tous, mais les 4 restants forcaient un RE-TIRAGE complet
# du placement, seize minutes a chaque fois.
#
# « L Inspecteur nettoie » etait une hypothese, pas une mesure.
# ---------------------------------------------------------------------------

def _board_ic_et_trois_capas(tmp_path: Path) -> Path:
    """U1 au centre, trois 100nF ALIGNEES a 20 mm — memes direction et distance.

    Sans evitement, les trois cibles sont le meme point.
    """
    pcb = PCB.create(width=_BOARD_W_MM, height=_BOARD_H_MM, layers=2)
    ox, oy = pcb.board_origin
    path = tmp_path / "empilement.kicad_pcb"
    pcb.save(str(path))
    text = path.read_text(encoding="utf-8")
    close_idx = text.rstrip().rfind(")")
    inject = _ic_sexp("U1", "cccccccc-cccc-cccc-cccc-ccccccccccc1", ox + 20.0, oy + 20.0)
    for i, dy in enumerate((-0.2, 0.0, 0.2)):
        inject += _cap_sexp(f"C{i + 1}", f"cccccccc-cccc-cccc-cccc-cccccccccc{i + 2}",
                            ox + 40.0, oy + 20.0 + dy)
    path.write_text(text[:close_idx] + inject + text[close_idx:], encoding="utf-8")
    return path


def test_le_snap_n_empile_pas_deux_membres(tmp_path):
    pcb = PCB.load(str(_board_ic_et_trois_capas(tmp_path)))
    snap_cluster_members(pcb)
    pos = [_xy(pcb, f"C{i}") for i in (1, 2, 3)]
    for a in range(3):
        for b in range(a + 1, 3):
            d = math.hypot(pos[a][0] - pos[b][0], pos[a][1] - pos[b][1])
            assert d > 0.5, (
                f"C{a + 1} et C{b + 1} empiles a {d:.2f} mm — le snap cree un court-circuit")


def test_un_membre_sans_place_libre_n_est_pas_deplace(tmp_path):
    """Mieux vaut le laisser loin que le poser sur un voisin.

    On sature le pourtour de l ancre : aucune cible ne peut etre libre.
    """
    pcb = PCB.create(width=_BOARD_W_MM, height=_BOARD_H_MM, layers=2)
    ox, oy = pcb.board_origin
    path = tmp_path / "sature.kicad_pcb"
    pcb.save(str(path))
    text = path.read_text(encoding="utf-8")
    close_idx = text.rstrip().rfind(")")
    inject = _ic_sexp("U1", "dddddddd-dddd-dddd-dddd-ddddddddddd1", ox + 20.0, oy + 20.0)
    inject += _cap_sexp("C1", "dddddddd-dddd-dddd-dddd-ddddddddddd2", ox + 45.0, oy + 20.0)
    # Une couronne serree de resistances tout autour de U1.
    k = 3
    for i in range(24):
        a = i * math.pi / 12.0
        inject += _resistor_sexp(f"R{i + 1}", f"dddddddd-dddd-dddd-dddd-{i:012d}",
                                 ox + 20.0 + 4.0 * math.cos(a),
                                 oy + 20.0 + 4.0 * math.sin(a))
        k += 1
    path.write_text(text[:close_idx] + inject + text[close_idx:], encoding="utf-8")
    pcb = PCB.load(str(path))
    avant = _xy(pcb, "C1")
    snap_cluster_members(pcb)
    apres = _xy(pcb, "C1")
    d = math.hypot(apres[0] - 20.0 - pcb.board_origin[0], apres[1] - 20.0 - pcb.board_origin[1])
    assert d > 4.0, (
        f"C1 pose a {d:.1f} mm du centre de U1, dans la couronne saturee")
