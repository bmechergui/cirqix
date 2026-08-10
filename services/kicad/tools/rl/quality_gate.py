"""Fail-closed quality gate for RL lab boards (place + route + DRC).

Historical Gate A/B could declare GO with residual placement ERROR or without
official DRC / unconnected_items. This module is the single fail-closed
checklist that must pass on **every** board before any prod flag discussion.

Order of checks (all required unless explicitly marked optional)::

  error_conflicts == 0
  → routed_percent >= 100  (routing_complete)
  → unrouted_count == 0     (if provided)
  → drc_error_count == 0    (if DRC was run; if required and missing → fail)
  → unconnected_items == 0  (if provided)
  → optional: wirelength / time vs baseline (informational or hard)

No silent pass: missing mandatory evidence fails closed.
"""

from __future__ import annotations

from typing import Any


def evaluate_board_hard_gate(
    *,
    error_conflicts: int | None,
    routed_percent: int | float | None,
    unrouted_count: int | None = None,
    drc_error_count: int | None = None,
    unconnected_items: int | None = None,
    require_drc: bool = True,
    require_unconnected: bool = True,
    require_unrouted_count: bool = False,
) -> dict[str, Any]:
    """Fail-closed checks for one board after place+route (+ optional DRC).

    Parameters use ``None`` for "not measured". When a field is required and
    ``None``, the gate fails (fail-closed).
    """
    reasons: list[str] = []
    checks: dict[str, bool] = {}

    # 1) Placement ERROR
    if error_conflicts is None:
        reasons.append("error_conflicts not measured")
        checks["error_conflicts_zero"] = False
    elif int(error_conflicts) != 0:
        reasons.append(f"error_conflicts={error_conflicts} != 0")
        checks["error_conflicts_zero"] = False
    else:
        checks["error_conflicts_zero"] = True

    # 2) Routing complete
    if routed_percent is None:
        reasons.append("routed_percent not measured")
        checks["routing_complete"] = False
    elif float(routed_percent) < 100.0 - 1e-9:
        reasons.append(f"routed_percent={routed_percent} < 100")
        checks["routing_complete"] = False
    else:
        checks["routing_complete"] = True

    # 3) Unrouted nets
    if require_unrouted_count:
        if unrouted_count is None:
            reasons.append("unrouted_count not measured")
            checks["unrouted_zero"] = False
        elif int(unrouted_count) != 0:
            reasons.append(f"unrouted_count={unrouted_count} != 0")
            checks["unrouted_zero"] = False
        else:
            checks["unrouted_zero"] = True
    elif unrouted_count is not None:
        ok = int(unrouted_count) == 0
        checks["unrouted_zero"] = ok
        if not ok:
            reasons.append(f"unrouted_count={unrouted_count} != 0")

    # 4) Official DRC errors
    if require_drc:
        if drc_error_count is None:
            reasons.append("drc_error_count not measured (DRC required)")
            checks["drc_clean"] = False
        elif int(drc_error_count) != 0:
            reasons.append(f"drc_error_count={drc_error_count} != 0")
            checks["drc_clean"] = False
        else:
            checks["drc_clean"] = True
    elif drc_error_count is not None:
        ok = int(drc_error_count) == 0
        checks["drc_clean"] = ok
        if not ok:
            reasons.append(f"drc_error_count={drc_error_count} != 0")

    # 5) Unconnected items (kicad-cli section)
    if require_unconnected:
        if unconnected_items is None:
            reasons.append("unconnected_items not measured")
            checks["unconnected_zero"] = False
        elif int(unconnected_items) != 0:
            reasons.append(f"unconnected_items={unconnected_items} != 0")
            checks["unconnected_zero"] = False
        else:
            checks["unconnected_zero"] = True
    elif unconnected_items is not None:
        ok = int(unconnected_items) == 0
        checks["unconnected_zero"] = ok
        if not ok:
            reasons.append(f"unconnected_items={unconnected_items} != 0")

    passed = all(checks.values()) if checks else False
    return {
        "passed": passed,
        "checks": checks,
        "reasons": reasons,
        "verdict": (
            "GO — hard gate (errors=0, route 100%, DRC/unconnected clean)"
            if passed
            else "NO-GO — hard gate fail-closed: " + "; ".join(reasons)
        ),
        "metrics": {
            "error_conflicts": error_conflicts,
            "routed_percent": routed_percent,
            "unrouted_count": unrouted_count,
            "drc_error_count": drc_error_count,
            "unconnected_items": unconnected_items,
        },
    }


def evaluate_dataset_hard_gate(
    board_gates: list[dict[str, Any]],
    *,
    require_all_boards: bool = True,
) -> dict[str, Any]:
    """Aggregate per-board hard gates. Default: **all** boards must pass."""
    if not board_gates:
        return {
            "passed": False,
            "n_boards": 0,
            "n_pass": 0,
            "n_fail": 0,
            "verdict": "NO-GO — empty dataset",
        }
    n_pass = sum(1 for g in board_gates if g.get("passed"))
    n_fail = len(board_gates) - n_pass
    if require_all_boards:
        passed = n_fail == 0
        majority_note = "all boards"
    else:
        passed = n_pass > n_fail
        majority_note = "majority (legacy, not recommended)"
    return {
        "passed": passed,
        "n_boards": len(board_gates),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "require_all_boards": require_all_boards,
        "verdict": (
            f"GO — hard gate dataset ({majority_note}, {n_pass}/{len(board_gates)})"
            if passed
            else f"NO-GO — hard gate dataset ({n_fail} fail / {len(board_gates)}; {majority_note})"
        ),
    }


def compare_vs_baseline(
    *,
    routed_percent: float,
    baseline_routed_percent: float,
    error_conflicts: int,
    baseline_error_conflicts: int,
    wirelength_mm: float | None = None,
    baseline_wirelength_mm: float | None = None,
) -> dict[str, Any]:
    """Optional comparison arm (RL vs CMA/kct). Never alone grants GO."""
    reasons: list[str] = []
    route_ok = float(routed_percent) + 1e-9 >= float(baseline_routed_percent)
    errors_ok = int(error_conflicts) <= int(baseline_error_conflicts)
    if not route_ok:
        reasons.append(
            f"routed_percent {routed_percent} < baseline {baseline_routed_percent}"
        )
    if not errors_ok:
        reasons.append(
            f"error_conflicts {error_conflicts} > baseline {baseline_error_conflicts}"
        )
    wl_ok = True
    if wirelength_mm is not None and baseline_wirelength_mm is not None:
        wl_ok = float(wirelength_mm) <= float(baseline_wirelength_mm) * 1.05 + 1e-9
        if not wl_ok:
            reasons.append(
                f"wirelength {wirelength_mm} > baseline*1.05 {baseline_wirelength_mm}"
            )
    competitive = route_ok and errors_ok and wl_ok
    return {
        "competitive_vs_baseline": competitive,
        "route_ok": route_ok,
        "errors_ok": errors_ok,
        "wirelength_ok": wl_ok,
        "reasons": reasons,
    }
