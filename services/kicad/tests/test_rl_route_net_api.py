"""TDD — incremental route_net contract + mock / kct_full backends."""

from __future__ import annotations

import pytest

from tools.rl.routing import route_net_api as rna
from tools.rl.routing.route_net_api import (
    STRATEGIES,
    MockRouterState,
    estimate_routed_percent_from_pcb,
    mock_route_net,
    route_net,
    strategy_from_index,
    strategy_index,
)


def test_strategies_include_proposed_taxonomy() -> None:
    for name in ("shortest", "low_vias", "balanced", "vcc_traces"):
        assert name in STRATEGIES


def test_strategy_index_roundtrip() -> None:
    for i, name in enumerate(STRATEGIES):
        assert strategy_index(name) == i
        assert strategy_from_index(i) == name


def test_mock_route_net_marks_net_and_increments_pct() -> None:
    state = MockRouterState.from_net_ids([1, 2, 3, 4])
    board = b"(kicad_pcb mock)"
    out, m = mock_route_net(board, net_id=2, strategy="low_vias", state=state)
    assert out == board
    assert m.success is True
    assert m.nets_routed == 1
    assert m.unrouted_count == 3
    assert m.routed_percent == 25
    assert 2 in state.routed


def test_mock_route_net_completes_all_nets() -> None:
    state = MockRouterState.from_net_ids([10, 20])
    board = b"pcb"
    for nid in (10, 20):
        board, m = route_net(
            board, nid, "balanced", backend="mock", state=state
        )
    assert m.routed_percent == 100
    assert m.unrouted_count == 0


def test_mock_ripup_unroutes_net() -> None:
    state = MockRouterState.from_net_ids([1, 2])
    board = b"x"
    board, m1 = mock_route_net(board, 1, "shortest", state=state)
    assert m1.nets_routed == 1
    board, m2 = mock_route_net(board, 1, "ripup_retry", state=state, ripup=True)
    assert m2.success is True
    assert 1 not in state.routed
    assert state.nets_routed == 0


def test_route_net_mock_requires_state() -> None:
    with pytest.raises(ValueError, match="MockRouterState"):
        route_net(b"pcb", 1, "shortest", backend="mock", state=None)


def test_unknown_strategy_raises() -> None:
    state = MockRouterState.from_net_ids([1])
    with pytest.raises(ValueError, match="unknown strategy"):
        mock_route_net(b"pcb", 1, "not_a_strategy", state=state)


def test_kct_full_updates_manager_state(monkeypatch) -> None:
    """Regression: kct_full must advance MockRouterState for obs/reward."""
    state = MockRouterState.from_net_ids([1, 2, 3])

    def fake_route_kct(pcb_bytes, timeout_s=600, vcc_as_traces=True):
        del timeout_s, vcc_as_traces
        return pcb_bytes + b"\n;routed", 80, "ok"

    monkeypatch.setattr(
        "tools.kct_route.route_kct",
        fake_route_kct,
    )
    # route_net imports route_kct inside the branch — patch module used after import
    import tools.kct_route as kct_mod

    monkeypatch.setattr(kct_mod, "route_kct", fake_route_kct)

    board = b"(kicad_pcb)"
    out, metrics = route_net(
        board,
        net_id=2,
        strategy="low_vias",
        backend="kct_full",
        state=state,
    )
    assert out.endswith(b";routed")
    assert metrics.success is True
    assert 2 in state.routed
    assert state.nets_routed >= 1
    assert state.routed_percent >= max(33, 80) or state.kct_reported_pct == 80
    assert state.kct_reported_pct == 80
    # Second call at 100% should mark all nets
    def fake_100(pcb_bytes, timeout_s=600, vcc_as_traces=True):
        del timeout_s, vcc_as_traces
        return pcb_bytes, 100, ""

    monkeypatch.setattr(kct_mod, "route_kct", fake_100)
    out2, m2 = route_net(
        out, net_id=1, strategy="balanced", backend="kct_full", state=state
    )
    assert m2.routed_percent == 100
    assert state.unrouted_count == 0
    assert state.routed == {1, 2, 3}


def test_kct_full_requires_state() -> None:
    with pytest.raises(ValueError, match="MockRouterState"):
        route_net(b"x", 1, "shortest", backend="kct_full", state=None)


def test_estimate_routed_percent_from_pcb_segments() -> None:
    # two multi-pad nets; only net 1 has a segment
    sexpr = b"""
    (kicad_pcb
      (net 0 "")
      (net 1 "SIG")
      (net 2 "VCC")
      (footprint "X" (pad "1" smd (net 1 "SIG")) (pad "2" smd (net 1 "SIG")))
      (footprint "Y" (pad "1" smd (net 2 "VCC")) (pad "2" smd (net 2 "VCC")))
      (segment (start 0 0) (end 1 0) (net 1))
    )
    """
    pct = estimate_routed_percent_from_pcb(sexpr)
    assert pct == 50


