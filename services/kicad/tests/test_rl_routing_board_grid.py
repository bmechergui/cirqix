"""Tests — RL routing BoardGrid on LED placed fixture."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tools.rl.routing.board_grid import (
    DEFAULT_NET_ORDER,
    N_CHANNELS,
    build_board_grid,
    pair_terminals,
)

_LED = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "led-blinker-full-pipeline"
    / "output"
    / "5_placed.kicad_pcb"
)


@pytest.fixture(scope="module")
def board():
    if not _LED.is_file():
        pytest.skip(f"LED fixture missing: {_LED}")
    return build_board_grid(_LED, resolution_mm=0.5)


def test_build_grid_loads_led(board) -> None:
    assert board.width_mm > 0 and board.height_mm > 0
    assert board.width_cells > 5 and board.height_cells > 5
    assert board.n_layers >= 1
    assert len(board.nets) >= 3


def test_led_has_expected_nets(board) -> None:
    # At least core nets from schema (names may vary slightly)
    names = set(board.nets)
    assert "GND" in names or any("GND" in n for n in names)
    multi = [n for n, t in board.nets.items() if len(t.pads) >= 2]
    assert len(multi) >= 2


def test_world_grid_roundtrip(board) -> None:
    term = next(t for t in board.nets.values() if t.pads)
    pad = term.pads[0]
    gx, gy = board.world_to_grid(pad.x, pad.y)
    wx, wy = board.grid_to_world(gx, gy)
    assert abs(wx - pad.x) < board.resolution_mm * 2
    assert abs(wy - pad.y) < board.resolution_mm * 2


def test_observation_shape(board) -> None:
    name = next(iter(board.nets))
    term = board.nets[name]
    pad = term.pads[0]
    obs = board.observation(net_name=name, cursor_xy=(pad.x, pad.y))
    assert obs.shape[0] == N_CHANNELS
    assert obs.shape[1] == board.height_cells
    assert obs.shape[2] == board.width_cells
    assert obs.dtype == np.float32
    flat = board.flat_observation(net_name=name, cursor_xy=(pad.x, pad.y))
    assert flat.shape == (N_CHANNELS * board.height_cells * board.width_cells,)


def test_pair_terminals() -> None:
    from kicad_tools.router.primitives import Pad
    from tools.rl.routing.board_grid import NetTerminals

    pads = [
        Pad(0, 0, 0.5, 0.5, 1, "N", ref="R1", pin="1"),
        Pad(1, 1, 0.5, 0.5, 1, "N", ref="R2", pin="1"),
    ]
    term = NetTerminals(1, "N", pads)
    pair = pair_terminals(term)
    assert pair is not None
    assert pair[0].ref == "R1"
    assert pair[1].ref == "R2"


def test_default_net_order_documented() -> None:
    assert "LED_A" in DEFAULT_NET_ORDER
    assert DEFAULT_NET_ORDER[-1] == "GND"
