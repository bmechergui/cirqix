#!/usr/bin/env python3
"""Offline PPO train / smoke for RL routing (LED fixture).

Example::

    cd services/kicad
    python -m tools.rl.routing.train_routing \\
      --pcb examples/led-blinker-full-pipeline/output/5_placed.kicad_pcb \\
      --algo random --steps 2000

    python -m tools.rl.routing.train_routing \\
      --pcb examples/led-blinker-full-pipeline/output/5_placed.kicad_pcb \\
      --algo ppo --steps 50000 \\
      --out models/routing_ppo_v1.zip \\
      --metrics-json tmp/rl_routing_v1_metrics.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[3]
_KT_SRC = _SERVICE_ROOT / "kicad-tools" / "src"
for _p in (str(_SERVICE_ROOT), str(_KT_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tools.rl.routing.env import RoutingEnv, _HAS_GYM  # noqa: E402
from tools.rl.routing.kct_env import FrRoutingEnv, KctRoutingEnv  # noqa: E402
from tools.rl.routing.manager_env import ManagerRoutingEnv  # noqa: E402


def _mock_route_fn(pcb_bytes: bytes, action: int) -> tuple[bytes, int, str]:
    """Fast backend — no kct/FR subprocess. Improves % slightly with action 0."""
    del action
    # Pretend partial progress so PPO sees non-zero reward occasionally
    return pcb_bytes, 10, "mock"


def _parse_net_ids(raw: str | None) -> list[int] | None:
    if raw is None or not str(raw).strip():
        return None
    out: list[int] = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        out.append(int(part))
    return out or None


def _make_route_env(
    *,
    env_kind: str,
    pcb: Path,
    max_episode_steps: int,
    resolution_mm: float,
    net: str | None,
    seed: int,
    kct_backend: str,
    net_ids: list[int] | None = None,
    manager_backend: str = "mock",
):
    if env_kind == "grid":
        return RoutingEnv(
            pcb,
            net_name=net,
            resolution_mm=resolution_mm,
            max_steps=max_episode_steps,
            seed=seed,
        )
    if env_kind == "manager":
        # Dreamer/PPO-transition env: net + strategy actions
        backend = "mock" if kct_backend == "mock" else manager_backend
        return ManagerRoutingEnv(
            pcb,
            net_ids=net_ids,
            backend=backend,
            max_steps=max_episode_steps,
            seed=seed,
        )
    route_fn = _mock_route_fn if kct_backend == "mock" else None
    if env_kind == "kct":
        return KctRoutingEnv(
            pcb_path=pcb,
            route_fn=route_fn,
            max_steps=max_episode_steps,
            seed=seed,
        )
    if env_kind == "fr":
        return FrRoutingEnv(
            pcb_path=pcb,
            route_fn=route_fn,
            max_steps=max_episode_steps,
            seed=seed,
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


def _random_smoke(env, steps: int) -> dict:
    import numpy as np

    obs, info = env.reset()
    t0 = time.perf_counter()
    total_reward = 0.0
    successes = 0
    episodes = 0
    for _ in range(steps):
        if _HAS_GYM and hasattr(env, "action_space"):
            action = int(env.action_space.sample())
        else:
            action = int(np.random.randint(0, 11))
        obs, reward, term, trunc, info = env.step(action)
        total_reward += float(reward)
        if term or trunc:
            episodes += 1
            if info.get("success"):
                successes += 1
            obs, info = env.reset()
    elapsed = time.perf_counter() - t0
    return {
        "mode": "random_smoke",
        "steps": steps,
        "elapsed_s": elapsed,
        "steps_per_s": steps / elapsed if elapsed > 0 else 0.0,
        "total_reward": total_reward,
        "episodes": episodes,
        "successes": successes,
        "has_gymnasium": _HAS_GYM,
    }


def _ppo_train(
    env,
    steps: int,
    out: Path,
    *,
    resume: Path | None = None,
    checkpoint_freq: int = 5_000,
    n_steps: int | None = None,
) -> dict:
    try:
        from stable_baselines3 import PPO
        from stable_baselines3.common.callbacks import BaseCallback
    except ImportError as exc:
        raise SystemExit(
            "stable-baselines3 required for --algo ppo "
            f"({exc})"
        ) from exc

    if not _HAS_GYM:
        raise SystemExit("gymnasium required for PPO")

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ckpt_dir = out.parent / f"{out.stem}_ckpts"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    class _SaveProgressCallback(BaseCallback):
        def __init__(self, save_path: Path, target: int, freq: int):
            super().__init__()
            self.save_path = save_path
            self.target = target
            self.freq = max(1, int(freq))
            self._last = 0

        def _on_step(self) -> bool:
            ts = int(self.num_timesteps)
            if ts - self._last >= self.freq:
                self._last = ts
                self.model.save(str(self.save_path))
                mid = ckpt_dir / f"{out.stem}_ts{ts}.zip"
                self.model.save(str(mid))
                _write_progress(
                    self.save_path, timesteps=ts, target=self.target, status="running"
                )
                print(f"[checkpoint] timesteps={ts}/{self.target} → {self.save_path}", flush=True)
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
    if resume is not None and not resume_path.is_file():
        raise SystemExit(f"error: --resume not found: {resume_path}")

    if resume_path is None and out.is_file():
        prog_file = _progress_path(out)
        if prog_file.is_file():
            try:
                prog = json.loads(prog_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                prog = None
            if prog and prog.get("status") != "completed":
                done = int(prog.get("timesteps") or 0)
                if 0 < done < steps:
                    resume_path = out
                    print(
                        f"[auto-resume] timesteps={done}/{steps}",
                        flush=True,
                    )

    t0 = time.perf_counter()
    already = 0

    if resume_path is not None:
        print(f"[resume] loading {resume_path}", flush=True)
        model = PPO.load(str(resume_path), env=env)
        already = int(getattr(model, "num_timesteps", 0) or 0)
        remaining = max(0, steps - already)
        if remaining == 0:
            _write_progress(out, timesteps=already, target=steps, status="completed")
            return {
                "mode": "ppo",
                "steps": steps,
                "already": already,
                "trained_this_run": 0,
                "status": "already_complete",
                "checkpoint": str(out),
            }
        cb = _SaveProgressCallback(out, target=steps, freq=checkpoint_freq)
        try:
            model.learn(
                total_timesteps=remaining,
                reset_num_timesteps=False,
                callback=cb,
            )
        except KeyboardInterrupt:
            model.save(str(out))
            ts = int(getattr(model, "num_timesteps", already) or already)
            _write_progress(out, timesteps=ts, target=steps, status="interrupted")
            print(f"[interrupt] saved at {ts}", flush=True)
            raise SystemExit(130) from None
    else:
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
        cb = _SaveProgressCallback(out, target=steps, freq=checkpoint_freq)
        try:
            model.learn(total_timesteps=steps, callback=cb)
        except KeyboardInterrupt:
            model.save(str(out))
            ts = int(getattr(model, "num_timesteps", 0) or 0)
            _write_progress(out, timesteps=ts, target=steps, status="interrupted")
            print(f"[interrupt] saved at {ts}", flush=True)
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
        "status": "completed",
        "has_gymnasium": True,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="RL routing train / smoke")
    p.add_argument(
        "--pcb",
        type=Path,
        default=Path("examples/led-blinker-full-pipeline/output/5_placed.kicad_pcb"),
        help="Placed .kicad_pcb (default: LED 5_placed)",
    )
    p.add_argument("--steps", type=int, default=10_000)
    p.add_argument("--algo", choices=("random", "ppo"), default="random")
    p.add_argument("--resolution-mm", type=float, default=0.5)
    p.add_argument(
        "--max-episode-steps",
        type=int,
        default=None,
        help="Default: 128 grid, 2 kct/fr, 32 manager",
    )
    p.add_argument(
        "--env",
        choices=("grid", "kct", "fr", "manager"),
        default="grid",
        help="grid|kct|fr=legacy; manager=net+strategy Dreamer/PPO-transition env",
    )
    p.add_argument(
        "--kct-backend",
        choices=("real", "mock", "kct_net", "kct_full"),
        default="real",
        help=(
            "kct/fr: real vs mock fn; manager: mock | kct_net (per-net --nets) | "
            "kct_full (full-board proxy). 'real' → kct_net for manager"
        ),
    )
    p.add_argument(
        "--net-ids",
        type=str,
        default=None,
        help="manager only: comma net ids e.g. 1,2,3,4,5,6 (default 1..6)",
    )
    p.add_argument("--net", type=str, default=None, help="Force single net name (grid only)")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--resume", type=Path, default=None)
    p.add_argument("--checkpoint-freq", type=int, default=5_000)
    p.add_argument("--metrics-json", type=Path, default=None)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args(argv)

    if not args.pcb.is_file():
        print(f"error: PCB not found: {args.pcb}", file=sys.stderr)
        return 2

    net_ids = _parse_net_ids(args.net_ids)
    max_ep = args.max_episode_steps
    if max_ep is None:
        if args.env == "grid":
            max_ep = 128
        elif args.env == "manager":
            max_ep = 32
        else:
            max_ep = 2

    if args.algo == "ppo" and args.out is None:
        args.out = Path(
            "models/routing_ppo_manager_v1.zip"
            if args.env == "manager"
            else "models/routing_ppo_kct_v1.zip"
            if args.env == "kct"
            else "models/routing_ppo_fr_v1.zip"
            if args.env == "fr"
            else "models/routing_ppo_v1.zip"
        )

    if args.kct_backend == "mock":
        manager_backend = "mock"
    elif args.kct_backend in ("kct_full",):
        manager_backend = "kct_full"
    else:
        # real | kct_net → true per-net kicad-tools
        manager_backend = "kct_net"
    env = _make_route_env(
        env_kind=args.env,
        pcb=args.pcb,
        max_episode_steps=max_ep,
        resolution_mm=args.resolution_mm,
        net=args.net,
        seed=args.seed,
        kct_backend=args.kct_backend,
        net_ids=net_ids,
        manager_backend=manager_backend,
    )

    meta: dict = {
        "pcb": str(args.pcb),
        "env": args.env,
        "kct_backend": args.kct_backend if args.env != "grid" else None,
        "manager_backend": manager_backend if args.env == "manager" else None,
        "net_ids": net_ids,
        "max_episode_steps": max_ep,
    }
    if args.env == "grid" and hasattr(env, "obs_dim"):
        meta.update(
            {
                "obs_dim": env.obs_dim,
                "nets": list(env.board.nets.keys()),
                "grid": [
                    env.board.n_layers,
                    env.board.height_cells,
                    env.board.width_cells,
                ],
                "resolution_mm": args.resolution_mm,
            }
        )
    print(json.dumps(meta, indent=2), flush=True)

    try:
        if args.algo == "ppo":
            if args.env == "manager":
                n_steps = 256 if args.kct_backend == "mock" else 16
            elif args.env != "grid" and args.kct_backend == "real":
                n_steps = 16
            else:
                n_steps = None
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

    metrics["pcb"] = str(args.pcb)
    metrics["env"] = args.env
    metrics["kct_backend"] = args.kct_backend if args.env != "grid" else None
    metrics["manager_backend"] = manager_backend if args.env == "manager" else None
    print(json.dumps(metrics, indent=2))
    if args.metrics_json:
        args.metrics_json.parent.mkdir(parents=True, exist_ok=True)
        args.metrics_json.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
