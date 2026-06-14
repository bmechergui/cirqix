#!/usr/bin/env python3
"""Pipeline COMPLET 8 agents rejoué en local avec les FONCTIONS DE PROD.

Couvre les 8 étapes (run_agent_chain.py ne couvre que ④→⑥b) :

    out/1_schema.kicad_sch     ← tools/schematic.generate_schematic   (agent ①)
    out/2_erc_report.json      ← routers/erc.run_erc                  (agent ②)
    out/3_gen.kicad_pcb        ← tools/pcb.generate_pcb               (agent ④)
    out/4_placed.kicad_pcb     ← tools/placement.auto_place           (agent ⑤)
    out/5_routed.kicad_pcb     ← tools/kct_route.route_kct            (agent ⑥)
    out/5_routing_analysis.txt ←   analyse d'échec (entrée driver LLM)
    out/6_rescued.kicad_pcb    ← tools/reasoning.rescue_…  (agent ⑥b, --rescue)
    out/6_steps.log
    out/7_drc_report.json      ← routers/drc.run_drc_auto             (agent ⑦)
    out/8_export/              ← routers/export.export_all            (agent ⑧)

Driver LLM (pattern « moi = le LLM », sans clé API) :
  rôle 1 — le circuit JSON d'entrée (input/circuit_full.json) ;
  rôle 2 — decisions.json si le routage reste < 100 % (déplacements).

Usage :
    # Étapes ①→⑥ (s'arrête sur l'analyse d'échec si routage < 100 %) :
    python run_full_pipeline.py input/circuit_full.json <out_dir>
    # Reprise ⑥b→⑧ après écriture de decisions.json par le driver LLM :
    python run_full_pipeline.py input/circuit_full.json <out_dir> --rescue <decisions.json>
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[2]          # services/kicad
sys.path.insert(0, str(_SERVICE_ROOT))
sys.path.insert(0, str(_SERVICE_ROOT / "kicad-tools" / "src"))

from routers.drc import DRCAutoRequest, run_drc_auto          # noqa: E402
from routers.erc import ERCRequest, run_erc                   # noqa: E402
from routers.export import ExportAllRequest, export_all       # noqa: E402
from tools import kct_route                                   # noqa: E402
from tools.pcb import generate_pcb                            # noqa: E402
from tools.placement import auto_place                        # noqa: E402
from tools.reasoning import rescue_with_placement_feedback    # noqa: E402
from tools.schematic import (                                 # noqa: E402
    SchemaComponent,
    SchemaNet,
    generate_schematic,
)

_ROUTE_TIMEOUT_S = 300


def _load_circuit(path: Path) -> tuple[list[SchemaComponent], list[SchemaNet], float, float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    components = [SchemaComponent(**c) for c in data["components"]]
    connections = [SchemaNet(**n) for n in data["nets"]]
    return components, connections, data["board"]["width_mm"], data["board"]["height_mm"]


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def stages_1_to_6(circuit: Path, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    components, connections, board_w, board_h = _load_circuit(circuit)

    # ① schéma — cascade prod : circuit_synth pip → kicad-tools → "" (fail)
    sch = generate_schematic(components, connections,
                             [n.name for n in connections], board_w, board_h,
                             project_id="stm32-full")
    if not sch:
        print("[1/8] schéma     : ÉCHEC (toutes les voies Python) — stop")
        return 1
    (out / "1_schema.kicad_sch").write_text(sch, encoding="utf-8")
    print(f"[1/8] schéma     : {len(components)} composants, {len(connections)} nets")

    # ② ERC — kicad-cli sch erc (auto-fix no_connect), non bloquant si skipped
    erc = run_erc(ERCRequest(kicad_sch_b64=_b64(sch.encode("utf-8"))))
    (out / "2_erc_report.json").write_text(erc.model_dump_json(indent=2), encoding="utf-8")
    print(f"[2/8] ERC        : clean={erc.erc_clean} violations={len(erc.violations)}"
          f"{' (skipped)' if erc.skipped else ''}")
    if erc.kicad_sch_b64:                                     # schéma auto-fixé
        sch = base64.b64decode(erc.kicad_sch_b64).decode("utf-8")
        (out / "1_schema.kicad_sch").write_text(sch, encoding="utf-8")

    # ④ génération PCB — kicad-tools PCBFromSchematic (vrais footprints + nets)
    pcb = generate_pcb(components, connections, board_w, board_h,
                       kicad_sch_content=sch)
    if not pcb:
        print("[3/8] gen PCB    : ÉCHEC (toutes les voies Python) — stop")
        return 1
    (out / "3_gen.kicad_pcb").write_text(pcb, encoding="utf-8")
    print(f"[3/8] gen PCB    : {len(pcb)} o")

    # ⑤ placement — PlacementOptimizer (clustering + connecteurs ancrés)
    res = auto_place(_b64(pcb.encode("utf-8")), board_w, board_h)
    placed = base64.b64decode(res["kicad_pcb_b64"])
    (out / "4_placed.kicad_pcb").write_bytes(placed)
    print(f"[4/8] placement  : {res['placed_count']} composants optimisés")

    # ⑥ routage — kct route négocié (auto-layers, auto-fix, seed 42)
    routed, pct, analysis = kct_route.route_kct(placed, timeout_s=_ROUTE_TIMEOUT_S)
    (out / "5_routed.kicad_pcb").write_bytes(routed)
    (out / "5_routing_analysis.txt").write_text(analysis or "(routage complet)",
                                                encoding="utf-8")
    print(f"[5/8] routage    : {pct}%")
    if pct < 100:
        print("      Analyse d'échec → 5_routing_analysis.txt")
        print("      Driver LLM : écris decisions.json puis relance avec --rescue")
        return 0

    return stages_7_to_8(out, routed)


def stage_6_rescue(out: Path, decisions_file: Path) -> int:
    # ⑥b sauvetage — boucle placement-feedback (le LLM déplace, kct route reroute)
    routed = (out / "5_routed.kicad_pcb").read_bytes()
    queue = list(json.loads(decisions_file.read_text(encoding="utf-8")))

    def decide(prompt: str) -> dict | None:
        return queue.pop(0) if queue else None

    iter_count = 0

    def route_fn(pcb_bytes: bytes):
        # Sauvegarde le board de CHAQUE itération (6_iter1_22pct.kicad_pcb, …)
        # pour comparaison — la boucle prod ne rend que le meilleur.
        nonlocal iter_count
        iter_count += 1
        result, pct, analysis = kct_route.route_kct(pcb_bytes, timeout_s=_ROUTE_TIMEOUT_S)
        (out / f"6_iter{iter_count}_{pct}pct.kicad_pcb").write_bytes(result)
        return result, pct, analysis

    rescued, pct, steps = rescue_with_placement_feedback(
        routed, route_fn=route_fn, max_iterations=3, decide=decide)
    (out / "6_rescued.kicad_pcb").write_bytes(rescued)
    (out / "6_steps.log").write_text("\n".join(steps), encoding="utf-8")
    print(f"[6/8] sauvetage  : {pct}%")
    return stages_7_to_8(out, rescued)


def stages_7_to_8(out: Path, board: bytes) -> int:
    # ⑦ DRC — kicad-tools 27 règles JLCPCB + kicad-cli auto-fix
    drc = run_drc_auto(DRCAutoRequest(kicad_pcb_b64=_b64(board)))
    (out / "7_drc_report.json").write_text(drc.model_dump_json(indent=2), encoding="utf-8")
    print(f"[7/8] DRC        : clean={drc.drc_clean} violations={len(drc.violations)}"
          f" fixed={drc.fixed_count}{' (skipped)' if drc.skipped else ''}")
    if drc.kicad_pcb_b64:                                     # board auto-fixé
        board = base64.b64decode(drc.kicad_pcb_b64)

    # ⑧ export — Gerbers + drill + BOM/CPL (kct export → kicad-cli)
    exp = export_all(ExportAllRequest(kicad_pcb_b64=_b64(board), project_id="stm32-full"))
    exp_dir = out / "8_export"
    exp_dir.mkdir(exist_ok=True)
    if exp.zip_b64:
        (exp_dir / "gerbers.zip").write_bytes(base64.b64decode(exp.zip_b64))
    (exp_dir / "manifest.json").write_text(
        exp.model_dump_json(indent=2, exclude={"zip_b64"}), encoding="utf-8")
    print(f"[8/8] export     : {len(exp.files)} fichiers, quote=${exp.quote_usd}"
          f"{' (skipped)' if exp.skipped else ''}")
    print(f"\nPipeline complet terminé → {out}")
    return 0


def main() -> int:
    circuit, out = Path(sys.argv[1]), Path(sys.argv[2])
    if "--rescue" in sys.argv:
        return stage_6_rescue(out, Path(sys.argv[sys.argv.index("--rescue") + 1]))
    return stages_1_to_6(circuit, out)


if __name__ == "__main__":
    raise SystemExit(main())
