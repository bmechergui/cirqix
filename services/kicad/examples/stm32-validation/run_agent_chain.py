#!/usr/bin/env python3
"""Chaîne agents Cirqix rejouée en local avec les FONCTIONS DE PROD, étape par étape.

Reproduit : call_agent_gen_pcb → call_agent_placement → call_agent_routing
→ call_agent_reason (boucle placement-feedback), en sauvegardant le board de
CHAQUE étape pour comparaison :

    out/1_gen.kicad_pcb        ← board généré (entrée)
    out/2_placed.kicad_pcb     ← tools/placement.auto_place (agent ⑤ prod)
    out/3_routed.kicad_pcb     ← tools/kct_route.route_kct (agent ⑥ prod)
    out/3_routing_analysis.txt ← analyse d'échec du routeur (entrée du driver LLM)
    out/4_rescued.kicad_pcb    ← tools/reasoning.rescue_with_placement_feedback
    out/4_steps.log               (agent ⑥b prod — décideur = decisions.json)

Usage :
    # Étapes 1→3 (s'arrête pour que le driver LLM lise l'analyse) :
    python run_agent_chain.py <gen.kicad_pcb> <out_dir>
    # Étape 4 (après écriture de decisions.json par le driver) :
    python run_agent_chain.py <gen.kicad_pcb> <out_dir> --rescue <decisions.json>
"""
from __future__ import annotations

import base64
import json
import sys
import subprocess
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[2]          # services/kicad
sys.path.insert(0, str(_SERVICE_ROOT))
sys.path.insert(0, str(_SERVICE_ROOT / "kicad-tools" / "src"))

from tools import kct_route                                   # noqa: E402
from tools.placement import auto_place                        # noqa: E402
from tools.reasoning import rescue_with_placement_feedback    # noqa: E402

_BOARD_W_MM, _BOARD_H_MM = 60.0, 40.0
_ROUTE_TIMEOUT_S = 300


def stages_1_to_3(gen_board: Path, out: Path) -> None:
    stage1_dir = out / "1_placement"
    stage1_dir.mkdir(parents=True, exist_ok=True)
    
    stage2_dir = out / "2_routing"
    stage2_dir.mkdir(parents=True, exist_ok=True)

    # ① gen — entrée telle quelle (call_agent_gen_pcb)
    gen_bytes = gen_board.read_bytes()
    print(f"[1/4] gen        : {gen_board.name} ({len(gen_bytes)} o)")

    # ② placement — fonction PROD de POST /place/auto (call_agent_placement)
    res = auto_place(base64.b64encode(gen_bytes).decode(), _BOARD_W_MM, _BOARD_H_MM)
    
    # Export Phase 1 (Physique) et Phase 2 (CMA-ES)
    if "kicad_pcb_phase1_b64" in res:
        phase1_bytes = base64.b64decode(res["kicad_pcb_phase1_b64"])
        (stage1_dir / "placed_phase1.kicad_pcb").write_bytes(phase1_bytes)
        
    placed_bytes = base64.b64decode(res["kicad_pcb_b64"])
    (stage1_dir / "placed_phase2.kicad_pcb").write_bytes(placed_bytes)
    
    with open(stage1_dir / "placement.log", "w") as f:
        f.write(f"Composants optimises: {res['placed_count']}\n")
        for p in res["positions"]:
            f.write(f"{p['ref']:5s} @ ({p['x']:7.2f},{p['y']:7.2f})\n")
            
    print(f"[2/4] placement  : {res['placed_count']} composants optimisés")

    # ③ routage — fonction PROD de POST /route/auto (call_agent_routing)
    routed_bytes, pct, analysis = kct_route.route_kct(placed_bytes, timeout_s=_ROUTE_TIMEOUT_S)
    (stage2_dir / "routed.kicad_pcb").write_bytes(routed_bytes)
    (stage2_dir / "routing_analysis.txt").write_text(analysis or "(routage complet)",
                                                encoding="utf-8")
    print(f"[3/4] routage    : {pct}%")
    if pct >= 100:
        print("      Routage complet — étape 4 (sauvetage) inutile.")
        return
    print("      Analyse d'échec -> 2_routing/routing_analysis.txt")
    print("      Driver LLM : écris decisions.json puis relance avec --rescue")


def stage_4(out: Path, decisions_file: Path) -> None:
    stage2_dir = out / "2_routing"
    stage3_dir = out / "3_rescue"
    stage3_dir.mkdir(parents=True, exist_ok=True)

    # ⑥b sauvetage — fonction PROD de POST /reason/auto (call_agent_reason)
    routed_bytes = (stage2_dir / "routed.kicad_pcb").read_bytes()
    queue = list(json.loads(decisions_file.read_text(encoding="utf-8")))

    def decide(prompt: str) -> dict | None:
        """Driver Claude Code : sert les décisions pré-établies, dans l'ordre."""
        return queue.pop(0) if queue else None

    iter_count = 0

    def route_fn(pcb_bytes: bytes):
        nonlocal iter_count
        iter_count += 1
        result, pct, analysis = kct_route.route_kct(pcb_bytes, timeout_s=_ROUTE_TIMEOUT_S)
        (stage3_dir / f"iter{iter_count}_{pct}pct.kicad_pcb").write_bytes(result)
        return result, pct, analysis

    out_bytes, pct, steps = rescue_with_placement_feedback(
        routed_bytes, route_fn=route_fn, max_iterations=3, decide=decide, log_dir=stage3_dir
    )
    (stage3_dir / "final_rescued.kicad_pcb").write_bytes(out_bytes)
    (stage3_dir / "steps.log").write_text("\n".join(steps), encoding="utf-8")
    print(f"[4/4] sauvetage  : {pct}%")
    for s in steps:
        print("  ", s)


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: run_agent_chain.py <out_dir> [--rescue batch.json]")
        return 1

    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    
    stage0_dir = out / "0_generation"
    stage0_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "="*60)
    print("STAGE 0: Generating Initial PCB")
    print("="*60)
    script_dir = Path(__file__).parent
    generate_script = script_dir / "input" / "generate_design.py"
    
    result = subprocess.run([sys.executable, str(generate_script), str(stage0_dir)], check=False)
    if result.returncode != 0:
        print("Generation failed.")
        return 1
    
    board_in = stage0_dir / "stm32_devboard.kicad_pcb"
    if not board_in.exists():
        print(f"Error: {board_in} was not generated.")
        return 1

    routed_pcb = out / "2_routing" / "routed.kicad_pcb"
    if not routed_pcb.exists():
        stages_1_to_3(board_in, out)
    else:
        print("Stages 1 to 3 already completed. Skipping to rescue.")

    if "--rescue" in sys.argv:
        stage_4(out, Path(sys.argv[sys.argv.index("--rescue") + 1]))
        
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
