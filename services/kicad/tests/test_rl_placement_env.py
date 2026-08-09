"""Tests — observation + PlacementEnv invariants (anchors fixed, obs/action align)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from kicad_tools.schema.pcb import PCB

from tools.rl.placement.env import PlacementEnv
from tools.rl.placement.observation import (
    MAX_COMPONENTS,
    OBS_DIM,
    _FEATS_PER_FP,
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
    mov = movable_references(pcb)
    assert "R1" in mov and "R2" in mov
    assert "J1" not in mov
    # Slot 0 = first movable — present flag set
    assert a[5] == 1.0  # present of first movable


def test_obs_slots_align_with_action_movables(board_path: Path) -> None:
    """Observation slots and action indices share movable_references order."""
    pcb = PCB.load(str(board_path))
    mov = movable_references(pcb)
    obs = build_observation(pcb, board_width_mm=_BOARD_W, board_height_mm=_BOARD_H)
    # Only movable slots have present=1 in the first len(mov) slots
    for i in range(min(len(mov), MAX_COMPONENTS)):
        present = obs[i * _FEATS_PER_FP + 5]
        assert present == 1.0, f"slot {i} ({mov[i]}) should be present"
    # Next slot empty
    if len(mov) < MAX_COMPONENTS:
        assert obs[len(mov) * _FEATS_PER_FP + 5] == 0.0


def test_env_anchors_never_move(board_path: Path) -> None:
    env = PlacementEnv(
        pcb_path=board_path,
        board_width_mm=_BOARD_W,
        board_height_mm=_BOARD_H,
        max_steps=8,
        check_conflicts=False,  # faster unit test
    )
    obs, info = env.reset()
    assert obs.shape == (OBS_DIM,)
    j1_before = next(fp.position for fp in env.pcb.footprints if fp.reference == "J1")

    for _ in range(5):
        env.step(np.array([0, 0, 6], dtype=np.int64))

    j1_after = next(fp.position for fp in env.pcb.footprints if fp.reference == "J1")
    assert j1_before == j1_after


def test_env_moves_movable_component(board_path: Path) -> None:
    env = PlacementEnv(
        pcb_path=board_path,
        board_width_mm=_BOARD_W,
        board_height_mm=_BOARD_H,
        max_steps=4,
        check_conflicts=False,
    )
    env.reset()
    r1_before = next(fp.position for fp in env.pcb.footprints if fp.reference == "R1")
    # dx_idx=0 → -2.0 mm, dy_idx=3 → 0.0
    obs, reward, term, trunc, info = env.step(np.array([0, 0, 3], dtype=np.int64))
    r1_after = next(fp.position for fp in env.pcb.footprints if fp.reference == "R1")
    assert info.get("applied") is True
    assert abs(r1_after[0] - (r1_before[0] - 2.0)) < 1e-6
    assert abs(r1_after[1] - r1_before[1]) < 1e-6
