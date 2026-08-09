#!/usr/bin/env python3
"""Lab eval: manager PPO + greedy kct_net on a placed board + hard gate.

Does **not** flip prod RL. Exit 0 only if hard gate passes on the best arm
(with DRC/unconnected measured when kicad-cli is available).

Example::

    cd services/kicad
    python -m tools.rl.routing.eval_manager_kct_net \\
      --pcb examples/led-blinker-full-pipeline/output/5_placed_clean.kicad_pcb \\
      --model models/routing_ppo_manager_kct_net_v1.zip \\
      --out-dir tmp/rl_mgr_kct_net_led \\
      --out-json tmp/rl_mgr_kct_net_led/report.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable

_SERVICE_ROOT = Path(__file__).resolve().parents[3]
_KT_SRC = _SERVICE_ROOT / "kicad-tools" / "src"
for _p in (str(_SERVICE_ROOT), str(_KT_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tools.rl.routing.manager_env import (  # noqa: E402
    ManagerRoutingEnv,
    decode_manager_action,
)
from tools.rl.routing.route_net_api import (  # noqa: E402
    MockRouterState,
    estimate_routed_percent_from_pcb,
    multi_pad_net_ids,
    route_net,
    strategy_from_index,
)

# Default strategy for greedy (maps to vcc_as_traces=True via strategy_uses_vcc_traces)
GREEDY_STRATEGY = "balanced"
DEFAULT_STRATEGY_IDX = 6  # balanced in STRATEGIES


def ensure_place_clean(pcb_path: Path, out_path: Path) -> dict[str, Any]:
    """Copy board; if placement ERRORs remain, run production conflict fixer."""
    from kicad_tools.schema.pcb import PCB

    from tools.placement import _connector_refs, _resolve_remaining_conflicts
    from tools.rl.placement.conflicts import count_error_conflicts

    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pcb_path, out_path)
    pcb = PCB.load(str(out_path))
    before = int(count_error_conflicts(pcb, pcb_path=out_path))
    fixed = False
    if before > 0:
        anchored = _connector_refs(pcb)
        _resolve_remaining_conflicts(out_path, list(anchored))
        fixed = True
        pcb = PCB.load(str(out_path))
    after = int(count_error_conflicts(pcb, pcb_path=out_path))
    return {
        "board_out": str(out_path),
        "error_conflicts_before": before,
        "error_conflicts_after": after,
        "fixed": fixed,
        "ok": after == 0,
    }


def run_full_kct(
    pcb_path: Path,
    out_path: Path,
    *,
    timeout_s: int = 120,
    route_fn: Callable[..., tuple[bytes, int, str]] | None = None,
) -> dict[str, Any]:
    """Baseline: full-board ``route_kct``."""
    from tools.kct_route import route_kct

    fn = route_fn or route_kct
    raw = pcb_path.read_bytes()
    t0 = time.perf_counter()
    try:
        routed, pct, analysis = fn(raw, timeout_s=timeout_s)
        err = None
        ok = True
    except Exception as exc:  # noqa: BLE001 — lab report
        elapsed = time.perf_counter() - t0
        shutil.copy2(pcb_path, out_path)
        return {
            "arm": "full_kct",
            "ok": False,
            "error": str(exc),
            "routed_percent": 0,
            "elapsed_s": elapsed,
            "board_out": str(out_path),
        }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(routed)
    return {
        "arm": "full_kct",
        "ok": ok,
        "routed_percent": int(pct),
        "elapsed_s": time.perf_counter() - t0,
        "board_out": str(out_path),
        "analysis_preview": (analysis or "")[:300],
        "estimated_pct_from_pcb": estimate_routed_percent_from_pcb(routed),
    }


def run_greedy_kct_net(
    pcb_path: Path,
    out_path: Path,
    *,
    strategy: str = GREEDY_STRATEGY,
    timeout_s: int = 120,
    route_net_fn: Callable[..., tuple[bytes, Any]] | None = None,
) -> dict[str, Any]:
    """Route each multi-pad net once with fixed strategy (no PPO)."""
    fn = route_net_fn or route_net
    pcb_bytes = pcb_path.read_bytes()
    net_ids = multi_pad_net_ids(pcb_bytes)
    state = MockRouterState.from_net_ids(net_ids)
    steps: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    for nid in net_ids:
        if nid in state.routed:
            continue
        try:
            pcb_bytes, metrics = fn(
                pcb_bytes,
                nid,
                strategy,
                backend="kct_net",
                state=state,
                timeout_s=timeout_s,
            )
            steps.append(metrics.as_dict() if hasattr(metrics, "as_dict") else dict(metrics))
        except Exception as exc:  # noqa: BLE001
            steps.append({"net_id": nid, "error": str(exc), "success": False})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(pcb_bytes)
    return {
        "arm": "greedy_kct_net",
        "ok": True,
        "strategy": strategy,
        "net_ids": net_ids,
        "manager_routed_percent": state.routed_percent,
        "manager_unrouted_count": state.unrouted_count,
        "nets_routed": state.nets_routed,
        "nets_total": state.nets_total,
        "routed_percent": estimate_routed_percent_from_pcb(pcb_bytes),
        "elapsed_s": time.perf_counter() - t0,
        "board_out": str(out_path),
        "steps": steps,
    }


def run_ppo_manager_kct_net(
    pcb_path: Path,
    out_path: Path,
    model_path: Path,
    *,
    max_steps: int = 32,
    seed: int = 0,
    timeout_s: int = 120,
    backend: str = "kct_net",
    load_ppo: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Roll out a trained SB3 PPO manager on ``ManagerRoutingEnv``."""
    t0 = time.perf_counter()
    if not model_path.is_file():
        return {
            "arm": "ppo_manager_kct_net",
            "ok": False,
            "error": f"model not found: {model_path}",
            "routed_percent": 0,
            "elapsed_s": 0.0,
            "board_out": None,
        }

    work_dir = out_path.parent / f"{out_path.stem}_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    env = ManagerRoutingEnv(
        pcb_path,
        backend=backend,
        max_steps=max_steps,
        seed=seed,
        work_dir=work_dir,
    )
    try:
        if load_ppo is not None:
            model = load_ppo(str(model_path))
        else:
            from stable_baselines3 import PPO

            model = PPO.load(str(model_path), env=env)

        obs, info = env.reset(seed=seed)
        actions: list[dict[str, Any]] = []
        terminated = truncated = False
        while not (terminated or truncated):
            action, _ = model.predict(obs, deterministic=True)
            a = int(action)
            net_slot, strat_idx, is_stop = decode_manager_action(
                a, n_slots=env.n_slots
            )
            obs, reward, terminated, truncated, step_info = env.step(a)
            actions.append(
                {
                    "action": a,
                    "stop": is_stop or a == env.stop_action,
                    "net_slot": net_slot,
                    "strategy": (
                        None if is_stop or strat_idx is None else strategy_from_index(strat_idx)
                    ),
                    "reward": float(reward),
                    "routed_percent": step_info.get("routed_percent"),
                    "unrouted_count": step_info.get("unrouted_count"),
                }
            )
        # Final board from env work copy
        assert env._work_pcb is not None
        final_bytes = env._work_pcb.read_bytes()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(final_bytes)
        st = env._state
        return {
            "arm": "ppo_manager_kct_net",
            "ok": True,
            "model": str(model_path),
            "backend": backend,
            "manager_routed_percent": st.routed_percent if st else 0,
            "manager_unrouted_count": st.unrouted_count if st else 0,
            "nets_routed": st.nets_routed if st else 0,
            "nets_total": st.nets_total if st else 0,
            "routed_percent": estimate_routed_percent_from_pcb(final_bytes),
            "elapsed_s": time.perf_counter() - t0,
            "board_out": str(out_path),
            "n_actions": len(actions),
            "actions": actions,
            "reset_info": info,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "arm": "ppo_manager_kct_net",
            "ok": False,
            "error": str(exc),
            "model": str(model_path),
            "routed_percent": 0,
            "elapsed_s": time.perf_counter() - t0,
            "board_out": None,
        }
    finally:
        env.close()


