#!/usr/bin/env python3
"""Compare RL routing model vs production ``kct route`` on the same placed PCB.

Example::

    cd services/kicad
    python -m tools.rl.routing.eval_vs_kct \\
      --pcb examples/led-blinker-full-pipeline/output/5_placed.kicad_pcb \\
      --model models/routing_ppo_v1_smoke.zip \\
      --out-json tmp/rl_routing_vs_kct.json
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

from tools.kct_route import route_kct  # noqa: E402
from tools.rl.routing.actions import RouteAction  # noqa: E402
from tools.rl.routing.board_grid import DEFAULT_NET_ORDER  # noqa: E402
from tools.rl.routing.env import RoutingEnv  # noqa: E402
from tools.rl.routing.export import export_paths_to_pcb, path_cells_to_points  # noqa: E402


def _eval_kct(pcb_path: Path, out_path: Path, timeout_s: int) -> dict:
    raw = pcb_path.read_bytes()
    t0 = time.perf_counter()
    try:
        routed, pct, analysis = route_kct(raw, timeout_s=timeout_s)
        ok = True
        err = None
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "routed_percent": 0,
            "elapsed_s": time.perf_counter() - t0,
            "board_out": None,
        }
    elapsed = time.perf_counter() - t0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(routed)
    return {
        "ok": True,
        "routed_percent": int(pct),
        "elapsed_s": elapsed,
        "board_out": str(out_path),
        "failure_analysis_preview": (analysis or "")[:300],
        "error": err,
    }


def _run_rl_net(
    env: RoutingEnv,
    model,
    *,
    net_name: str,
    inference_steps: int,
    deterministic: bool,
) -> dict:
    """Run one net episode; return path + success."""
    # Force net by rebuilding env state after reset with forced net
    env._forced_net = net_name
    obs, info = env.reset()
    path = list(env._path)
    total_reward = 0.0
    success = False
    for _ in range(inference_steps):
        if model is None:
            # greedy-ish: prefer moves east/north then finish
            action = int(RouteAction.EAST)
        else:
            action, _ = model.predict(obs, deterministic=deterministic)
            action = int(action)
        obs, reward, term, trunc, step_info = env.step(action)
        total_reward += float(reward)
        path = list(env._path)
        if term or trunc:
            success = bool(step_info.get("success"))
            break
    points = path_cells_to_points(env.board, path)
    layer = "F.Cu" if env._layer == 0 else "B.Cu"
    return {
        "net": net_name,
        "success": success,
        "steps": env._steps,
        "total_reward": total_reward,
        "path_len": len(path),
        "points": points,
        "layer": layer,
        "net_id": env._net_id,
    }


def _eval_rl(
    pcb_path: Path,
    model_path: Path | None,
    *,
    resolution_mm: float,
    inference_steps: int,
    out_path: Path,
    nets: list[str] | None,
) -> dict:
    try:
        from stable_baselines3 import PPO
    except ImportError as exc:
        return {"ok": False, "error": f"stable-baselines3 required: {exc}"}

    model = None
    if model_path is not None:
        if not model_path.is_file():
            return {"ok": False, "error": f"model not found: {model_path}"}
        # Env for load shape
        env0 = RoutingEnv(
            pcb_path,
            resolution_mm=resolution_mm,
            max_steps=inference_steps,
            seed=0,
        )
        try:
            model = PPO.load(str(model_path), env=env0)
        except Exception as exc:
            return {"ok": False, "error": f"PPO.load failed: {exc}"}

    env = RoutingEnv(
        pcb_path,
        resolution_mm=resolution_mm,
        max_steps=inference_steps,
        seed=0,
    )
    # Nets with ≥2 pads
    multi = [
        n
        for n, t in env.board.nets.items()
        if len(t.pads) >= 2
    ]
    order = [n for n in (nets or list(DEFAULT_NET_ORDER)) if n in multi]
    for n in multi:
        if n not in order:
            order.append(n)

    t0 = time.perf_counter()
    net_results: list[dict] = []
    paths_export: list[dict] = []
    for net_name in order:
        r = _run_rl_net(
            env,
            model,
            net_name=net_name,
            inference_steps=inference_steps,
            deterministic=True,
        )
        net_results.append(
            {
                "net": r["net"],
                "success": r["success"],
                "steps": r["steps"],
                "total_reward": r["total_reward"],
                "path_len": r["path_len"],
            }
        )
        if len(r["points"]) >= 2:
            paths_export.append(
                {
                    "net_name": r["net"],
                    "net_id": r["net_id"],
                    "points": r["points"],
                    "layer": r["layer"],
                }
            )

    elapsed = time.perf_counter() - t0
    n_ok = sum(1 for r in net_results if r["success"])
    n_tot = len(net_results) or 1
    # Surrogate "routed percent" ≈ fraction of nets that reached target
    routed_proxy = int(round(100.0 * n_ok / n_tot))

    board_out = None
    export_error = None
    try:
        board_out = str(
            export_paths_to_pcb(pcb_path, paths_export, out_path, width_mm=0.25)
        )
    except Exception as exc:
        export_error = str(exc)

    return {
        "ok": True,
        "model": str(model_path) if model_path else None,
        "elapsed_s": elapsed,
        "n_nets": len(net_results),
        "n_nets_success": n_ok,
        "routed_percent_proxy": routed_proxy,
        "nets": net_results,
        "board_out": board_out,
        "export_error": export_error,
        "note": (
            "routed_percent_proxy = % nets où finish_net a réussi près de la cible "
            "(surrogate). Pas le même compteur que kct route tant que le DRC "
            "officiel n'est pas appliqué."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="RL routing vs kct route")
    p.add_argument(
        "--pcb",
        type=Path,
        default=Path("examples/led-blinker-full-pipeline/output/5_placed.kicad_pcb"),
    )
    p.add_argument(
        "--model",
        type=Path,
        default=Path("models/routing_ppo_v1_smoke.zip"),
    )
    p.add_argument("--timeout-s", type=int, default=120)
    p.add_argument("--resolution-mm", type=float, default=0.5)
    p.add_argument("--inference-steps", type=int, default=128)
    p.add_argument("--out-json", type=Path, default=Path("tmp/rl_routing_vs_kct.json"))
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("tmp/rl_routing_vs_kct_art"),
    )
    args = p.parse_args(argv)

    if not args.pcb.is_file():
        print(f"error: pcb not found: {args.pcb}", file=sys.stderr)
        return 2

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[1/2] kct route (baseline)…", flush=True)
    kct = _eval_kct(args.pcb, out_dir / "arm_kct_routed.kicad_pcb", args.timeout_s)
    print(
        f"  → kct routed_percent={kct.get('routed_percent')} "
        f"ok={kct.get('ok')} ({kct.get('elapsed_s', 0):.1f}s)",
        flush=True,
    )

    print("[2/2] RL routing (model)…", flush=True)
    model_path = args.model if args.model.is_file() else None
    if model_path is None:
        print(f"  warning: model missing {args.model} — random policy", flush=True)
    rl = _eval_rl(
        args.pcb,
        model_path,
        resolution_mm=args.resolution_mm,
        inference_steps=args.inference_steps,
        out_path=out_dir / "arm_rl_routed.kicad_pcb",
        nets=None,
    )
    print(
        f"  → RL proxy%={rl.get('routed_percent_proxy')} "
        f"nets_ok={rl.get('n_nets_success')}/{rl.get('n_nets')} "
        f"ok={rl.get('ok')} ({rl.get('elapsed_s', 0):.1f}s)",
        flush=True,
    )

    pct_k = int(kct.get("routed_percent") or 0)
    pct_r = int(rl.get("routed_percent_proxy") or 0)
    if pct_r > pct_k:
        winner = "rl"
    elif pct_k > pct_r:
        winner = "kct"
    else:
        winner = "tie"

    # Strict GO: RL proxy must reach 100 and match/beat kct, and kct ok
    gate = {
        "passed": bool(rl.get("ok"))
        and pct_r >= 100
        and pct_r >= pct_k
        and bool(kct.get("ok")),
        "winner": winner,
        "verdict": (
            "GO — RL proxy ≥ 100% et ≥ kct"
            if (pct_r >= 100 and pct_r >= pct_k and rl.get("ok"))
            else "NO-GO — garder kct route (RL pas encore au niveau)"
        ),
    }

    report = {
        "pcb": str(args.pcb),
        "model": str(args.model),
        "kct": kct,
        "rl": rl,
        "gate": gate,
        "comparison": {
            "kct_routed_percent": pct_k,
            "rl_routed_percent_proxy": pct_r,
            "delta": pct_r - pct_k,
            "winner": winner,
        },
    }
    print(json.dumps(report, indent=2))
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {args.out_json}", flush=True)
    return 0 if gate["passed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
