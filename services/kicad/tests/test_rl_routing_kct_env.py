"""Unit tests — KctRoutingEnv / FrRoutingEnv (injectable route_fn)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from kicad_tools.schema.pcb import PCB

from tools.rl.routing.kct_env import (
    N_FR_ROUTE_ACTIONS,
    N_KCT_ROUTE_ACTIONS,
    ROUTING_OBS_DIM,
    FrRoutingEnv,
    KctRoutingEnv,
)


def _minimal_board(tmp_path: Path) -> Path:
    pcb = PCB.create(width=40.0, height=30.0, layers=2)
    path = tmp_path / "route_kct.kicad_pcb"
    pcb.save(str(path))
    return path


def test_kct_routing_env_reset_and_route(tmp_path: Path) -> None:
    path = _minimal_board(tmp_path)
    raw = path.read_bytes()
    calls: list[int] = []

    def fake_route(pcb_bytes: bytes, action: int) -> tuple[bytes, int, str]:
        calls.append(action)
        # pretend we improved routing
        return pcb_bytes + b"\n", 80, ""

    env = KctRoutingEnv(pcb_path=path, route_fn=fake_route, max_steps=3)
    try:
        obs, info = env.reset(seed=0)
        assert obs.shape == (ROUTING_OBS_DIM,)
        assert info["env"] == "kct_routing"
        assert info["routed_percent"] == 0

        obs2, reward, term, trunc, info2 = env.step(0)
        assert calls == [0]
        assert info2["routed_percent"] == 80
        assert reward > 0  # +0.8 pct reward minus step cost
        assert obs2[0] == pytest.approx(0.8)
    finally:
        env.close()


def test_kct_routing_env_stop_no_call(tmp_path: Path) -> None:
    path = _minimal_board(tmp_path)
    calls: list[int] = []

    def fake_route(pcb_bytes: bytes, action: int) -> tuple[bytes, int, str]:
        calls.append(action)
        return pcb_bytes, 0, ""

    env = KctRoutingEnv(pcb_path=path, route_fn=fake_route, max_steps=5)
    try:
        env.reset()
        _, _, term, _, info = env.step(2)
        assert term is True
        assert calls == []
        assert info["step_meta"].get("stop") is True
    finally:
        env.close()


def test_kct_routing_env_100_percent_terminates(tmp_path: Path) -> None:
    path = _minimal_board(tmp_path)

    def fake_route(pcb_bytes: bytes, action: int) -> tuple[bytes, int, str]:
        return pcb_bytes, 100, ""

    env = KctRoutingEnv(pcb_path=path, route_fn=fake_route, max_steps=5)
    try:
        env.reset()
        _, reward, term, _, info = env.step(0)
        assert term is True
        assert info["routed_percent"] == 100
        assert reward > 0.5
    finally:
        env.close()


def test_kct_routing_env_resume_initial_percent(tmp_path: Path) -> None:
    """Fallback training: start from partial board (not from zero)."""
    path = _minimal_board(tmp_path)

    def fake_route(pcb_bytes: bytes, action: int) -> tuple[bytes, int, str]:
        return pcb_bytes, 95, ""

    env = KctRoutingEnv(pcb_path=path, route_fn=fake_route, max_steps=2)
    try:
        obs, info = env.reset(options={"initial_routed_percent": 70})
        assert info["routed_percent"] == 70
        assert obs[0] == pytest.approx(0.7)
        _, reward, _, _, info2 = env.step(0)
        # delta 95-70 = 25 → +0.25 reward-ish
        assert info2["routed_percent"] == 95
        assert reward > 0.2
    finally:
        env.close()


def test_kct_routing_env_route_error_penalty(tmp_path: Path) -> None:
    path = _minimal_board(tmp_path)

    def boom(pcb_bytes: bytes, action: int) -> tuple[bytes, int, str]:
        raise RuntimeError("kct down")

    env = KctRoutingEnv(pcb_path=path, route_fn=boom, max_steps=2)
    try:
        env.reset()
        _, reward, _, _, info = env.step(0)
        assert reward < 0
        assert "error" in info["step_meta"]
    finally:
        env.close()


def test_fr_routing_env_step(tmp_path: Path) -> None:
    path = _minimal_board(tmp_path)
    calls: list[int] = []

    def fake_fr(pcb_bytes: bytes, action: int) -> tuple[bytes, int, str]:
        calls.append(action)
        return pcb_bytes, 60, "fr-ok"

    env = FrRoutingEnv(pcb_path=path, route_fn=fake_fr, max_steps=2)
    try:
        obs, info = env.reset()
        assert info["env"] == "fr_routing"
        assert obs.shape == (ROUTING_OBS_DIM,)
        _, _, term, _, info2 = env.step(0)
        assert calls == [0]
        assert info2["routed_percent"] == 60
        _, _, term2, _, _ = env.step(1)  # stop
        assert term2 is True
    finally:
        env.close()


def test_action_counts(tmp_path: Path) -> None:
    path = _minimal_board(tmp_path)
    kct = KctRoutingEnv(
        pcb_path=path, route_fn=lambda b, a: (b, 0, ""), max_steps=1
    )
    fr = FrRoutingEnv(
        pcb_path=path, route_fn=lambda b, a: (b, 0, ""), max_steps=1
    )
    try:
        if hasattr(kct, "action_space"):
            assert kct.action_space.n == N_KCT_ROUTE_ACTIONS
        if hasattr(fr, "action_space"):
            assert fr.action_space.n == N_FR_ROUTE_ACTIONS
    finally:
        kct.close()
        fr.close()


def test_kct_routing_missing_file() -> None:
    with pytest.raises(FileNotFoundError):
        KctRoutingEnv(pcb_path=Path("/nonexistent/board.kicad_pcb"))
