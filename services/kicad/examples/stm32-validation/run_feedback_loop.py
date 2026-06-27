#!/usr/bin/env python3
"""Test local de la boucle placement-feedback — Claude Code joue le driver LLM.

Exécute la VRAIE fonction de production ``rescue_with_placement_feedback``
(tools/reasoning.py) avec le VRAI routeur (tools/kct_route.py), mais sans clé
API : le décideur lit les commandes depuis ``decisions.json`` (écrites par
Claude Code après lecture de l'analyse d'échec du routeur — pattern « moi = le
LLM », voir README).

Usage :
    python run_feedback_loop.py <input.kicad_pcb> <decisions.json> <out_dir>

decisions.json = liste de commandes {"type":"place_component"|"delete_trace",...}
servies au loop dans l'ordre ; None (épuisé) = plus rien à déplacer.

Sorties dans <out_dir> : final.kicad_pcb + steps.log
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[2]          # services/kicad
sys.path.insert(0, str(_SERVICE_ROOT))
sys.path.insert(0, str(_SERVICE_ROOT / "kicad-tools" / "src"))

from tools import kct_route                    # noqa: E402
from tools.reasoning import rescue_with_placement_feedback  # noqa: E402


def main() -> int:
    board_in, decisions_file, out_dir = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    out_dir.mkdir(parents=True, exist_ok=True)

    decisions = json.loads(Path(decisions_file).read_text(encoding="utf-8"))
    queue = list(decisions)

    def decide(prompt: str) -> dict | None:
        """Driver Claude Code : sert les décisions pré-établies dans l'ordre."""
        return queue.pop(0) if queue else None

    iter_count = 0

    def route_fn(pcb_bytes: bytes):
        # Sauvegarde le board de CHAQUE itération (iter1_22pct.kicad_pcb, …)
        # pour comparaison — la boucle prod ne rend que le meilleur.
        nonlocal iter_count
        iter_count += 1
        result, pct, analysis = kct_route.route_kct(pcb_bytes, timeout_s=300)
        (out_dir / f"iter{iter_count}_{pct}pct.kicad_pcb").write_bytes(result)
        return result, pct, analysis

    pcb_bytes = Path(board_in).read_bytes()
    out_bytes, pct, steps = rescue_with_placement_feedback(
        pcb_bytes, route_fn=route_fn, max_iterations=3, decide=decide, log_dir=out_dir
    )

    (out_dir / "final.kicad_pcb").write_bytes(out_bytes)
    (out_dir / "steps.log").write_text("\n".join(steps), encoding="utf-8")

    print(f"\n=== RESULTAT : {pct}% ===")
    for s in steps:
        print(" ", s)
    print(f"\nfinal.kicad_pcb + steps.log -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