def test_estimate_routed_percent_all_copper() -> None:
    sexpr = b"""
    (kicad_pcb
      (net 1 "A")
      (footprint "X" (pad "1" smd (net 1 "A")) (pad "2" smd (net 1 "A")))
      (segment (start 0 0) (end 1 0) (net 1))
    )
    """
    assert estimate_routed_percent_from_pcb(sexpr) == 100


def test_parse_net_id_name_map_and_copper() -> None:
    sexpr = b"""
    (kicad_pcb
      (net 0 "")
      (net 1 "SIG")
      (net 2 "VCC")
      (segment (start 0 0) (end 1 0) (net 1))
    )
    """
    assert rna.parse_net_id_name_map(sexpr) == {1: "SIG", 2: "VCC"}
    assert rna.resolve_net_name(sexpr, 1) == "SIG"
    assert rna.net_id_has_copper(sexpr, 1) is True
    assert rna.net_id_has_copper(sexpr, 2) is False


def test_net_id_has_copper_detects_filled_zone() -> None:
    """GND pours have no segment — filled zone must still count as copper."""
    sexpr = b"""
    (kicad_pcb
      (net 1 "GND")
      (zone (net 1) (net_name "GND")
        (layer "B.Cu")
        (filled_polygon (layer "B.Cu") (pts (xy 0 0) (xy 1 0) (xy 1 1)))
      )
    )
    """
    assert rna.net_id_has_copper(sexpr, 1) is True


def test_multi_pad_net_ids_skips_single_pad() -> None:
    sexpr = b"""
    (kicad_pcb
      (net 1 "A")
      (net 2 "B")
      (footprint "X"
        (pad "1" smd rect (at 0 0) (size 1 1) (layers F.Cu)
          (net 1 "A")
        )
        (pad "2" smd rect (at 1 0) (size 1 1) (layers F.Cu)
          (net 1 "A")
        )
        (pad "3" smd rect (at 2 0) (size 1 1) (layers F.Cu)
          (net 2 "B")
        )
      )
    )
    """
    assert rna.pad_count_by_net_id(sexpr) == {1: 2, 2: 1}
    assert rna.multi_pad_net_ids(sexpr) == [1]


def test_kct_net_routes_single_net_and_updates_state(monkeypatch) -> None:
    """kct_net calls route_kct_net with the net name; credits that net only."""
    state = MockRouterState.from_net_ids([1, 2])
    board = b"""
    (kicad_pcb
      (net 1 "SIG")
      (net 2 "VCC")
    )
    """
    routed_out = (
        board
        + b'\n(segment (start 0 0) (end 1 0) (net 1))\n'
    )
    calls: list[str] = []

    def fake_route_kct_net(
        pcb_bytes, net_name, timeout_s=120, vcc_as_traces=True
    ):
        del timeout_s, vcc_as_traces
        calls.append(net_name)
        return routed_out, 50, ""

    import tools.kct_route as kct_mod

    monkeypatch.setattr(kct_mod, "route_kct_net", fake_route_kct_net)

    out, metrics = route_net(
        board,
        net_id=1,
        strategy="balanced",
        backend="kct_net",
        state=state,
    )
    assert calls == ["SIG"]
    assert metrics.success is True
    assert 1 in state.routed
    assert 2 not in state.routed
    assert state.nets_routed == 1
    assert state.routed_percent == 50
    assert b"(segment" in out
    assert "kct_net:SIG" in metrics.note


def test_kct_net_requires_state() -> None:
    with pytest.raises(ValueError, match="MockRouterState"):
        route_net(b'(net 1 "A")', 1, "shortest", backend="kct_net", state=None)


def test_kct_net_unknown_net_id() -> None:
    state = MockRouterState.from_net_ids([9])
    board = b'(kicad_pcb (net 1 "A"))'
    with pytest.raises(ValueError, match="not found"):
        route_net(board, 9, "balanced", backend="kct_net", state=state)


def test_build_route_cmd_includes_only_nets() -> None:
    from pathlib import Path

    from tools.kct_route import _build_route_cmd

    cmd = _build_route_cmd(
        Path("in.kicad_pcb"),
        Path("out.kicad_pcb"),
        60,
        only_nets=["SIG", "GND"],
    )
    assert "--nets" in cmd
    assert cmd[cmd.index("--nets") + 1] == "SIG,GND"
    assert "--preserve-existing" in cmd


def test_build_route_cmd_full_board_has_no_preserve_flag() -> None:
    from pathlib import Path

    from tools.kct_route import _build_route_cmd

    cmd = _build_route_cmd(Path("in.kicad_pcb"), Path("out.kicad_pcb"), 60)
    assert "--nets" not in cmd
    assert "--preserve-existing" not in cmd
