#!/usr/bin/env python3
"""Route le board STM32 à partir du PLACEMENT FINAL (output/phase3/3_final.kicad_pcb,
= ce que reçoit l'agent routage) via le routeur OFFICIEL natif kct, et sauve la
sortie pour inspection visuelle dans KiCad — pas un test automatisé.

    output/routage/4_routed.kicad_pcb   <- board routé (kct route negotiated, auto-layers, auto-fix)
    output/routage/report.txt          <- routed %, segments, zones, nets non routés

Routeur = tools/kct_route.py::route_kct() — exactement la commande native que
l'agent routage (routers/routing.py) lance en prod : ``kct route --strategy
negotiated --auto-layers --auto-fix --seed 42``. Aucun Freerouting, aucun
post-traitement S-expr custom : la lib route les signaux ET coule les power nets
en zones cuivre elle-même.

Usage : python run_routing_visual.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[2]  # services/kicad
sys.path.insert(0, str(_SERVICE_ROOT))
sys.path.insert(0, str(_SERVICE_ROOT / "kicad-tools" / "src"))

from tools.kct_route import route_kct  # noqa: E402

_ROUTE_TIMEOUT_S = 120


def main() -> int:
    example_dir = Path(__file__).parent
    placed = example_dir / "output" / "phase3" / "3_final.kicad_pcb"
    if not placed.exists():
        print(f"Erreur : placement final introuvable — {placed}")
        print("Lance d'abord : python run_phase3_visual.py")
        return 1

    out = example_dir / "output" / "routage"
    out.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("ROUTAGE — kct route (negotiated, auto-layers, auto-fix, seed=42)")
    print("=" * 60)
    print(f"Input  : {placed}")

    pcb_bytes = placed.read_bytes()
    routed_bytes, routed_pct, failure_analysis = route_kct(
        pcb_bytes, timeout_s=_ROUTE_TIMEOUT_S
    )

    routed_board = out / "4_routed.kicad_pcb"
    routed_board.write_bytes(routed_bytes)

    routed_text = routed_bytes.decode("utf-8", errors="replace")
    seg_count = len(re.findall(r"\(segment[\s\n]", routed_text))
    via_count = len(re.findall(r"\(via[\s\n]", routed_text))
    zone_count = len(re.findall(r"\(zone[\s\n]", routed_text))

    report = [
        "ROUTAGE STM32 — kct route natif (negotiated / auto-layers / auto-fix / seed=42)",
        "=" * 60,
        f"Input            : {placed.name} (placement final auto_place)",
        f"Output           : {routed_board.name}",
        "",
        f"Routed           : {routed_pct}%",
        f"Segments         : {seg_count}",
        f"Vias             : {via_count}",
        f"Zones (power)    : {zone_count}",
    ]
    if failure_analysis:
        report.append("")
        report.append("Analyse d'échec (nets non routés) :")
        report.append("-" * 60)
        report.append(failure_analysis)
    else:
        report.append("")
        report.append("Tous les nets routés (100%).")

    (out / "report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    print(f"\n  -> {routed_board.name} : {routed_pct}% routé "
          f"({seg_count} segments, {via_count} vias, {zone_count} zones)")
    print("Rapport : " + str(out / "report.txt"))
    print("Ouvrir dans KiCad : " + str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
