#!/usr/bin/env python3
"""Driver LLM manuel pour PCBReasoningAgent — Claude joue le rôle du LLM.

Usage:
    python driver_llm.py state <board.kicad_pcb>
    python driver_llm.py exec <board.kicad_pcb> <out.kicad_pcb> <commands.json>

commands.json = liste de dicts {"type": "place_component"|"route_net"|"delete_trace"|"add_via", ...}
"""
import json
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_SERVICE_ROOT / "kicad-tools" / "src"))

from kicad_tools.reasoning.agent import PCBReasoningAgent


def show_state(agent: PCBReasoningAgent) -> None:
    s = agent.state
    print("=== COMPONENTS (ref @ x,y rot) ===")
    for ref, comp in sorted(s.components.items()):
        print(f"  {ref:5s} @ ({comp.x:7.2f},{comp.y:7.2f}) rot={comp.rotation:.0f}")
    print("=== OUTLINE ===")
    o = s.outline
    print(f"  center=({o.center_x:.1f},{o.center_y:.1f})  {o.width:.0f}x{o.height:.0f}mm")
    print("=== NETS ===")
    print(f"  routed:   {sorted(n.name for n in s.routed_nets)}")
    print(f"  unrouted: {sorted(n.name for n in s.unrouted_nets)}")
    print(f"  violations: {len(s.violations)}")
    print()
    print(agent.get_prompt(max_history=3))


def main() -> int:
    mode, board = sys.argv[1], sys.argv[2]
    agent = PCBReasoningAgent.from_pcb(board)

    if mode == "state":
        show_state(agent)
        return 0

    out, cmds_file = sys.argv[3], sys.argv[4]
    commands = json.loads(open(cmds_file, encoding="utf-8").read())
    for i, cmd in enumerate(commands, 1):
        print(f"--- [{i}/{len(commands)}] {cmd}")
        result, diagnosis = agent.execute_dict(cmd)
        print(f"    success={result.success}  msg={result.message}")
        if diagnosis:
            print(f"    DIAGNOSIS:\n{diagnosis}")
    p = agent.get_progress()
    print(f"\n=== PROGRESS: routed {p.nets_routed}/{p.nets_total} | violations {p.violations_current} (init {p.violations_initial}) ===")
    agent.save(out)
    print(f"saved -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
