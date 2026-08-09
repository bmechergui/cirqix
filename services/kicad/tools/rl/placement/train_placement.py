#!/usr/bin/env python3
"""Offline RL placement training / smoke (Phase 6a).

kicad-tools only. Not called from FastAPI.

Supports interrupt-safe PPO training:
  - periodic checkpoints (``--checkpoint-freq``)
  - progress sidecar JSON (``*.progress.json``)
  - ``--resume`` to continue after reboot / Ctrl+C

Examples::

    # Multi-board v2 (synthetic pre-CMA-ES dataset)
    python -m tools.rl.placement.generate_dataset
    python -m tools.rl.placement.train_placement \\
        --pcb-dir examples/rl-placement-dataset/boards \\
        --algo ppo --steps 200000 \\
        --out models/placement_ppo_v2.zip

    # Single board (legacy)
    python -m tools.rl.placement.train_placement \\
        --pcb examples/led-blinker-full-pipeline/output/4_gen.kicad_pcb \\
        --algo ppo --steps 100000 \\
        --out models/placement_ppo_100k.zip

    # After PC reboot / kill — continue toward the same target
    python -m tools.rl.placement.train_placement \\
        --pcb-dir examples/rl-placement-dataset/boards \\
        --algo ppo --steps 200000 \\
        --out models/placement_ppo_v2.zip \\
        --resume models/placement_ppo_v2.zip
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
from tools.rl.placement.kct_env import KctPlacementEnv  # noqa: E402


def _mock_kct_place_fn(work_pcb: Path, action: int, anchors: list[str]) -> dict:
    """Fast backend for smoke train — no CMA-ES subprocess.

    Leaves the board unchanged; marks applied only for refine actions (0/1).
    """
    del work_pcb, anchors
    if int(action) >= 2:
        return {"applied": False, "refined": False, "elapsed_s": 0.0, "action": action}
    return {
        "applied": True,
        "refined": False,
        "elapsed_s": 0.0,
        "action": action,
        "backend": "mock",
    }


def _make_env(
    *,
    env_kind: str,
    pcb_paths: list[Path],
    max_episode_steps: int,
    board_width: float | None,
    board_height: float | None,
    kct_backend: str,
) -> PlacementEnv | KctPlacementEnv:
    if env_kind == "moves":
        return PlacementEnv(
            pcb_paths=pcb_paths,
            board_width_mm=board_width,
            board_height_mm=board_height,
            max_steps=max_episode_steps,
        )
    if env_kind == "kct":
        place_fn = _mock_kct_place_fn if kct_backend == "mock" else None
        return KctPlacementEnv(
            pcb_paths=pcb_paths,
            place_fn=place_fn,
            max_steps=max_episode_steps,
            board_width_mm=board_width,
            board_height_mm=board_height,
            force_refine_if_errors=True,
        )
    raise SystemExit(f"error: unknown --env {env_kind!r}")


def _progress_path(out: Path) -> Path:
    return out.with_suffix(out.suffix + ".progress.json")


def _write_progress(out: Path, *, timesteps: int, target: int, status: str) -> None:
    payload = {
        "checkpoint": str(out),
        "timesteps": int(timesteps),
        "target": int(target),
        "status": status,
        "updated_unix": time.time(),
    }
    _progress_path(out).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_progress(out: Path) -> dict | None:
    p = _progress_path(out)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _random_smoke(env: PlacementEnv | KctPlacementEnv, steps: int) -> dict:
    """Measure env step rate with random actions (no SB3 required)."""
    import numpy as np

    obs, info = env.reset()
    t0 = time.perf_counter()
    total_reward = 0.0
    for i in range(steps):
        if _HAS_GYM and hasattr(env, "action_space"):
            action = env.action_space.sample()
        else:
            action = np.array([0, 3, 3], dtype=np.int64)  # no-op-ish (moves env)
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


def _ppo_train(
    env: PlacementEnv | KctPlacementEnv,
    steps: int,
    out: Path | None,
    *,
    resume: Path | None = None,
    checkpoint_freq: int = 5_000,
    n_steps: int | None = None,
) -> dict:
    """PPO train with periodic checkpoints + resume after interrupt/reboot."""
    try:
        from stable_baselines3 import PPO
        from stable_baselines3.common.callbacks import BaseCallback
    except ImportError as exc:
        raise SystemExit(
            "stable-baselines3 is required for --algo ppo. "
            "Install: pip install stable-baselines3  "
            f"({exc})"
        ) from exc

    if not _HAS_GYM:
        raise SystemExit("gymnasium is required for PPO training")

    if out is None:
        raise SystemExit("--out is required for --algo ppo (checkpoint path)")

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ckpt_dir = out.parent / f"{out.stem}_ckpts"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    class _SaveProgressCallback(BaseCallback):
        """Save model + progress JSON every ``checkpoint_freq`` env steps."""

        def __init__(self, save_path: Path, target: int, freq: int):
            super().__init__()
            self.save_path = save_path
            self.target = target
            self.freq = max(1, int(freq))
            self._last_save_ts = 0

        def _on_step(self) -> bool:
            ts = int(self.num_timesteps)
            if ts - self._last_save_ts >= self.freq:
                self._last_save_ts = ts
                self.model.save(str(self.save_path))
                # Rolling intermediate copy (never lose more than ``freq`` steps)
                mid = ckpt_dir / f"{out.stem}_ts{ts}.zip"
                self.model.save(str(mid))
                _write_progress(
                    self.save_path, timesteps=ts, target=self.target, status="running"
                )
                print(
                    f"[checkpoint] timesteps={ts}/{self.target} → {self.save_path}",
                    flush=True,
                )
            return True

        def _on_training_end(self) -> None:
            self.model.save(str(self.save_path))
            _write_progress(
                self.save_path,
                timesteps=int(self.num_timesteps),
                target=self.target,
                status="completed",
            )

    resume_path = Path(resume) if resume is not None else None
    # Explicit --resume must exist (fail loud — never silent new train)
    if resume is not None and not resume_path.is_file():
        raise SystemExit(f"error: --resume not found: {resume_path}")

    # Auto-resume from --out if progress says incomplete and no explicit --resume
    if resume_path is None and out.is_file():
        prog = _read_progress(out)
        if prog and prog.get("status") != "completed":
            done = int(prog.get("timesteps") or 0)
            if done > 0 and done < steps:
                resume_path = out
                print(
                    f"[auto-resume] found incomplete progress timesteps={done}/{steps}",
                    flush=True,
                )

    t0 = time.perf_counter()
    already = 0

    if resume_path is not None:
        if not resume_path.is_file():
            raise SystemExit(f"error: resume checkpoint missing: {resume_path}")
        print(f"[resume] loading {resume_path}", flush=True)
        model = PPO.load(str(resume_path), env=env)
        # Trust the loaded model counter — sidecar may be stale/wrong
        already = int(getattr(model, "num_timesteps", 0) or 0)
        remaining = max(0, steps - already)
        print(
            f"[resume] already={already} target={steps} remaining={remaining}",
            flush=True,
        )
        if remaining == 0:
            _write_progress(out, timesteps=already, target=steps, status="completed")
            return {
                "mode": "ppo",
                "steps": steps,
                "already": already,
                "trained_this_run": 0,
                "elapsed_s": 0.0,
                "steps_per_s": 0.0,
                "checkpoint": str(out),
                "resumed": True,
                "status": "already_complete",
                "has_gymnasium": True,
            }
        callback = _SaveProgressCallback(out, target=steps, freq=checkpoint_freq)
        try:
            model.learn(
                total_timesteps=remaining,
                reset_num_timesteps=False,
                callback=callback,
            )
        except KeyboardInterrupt:
            model.save(str(out))
            ts = int(getattr(model, "num_timesteps", already) or already)
            _write_progress(out, timesteps=ts, target=steps, status="interrupted")
            print(f"[interrupt] saved {out} at timesteps={ts}", flush=True)
            raise SystemExit(130) from None
    else:
        # kct+cmaes: each env step is expensive → small rollouts by default
        roll = int(n_steps) if n_steps is not None else min(2048, max(64, steps // 16))
        roll = max(8, min(roll, steps))
        batch = min(64, max(8, roll // 2))
        model = PPO(
            "MlpPolicy",
            env,
            verbose=0,
            n_steps=roll,
            batch_size=batch,
        )
        callback = _SaveProgressCallback(out, target=steps, freq=checkpoint_freq)
        try:
            model.learn(total_timesteps=steps, callback=callback)
        except KeyboardInterrupt:
            model.save(str(out))
            ts = int(getattr(model, "num_timesteps", 0) or 0)
            _write_progress(out, timesteps=ts, target=steps, status="interrupted")
            print(f"[interrupt] saved {out} at timesteps={ts}", flush=True)
            raise SystemExit(130) from None

    elapsed = time.perf_counter() - t0
    final_ts = int(getattr(model, "num_timesteps", steps) or steps)
    model.save(str(out))
    _write_progress(out, timesteps=final_ts, target=steps, status="completed")
    trained = max(0, final_ts - already)
    return {
        "mode": "ppo",
        "steps": steps,
        "already": already,
        "trained_this_run": trained,
        "final_timesteps": final_ts,
        "elapsed_s": elapsed,
        "steps_per_s": trained / elapsed if elapsed > 0 and trained > 0 else 0.0,
        "checkpoint": str(out),
        "progress_file": str(_progress_path(out)),
        "checkpoint_freq": checkpoint_freq,
        "resumed": resume_path is not None,
        "status": "completed",
        "has_gymnasium": True,
    }


def _resolve_pcb_paths(
    pcb: Path | None,
    pcb_dir: Path | None,
    pcb_list: Path | None,
) -> list[Path]:
    """Collect .kicad_pcb paths from --pcb / --pcb-dir / --pcb-list (any combo)."""
    paths: list[Path] = []
    if pcb is not None:
        paths.append(Path(pcb))
    if pcb_dir is not None:
        d = Path(pcb_dir)
        if not d.is_dir():
            raise SystemExit(f"error: --pcb-dir is not a directory: {d}")
        found = sorted(d.glob("*.kicad_pcb"))
        if not found:
            raise SystemExit(f"error: no .kicad_pcb under --pcb-dir: {d}")
        paths.extend(found)
    if pcb_list is not None:
        list_path = Path(pcb_list)
        if not list_path.is_file():
            raise SystemExit(f"error: --pcb-list not found: {list_path}")
        root = list_path.parent
        for line in list_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            p = Path(line)
            if not p.is_file():
                # Relative to list file, then to CWD, then to service root
                for base in (root, Path.cwd(), _SERVICE_ROOT):
                    cand = (base / line).resolve()
                    if cand.is_file():
                        p = cand
                        break
            paths.append(p)
    # De-dupe preserving order
    seen: set[str] = set()
    unique: list[Path] = []
    for p in paths:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    if not unique:
        raise SystemExit(
            "error: provide at least one of --pcb, --pcb-dir, or --pcb-list"
        )
    missing = [p for p in unique if not p.is_file()]
    if missing:
        raise SystemExit(
            "error: PCB not found:\n  " + "\n  ".join(str(m) for m in missing)
        )
    return unique


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RL placement train / smoke")
    parser.add_argument(
        "--pcb",
        type=Path,
        default=None,
        help="Single .kicad_pcb fixture (can combine with --pcb-dir)",
    )
    parser.add_argument(
        "--pcb-dir",
        type=Path,
        default=None,
        help="Directory of *.kicad_pcb boards (multi-fixture training)",
    )
    parser.add_argument(
        "--pcb-list",
        type=Path,
        default=None,
        help="Text file with one .kicad_pcb path per line (# comments ok)",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=100_000,
        help="Target total timesteps (default 100000)",
    )
    parser.add_argument(
        "--algo",
        choices=("random", "ppo"),
        default="random",
        help="random = step-rate smoke; ppo = SB3 PPO (needs deps)",
    )
    parser.add_argument("--board-width", type=float, default=None)
    parser.add_argument("--board-height", type=float, default=None)
    parser.add_argument(
        "--max-episode-steps",
        type=int,
        default=None,
        help="Episode length (default: 32 for moves, 2 for kct)",
    )
    parser.add_argument(
        "--env",
        choices=("moves", "kct"),
        default="moves",
        help="moves = PlacementEnv micro-moves; kct = KctPlacementEnv (Phase 2)",
    )
    parser.add_argument(
        "--kct-backend",
        choices=("cmaes", "mock"),
        default="cmaes",
        help="kct only: cmaes = real refine; mock = fast smoke (no subprocess)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Checkpoint path for --algo ppo (required for ppo)",
    )
    parser.add_argument(
        "--resume",
        type=Path,
        default=None,
        help="Load this zip and continue training toward --steps",
    )
    parser.add_argument(
        "--checkpoint-freq",
        type=int,
        default=5_000,
        help="Save zip every N env steps (default 5000) so reboot loses at most N steps",
    )
    parser.add_argument(
        "--metrics-json",
        type=Path,
        default=None,
        help="Write metrics JSON (steps/s, elapsed, …)",
    )
    args = parser.parse_args(argv)

    pcb_paths = _resolve_pcb_paths(args.pcb, args.pcb_dir, args.pcb_list)
    max_ep = args.max_episode_steps
    if max_ep is None:
        max_ep = 2 if args.env == "kct" else 32

    # Default checkpoint path for kct PPO
    if args.algo == "ppo" and args.out is None:
        args.out = Path(
            "models/placement_ppo_kct_v1.zip"
            if args.env == "kct"
            else "models/placement_ppo_v2.zip"
        )

    print(
        json.dumps(
            {
                "n_boards": len(pcb_paths),
                "boards": [str(p) for p in pcb_paths],
                "env": args.env,
                "kct_backend": args.kct_backend if args.env == "kct" else None,
                "max_episode_steps": max_ep,
            },
            indent=2,
        ),
        flush=True,
    )

    env = _make_env(
        env_kind=args.env,
        pcb_paths=pcb_paths,
        max_episode_steps=max_ep,
        board_width=args.board_width,
        board_height=args.board_height,
        kct_backend=args.kct_backend,
    )

    try:
        if args.algo == "ppo":
            # kct+cmaes: each step is seconds — smaller rollouts
            n_steps = 16 if args.env == "kct" and args.kct_backend == "cmaes" else None
            metrics = _ppo_train(
                env,
                args.steps,
                args.out,
                resume=args.resume,
                checkpoint_freq=args.checkpoint_freq,
                n_steps=n_steps,
            )
        else:
            metrics = _random_smoke(env, args.steps)
    finally:
        close = getattr(env, "close", None)
        if callable(close):
            close()

    metrics["n_dataset_boards"] = len(pcb_paths)
    metrics["dataset_boards"] = [str(p) for p in pcb_paths]
    metrics["env"] = args.env
    metrics["kct_backend"] = args.kct_backend if args.env == "kct" else None
    metrics["max_episode_steps"] = max_ep
    print(json.dumps(metrics, indent=2))
    if args.metrics_json:
        args.metrics_json.parent.mkdir(parents=True, exist_ok=True)
        args.metrics_json.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
