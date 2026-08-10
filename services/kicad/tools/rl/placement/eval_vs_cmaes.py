#!/usr/bin/env python3
"""Lab gate — compare PPO placement candidate vs CMA-ES.

Metrics (same FOM weights for both arms):
  - fom_score (compute_fom)
  - PlacementAnalyzer ERROR count (real overlaps / pad clearance)

Optional: routing / kicad-cli DRC remain Phase 6a step-8 extensions
(not required to fail a regressing model).

Example::

    python -m tools.rl.placement.eval_vs_cmaes \\
      --pcb examples/led-blinker-full-pipeline/output/5_placed.kicad_pcb \\
      --model models/placement_ppo_100k.zip \\
      --artifact-dir tmp/rl_vs_cmaes_art \\
      --out-json tmp/rl_vs_cmaes.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[3]
_KT_SRC = _SERVICE_ROOT / "kicad-tools" / "src"
for _p in (str(_SERVICE_ROOT), str(_KT_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kicad_tools.schema.pcb import PCB  # noqa: E402

from tools.placement import _connector_refs, _refine_with_cmaes  # noqa: E402
from tools.rl.placement.conflicts import count_error_conflicts  # noqa: E402
from tools.rl.placement.env import PlacementEnv  # noqa: E402
from tools.rl.placement.kct_env import KctPlacementEnv  # noqa: E402
from tools.rl.placement.reward import fom_score  # noqa: E402


def _copy_pcb(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def _metrics(pcb_path: Path) -> dict:
    pcb = PCB.load(str(pcb_path))
    return {
        "fom": fom_score(pcb, pcb_path=str(pcb_path)),
        "error_conflicts": count_error_conflicts(pcb, pcb_path=pcb_path),
    }


def _eval_baseline(pcb_path: Path) -> dict:
    t0 = time.perf_counter()
    m = _metrics(pcb_path)
    m["elapsed_s"] = time.perf_counter() - t0
    return m


def _eval_cmaes(pcb_path: Path, time_budget_s: float) -> dict:
    pcb = PCB.load(str(pcb_path))
    anchors = _connector_refs(pcb)
    t0 = time.perf_counter()
    refine = _refine_with_cmaes(pcb_path, anchors, time_budget_s=time_budget_s)
    elapsed = time.perf_counter() - t0
    m = _metrics(pcb_path)
    m["refined"] = bool(refine.get("refined"))
    m["elapsed_s"] = elapsed
    m["cmaes_meta"] = refine
    return m


def _eval_rl(
    pcb_path: Path,
    model_path: Path,
    *,
    board_width_mm: float | None,
    board_height_mm: float | None,
    inference_steps: int,
    artifact_dir: Path,
    rl_env: str = "moves",
    kct_backend: str = "cmaes",
) -> dict:
    try:
        from stable_baselines3 import PPO
    except ImportError as exc:
        raise SystemExit(f"stable-baselines3 required for RL arm: {exc}") from exc

    if rl_env == "kct":
        from tools.rl.placement.train_placement import _mock_kct_place_fn

        place_fn = _mock_kct_place_fn if kct_backend == "mock" else None
        env: PlacementEnv | KctPlacementEnv = KctPlacementEnv(
            pcb_path=pcb_path,
            place_fn=place_fn,
            max_steps=max(inference_steps, 1),
            board_width_mm=board_width_mm,
            board_height_mm=board_height_mm,
            force_refine_if_errors=True,
        )
    else:
        env = PlacementEnv(
            pcb_path=pcb_path,
            board_width_mm=board_width_mm,
            board_height_mm=board_height_mm,
            max_steps=max(inference_steps, 1),
        )
    # OBS_DIM / action space must match the checkpoint (moves vs kct).
    try:
        model = PPO.load(str(model_path), env=env)
        t0 = time.perf_counter()
        obs, info = env.reset()
        total_reward = 0.0
        for _ in range(inference_steps):
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, term, trunc, info = env.step(action)
            total_reward += float(reward)
            if term or trunc:
                break
        elapsed = time.perf_counter() - t0

        artifact_dir.mkdir(parents=True, exist_ok=True)
        out_pcb = artifact_dir / "arm_rl_result.kicad_pcb"
        if isinstance(env, KctPlacementEnv) and env.work_pcb_path is not None:
            import shutil

            shutil.copy2(env.work_pcb_path, out_pcb)
        else:
            assert env.pcb is not None
            env.pcb.save(str(out_pcb))
        m = _metrics(out_pcb)
        m["elapsed_s"] = elapsed
        m["inference_steps"] = inference_steps
        m["total_reward"] = total_reward
        m["final_info_fom"] = info.get("fom_score")
        m["final_info_errors"] = info.get("error_conflicts")
        m["board_out"] = str(out_pcb.resolve())
        m["board_exists"] = out_pcb.is_file()
        m["rl_env"] = rl_env
        m["kct_backend"] = kct_backend if rl_env == "kct" else None
        return m
    finally:
        close = getattr(env, "close", None)
        if callable(close):
            close()


def _gate(
    fom_rl: float,
    fom_cmaes: float,
    errors_rl: int,
    errors_cmaes: int,
    margin: float,
) -> dict:
    """GO only if FOM improves by margin AND RL has no more ERROR than CMA-ES."""
    eps = 1e-12
    denom = max(abs(fom_cmaes), eps)
    rel = (fom_rl - fom_cmaes) / denom
    abs_delta = fom_rl - fom_cmaes
    fom_ok = rel > margin
    errors_ok = errors_rl <= errors_cmaes
    passed = fom_ok and errors_ok
    reasons: list[str] = []
    if not fom_ok:
        reasons.append(f"FOM rel improvement {rel:.4f} <= margin {margin}")
    if not errors_ok:
        reasons.append(f"RL errors {errors_rl} > CMA-ES errors {errors_cmaes}")
    return {
        "margin_required": margin,
        "relative_improvement": rel,
        "absolute_delta": abs_delta,
        "fom_ok": fom_ok,
        "errors_ok": errors_ok,
        "errors_rl": errors_rl,
        "errors_cmaes": errors_cmaes,
        "passed": passed,
        "reasons": reasons,
        "verdict": (
            "GO — RL bat CMA-ES (FOM + errors)"
            if passed
            else "NO-GO — garder CMA-ES (" + "; ".join(reasons) + ")"
        ),
    }


def _eval_one_pcb(
    pcb: Path,
    model: Path,
    *,
    board_width_mm: float | None,
    board_height_mm: float | None,
    inference_steps: int,
    cmaes_budget_s: float,
    margin: float,
    artifact_dir: Path,
    rl_env: str = "moves",
    kct_backend: str = "cmaes",
) -> dict:
    """Baseline + CMA-ES + RL on one board; returns report with gate."""
    board_art = artifact_dir / pcb.stem
    board_art.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="rl_vs_cmaes_") as tmp:
        tmp_path = Path(tmp)
        base = _copy_pcb(pcb, tmp_path / "start.kicad_pcb")
        cmaes_pcb = _copy_pcb(base, tmp_path / "arm_cmaes.kicad_pcb")
        rl_pcb = _copy_pcb(base, tmp_path / "arm_rl.kicad_pcb")

        print(f"  [{pcb.stem}] baseline…", flush=True)
        baseline = _eval_baseline(base)

        print(f"  [{pcb.stem}] CMA-ES refine…", flush=True)
        cmaes = _eval_cmaes(cmaes_pcb, cmaes_budget_s)
        cmaes_art = board_art / "arm_cmaes_result.kicad_pcb"
        shutil.copy2(cmaes_pcb, cmaes_art)
        cmaes["board_out"] = str(cmaes_art)
        cmaes["board_exists"] = cmaes_art.is_file()

        print(f"  [{pcb.stem}] RL inference…", flush=True)
        try:
            rl = _eval_rl(
                rl_pcb,
                model,
                board_width_mm=board_width_mm,
                board_height_mm=board_height_mm,
                inference_steps=inference_steps,
                artifact_dir=board_art,
                rl_env=rl_env,
                kct_backend=kct_backend,
            )
        except Exception as exc:
            # OBS_DIM mismatch after env fix is expected for old checkpoints
            rl = {
                "fom": float("nan"),
                "error_conflicts": -1,
                "elapsed_s": 0.0,
                "error": str(exc),
                "board_exists": False,
            }

    gate = _gate(
        float(rl.get("fom") or 0.0),
        float(cmaes.get("fom") or 0.0),
        int(rl.get("error_conflicts") or 0),
        int(cmaes.get("error_conflicts") or 0),
        margin,
    )
    if rl.get("error"):
        gate["passed"] = False
        gate["verdict"] = f"NO-GO — RL eval failed: {rl['error']}"

    return {
        "pcb": str(pcb),
        "board_id": pcb.stem,
        "artifact_dir": str(board_art),
        "baseline": baseline,
        "cmaes": cmaes,
        "rl": rl,
        "gate": gate,
    }


def _aggregate_gates(per_board: list[dict], margin: float) -> dict:
    """Dataset-level gate: mean relative FOM improvement + mean errors."""
    rels: list[float] = []
    fom_rl: list[float] = []
    fom_cma: list[float] = []
    err_rl: list[int] = []
    err_cma: list[int] = []
    n_pass = 0
    n_fail = 0
    for r in per_board:
        g = r.get("gate") or {}
        if g.get("passed"):
            n_pass += 1
        else:
            n_fail += 1
        if r.get("rl", {}).get("error"):
            continue
        rels.append(float(g.get("relative_improvement") or 0.0))
        fom_rl.append(float(r["rl"].get("fom") or 0.0))
        fom_cma.append(float(r["cmaes"].get("fom") or 0.0))
        err_rl.append(int(r["rl"].get("error_conflicts") or 0))
        err_cma.append(int(r["cmaes"].get("error_conflicts") or 0))

    if not rels:
        return {
            "margin_required": margin,
            "n_boards": len(per_board),
            "n_pass_board": n_pass,
            "n_fail_board": n_fail,
            "passed": False,
            "verdict": "NO-GO — aucune board évaluable (modèle / OBS_DIM ?)",
        }

    mean_rel = sum(rels) / len(rels)
    mean_err_rl = sum(err_rl) / len(err_rl)
    mean_err_cma = sum(err_cma) / len(err_cma)
    fom_ok = mean_rel > margin
    errors_ok = mean_err_rl <= mean_err_cma + 1e-9
    # Majority of individual boards must also pass FOM+errors gate
    majority_ok = n_pass > n_fail
    passed = fom_ok and errors_ok and majority_ok
    reasons: list[str] = []
    if not fom_ok:
        reasons.append(f"mean FOM rel {mean_rel:.4f} <= margin {margin}")
    if not errors_ok:
        reasons.append(f"mean RL errors {mean_err_rl:.2f} > mean CMA-ES {mean_err_cma:.2f}")
    if not majority_ok:
        reasons.append(f"board pass {n_pass} <= fail {n_fail}")
    return {
        "margin_required": margin,
        "n_boards": len(per_board),
        "n_scored": len(rels),
        "n_pass_board": n_pass,
        "n_fail_board": n_fail,
        "mean_relative_improvement": mean_rel,
        "mean_fom_rl": sum(fom_rl) / len(fom_rl),
        "mean_fom_cmaes": sum(fom_cma) / len(fom_cma),
        "mean_errors_rl": mean_err_rl,
        "mean_errors_cmaes": mean_err_cma,
        "fom_ok": fom_ok,
        "errors_ok": errors_ok,
        "majority_ok": majority_ok,
        "passed": passed,
        "reasons": reasons,
        "verdict": (
            "GO — RL bat CMA-ES sur le dataset (FOM + errors + majorité)"
            if passed
            else "NO-GO — garder CMA-ES (" + "; ".join(reasons) + ")"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Gate FOM + placement ERROR: RL vs CMA-ES")
    p.add_argument(
        "--pcb",
        type=Path,
        default=None,
        help="Single .kicad_pcb (can combine with --pcb-dir)",
    )
    p.add_argument(
        "--pcb-dir",
        type=Path,
        default=None,
        help="Directory of *.kicad_pcb — multi-board gate (mean + majority)",
    )
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--board-width", type=float, default=None)
    p.add_argument("--board-height", type=float, default=None)
    p.add_argument("--inference-steps", type=int, default=64)
    p.add_argument(
        "--rl-env",
        choices=("moves", "kct"),
        default="moves",
        help="Must match the env used to train --model",
    )
    p.add_argument(
        "--kct-backend",
        choices=("cmaes", "mock"),
        default="cmaes",
        help="Only with --rl-env kct",
    )
    p.add_argument("--cmaes-budget-s", type=float, default=20.0)
    p.add_argument("--margin", type=float, default=0.05)
    p.add_argument("--out-json", type=Path, default=None)
    p.add_argument(
        "--artifact-dir",
        type=Path,
        default=None,
        help="Persistent dir for RL/CMA-ES result boards (default: tmp/rl_vs_cmaes_art)",
    )
    args = p.parse_args(argv)

    pcbs: list[Path] = []
    if args.pcb is not None:
        pcbs.append(Path(args.pcb))
    if args.pcb_dir is not None:
        d = Path(args.pcb_dir)
        if not d.is_dir():
            print(f"error: --pcb-dir not a directory: {d}", file=sys.stderr)
            return 2
        pcbs.extend(sorted(d.glob("*.kicad_pcb")))
    if not pcbs:
        print("error: provide --pcb and/or --pcb-dir", file=sys.stderr)
        return 2
    missing = [p for p in pcbs if not p.is_file()]
    if missing:
        print(f"error: pcb not found: {missing[0]}", file=sys.stderr)
        return 2
    if not args.model.is_file():
        print(f"error: model not found: {args.model}", file=sys.stderr)
        return 2

    artifact_dir = args.artifact_dir or (_SERVICE_ROOT / "tmp" / "rl_vs_cmaes_art")
    artifact_dir = artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # kct episodes are short (1–2 refine calls)
    inference_steps = args.inference_steps
    if args.rl_env == "kct" and args.inference_steps == 64:
        inference_steps = 2

    print(
        f"Evaluating {len(pcbs)} board(s) vs CMA-ES "
        f"(rl_env={args.rl_env}, inference_steps={inference_steps})…",
        flush=True,
    )
    per_board: list[dict] = []
    for pcb in pcbs:
        report = _eval_one_pcb(
            pcb,
            args.model,
            board_width_mm=args.board_width,
            board_height_mm=args.board_height,
            inference_steps=inference_steps,
            cmaes_budget_s=args.cmaes_budget_s,
            margin=args.margin,
            artifact_dir=artifact_dir,
            rl_env=args.rl_env,
            kct_backend=args.kct_backend,
        )
        per_board.append(report)
        g = report["gate"]
        print(
            f"  → {report['board_id']}: "
            f"FOM RL={report['rl'].get('fom')} CMA={report['cmaes'].get('fom')} "
            f"passed={g.get('passed')} | {g.get('verdict')}",
            flush=True,
        )

    if len(per_board) == 1:
        gate = per_board[0]["gate"]
        report_out: dict = {
            **per_board[0],
            "model": str(args.model),
            "metrics": "fom_score + PlacementAnalyzer ERROR count",
        }
    else:
        gate = _aggregate_gates(per_board, args.margin)
        report_out = {
            "model": str(args.model),
            "n_boards": len(per_board),
            "boards": per_board,
            "gate": gate,
            "artifact_dir": str(artifact_dir),
            "metrics": "fom_score + PlacementAnalyzer ERROR count (multi-board mean+majority)",
        }

    print(json.dumps(report_out, indent=2))
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(report_out, indent=2), encoding="utf-8")
        print(f"wrote {args.out_json}", flush=True)

    return 0 if gate["passed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
