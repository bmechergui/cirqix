"""Train CLI — Phase 2 wiring for --env kct (mock backend, no CMA-ES)."""

from __future__ import annotations

from pathlib import Path

import pytest
from kicad_tools.schema.pcb import PCB

from tools.rl.placement.train_placement import _make_env, main


def _board(tmp_path: Path) -> Path:
    pcb = PCB.create(width=40.0, height=30.0, layers=2)
    path = tmp_path / "t.kicad_pcb"
    pcb.save(str(path))
    return path


def test_make_env_kct_mock(tmp_path: Path) -> None:
    path = _board(tmp_path)
    env = _make_env(
        env_kind="kct",
        pcb_paths=[path],
        max_episode_steps=2,
        board_width=None,
        board_height=None,
        kct_backend="mock",
    )
    try:
        obs, info = env.reset()
        assert info["env"] == "kct_placement"
        assert obs is not None
    finally:
        env.close()


def test_train_ppo_kct_mock_smoke(tmp_path: Path) -> None:
    pytest.importorskip("stable_baselines3")
    path = _board(tmp_path)
    out = tmp_path / "placement_ppo_kct_smoke.zip"
    metrics = tmp_path / "metrics.json"
    rc = main(
        [
            "--pcb",
            str(path),
            "--env",
            "kct",
            "--kct-backend",
            "mock",
            "--algo",
            "ppo",
            "--steps",
            "128",
            "--max-episode-steps",
            "2",
            "--checkpoint-freq",
            "64",
            "--out",
            str(out),
            "--metrics-json",
            str(metrics),
        ]
    )
    assert rc == 0
    assert out.is_file()
    assert metrics.is_file()
    payload = metrics.read_text(encoding="utf-8")
    assert "kct" in payload
    assert "completed" in payload or "ppo" in payload
