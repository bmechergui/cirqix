"""TDD — ManagerRoutingEnv (net + strategy actions, mock operator)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from kicad_tools.schema.pcb import PCB

from tools.rl.routing.manager_env import (
    MANAGER_OBS_DIM,
    STOP_ACTION,
    ManagerRoutingEnv,
    decode_manager_action,
    n_manager_actions,
    stop_action_for_slots,
)
from tools.rl.routing.route_net_api import N_STRATEGIES, strategy_index


def _board(tmp_path: Path) -> Path:
    pcb = PCB.create(width=40.0, height=30.0, layers=2)
    path = tmp_path / "m.kicad_pcb"
    pcb.save(str(path))
    return path


def test_decode_stop_and_net_strategy() -> None:
    assert decode_manager_action(STOP_ACTION)[2] is True
    assert decode_manager_action(stop_action_for_slots(6), n_slots=6)[2] is True
    slot, strat, stop = decode_manager_action(0, n_slots=6)
    assert stop is False
    assert slot == 0
    assert strat == 0
    # net slot 1, strategy low_vias
    idx = 1 * N_STRATEGIES + strategy_index("low_vias")
    slot, strat, stop = decode_manager_action(idx, n_slots=6)
    assert slot == 1
    assert strat == strategy_index("low_vias")
    assert stop is False
    # slot beyond n_slots is treated as stop/invalid
    bad = 6 * N_STRATEGIES  # would be stop for 6 slots only if == stop
    assert decode_manager_action(bad + 5, n_slots=6)[2] is True


def test_manager_env_reset_obs_shape(tmp_path: Path) -> None:
    path = _board(tmp_path)
    env = ManagerRoutingEnv(path, net_ids=[1, 2, 3], backend="mock", max_steps=10)
    try:
        obs, info = env.reset(seed=0)
        assert obs.shape == (MANAGER_OBS_DIM,)
        assert info["env"] == "manager_routing"
        assert info["nets_total"] == 3
        if hasattr(env, "action_space"):
            assert env.action_space.n == n_manager_actions(3)
            assert env.action_space.n == env.n_actions
            assert env.stop_action == stop_action_for_slots(3)
    finally:
        env.close()


def test_manager_env_routes_all_nets_with_sequence(tmp_path: Path) -> None:
    path = _board(tmp_path)
    net_ids = [5, 6, 7]
    env = ManagerRoutingEnv(path, net_ids=net_ids, backend="mock", max_steps=20)
    try:
        obs, info = env.reset()
        total_r = 0.0
        for slot, nid in enumerate(net_ids):
            action = slot * N_STRATEGIES + strategy_index("balanced")
            obs, reward, term, trunc, info = env.step(action)
            total_r += reward
            assert info["nets_routed"] == slot + 1
        assert info["routed_percent"] == 100
        assert info["unrouted_count"] == 0
        assert term is True
        assert total_r > 0
    finally:
        env.close()


def test_manager_env_stop_terminates(tmp_path: Path) -> None:
    path = _board(tmp_path)
    env = ManagerRoutingEnv(path, net_ids=[1, 2], backend="mock", max_steps=5)
    try:
        env.reset()
        _, _, term, _, info = env.step(env.stop_action)
        assert term is True
        assert info["step_meta"].get("stop") is True
    finally:
        env.close()


def test_manager_env_partial_resume(tmp_path: Path) -> None:
    path = _board(tmp_path)
    env = ManagerRoutingEnv(path, net_ids=[1, 2, 3], backend="mock", max_steps=5)
    try:
        obs, info = env.reset(options={"pre_routed": [1, 2]})
        assert info["routed_percent"] in (66, 67)
        assert info["nets_total"] == 3
        # net_ids sorted [1,2,3] → slot 2 = net 3
        action = 2 * N_STRATEGIES + 0
        _, _, term, _, info2 = env.step(action)
        assert info2["unrouted_count"] == 0
        assert info2["routed_percent"] == 100
        assert term is True
    finally:
        env.close()


def test_manager_env_missing_file() -> None:
    with pytest.raises(FileNotFoundError):
        ManagerRoutingEnv(Path("/nonexistent/x.kicad_pcb"))


def test_manager_env_kct_full_progress_with_mocked_route_kct(
    tmp_path: Path, monkeypatch
) -> None:
    """kct_full must not leave progress stuck at 0% (review blocker)."""
    path = _board(tmp_path)
    calls = {"n": 0}

    def fake_route_kct(pcb_bytes, timeout_s=600, vcc_as_traces=True, only_nets=None):
        del timeout_s, vcc_as_traces, only_nets
        calls["n"] += 1
        # First call partial, second full
        pct = 50 if calls["n"] == 1 else 100
        return pcb_bytes, pct, "mock-kct"

    import tools.kct_route as kct_mod

    monkeypatch.setattr(kct_mod, "route_kct", fake_route_kct)

    env = ManagerRoutingEnv(
        path, net_ids=[1, 2], backend="kct_full", max_steps=10
    )
    try:
        obs, info = env.reset(seed=0)
        assert info["routed_percent"] == 0
        action = 0 * N_STRATEGIES + 0
        obs1, r1, term1, _, info1 = env.step(action)
        assert info1["nets_routed"] >= 1
        assert info1["routed_percent"] >= 50
        assert r1 != 0 or info1["nets_routed"] > 0
        action2 = 1 * N_STRATEGIES + 0
        _, _, term2, _, info2 = env.step(action2)
        assert info2["routed_percent"] == 100
        assert info2["unrouted_count"] == 0
        assert term2 is True
    finally:
        env.close()


def test_manager_env_kct_net_progress_with_mocked_route_kct_net(
    tmp_path: Path, monkeypatch
) -> None:
    """kct_net credits one net per step (true incremental contract)."""
    path = _board(tmp_path)
    # Board needs net table for resolve_net_name
    text = path.read_text(encoding="utf-8")
    if "(net 1 " not in text:
        path.write_text(
            text.replace(
                "(kicad_pcb",
                '(kicad_pcb\n  (net 0 "")\n  (net 1 "N1")\n  (net 2 "N2")',
                1,
            ),
            encoding="utf-8",
        )

    def fake_route_kct_net(pcb_bytes, net_name, timeout_s=120, vcc_as_traces=True):
        del timeout_s, vcc_as_traces
        # Append a segment for the requested net id (1 for N1, 2 for N2)
        nid = 1 if net_name == "N1" else 2
        extra = f"\n(segment (start 0 0) (end 1 0) (net {nid}))\n".encode()
        return pcb_bytes + extra, 50, "ok"

    import tools.kct_route as kct_mod

    monkeypatch.setattr(kct_mod, "route_kct_net", fake_route_kct_net)

    env = ManagerRoutingEnv(
        path, net_ids=[1, 2], backend="kct_net", max_steps=10
    )
    try:
        env.reset(seed=0)
        a0 = 0 * N_STRATEGIES + 0
        _, _, _, _, info1 = env.step(a0)
        assert info1["nets_routed"] == 1
        assert info1["routed_percent"] == 50
        a1 = 1 * N_STRATEGIES + 0
        _, _, term, _, info2 = env.step(a1)
        assert info2["nets_routed"] == 2
        assert info2["routed_percent"] == 100
        assert term is True
    finally:
        env.close()
