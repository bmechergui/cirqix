"""Unit tests — KctPlacementEnv (injectable place_fn, no real CMA-ES)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from kicad_tools.schema.pcb import PCB

from tools.rl.placement.kct_env import N_PLACE_ACTIONS, KctPlacementEnv
from tools.rl.placement.observation import OBS_DIM


def _minimal_board(tmp_path: Path) -> Path:
    pcb = PCB.create(width=40.0, height=30.0, layers=2)
    path = tmp_path / "place_kct.kicad_pcb"
    pcb.save(str(path))
    return path


def test_kct_placement_env_reset_obs_shape(tmp_path: Path) -> None:
    path = _minimal_board(tmp_path)

    def fake_place(work: Path, action: int, anchors: list[str]) -> dict:
        return {"applied": True, "refined": True, "elapsed_s": 0.01, "action": action}

    env = KctPlacementEnv(pcb_path=path, place_fn=fake_place, max_steps=2)
    try:
        obs, info = env.reset(seed=0)
        assert obs.shape == (OBS_DIM,)
        assert info["env"] == "kct_placement"
        assert Path(info["pcb_path"]).is_file()
        assert info["source_path"].endswith("place_kct.kicad_pcb")
    finally:
        env.close()


def test_kct_placement_env_step_calls_place_fn(tmp_path: Path) -> None:
    path = _minimal_board(tmp_path)
    calls: list[int] = []

    def fake_place(work: Path, action: int, anchors: list[str]) -> dict:
        calls.append(action)
        assert work.is_file()
        return {"applied": True, "refined": True, "elapsed_s": 0.0, "action": action}

    env = KctPlacementEnv(pcb_path=path, place_fn=fake_place, max_steps=3)
    try:
        env.reset(seed=1)
        obs, reward, term, trunc, info = env.step(0)
        assert calls == [0]
        assert obs.shape == (OBS_DIM,)
        assert isinstance(reward, float)
        assert info["step_meta"]["applied"] is True
        assert not term
    finally:
        env.close()


def test_kct_placement_env_stop_action_terminates(tmp_path: Path) -> None:
    path = _minimal_board(tmp_path)
    calls: list[int] = []

    def fake_place(work: Path, action: int, anchors: list[str]) -> dict:
        calls.append(action)
        return {"applied": True, "refined": False}

    env = KctPlacementEnv(pcb_path=path, place_fn=fake_place, max_steps=5)
    try:
        env.reset()
        # clean board (0 ERROR) → stop allowed
        _, _, term, trunc, info = env.step(2)  # stop
        assert term is True
        assert calls == []  # stop must not call kct
        assert info["step_meta"].get("stop") is True
    finally:
        env.close()


def test_kct_placement_env_stop_forced_to_refine_if_errors(tmp_path: Path) -> None:
    """Gate A fix: stop is rewritten to CMA when ERROR > 0."""
    path = _minimal_board(tmp_path)
    calls: list[int] = []

    def fake_place(work: Path, action: int, anchors: list[str]) -> dict:
        calls.append(action)
        return {"applied": True, "refined": True, "action": action}

    env = KctPlacementEnv(
        pcb_path=path,
        place_fn=fake_place,
        max_steps=3,
        force_refine_if_errors=True,
    )
    try:
        env.reset()
        env._prev_errors = 6  # simulate dense board residual ERROR
        _, reward, term, trunc, info = env.step(2)  # agent wanted stop
        assert calls == [0], "stop must become short CMA (action 0)"
        assert info["step_meta"].get("forced_refine") is True
        assert info["step_meta"].get("stop") is not True
        assert not term  # refine is not a terminal stop
    finally:
        env.close()


def test_kct_placement_env_max_steps_truncates(tmp_path: Path) -> None:
    path = _minimal_board(tmp_path)

    def fake_place(work: Path, action: int, anchors: list[str]) -> dict:
        return {"applied": True, "refined": True}

    env = KctPlacementEnv(pcb_path=path, place_fn=fake_place, max_steps=1)
    try:
        env.reset()
        _, _, term, trunc, _ = env.step(0)
        assert trunc is True or term is True
    finally:
        env.close()


def test_kct_placement_env_action_space(tmp_path: Path) -> None:
    path = _minimal_board(tmp_path)
    env = KctPlacementEnv(
        pcb_path=path,
        place_fn=lambda w, a, an: {"applied": False},
    )
    try:
        if hasattr(env, "action_space"):
            assert env.action_space.n == N_PLACE_ACTIONS
    finally:
        env.close()


def test_kct_placement_env_missing_file() -> None:
    with pytest.raises(FileNotFoundError):
        KctPlacementEnv(pcb_path=Path("/nonexistent/board.kicad_pcb"))
