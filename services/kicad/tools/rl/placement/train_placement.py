#!/usr/bin/env python3
"""Offline RL placement training / smoke (Phase 6a).

kicad-tools only. Not called from FastAPI.

Examples::

    # Smoke (default 100_000 if SB3 available, else random-policy rate test)
    python -m tools.rl.placement.train_placement \\
        --pcb examples/led-blinker-full-pipeline/output/5_placed.kicad_pcb \\
        --steps 100

    # Longer run when deps installed
    python -m tools.rl.placement.train_placement --steps 100000 --out models/placement_ppo_smoke.zip
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Allow ``python -m tools.rl.placement.train_placement`` from services/kicad
# (must run before package imports pull in kicad_tools).
_SERVICE_ROOT = Path(__file__).resolve().parents[3]
_KT_SRC = _SERVICE_ROOT / "kicad-tools" / "src"
for _p in (str(_SERVICE_ROOT), str(_KT_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Re-export path setup for ``python tools/rl/placement/train_placement.py``
if __name__ == "__main__" and __package__ is None:
    __package__ = "tools.rl.placement"

from tools.rl.placement.env import PlacementEnv, _HAS_GYM  # noqa: E402


def _random_smoke(env: PlacementEnv, steps: int) -> dict:
    """Measure env step rate with random actions (no SB3 required)."""
    import numpy as np

    obs, info = env.reset()
    t0 = time.perf_counter()
    total_reward = 0.0
    for i in range(steps):
        if _HAS_GYM and hasattr(env, "action_space"):
            action = env.action_space.sample()
        else:
            action = np.array([0, 3, 3], dtype=np.int64)  # no-op-ish
        obs, reward, term, trunc, info = env.step(action)
        total_reward += float(reward)
        if term or trunc:
            obs, info = env.reset()
    elapsed = time.perf_counter() - t0
    return {
        "mode": "random_smoke",
        "steps": steps,
        "elapsed_s": elapsed,
        "steps_per_s": steps / elapsed if elapsed > 0 else 0.0,
        "total_reward": total_reward,
        "final_fom": info.get("fom_score"),
        "has_gymnasium": _HAS_GYM,
    }


def _ppo_train(env: PlacementEnv, steps: int, out: Path | None) -> dict:
    """PPO smoke / short train via Stable-Baselines3 when installed."""
    try:
        from stable_baselines3 import PPO
    except ImportError as exc:
        raise SystemExit(
            "stable-baselines3 is required for --algo ppo. "
            "Install: pip install stable-baselines3  "
            f"({exc})"
        ) from exc

    if not _HAS_GYM:
        raise SystemExit("gymnasium is required for PPO training")

    t0 = time.perf_counter()
    model = PPO(
        "MlpPolicy",
        env,
        verbose=0,
        n_steps=min(64, max(8, steps // 4)),
        batch_size=min(64, max(8, steps // 8)),
    )
    model.learn(total_timesteps=steps)
    elapsed = time.perf_counter() - t0
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        model.save(str(out))
    return {
        "mode": "ppo",
        "steps": steps,
        "elapsed_s": elapsed,
        "steps_per_s": steps / elapsed if elapsed > 0 else 0.0,
        "checkpoint": str(out) if out else None,
        "has_gymnasium": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RL placement train / smoke")
    parser.add_argument(
        "--pcb",
        type=Path,
        required=True,
        help="Path to a placed .kicad_pcb fixture",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=100_000,
        help="Timesteps (default 100000 smoke; use smaller for local debug)",
    )
    parser.add_argument(
        "--algo",
        choices=("random", "ppo"),
        default="random",
        help="random = step-rate smoke; ppo = SB3 PPO (needs deps)",
    )
    parser.add_argument("--board-width", type=float, default=None)
    parser.add_argument("--board-height", type=float, default=None)
    parser.add_argument("--max-episode-steps", type=int, default=32)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Checkpoint path for --algo ppo",
    )
    parser.add_argument(
        "--metrics-json",
        type=Path,
        default=None,
        help="Write metrics JSON (steps/s, elapsed, …)",
    )
    args = parser.parse_args(argv)

    if not args.pcb.is_file():
        print(f"error: PCB not found: {args.pcb}", file=sys.stderr)
        return 2

    env = PlacementEnv(
        pcb_path=args.pcb,
        board_width_mm=args.board_width,
        board_height_mm=args.board_height,
        max_steps=args.max_episode_steps,
    )

    if args.algo == "ppo":
        metrics = _ppo_train(env, args.steps, args.out)
    else:
        metrics = _random_smoke(env, args.steps)

    print(json.dumps(metrics, indent=2))
    if args.metrics_json:
        args.metrics_json.parent.mkdir(parents=True, exist_ok=True)
        args.metrics_json.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
