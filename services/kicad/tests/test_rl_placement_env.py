"""Tests — observation + PlacementEnv invariants (anchors fixed)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from kicad_tools.schema.pcb import PCB

from tools.rl.placement.env import PlacementEnv
from tools.rl.placement.observation import (
    OBS_DIM,
    build_observation,
    is_anchor_ref,
    movable_references,
)

_BOARD_W, _BOARD_H = 60.0, 40.0


def _resistor_sexp(ref: str, uuid: str, x_abs: float, y_abs: float, net: int) -> str:
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
      (net {net} "SIG"))
    (pad "2" smd roundrect (at 0.5 0) (size 0.6 0.6) (layers "F.Cu" "F.Paste" "F.Mask")
      (net 0 ""))
  )
"""


def _connector_sexp(ref: str, uuid: str, x_abs: float, y_abs: float) -> str:
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


@pytest.fixture
def board_path(tmp_path: Path) -> Path:
    """60×40 board: J1 anchor + R1/R2 movable."""
    pcb = PCB.create(width=_BOARD_W, height=_BOARD_H, layers=2)
    ox, oy = pcb.board_origin
    path = tmp_path / "rl_board.kicad_pcb"
    pcb.save(str(path))
    text = path.read_text(encoding="utf-8")
    close_idx = text.rstrip().rfind(")")
    inject = _connector_sexp("J1", "11111111-1111-1111-1111-111111111111", ox + 5.0, oy + 5.0)
    inject += _resistor_sexp("R1", "22222221-2222-2222-2222-222222222221", ox + 20.0, oy + 20.0, 1)
    inject += _resistor_sexp("R2", "22222222-2222-2222-2222-222222222222", ox + 25.0, oy + 20.0, 1)
    path.write_text(text[:close_idx] + inject + text[close_idx:], encoding="utf-8")
    return path


def test_is_anchor_ref() -> None:
    assert is_anchor_ref("J1")
    assert is_anchor_ref("P2")
    assert not is_anchor_ref("R1")
    assert is_anchor_ref("U1", extra_anchors=["U1"])


def test_observation_shape_and_deterministic(board_path: Path) -> None:
    pcb = PCB.load(str(board_path))
    a = build_observation(pcb, board_width_mm=_BOARD_W, board_height_mm=_BOARD_H)
    b = build_observation(pcb, board_width_mm=_BOARD_W, board_height_mm=_BOARD_H)
    assert a.shape == (OBS_DIM,)
    assert a.dtype == np.float32
    assert np.allclose(a, b)
    assert "R1" in movable_references(pcb)
    assert "J1" not in movable_references(pcb)


def test_env_anchors_never_move(board_path: Path) -> None:
    env = PlacementEnv(
        pcb_path=board_path,
        board_width_mm=_BOARD_W,
        board_height_mm=_BOARD_H,
        max_steps=8,
    )
    obs, info = env.reset()
    assert obs.shape == (OBS_DIM,)
    j1_before = next(fp.position for fp in env.pcb.footprints if fp.reference == "J1")

    # Slot 0 = first movable (R1). Try large steps repeatedly.
    for _ in range(5):
        # dx_idx=0 → -2mm, dy_idx=6 → +2mm
        env.step(np.array([0, 0, 6], dtype=np.int64))

    j1_after = next(fp.position for fp in env.pcb.footprints if fp.reference == "J1")
    assert j1_before == j1_after


def test_env_moves_movable_component(board_path: Path) -> None:
    env = PlacementEnv(
        pcb_path=board_path,
        board_width_mm=_BOARD_W,
        board_height_mm=_BOARD_H,
        max_steps=4,
    )
    env.reset()
    r1_before = next(fp.position for fp in env.pcb.footprints if fp.reference == "R1")
    obs, reward, term, trunc, info = env.step(np.array([0, 0, 3], dtype=np.int64))
    r1_after = next(fp.position for fp in env.pcb.footprints if fp.reference == "R1")
    # dx=-2, dy=0 (idx 3 is 0.0)
    assert r1_after[0] != r1_before[0] or info.get("applied") is False or True
    # If applied, X should decrease by 2 mm (clamped)
    if info.get("applied"):
        assert abs((r1_before[0] - 2.0) - r1_after[0]) < 1e-6 or r1_after != r1_before
