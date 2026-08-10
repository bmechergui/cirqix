"""TDD — reward.py mirrors kicad-tools compute_fom exactly (3 fixtures)."""

from __future__ import annotations

from pathlib import Path

import pytest
from kicad_tools.optim.fom import compute_fom
from kicad_tools.schema.pcb import PCB

from tools.rl.placement.reward import compute_placement_reward, fom_score

_SERVICE = Path(__file__).resolve().parents[1]
_EXAMPLES = _SERVICE / "examples"

# Three real fixtures (PLAN step 1 validation)
_FIXTURES = [
    _EXAMPLES
    / "led-blinker-full-pipeline"
    / "expected"
    / "led_blinker_final.kicad_pcb",
    _EXAMPLES
    / "led-blinker-full-pipeline"
    / "output"
    / "5_placed.kicad_pcb",
    _EXAMPLES / "stm32-validation" / "expected" / "stm32_final.kicad_pcb",
]


def _available_fixtures() -> list[Path]:
    return [p for p in _FIXTURES if p.is_file()]


@pytest.fixture(scope="module")
def three_fixtures() -> list[Path]:
    found = _available_fixtures()
    if len(found) < 3:
        pytest.skip(
            f"need 3 PCB fixtures for FOM parity, found {len(found)}: {found}"
        )
    return found[:3]


@pytest.mark.parametrize("idx", [0, 1, 2])
def test_reward_matches_compute_fom_score(three_fixtures: list[Path], idx: int) -> None:
    path = three_fixtures[idx]
    pcb = PCB.load(str(path))
    direct = compute_fom(pcb, pcb_path=str(path))
    wrapped = compute_placement_reward(pcb, pcb_path=str(path))

    assert wrapped.score == direct.score
    assert wrapped.soft_score == direct.soft_score
    assert wrapped.hard_gate_passed is direct.hard_gate_passed
    assert wrapped.hard_failures == direct.hard_failures
    assert fom_score(pcb, pcb_path=str(path)) == direct.score


def test_reward_default_kwargs_match_compute_fom(three_fixtures: list[Path]) -> None:
    """Same call signature path: no extra kwargs → identical FOMResult fields."""
    path = three_fixtures[0]
    pcb = PCB.load(str(path))
    a = compute_fom(pcb)
    b = compute_placement_reward(pcb)
    assert a.score == b.score
    assert a.soft_terms == b.soft_terms
