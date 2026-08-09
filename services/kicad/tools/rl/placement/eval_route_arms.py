#!/usr/bin/env python3
"""Gate B lab — route already-placed RL vs CMA-ES boards and compare %.

Input: artifact dir from ``eval_vs_cmaes`` (per-board folders with
``arm_cmaes_result.kicad_pcb`` and ``arm_rl_result.kicad_pcb``).

Uses production ``tools.kct_route.route_kct`` (not Freerouting-only).

Example::

    python -m tools.rl.placement.eval_route_arms \\
      --artifact-dir tmp/rl_vs_cmaes_v2_art \\
      --timeout-s 120 \\
      --out-json tmp/rl_vs_cmaes_v2_routed.json
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
from tools.rl.placement.conflicts import count_error_conflicts  # noqa: E402
from tools.rl.placement.reward import fom_score  # noqa: E402
from kicad_tools.schema.pcb import PCB  # noqa: E402


def _route_one(pcb_path: Path, out_path: Path, timeout_s: int) -> dict:
    raw = pcb_path.read_bytes()
    t0 = time.perf_counter()
    try:
        routed_bytes, pct, analysis = route_kct(raw, timeout_s=timeout_s)
        err = None
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        return {
            "ok": False,
            "error": str(exc),
            "routed_percent": 0,
            "elapsed_s": elapsed,
            "board_out": None,
        }
    elapsed = time.perf_counter() - t0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(routed_bytes)
    pcb = PCB.load(str(out_path))
    return {
        "ok": True,
        "routed_percent": int(pct),
        "elapsed_s": elapsed,
        "board_out": str(out_path),
        "fom_after_route": fom_score(pcb, pcb_path=str(out_path)),
        "error_conflicts": count_error_conflicts(pcb, pcb_path=out_path),
        "failure_analysis_preview": (analysis or "")[:400],
    }


def _discover_boards(artifact_dir: Path) -> list[tuple[str, Path, Path]]:
    """Return (board_id, cmaes_pcb, rl_pcb) for each subfolder."""
    found: list[tuple[str, Path, Path]] = []
    for sub in sorted(artifact_dir.iterdir()):
        if not sub.is_dir():
            continue
        cma = sub / "arm_cmaes_result.kicad_pcb"
        rl = sub / "arm_rl_result.kicad_pcb"
        if cma.is_file() and rl.is_file():
            found.append((sub.name, cma, rl))
    return found


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Route RL vs CMA-ES placement arms (Gate B lab)"
    )
    p.add_argument(
        "--artifact-dir",
        type=Path,
        required=True,
        help="Dir from eval_vs_cmaes --artifact-dir (board subfolders)",
    )
    p.add_argument(
        "--timeout-s",
        type=int,
        default=120,
        help="Per-board route_kct timeout seconds (default 120 lab)",
    )
    p.add_argument("--out-json", type=Path, default=None)
    p.add_argument(
        "--out-art",
        type=Path,
        default=None,
        help="Where to write routed boards (default: <artifact-dir>_routed)",
    )
    args = p.parse_args(argv)

    art = args.artifact_dir.resolve()
    if not art.is_dir():
        print(f"error: artifact-dir not found: {art}", file=sys.stderr)
        return 2

    pairs = _discover_boards(art)
    if not pairs:
        print(f"error: no arm_cmaes/arm_rl pairs under {art}", file=sys.stderr)
        return 2

    out_art = (args.out_art or Path(str(art) + "_routed")).resolve()
    out_art.mkdir(parents=True, exist_ok=True)

    print(f"Routing {len(pairs)} board(s) × 2 arms (timeout={args.timeout_s}s)…", flush=True)
    per_board: list[dict] = []
    for board_id, cma_path, rl_path in pairs:
        board_out = out_art / board_id
        print(f"  [{board_id}] CMA-ES arm…", flush=True)
        cma_r = _route_one(
            cma_path, board_out / "arm_cmaes_routed.kicad_pcb", args.timeout_s
        )
        print(
            f"    → CMA routed_percent={cma_r.get('routed_percent')} "
            f"ok={cma_r.get('ok')} ({cma_r.get('elapsed_s', 0):.1f}s)",
            flush=True,
        )
        print(f"  [{board_id}] RL arm…", flush=True)
        rl_r = _route_one(
            rl_path, board_out / "arm_rl_routed.kicad_pcb", args.timeout_s
        )
        print(
            f"    → RL  routed_percent={rl_r.get('routed_percent')} "
            f"ok={rl_r.get('ok')} ({rl_r.get('elapsed_s', 0):.1f}s)",
            flush=True,
        )

        pct_c = int(cma_r.get("routed_percent") or 0)
        pct_r = int(rl_r.get("routed_percent") or 0)
        # Best arm for this board: higher routed % wins; tie → prefer CMA (baseline)
        if pct_r > pct_c:
            winner = "rl"
        elif pct_c > pct_r:
            winner = "cmaes"
        else:
            winner = "tie"

        per_board.append(
            {
                "board_id": board_id,
                "cmaes": cma_r,
                "rl": rl_r,
                "winner": winner,
                "delta_routed_percent": pct_r - pct_c,
            }
        )

    n = len(per_board)
    mean_c = sum(int(b["cmaes"].get("routed_percent") or 0) for b in per_board) / n
    mean_r = sum(int(b["rl"].get("routed_percent") or 0) for b in per_board) / n
    n_rl_win = sum(1 for b in per_board if b["winner"] == "rl")
    n_cma_win = sum(1 for b in per_board if b["winner"] == "cmaes")
    n_tie = sum(1 for b in per_board if b["winner"] == "tie")
    n_rl_100 = sum(1 for b in per_board if int(b["rl"].get("routed_percent") or 0) >= 100)
    n_cma_100 = sum(
        1 for b in per_board if int(b["cmaes"].get("routed_percent") or 0) >= 100
    )

    # Legacy Gate B (percent only) — kept for history, NOT deployment authority
    gate_b_legacy_passed = mean_r >= mean_c and n_rl_100 >= n_cma_100

    # Fail-closed hard gate per board (errors + 100% + DRC/unconnected when known)
    from tools.rl.quality_gate import (
        evaluate_board_hard_gate,
        evaluate_dataset_hard_gate,
    )

    hard_gates: list[dict] = []
    for b in per_board:
        rl = b.get("rl") or {}
        # After route, placement ERROR on the *placed* arm should still be 0.
        # Prefer post-route error_conflicts when present (from _route_one metrics).
        err = rl.get("error_conflicts")
        hard = evaluate_board_hard_gate(
            error_conflicts=err if err is not None else None,
            routed_percent=rl.get("routed_percent"),
            unrouted_count=rl.get("unrouted_count"),
            drc_error_count=rl.get("drc_error_count"),
            unconnected_items=rl.get("unconnected_items"),
            # DRC / unconnected often not run in this script yet → fail-closed
            require_drc=True,
            require_unconnected=True,
            require_unrouted_count=False,
        )
        b["hard_gate"] = hard
        hard_gates.append(hard)

    hard_dataset = evaluate_dataset_hard_gate(hard_gates, require_all_boards=True)

    report = {
        "artifact_dir": str(art),
        "out_art": str(out_art),
        "timeout_s": args.timeout_s,
        "n_boards": n,
        "boards": per_board,
        "summary": {
            "mean_routed_percent_cmaes": mean_c,
            "mean_routed_percent_rl": mean_r,
            "n_cmaes_win": n_cma_win,
            "n_rl_win": n_rl_win,
            "n_tie": n_tie,
            "n_cmaes_100pct": n_cma_100,
            "n_rl_100pct": n_rl_100,
        },
        "gate_b_legacy_percent_only": {
            "passed": gate_b_legacy_passed,
            "verdict": (
                "LEGACY GO-B (percent only — NOT deployment authority)"
                if gate_b_legacy_passed
                else "LEGACY NO-GO-B (percent only)"
            ),
            "note": (
                "Do not use for prod. Requires hard_gate: error_conflicts=0, "
                "route 100%, DRC 0, unconnected_items=0 on every board."
            ),
        },
        "hard_gate": hard_dataset,
        "gate_b": {
            # Deployment authority = hard gate only
            "passed": hard_dataset["passed"],
            "verdict": hard_dataset["verdict"],
            "legacy_percent_only_passed": gate_b_legacy_passed,
        },
        "router": "tools.kct_route.route_kct",
        "prod_flag_authority": "hard_gate only — legacy percent GO is not sufficient",
    }

    print(json.dumps(report, indent=2))
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"wrote {args.out_json}", flush=True)

    return 0 if hard_dataset["passed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
