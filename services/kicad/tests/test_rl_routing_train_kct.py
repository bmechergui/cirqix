"""Train CLI — Phase 3 wiring for --env kct (mock backend)."""

from __future__ import annotations

from pathlib import Path

import pytest
from kicad_tools.schema.pcb import PCB

from tools.rl.routing.train_routing import main


def _board(tmp_path: Path) -> Path:
    pcb = PCB.create(width=40.0, height=30.0, layers=2)
    path = tmp_path / "r.kicad_pcb"
    pcb.save(str(path))
    return path


def test_train_ppo_kct_mock_smoke(tmp_path: Path) -> None:
    pytest.importorskip("stable_baselines3")
    path = _board(tmp_path)
    out = tmp_path / "routing_ppo_kct_smoke.zip"
    metrics = tmp_path / "m.json"
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
    assert "kct" in metrics.read_text(encoding="utf-8")
