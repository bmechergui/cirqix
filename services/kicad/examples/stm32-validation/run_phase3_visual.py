#!/usr/bin/env python3
"""Génère le board STM32 réel et sauve un .kicad_pcb après CHAQUE phase du
pipeline placement (tools/placement.py::auto_place), pour inspection visuelle
dans KiCad — pas un test automatisé, juste une sortie comparative manuelle.

    output/phase3/0_gen.kicad_pcb           <- board brut (call_agent_gen_pcb)
    output/phase3/1_architecte.kicad_pcb    <- hybrid+cluster + Inspecteur (0 erreur garanti)
    output/phase3/2_geometre_brut.kicad_pcb <- CMA-ES, AVANT l'Inspecteur (peut avoir des conflits)
    output/phase3/3_final.kicad_pcb         <- résultat livré par auto_place() (= ce que reçoit l'agent)
    output/phase3/report.txt                <- conflits + distances avant/après par étape

Usage : python run_phase3_visual.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[2]  # services/kicad
sys.path.insert(0, str(_SERVICE_ROOT))
sys.path.insert(0, str(_SERVICE_ROOT / "kicad-tools" / "src"))

import tools.placement as placement_mod  # noqa: E402
from kicad_tools.placement.analyzer import DesignRules, PlacementAnalyzer  # noqa: E402
from kicad_tools.placement.conflict import ConflictSeverity  # noqa: E402
from kicad_tools.schema.pcb import PCB  # noqa: E402

_BOARD_W_MM, _BOARD_H_MM = 60.0, 40.0


def _conflicts(path: Path) -> tuple[int, int]:
    rules = DesignRules()
    cs = PlacementAnalyzer().find_conflicts(str(path), rules)
    err = sum(1 for c in cs if c.severity == ConflictSeverity.ERROR)
    warn = sum(1 for c in cs if c.severity == ConflictSeverity.WARNING)
    return err, warn


def main() -> int:
    out = Path(__file__).parent / "output" / "phase3"
    out.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("STAGE 0 — génération du board STM32 réel")
    print("=" * 60)
    gen_dir = out / "_gen"
    gen_dir.mkdir(exist_ok=True)
    generate_script = Path(__file__).parent / "input" / "generate_design.py"
    result = subprocess.run([sys.executable, str(generate_script), str(gen_dir)], check=False)
    if result.returncode != 0:
        print("Échec génération.")
        return 1

    gen_board = gen_dir / "stm32_devboard.kicad_pcb"
    if not gen_board.exists():
        print(f"Erreur : {gen_board} non généré.")
        return 1

    board0 = out / "0_gen.kicad_pcb"
    board0.write_bytes(gen_board.read_bytes())

    pcb = PCB.load(str(board0))
    conn = placement_mod._connector_refs(pcb)

    report: list[str] = []

    print("\n" + "=" * 60)
    print("STAGE 1 — Architecte (hybrid+cluster) + Inspecteur")
    print("=" * 60)
    from kicad_tools.optim import OptimizationWorkflow, WorkflowConfig

    placement_mod._clamp_fixed_refs_to_outline(pcb, conn)
    cfg = WorkflowConfig(
        strategy="hybrid", enable_clustering=True, fixed_refs=conn,
        iterations=placement_mod._WF_ITERATIONS,
        generations=placement_mod._WF_GENERATIONS,
        population=placement_mod._WF_POPULATION,
    )
    workflow = OptimizationWorkflow(pcb=pcb, config=cfg)
    workflow.run()
    workflow.write_to_pcb()

    board1 = out / "1_architecte.kicad_pcb"
    pcb.save(str(board1))
    n_before, n_after = placement_mod._resolve_remaining_conflicts(board1, conn)
    err1, warn1 = _conflicts(board1)
    report.append(f"Architecte (avant fix)      : {n_before} ERROR")
    report.append(f"Architecte (après Inspecteur): {err1} ERROR / {warn1} WARNING (garanti 0 ERROR)")
    print(f"  -> {board1.name} : {err1} ERROR / {warn1} WARNING")

    print("\n" + "=" * 60)
    print("STAGE 2 — Géomètre (CMA-ES, seed=current)")
    print("=" * 60)
    board2 = out / "2_geometre_brut.kicad_pcb"
    board2.write_bytes(board1.read_bytes())
    refine = placement_mod._refine_with_cmaes(board2, conn, time_budget_s=placement_mod._CMAES_TIME_BUDGET_S)
    err2, warn2 = _conflicts(board2)
    report.append(f"Géomètre brut (refined={refine['refined']}, {refine['elapsed_s']:.1f}s) : {err2} ERROR / {warn2} WARNING")
    print(f"  -> {board2.name} : refined={refine['refined']} ({refine['elapsed_s']:.1f}s), {err2} ERROR / {warn2} WARNING")

    print("\n" + "=" * 60)
    print("STAGE 3 — pipeline complet auto_place() (= ce que reçoit l'agent)")
    print("=" * 60)
    import base64
    b64 = base64.b64encode(board0.read_bytes()).decode()
    result = placement_mod.auto_place(b64, _BOARD_W_MM, _BOARD_H_MM)
    board3 = out / "3_final.kicad_pcb"
    board3.write_bytes(base64.b64decode(result["kicad_pcb_b64"]))
    err3, warn3 = _conflicts(board3)
    report.append(f"Final auto_place()         : {err3} ERROR / {warn3} WARNING ({result['placed_count']} composants)")
    print(f"  -> {board3.name} : {err3} ERROR / {warn3} WARNING")

    (out / "report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\nRapport : " + str(out / "report.txt"))
    print("Ouvrir dans KiCad : " + str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
