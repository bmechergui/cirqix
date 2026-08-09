#!/usr/bin/env python3
"""Lab end-to-end RL pipeline (Phases 2–5) — best-of + hard gate.

Does **not** enable production RL. Exit code is driven by the fail-closed
hard gate after routing (unless ``--skip-route``).

Flags (env or CLI)::

  RL_PLACE_ALGO=off|ppo|dreamer
  RL_ROUTE_ALGO=off|ppo|dreamer
  RL_ROUTE_FALLBACK=off|ppo_fr|fr_only

Example::

    cd services/kicad
    python -m tools.rl.run_phase_pipeline \\
      --pcb examples/led-blinker-full-pipeline/output/5_placed.kicad_pcb \\
      --out-dir tmp/rl_pipeline_run \\
      --out-json tmp/rl_pipeline_run.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_KT_SRC = _SERVICE_ROOT / "kicad-tools" / "src"
for _p in (str(_SERVICE_ROOT), str(_KT_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _best_of_route(a: dict, b: dict) -> dict:
    """Prefer higher routed_percent; tie → prefer arm marked preferred."""
    pa = int(a.get("routed_percent") or 0)
    pb = int(b.get("routed_percent") or 0)
    if pa > pb:
        return {**a, "selected": True, "reason": "higher_pct"}
    if pb > pa:
        return {**b, "selected": True, "reason": "higher_pct"}
    if a.get("preferred"):
        return {**a, "selected": True, "reason": "tie_prefer_kct"}
    if b.get("preferred"):
        return {**b, "selected": True, "reason": "tie_prefer_kct"}
    return {**a, "selected": True, "reason": "tie_first"}


def _run_place_ppo(pcb: Path, model: Path, out_pcb: Path) -> dict:
    from stable_baselines3 import PPO

    from tools.rl.placement.kct_env import KctPlacementEnv

    env = KctPlacementEnv(pcb_path=pcb, max_steps=2)
    try:
        model_ppo = PPO.load(str(model), env=env)
        obs, info = env.reset()
        total_r = 0.0
        for _ in range(2):
            action, _ = model_ppo.predict(obs, deterministic=True)
            obs, reward, term, trunc, info = env.step(action)
            total_r += float(reward)
            if term or trunc:
                break
        assert env.work_pcb_path is not None
        shutil.copy2(env.work_pcb_path, out_pcb)
        return {
            "ok": True,
            "algo": "ppo",
            "fom": info.get("fom_score"),
            "error_conflicts": info.get("error_conflicts"),
            "total_reward": total_r,
            "board_out": str(out_pcb),
        }
    except Exception as exc:
        shutil.copy2(pcb, out_pcb)
        return {
            "ok": False,
            "algo": "ppo",
            "error": str(exc),
            "board_out": str(out_pcb),
            "fallback": "input_pcb",
        }
    finally:
        env.close()


def _run_route_kct(pcb: Path, out_pcb: Path, timeout_s: int) -> dict:
    from tools.kct_route import route_kct

    t0 = time.perf_counter()
    try:
        routed, pct, analysis = route_kct(pcb.read_bytes(), timeout_s=timeout_s)
        out_pcb.write_bytes(routed)
        return {
            "ok": True,
            "arm": "kct",
            "preferred": True,
            "routed_percent": int(pct),
            "elapsed_s": time.perf_counter() - t0,
            "board_out": str(out_pcb),
            "analysis_preview": (analysis or "")[:200],
        }
    except Exception as exc:
        shutil.copy2(pcb, out_pcb)
        return {
            "ok": False,
            "arm": "kct",
            "preferred": True,
            "routed_percent": 0,
            "elapsed_s": time.perf_counter() - t0,
            "error": str(exc),
            "board_out": str(out_pcb),
        }


def _run_route_ppo_kct(pcb: Path, model: Path, out_pcb: Path) -> dict:
    from stable_baselines3 import PPO

    from tools.rl.routing.kct_env import KctRoutingEnv

    env = KctRoutingEnv(pcb_path=pcb, max_steps=2)
    try:
        m = PPO.load(str(model), env=env)
        obs, info = env.reset()
        total_r = 0.0
        for _ in range(2):
            action, _ = m.predict(obs, deterministic=True)
            obs, reward, term, trunc, info = env.step(action)
            total_r += float(reward)
            if term or trunc:
                break
        assert env.work_pcb_path is not None
        shutil.copy2(env.work_pcb_path, out_pcb)
        return {
            "ok": True,
            "arm": "ppo_kct",
            "preferred": False,
            "routed_percent": int(info.get("routed_percent") or 0),
            "total_reward": total_r,
            "board_out": str(out_pcb),
        }
    except Exception as exc:
        shutil.copy2(pcb, out_pcb)
        return {
            "ok": False,
            "arm": "ppo_kct",
            "preferred": False,
            "routed_percent": 0,
            "error": str(exc),
            "board_out": str(out_pcb),
        }
    finally:
        env.close()


def _run_fr_fallback(
    pcb: Path,
    out_pcb: Path,
    *,
    route_fn=None,
    timeout_s: int = 120,
) -> dict:
    """Secondary route arm — **kicad-tools only** (never pcbnew / FreeRouting).

    Historical name ``fr`` kept for report keys; implementation is
    ``route_kct(..., vcc_as_traces=False)`` (alternate power-planes policy).

    Injectable ``route_fn`` for tests::
        route_fn(pcb_bytes, timeout_s=...) -> (routed_bytes, pct, analysis)
    """
    t0 = time.perf_counter()
    try:
        if route_fn is None:
            from tools.kct_route import route_kct

            def _kct_alt(pcb_bytes: bytes, timeout_s: int = 120):
                return route_kct(
                    pcb_bytes, timeout_s=timeout_s, vcc_as_traces=False
                )

            route_fn = _kct_alt

        routed, pct, analysis = route_fn(
            pcb.read_bytes(), timeout_s=timeout_s
        )
        out_pcb.write_bytes(routed)
        return {
            "ok": True,
            "arm": "kct_alt",
            "preferred": False,
            "routed_percent": int(pct),
            "elapsed_s": time.perf_counter() - t0,
            "board_out": str(out_pcb),
            "analysis_preview": (analysis or "")[:200],
            "note": "kicad-tools route_kct vcc_as_traces=False (no pcbnew/FreeRouting)",
        }
    except Exception as exc:
        shutil.copy2(pcb, out_pcb)
        return {
            "ok": False,
            "arm": "kct_alt",
            "preferred": False,
            "routed_percent": 0,
            "elapsed_s": time.perf_counter() - t0,
            "error": str(exc),
            "board_out": str(out_pcb),
        }


def _count_placement_errors(pcb_path: Path) -> int | None:
    """PlacementAnalyzer ERROR count; None if kicad-tools unavailable."""
    try:
        from kicad_tools.schema.pcb import PCB

        from tools.rl.placement.conflicts import count_error_conflicts

        pcb = PCB.load(str(pcb_path))
        return int(count_error_conflicts(pcb, pcb_path=pcb_path))
    except Exception:
        return None


def try_kicad_cli_drc(pcb_path: Path) -> tuple[int | None, int | None, str | None]:
    """Run ``kicad-cli pcb drc --format json`` if available.

    Returns ``(drc_error_count, unconnected_items, error_message)``.
    Counts are ``None`` when DRC was not measured (fail-closed for hard gate).
    """
    kicad_cli = shutil.which("kicad-cli")
    if kicad_cli is None:
        # Common Windows install path (optional)
        for candidate in (
            Path(r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe"),
            Path(r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe"),
        ):
            if candidate.is_file():
                kicad_cli = str(candidate)
                break
    if kicad_cli is None:
        return None, None, "kicad-cli not found"

    out_json = pcb_path.with_suffix(pcb_path.suffix + ".drc.json")
    try:
        proc = subprocess.run(
            [
                kicad_cli,
                "pcb",
                "drc",
                "--format",
                "json",
                "-o",
                str(out_json),
                str(pcb_path),
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, None, str(exc)

    if not out_json.is_file():
        err = (proc.stderr or proc.stdout or f"rc={proc.returncode}")[:300]
        return None, None, f"kicad-cli produced no report: {err}"

    try:
        raw = json.loads(out_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, None, f"drc json parse: {exc}"

    # kicad-cli json: violations + unconnected_items sections
    violations = raw.get("violations") or []
    unconnected = raw.get("unconnected_items") or []
    # Count non-warning errors when severity present
    n_err = 0
    for v in violations:
        sev = str(v.get("severity") or v.get("type") or "").lower()
        if "warning" in sev:
            continue
        n_err += 1
    if not violations and isinstance(raw.get("errors"), list):
        n_err = len(raw["errors"])
    n_unconn = len(unconnected) if isinstance(unconnected, list) else 0
    return n_err, n_unconn, None


def evaluate_final_hard_gate(
    *,
    final_pcb: Path,
    routed_percent: int | float | None,
    baseline_arm: dict[str, Any] | None,
    require_drc: bool = True,
    require_unconnected: bool = True,
) -> dict[str, Any]:
    """Measure board + run fail-closed hard gate + baseline compare."""
    from tools.rl.quality_gate import compare_vs_baseline, evaluate_board_hard_gate

    error_conflicts = _count_placement_errors(final_pcb)
    drc_n, unconn_n, drc_msg = try_kicad_cli_drc(final_pcb)

    hard = evaluate_board_hard_gate(
        error_conflicts=error_conflicts,
        routed_percent=routed_percent,
        unrouted_count=None,
        drc_error_count=drc_n,
        unconnected_items=unconn_n,
        require_drc=require_drc,
        require_unconnected=require_unconnected,
        require_unrouted_count=False,
    )

    baseline_cmp: dict[str, Any] | None = None
    if baseline_arm is not None:
        baseline_cmp = compare_vs_baseline(
            routed_percent=float(routed_percent or 0),
            baseline_routed_percent=float(baseline_arm.get("routed_percent") or 0),
            error_conflicts=int(error_conflicts or 0),
            baseline_error_conflicts=0,
        )

    return {
        "hard_gate": hard,
        "measurements": {
            "error_conflicts": error_conflicts,
            "routed_percent": routed_percent,
            "drc_error_count": drc_n,
            "unconnected_items": unconn_n,
            "drc_tool_error": drc_msg,
        },
        "baseline_compare": baseline_cmp,
        "passed": bool(hard.get("passed")),
        "verdict": hard.get("verdict"),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="RL lab pipeline Phases 2–5 (no prod flag)")
    p.add_argument("--pcb", type=Path, required=True, help="Placed .kicad_pcb input")
    p.add_argument("--out-dir", type=Path, default=Path("tmp/rl_pipeline_run"))
    p.add_argument("--out-json", type=Path, default=None)
    p.add_argument("--place-model", type=Path, default=None)
    p.add_argument("--route-model", type=Path, default=None)
    p.add_argument(
        "--place-algo",
        choices=("off", "ppo", "dreamer"),
        default=os.environ.get("RL_PLACE_ALGO", "off"),
    )
    p.add_argument(
        "--route-algo",
        choices=("off", "ppo", "dreamer"),
        default=os.environ.get("RL_ROUTE_ALGO", "off"),
    )
    p.add_argument(
        "--route-fallback",
        choices=("off", "ppo_fr", "fr_only"),
        default=os.environ.get("RL_ROUTE_FALLBACK", "fr_only"),
    )
    p.add_argument("--route-timeout-s", type=int, default=120)
    p.add_argument(
        "--skip-route",
        action="store_true",
        help="Only place arms (faster lab); hard gate not applied",
    )
    p.add_argument(
        "--skip-hard-gate",
        action="store_true",
        help="Do not run hard gate (debug only; not for GO claims)",
    )
    args = p.parse_args(argv)

    if not args.pcb.is_file():
        print(f"error: PCB not found: {args.pcb}", file=sys.stderr)
        return 2

    notes: list[str] = []
    if args.place_algo == "dreamer":
        notes.append("RL_PLACE_ALGO=dreamer → off (JAX/DreamerV3 not wired)")
        args.place_algo = "off"
    if args.route_algo == "dreamer":
        notes.append("RL_ROUTE_ALGO=dreamer → off (JAX/DreamerV3 not wired)")
        args.route_algo = "off"
    if args.route_fallback == "ppo_fr":
        notes.append("ppo_fr not trained → using fr_only if needed")
        args.route_fallback = "fr_only"

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "phase": "lab_pipeline_2_to_5",
        "input": str(args.pcb),
        "place_algo": args.place_algo,
        "route_algo": args.route_algo,
        "route_fallback": args.route_fallback,
        "notes": notes,
        "prod_flag": "OFF",
        "arms": {},
    }

    placed = out_dir / "01_placed.kicad_pcb"
    if args.place_algo == "ppo" and args.place_model and args.place_model.is_file():
        report["arms"]["place_rl"] = _run_place_ppo(args.pcb, args.place_model, placed)
    else:
        shutil.copy2(args.pcb, placed)
        report["arms"]["place"] = {
            "ok": True,
            "algo": "off",
            "board_out": str(placed),
            "note": "input used as placed board (hybrid/CMA-ES expected upstream)",
        }

    if args.skip_route:
        report["skipped_route"] = True
        report["final_board"] = str(placed)
        report["hard_gate"] = {
            "skipped": True,
            "reason": "--skip-route: hard gate not applied",
            "passed": False,
            "note": "Not deployment authority",
        }
        report["phase6_ready"] = False
        _write(report, args.out_json)
        print(json.dumps(report, indent=2))
        return 0

    kct_out = out_dir / "02_kct.kicad_pcb"
    arm_kct = _run_route_kct(placed, kct_out, args.route_timeout_s)
    report["arms"]["route_kct"] = arm_kct
    candidates = [arm_kct]

    if args.route_algo == "ppo" and args.route_model and args.route_model.is_file():
        ppo_out = out_dir / "02_ppo_kct.kicad_pcb"
        arm_ppo = _run_route_ppo_kct(placed, args.route_model, ppo_out)
        report["arms"]["route_ppo_kct"] = arm_ppo
        candidates.append(arm_ppo)

    winner = candidates[0]
    for c in candidates[1:]:
        winner = _best_of_route(winner, c)
    report["after_principal"] = {
        "routed_percent": winner.get("routed_percent"),
        "board_out": winner.get("board_out"),
        "arm": winner.get("arm"),
    }

    final_board = Path(str(winner["board_out"]))
    pct = int(winner.get("routed_percent") or 0)

    if pct < 100 and args.route_fallback != "off":
        fr_out = out_dir / "03_fr.kicad_pcb"
        arm_fr = _run_fr_fallback(final_board, fr_out)
        report["arms"]["route_fr"] = arm_fr
        if arm_fr.get("ok") and int(arm_fr.get("routed_percent") or 0) >= pct:
            winner = _best_of_route(
                {**winner, "preferred": True},
                {**arm_fr, "preferred": False},
            )
            final_board = Path(str(winner["board_out"]))
            pct = int(winner.get("routed_percent") or 0)

    final_copy = out_dir / "99_final.kicad_pcb"
    shutil.copy2(final_board, final_copy)
    report["final"] = {
        "board_out": str(final_copy),
        "routed_percent": pct,
        "arm": winner.get("arm"),
        "reason": winner.get("reason"),
    }

    if args.skip_hard_gate:
        report["hard_gate"] = {
            "skipped": True,
            "reason": "--skip-hard-gate",
            "passed": False,
            "note": "Not deployment authority",
        }
        report["phase6_ready"] = False
        _write(report, args.out_json)
        print(json.dumps(report, indent=2))
        return 0 if arm_kct.get("ok") or pct > 0 else 3

    gate_report = evaluate_final_hard_gate(
        final_pcb=final_copy,
        routed_percent=pct,
        baseline_arm=arm_kct,
    )
    report["gate"] = gate_report
    report["hard_gate"] = gate_report["hard_gate"]
    report["phase6_ready"] = bool(gate_report.get("passed"))
    report["phase6_note"] = (
        "phase6_ready True only if hard gate passed (DRC+unconnected measured "
        "and clean, route 100%, error_conflicts=0). Prod flag still OFF by policy."
        if gate_report.get("passed")
        else "Hard gate NO-GO — not deployment eligible. See quality_gate.py."
    )

    _write(report, args.out_json)
    print(json.dumps(report, indent=2))
    # Exit: hard gate is authority (not mere kct ok / pct > 0)
    return 0 if gate_report.get("passed") else 3


def _write(report: dict, path: Path | None) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {path}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
