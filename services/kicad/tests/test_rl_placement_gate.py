"""Unit tests for FOM + ERROR gate logic."""

from __future__ import annotations

from tools.rl.placement.eval_vs_cmaes import _gate


def test_gate_pass_when_rl_beats_margin_and_errors() -> None:
    g = _gate(fom_rl=1.1, fom_cmaes=1.0, errors_rl=0, errors_cmaes=0, margin=0.05)
    assert g["passed"] is True
    assert abs(g["relative_improvement"] - 0.1) < 1e-9


def test_gate_fail_when_rl_worse_fom() -> None:
    g = _gate(fom_rl=0.9, fom_cmaes=1.0, errors_rl=0, errors_cmaes=0, margin=0.05)
    assert g["passed"] is False


def test_gate_fail_when_improvement_too_small() -> None:
    g = _gate(fom_rl=1.02, fom_cmaes=1.0, errors_rl=0, errors_cmaes=0, margin=0.05)
    assert g["passed"] is False


def test_gate_fail_when_more_errors_even_if_fom_better() -> None:
    g = _gate(fom_rl=1.2, fom_cmaes=1.0, errors_rl=3, errors_cmaes=0, margin=0.05)
    assert g["passed"] is False
    assert g["errors_ok"] is False
