"""Regression: LED placed board can be cleaned to 0 placement ERRORs.

Uses shipped PlacementFixer path (``_resolve_remaining_conflicts``) — same
inspector used in production ``auto_place``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from kicad_tools.schema.pcb import PCB

from tools.placement import _connector_refs, _resolve_remaining_conflicts
from tools.rl.placement.conflicts import count_error_conflicts

_LED_PLACED = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "led-blinker-full-pipeline"
    / "output"
    / "5_placed.kicad_pcb"
)


@pytest.mark.skipif(not _LED_PLACED.is_file(), reason="LED placed fixture missing")
def test_led_placed_fix_reaches_zero_errors(tmp_path: Path) -> None:
    work = tmp_path / "led.kicad_pcb"
    shutil.copy2(_LED_PLACED, work)
    pcb = PCB.load(str(work))
    before = count_error_conflicts(pcb, pcb_path=work)
    assert before >= 1, "fixture should start with at least one ERROR"

    anchored = _connector_refs(pcb)
    n_before, n_after = _resolve_remaining_conflicts(work, list(anchored))
    assert n_before >= 1
    assert n_after == 0

    pcb2 = PCB.load(str(work))
    assert count_error_conflicts(pcb2, pcb_path=work) == 0
