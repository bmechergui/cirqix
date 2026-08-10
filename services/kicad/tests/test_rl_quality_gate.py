"""Fail-closed RL quality gate — unit tests (no kicad-cli required)."""

from __future__ import annotations

from tools.rl.quality_gate import (
    compare_vs_baseline,
    evaluate_board_hard_gate,
    evaluate_dataset_hard_gate,
)


def test_hard_gate_passes_only_when_all_clean() -> None:
    g = evaluate_board_hard_gate(
        error_conflicts=0,
        routed_percent=100,
        unrouted_count=0,
        drc_error_count=0,
        unconnected_items=0,
        require_unrouted_count=True,
    )
    assert g["passed"] is True
    assert g["checks"]["error_conflicts_zero"] is True
    assert g["checks"]["routing_complete"] is True


def test_hard_gate_fails_on_placement_errors() -> None:
    g = evaluate_board_hard_gate(
        error_conflicts=6,
        routed_percent=100,
        drc_error_count=0,
        unconnected_items=0,
    )
    assert g["passed"] is False
    assert "error_conflicts=6" in g["verdict"]


def test_hard_gate_fails_on_partial_route() -> None:
    g = evaluate_board_hard_gate(
        error_conflicts=0,
        routed_percent=82,
        drc_error_count=0,
        unconnected_items=0,
    )
    assert g["passed"] is False
    assert "routed_percent=82" in g["verdict"]


def test_hard_gate_fails_closed_when_drc_missing() -> None:
    g = evaluate_board_hard_gate(
        error_conflicts=0,
        routed_percent=100,
        drc_error_count=None,
        unconnected_items=0,
        require_drc=True,
    )
    assert g["passed"] is False
    assert "drc_error_count not measured" in g["verdict"]


def test_hard_gate_fails_closed_when_unconnected_missing() -> None:
    g = evaluate_board_hard_gate(
        error_conflicts=0,
        routed_percent=100,
        drc_error_count=0,
        unconnected_items=None,
        require_unconnected=True,
    )
    assert g["passed"] is False
    assert "unconnected_items not measured" in g["verdict"]


def test_legacy_gate_b_style_would_pass_but_hard_gate_fails() -> None:
    """Board 05 style: 100% route but residual placement ERROR → NO-GO hard."""
    # Old Gate B only looked at mean routed_percent → would "GO"
    legacy_route_ok = 100 >= 100
    hard = evaluate_board_hard_gate(
        error_conflicts=6,
        routed_percent=100,
        drc_error_count=0,
        unconnected_items=0,
    )
    assert legacy_route_ok is True
    assert hard["passed"] is False


def test_dataset_requires_all_boards() -> None:
    boards = [
        {"passed": True},
        {"passed": True},
        {"passed": False},
    ]
    agg = evaluate_dataset_hard_gate(boards, require_all_boards=True)
    assert agg["passed"] is False
    assert agg["n_pass"] == 2
    assert agg["n_fail"] == 1


def test_dataset_all_pass() -> None:
    boards = [{"passed": True}, {"passed": True}]
    agg = evaluate_dataset_hard_gate(boards, require_all_boards=True)
    assert agg["passed"] is True


def test_compare_vs_baseline() -> None:
    c = compare_vs_baseline(
        routed_percent=100,
        baseline_routed_percent=100,
        error_conflicts=0,
        baseline_error_conflicts=0,
        wirelength_mm=10.0,
        baseline_wirelength_mm=10.0,
    )
    assert c["competitive_vs_baseline"] is True
