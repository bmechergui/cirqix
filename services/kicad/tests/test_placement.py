"""Tests — auto_place() + helpers (tools/placement.py), TDD.

Architecture 2 phases COMPLÉMENTAIRES + bridge :
  - Phase 1 : PlacementOptimizer (clustering natif + connecteurs J*/P* ANCRÉS,
    clampés dans le contour) — physique locale, pose la structure.
  - Bridge  : _restore_bypass_caps_near_mcu() — repositionne les caps de
    découplage qui ont dérivé loin du MCU (seed de qualité pour Phase 2).
  - Phase 2 : CMA-ES via run_optimize_placement (seed_method="current") —
    raffinement global seeded depuis bridge, minimise overlap+wirelength.
  - Re-ancrage : les connecteurs sont restaurés à leurs positions de Phase 1
    après la Phase 2 (garde-fou).

Invariants testés :
  - _find_mcu_footprint : retourne le footprint avec le plus de pads (>10)
  - _restore_bypass_caps_near_mcu : repositionne les caps loin du MCU,
    ne touche pas les caps proches, ni les composants hors-réseau MCU
  - auto_place : connecteur hors-carte → ramené dans le contour ;
    connecteur bien placé → position stable post-CMA-ES.
"""
from __future__ import annotations

import base64
import types
from pathlib import Path

import pytest

from kicad_tools.schema.pcb import PCB

from tools.placement import (
    auto_place,
    _find_mcu_footprint,
    _is_bypass_cap,
    _restore_bypass_caps_near_mcu,
    _snap_bypass_caps_to_ics,
)

_BOARD_W_MM, _BOARD_H_MM = 60.0, 40.0


def _footprint_sexp(ref: str, uuid: str, x_abs: float, y_abs: float) -> str:
    """Footprint minimal (connecteur 2 broches) à la position sheet-absolute donnée."""
    return f"""\
  (footprint "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
    (layer "F.Cu")
    (uuid "{uuid}")
    (at {x_abs} {y_abs})
    (property "Reference" "{ref}" (at 0 -2 0) (layer "F.SilkS")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Value" "Conn" (at 0 2 0) (layer "F.Fab")
      (effects (font (size 1 1) (thickness 0.15))))
    (pad "1" thru_hole circle (at 0 0) (size 1.7 1.7) (drill 1)
      (layers "*.Cu" "*.Mask") (net 0 ""))
    (pad "2" thru_hole circle (at 0 2.54) (size 1.7 1.7) (drill 1)
      (layers "*.Cu" "*.Mask") (net 0 ""))
  )
"""


def _board_with_connectors(
    tmp_path: Path,
    j1_board_xy: tuple[float, float],
    j2_board_xy: tuple[float, float] | None = None,
) -> bytes:
    """Board 60x40mm centré sur feuille A4 (PCB.create(center=True), défaut prod).

    ``j1_board_xy`` / ``j2_board_xy`` sont board-relative ; convertis en
    sheet-absolute (+ pcb.board_origin) pour l'injection S-expr.
    """
    pcb = PCB.create(width=_BOARD_W_MM, height=_BOARD_H_MM, layers=2)
    ox, oy = pcb.board_origin
    board_path = tmp_path / "board.kicad_pcb"
    pcb.save(str(board_path))

    text = board_path.read_text(encoding="utf-8")
    close_idx = text.rstrip().rfind(")")

    inject = _footprint_sexp("J1", "11111111-1111-1111-1111-111111111111",
                              ox + j1_board_xy[0], oy + j1_board_xy[1])
    if j2_board_xy is not None:
        inject += _footprint_sexp("J2", "22222222-2222-2222-2222-222222222222",
                                   ox + j2_board_xy[0], oy + j2_board_xy[1])

    text = text[:close_idx] + inject + text[close_idx:]
    board_path.write_text(text, encoding="utf-8")
    return board_path.read_bytes()


# ---------------------------------------------------------------------------
# Helpers pour créer des mock footprints/pcb sans fichiers disque
# ---------------------------------------------------------------------------

def _make_pad(net: int) -> object:
    p = types.SimpleNamespace()
    p.net = net
    return p


def _make_fp(ref: str, x: float, y: float, pad_nets: list[int], value: str = "100nF") -> object:
    fp = types.SimpleNamespace()
    fp.reference = ref
    fp.value = value
    fp.position = (x, y)
    fp.pads = [_make_pad(n) for n in pad_nets]
    return fp


def _make_pcb(footprints: list) -> object:
    pcb = types.SimpleNamespace()
    pcb.footprints = footprints
    return pcb


# ---------------------------------------------------------------------------
# Tests unitaires — _is_bypass_cap (wrapper kicad-tools is_bypass_cap)
# ---------------------------------------------------------------------------

def test_is_bypass_cap_true_for_100nf():
    """C12 avec valeur 100nF → bypass cap détecté via kicad-tools."""
    fp = _make_fp("C12", 0, 0, [2, 3], value="100nF")
    assert _is_bypass_cap(fp) is True


