"""PPO-transition smoke on ManagerRoutingEnv (mock operator)."""

from __future__ import annotations

from pathlib import Path

import pytest
from kicad_tools.schema.pcb import PCB

from tools.rl.routing.train_routing import main


def _board(tmp_path: Path) -> Path:
    pcb = PCB.create(width=40.0, height=30.0, layers=2)
    path = tmp_path / "mgr.kicad_pcb"
    pcb.save(str(path))
    return path


def test_train_ppo_manager_mock_smoke(tmp_path: Path) -> None:
    pytest.importorskip("stable_baselines3")
    path = _board(tmp_path)
    out = tmp_path / "routing_ppo_manager_smoke.zip"
    metrics = tmp_path / "m.json"
    rc = main(
        [
            "--pcb",
            str(path),
            "--env",
            "manager",
            "--kct-backend",
            "mock",
            "--net-ids",
            "1,2,3,4",
            "--algo",
            "ppo",
            "--steps",
            "512",
            "--max-episode-steps",
            "16",
            "--checkpoint-freq",
            "256",
            "--out",
            str(out),
            "--metrics-json",
            str(metrics),
        ]
    )
    assert rc == 0
    assert out.is_file()
    text = metrics.read_text(encoding="utf-8")
    assert "manager" in text
    assert "completed" in text or "ppo" in text
