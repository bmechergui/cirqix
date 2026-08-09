"""Tests — RL RoutingEnv smoke on LED fixture."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tools.rl.routing.actions import N_ACTIONS, RouteAction
from tools.rl.routing.env import RoutingEnv, _HAS_GYM

_LED = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "led-blinker-full-pipeline"
    / "output"
    / "5_placed.kicad_pcb"
)


@pytest.fixture
def env():
    if not _LED.is_file():
        pytest.skip(f"LED fixture missing: {_LED}")
    # Coarser grid for fast tests
    return RoutingEnv(_LED, resolution_mm=0.5, max_steps=64, seed=0)


def test_reset_returns_obs(env) -> None:
    obs, info = env.reset(seed=0)
    assert obs.shape == (env.obs_dim,)
    assert obs.dtype == np.float32
    assert "net" in info
    assert info["net"]


def test_step_move_and_collision(env) -> None:
    obs, info = env.reset(seed=1)
    # Many random moves should not crash
    for a in range(N_ACTIONS):
        obs, reward, term, trunc, info = env.step(a)
        assert isinstance(reward, float)
        if term or trunc:
            break
    assert obs.shape == (env.obs_dim,)


def test_finish_without_target_aborts(env) -> None:
    env.reset(seed=2)
    # Immediately finish far from target
    obs, reward, term, trunc, info = env.step(int(RouteAction.FINISH_NET))
    assert term is True
    assert info.get("success") is False
    assert reward <= -100  # abort penalty


def test_gym_spaces(env) -> None:
    if not _HAS_GYM:
        pytest.skip("gymnasium not installed")
    assert env.action_space.n == N_ACTIONS
    assert env.observation_space.shape == (env.obs_dim,)