def test_is_bypass_cap_false_for_resistor():
    """R1 (résistance, ref commence par R) → pas un bypass cap même si value=100nF."""
    fp = _make_fp("R1", 0, 0, [2, 5], value="100nF")
    assert _is_bypass_cap(fp) is False


def test_is_bypass_cap_false_for_bulk_cap():
    """C1 avec valeur 100uF → bulk cap, pas un bypass cap (value hors liste)."""
    fp = _make_fp("C1", 0, 0, [1, 3], value="100uF")
    assert _is_bypass_cap(fp) is False


def test_is_bypass_cap_false_for_non_2pad():
    """Composant IC avec value 100nF mais 4 pads → pas un bypass cap (>2 pads)."""
    fp = _make_fp("C99", 0, 0, [2, 3, 4, 5], value="100nF")
    assert _is_bypass_cap(fp) is False


# ---------------------------------------------------------------------------
# Tests unitaires — _find_mcu_footprint
# ---------------------------------------------------------------------------

def test_find_mcu_footprint_returns_highest_pad_count():
    """Le MCU = footprint avec le plus de pads (minimum >10)."""
    pcb = _make_pcb([
        _make_fp("C1", 5.0, 5.0, [2, 0]),
        _make_fp("U2", 30.0, 20.0, list(range(48))),
        _make_fp("R1", 10.0, 10.0, [3, 0]),
        _make_fp("J1", 50.0, 20.0, list(range(6))),
    ])
    mcu = _find_mcu_footprint(pcb)
    assert mcu is not None
    assert mcu.reference == "U2"


def test_find_mcu_footprint_returns_none_if_no_large_ic():
    """Sans composant >10 pads → None (board sans MCU)."""
    pcb = _make_pcb([
        _make_fp("C1", 5.0, 5.0, [2, 0]),
        _make_fp("J1", 50.0, 20.0, list(range(6))),
    ])
    assert _find_mcu_footprint(pcb) is None


# ---------------------------------------------------------------------------
# Tests unitaires — _restore_bypass_caps_near_mcu
# ---------------------------------------------------------------------------

def test_restore_bypass_caps_far_from_mcu():
    """Cap bypass (2 pads, net commun MCU) à >12mm → repositionné vers initial."""
    mcu = _make_fp("U2", 30.0, 20.0, [2] * 48)
    cap_far = _make_fp("C12", 5.0, 20.0, [2, 0])    # 25mm du MCU → doit bouger
    cap_close = _make_fp("C13", 32.0, 22.0, [2, 0])  # 2.8mm du MCU → ne bouge pas
    cap_other = _make_fp("R1", 5.0, 20.0, [5, 0])    # net 5 ≠ MCU → ne bouge pas

    pcb = _make_pcb([mcu, cap_far, cap_close, cap_other])
    initial = {
        "U2": (30.0, 20.0),
        "C12": (28.0, 22.0),  # position initiale → près du MCU
        "C13": (32.0, 22.0),
        "R1": (5.0, 20.0),
    }

    changed = _restore_bypass_caps_near_mcu(pcb, initial)

    assert changed is True
    assert cap_far.position == (28.0, 22.0), "C12 restauré à sa position initiale"
    assert cap_close.position == (32.0, 22.0), "C13 ne bouge pas (déjà près du MCU)"
    assert cap_other.position == (5.0, 20.0), "R1 ne bouge pas (net différent)"


def test_restore_bypass_caps_no_mcu():
    """Sans MCU (>10 pads) → rien ne bouge, retourne False."""
    pcb = _make_pcb([
        _make_fp("C1", 5.0, 5.0, [2, 0]),
        _make_fp("J1", 50.0, 35.0, list(range(6))),
    ])
    initial = {"C1": (10.0, 10.0), "J1": (50.0, 35.0)}

    changed = _restore_bypass_caps_near_mcu(pcb, initial)

    assert changed is False
    assert pcb.footprints[0].position == (5.0, 5.0), "C1 ne bouge pas sans MCU"


def test_restore_bypass_caps_already_close_unchanged():
    """Tous les caps déjà <12mm du MCU → retourne False, aucune modification."""
    mcu = _make_fp("U2", 30.0, 20.0, [2] * 48)
    cap1 = _make_fp("C12", 32.0, 22.0, [2, 0])   # 2.8mm
    cap2 = _make_fp("C13", 25.0, 18.0, [2, 0])   # 5.8mm

    pcb = _make_pcb([mcu, cap1, cap2])
    initial = {"U2": (30.0, 20.0), "C12": (32.0, 22.0), "C13": (25.0, 18.0)}

    changed = _restore_bypass_caps_near_mcu(pcb, initial)

    assert changed is False


# ---------------------------------------------------------------------------
# Tests unitaires — _snap_bypass_caps_to_ics
# ---------------------------------------------------------------------------