def pick_best_arm(arms: list[dict[str, Any]]) -> dict[str, Any]:
    """Prefer higher routed_percent; ties prefer full_kct then greedy."""
    order = {"full_kct": 0, "greedy_kct_net": 1, "ppo_manager_kct_net": 2}

    def key(a: dict[str, Any]) -> tuple:
        ok = 1 if a.get("ok") and a.get("board_out") else 0
        pct = int(a.get("routed_percent") or 0)
        pref = -order.get(str(a.get("arm")), 9)
        return (ok, pct, pref)

    return max(arms, key=key)


def run_eval(
    *,
    pcb: Path,
    out_dir: Path,
    model: Path | None,
    timeout_s: int = 120,
    max_manager_steps: int = 32,
    skip_ppo: bool = False,
    skip_full_kct: bool = False,
    skip_greedy: bool = False,
    seed: int = 0,
) -> dict[str, Any]:
    """Full lab report: place clean check + arms + hard gate on winner."""
    from tools.rl.run_phase_pipeline import evaluate_final_hard_gate

    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "lab": "manager_ppo_kct_net_hard_gate",
        "input": str(pcb),
        "prod_flag": "OFF",
        "arms": {},
    }

    clean_path = out_dir / "00_place_clean.kicad_pcb"
    place = ensure_place_clean(pcb, clean_path)
    report["place"] = place
    if not place.get("ok"):
        report["hard_gate"] = {
            "passed": False,
            "reasons": [f"placement ERROR remains: {place.get('error_conflicts_after')}"],
            "verdict": "NO-GO — place not clean",
        }
        report["phase6_ready"] = False
        return report

    arms: list[dict[str, Any]] = []

    if not skip_full_kct:
        arm = run_full_kct(
            clean_path, out_dir / "01_full_kct.kicad_pcb", timeout_s=timeout_s
        )
        report["arms"]["full_kct"] = arm
        arms.append(arm)

    if not skip_greedy:
        arm = run_greedy_kct_net(
            clean_path,
            out_dir / "02_greedy_kct_net.kicad_pcb",
            timeout_s=timeout_s,
        )
        report["arms"]["greedy_kct_net"] = arm
        arms.append(arm)

    if not skip_ppo and model is not None:
        arm = run_ppo_manager_kct_net(
            clean_path,
            out_dir / "03_ppo_manager_kct_net.kicad_pcb",
            model,
            max_steps=max_manager_steps,
            seed=seed,
            timeout_s=timeout_s,
        )
        report["arms"]["ppo_manager_kct_net"] = arm
        arms.append(arm)
    elif not skip_ppo:
        report["arms"]["ppo_manager_kct_net"] = {
            "arm": "ppo_manager_kct_net",
            "ok": False,
            "error": "no --model provided",
            "routed_percent": 0,
        }

    if not arms:
        report["error"] = "no arms run"
        report["phase6_ready"] = False
        return report

    winner = pick_best_arm(arms)
    report["winner"] = {
        "arm": winner.get("arm"),
        "routed_percent": winner.get("routed_percent"),
        "board_out": winner.get("board_out"),
        "ok": winner.get("ok"),
    }

    final_board = Path(str(winner["board_out"]))
    final_copy = out_dir / "99_final.kicad_pcb"
    shutil.copy2(final_board, final_copy)
    pct = int(winner.get("routed_percent") or 0)

    gate = evaluate_final_hard_gate(
        final_pcb=final_copy,
        routed_percent=pct,
        baseline_arm=report["arms"].get("full_kct"),
    )
    report["gate"] = gate
    report["hard_gate"] = gate.get("hard_gate")
    report["measurements"] = gate.get("measurements")
    report["phase6_ready"] = bool(gate.get("passed"))
    report["phase6_note"] = (
        "Lab hard-gate GO only; prod RL flag remains OFF."
        if gate.get("passed")
        else "Hard gate NO-GO — not deployment eligible."
    )
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Lab: greedy + PPO manager kct_net on place-clean board + hard gate"
    )
    p.add_argument(
        "--pcb",
        type=Path,
        default=Path(
            "examples/led-blinker-full-pipeline/output/5_placed_clean.kicad_pcb"
        ),
    )
    p.add_argument(
        "--model",
        type=Path,
        default=Path("models/routing_ppo_manager_kct_net_v1.zip"),
    )
    p.add_argument("--out-dir", type=Path, default=Path("tmp/rl_mgr_kct_net_led"))
    p.add_argument("--out-json", type=Path, default=None)
    p.add_argument("--timeout-s", type=int, default=120)
    p.add_argument("--max-manager-steps", type=int, default=32)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--skip-ppo", action="store_true")
    p.add_argument("--skip-full-kct", action="store_true")
    p.add_argument("--skip-greedy", action="store_true")
    args = p.parse_args(argv)

    if not args.pcb.is_file():
        print(f"error: PCB not found: {args.pcb}", file=sys.stderr)
        return 2

    report = run_eval(
        pcb=args.pcb,
        out_dir=args.out_dir,
        model=None if args.skip_ppo else args.model,
        timeout_s=args.timeout_s,
        max_manager_steps=args.max_manager_steps,
        skip_ppo=args.skip_ppo,
        skip_full_kct=args.skip_full_kct,
        skip_greedy=args.skip_greedy,
        seed=args.seed,
    )
    out_json = args.out_json or (args.out_dir / "report.json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"wrote {out_json}", flush=True)
    return 0 if report.get("phase6_ready") else 3


if __name__ == "__main__":
    raise SystemExit(main())