def test_snap_bypass_caps_moves_far_cap_to_ic_owner():
    """Cap >10mm de son IC owner → snappé en grille près de cet IC."""
    u1 = _make_fp("U1", 10.0, 20.0, list(range(4)))   # 4-pad LDO
    u2 = _make_fp("U2", 40.0, 20.0, list(range(48)))  # 48-pad MCU

    # C2 initialement proche de U1 (x=12) — owner=U1
    # CMA-ES l'a déplacé loin (x=5, dist U1=5mm, dist U2=35mm)
    # Après CMA-ES : C2 à (5, 20) → 5mm de U1 → OK (≤10mm)
    # Mais si C2 atterrit à (50, 20) = 40mm de U1 → snappé vers U1
    c2 = _make_fp("C2", 50.0, 20.0, [2, 3])

    # C12 initialement proche de U2 (x=38) — owner=U2
    # Après CMA-ES : C12 à (5, 20) = 35mm de U2 → snappé vers U2
    c12 = _make_fp("C12", 5.0, 20.0, [2, 3])

    pcb = _make_pcb([u1, u2, c2, c12])
    initial = {
        "U1": (10.0, 20.0), "U2": (40.0, 20.0),
        "C2": (12.0, 22.0),   # initial near U1 → owner=U1
        "C12": (38.0, 22.0),  # initial near U2 → owner=U2
    }

    changed = _snap_bypass_caps_to_ics(pcb, initial)

    assert changed is True
    # C12 doit être près de U2 (x=40)
    c12_x, c12_y = c12.position
    import math
    dist_u2 = math.sqrt((c12_x - 40.0)**2 + (c12_y - 20.0)**2)
    assert dist_u2 <= 10.0, f"C12 à {dist_u2:.1f}mm de U2 (attendu ≤10mm)"
    # C2 doit être près de U1 (x=10)
    c2_x, c2_y = c2.position
    dist_u1 = math.sqrt((c2_x - 10.0)**2 + (c2_y - 20.0)**2)
    assert dist_u1 <= 10.0, f"C2 à {dist_u1:.1f}mm de U1 (attendu ≤10mm)"


def test_snap_bypass_caps_leaves_close_caps_unchanged():
    """Cap déjà <10mm de son IC owner → ne bouge pas."""
    u2 = _make_fp("U2", 40.0, 20.0, list(range(48)))
    c12 = _make_fp("C12", 43.0, 22.0, [2, 3])  # 3.6mm de U2

    pcb = _make_pcb([u2, c12])
    initial = {"U2": (40.0, 20.0), "C12": (42.0, 22.0)}

    changed = _snap_bypass_caps_to_ics(pcb, initial)

    assert changed is False
    assert c12.position == (43.0, 22.0)


def test_snap_bypass_caps_no_ics():
    """Sans IC (>10 pads) → rien ne bouge, retourne False."""
    c1 = _make_fp("C1", 5.0, 5.0, [2, 3])
    pcb = _make_pcb([c1])
    initial = {"C1": (5.0, 5.0)}

    changed = _snap_bypass_caps_to_ics(pcb, initial)

    assert changed is False


# ---------------------------------------------------------------------------
# Tests intégration — auto_place (board PCB réel)
# ---------------------------------------------------------------------------

def test_auto_place_clamps_connector_outside_outline(tmp_path):
    """J1 ancré hors du contour Edge.Cuts doit être ramené dedans (Phase 1 clamp),
    et y rester après la Phase 2 CMA-ES seed=current (re-ancrage)."""
    pcb_bytes = _board_with_connectors(tmp_path, j1_board_xy=(30.0, 135.0))
    b64 = base64.b64encode(pcb_bytes).decode()

    result = auto_place(b64, _BOARD_W_MM, _BOARD_H_MM)

    j1 = next(p for p in result["positions"] if p["ref"] == "J1")
    assert 0.0 <= j1["x"] <= _BOARD_W_MM, f"J1.x={j1['x']} hors contour [0,{_BOARD_W_MM}]"
    assert 0.0 <= j1["y"] <= _BOARD_H_MM, f"J1.y={j1['y']} hors contour [0,{_BOARD_H_MM}]"


def test_auto_place_does_not_move_connector_inside_outline(tmp_path):
    """J2 déjà bien placé (30,20) reste à sa position : ancré en Phase 1
    (fixed_refs) ET restauré post-CMA-ES Phase 2 seed=current (re-ancrage)."""
    pcb_bytes = _board_with_connectors(
        tmp_path, j1_board_xy=(30.0, 135.0), j2_board_xy=(30.0, 20.0),
    )
    b64 = base64.b64encode(pcb_bytes).decode()

    result = auto_place(b64, _BOARD_W_MM, _BOARD_H_MM)

    j2 = next(p for p in result["positions"] if p["ref"] == "J2")
    assert j2["x"] == pytest.approx(30.0, abs=0.01)
    assert j2["y"] == pytest.approx(20.0, abs=0.01)
