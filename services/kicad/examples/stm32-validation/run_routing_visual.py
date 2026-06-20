#!/usr/bin/env python3
"""Route + finit le board STM32 à partir du PLACEMENT FINAL
(output/phase3/3_final.kicad_pcb) — pour inspection visuelle dans KiCad.

Chaîne 100% native kicad-tools, escalade de couches NATIVE (pas de boucle custom) :

  ① kct route --auto-layers --max-layers 6 --auto-fix
       escalade native 2L → 4L → 4L-all-sig → 6L jusqu'à ce que le board route
       (le STM32 QFP-48 0.5mm ne s'échappe pas en 2 couches → passe en 4 tout seul)
  ② kct pipeline --layers <N résolu> --best-effort
       finition au nombre de couches trouvé par ① : fix-silkscreen, fix-vias,
       stitch des plans, optimize-traces, fix-drc, audit, export

Pourquoi pas le pipeline seul : `kct pipeline --layers auto` fige le board à
2 couches (pipeline_cmd.py: layer_count("auto")==2) → ne peut pas router ce
STM32. Seul `kct route --auto-layers` escalade nativement (route_cmd.py: tries
2L,4L,4L-all-sig,6L). On enchaîne donc route(escalade) → pipeline(finition).

Sorties :
  output/routage/4_routed.kicad_pcb   <- board routé par ① (au N de couches résolu)
  output/routage/5_pipeline.kicad_pcb <- board après finition pipeline ②
  output/routage/manufacturing/vN/    <- audit fab (report.md + JSON)
  output/routage/report.txt           <- couches résolues, signal %, DRC, verdict

⚠️ Local : routeur Python pur (kct build-native non compilé) → l'escalade 4L
peut être lente ; `zones fill`/`export` Gerber sautés sans kicad-cli. Docker
prod : backend C++ + kicad-cli → complet et rapide.

Usage : python run_routing_visual.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[2]  # services/kicad
_KCT_SRC = _SERVICE_ROOT / "kicad-tools" / "src"
sys.path.insert(0, str(_SERVICE_ROOT))
sys.path.insert(0, str(_KCT_SRC))

from tools.kct_route import parse_routed_pct  # noqa: E402

_ROUTE_TIMEOUT_S = 300
_ROUTE_FLAGS = ["--auto-layers", "--max-layers", "6", "--auto-fix", "--seed", "42"]


def _run(cmd: list[str], timeout_s: int) -> subprocess.CompletedProcess[str]:
    """Lance une commande kct enfant avec UTF-8 forcé (évite le crash charmap
    Windows sur les logs emoji — cf. tools/kct_route.py)."""
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": str(_KCT_SRC),
    }
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, check=False, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        # Dégrade proprement au lieu de crasher : sans backend C++ (kct
        # build-native) l'escalade 4L en Python pur peut dépasser le budget.
        # On garde la sortie partielle éventuelle du routeur.
        out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        print(f"  [timeout] commande tuée après {timeout_s}s (routeur Python pur trop lent).")
        return subprocess.CompletedProcess(cmd, returncode=-1, stdout=out, stderr="TIMEOUT")


def _copper_layer_count(pcb_path: Path) -> int:
    """Compte les couches cuivre déclarées (F.Cu, B.Cu, In*.Cu)."""
    t = pcb_path.read_text(encoding="utf-8", errors="replace")
    block = re.search(r"\(layers\b(.*?)\n\s*\)", t, re.DOTALL)
    scope = block.group(1) if block else t
    return len(re.findall(r'"(?:F|B|In\d+)\.Cu"', scope)) or 2


def _latest_manufacturing_data(out: Path) -> Path | None:
    versions = sorted(
        (out / "manufacturing").glob("v*/data"),
        key=lambda p: int(p.parent.name[1:]) if p.parent.name[1:].isdigit() else -1,
    )
    return versions[-1] if versions else None


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("data", {})
    except (OSError, ValueError):
        return {}


def main() -> int:
    example_dir = Path(__file__).parent
    placed = example_dir / "output" / "phase3" / "3_final.kicad_pcb"
    if not placed.exists():
        print(f"Erreur : placement final introuvable — {placed}")
        print("Lance d'abord : python run_phase3_visual.py")
        return 1

    out = example_dir / "output" / "routage"
    out.mkdir(parents=True, exist_ok=True)

    # ── ① ROUTE avec escalade native de couches ────────────────────────────
    print("=" * 60)
    print("① kct route --auto-layers --max-layers 6 (escalade native 2→4→6)")
    print("=" * 60)
    src = out / "_route_src.kicad_pcb"
    src.write_bytes(placed.read_bytes())
    routed = out / "4_routed.kicad_pcb"
    for old in out.glob("4_routed*.kicad_pcb"):
        old.unlink()

    cmd_route = [
        sys.executable, "-m", "kicad_tools.cli", "route",
        str(src), "-o", str(routed),
        *_ROUTE_FLAGS, "--timeout", str(_ROUTE_TIMEOUT_S),
    ]
    r = _run(cmd_route, timeout_s=_ROUTE_TIMEOUT_S + 120)

    # L'escalade renomme parfois la sortie (..._4layer.kicad_pcb) → on prend le
    # plus récent des candidats.
    candidates = sorted(out.glob("4_routed*.kicad_pcb"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        print("Échec : ① route n'a produit aucun board.")
        print((r.stderr or r.stdout)[-400:])
        src.unlink(missing_ok=True)
        return 1
    routed_file = candidates[-1]
    n_layers = _copper_layer_count(routed_file)
    routed_pct = parse_routed_pct(r.stdout)
    src.unlink(missing_ok=True)
    print(f"  -> {routed_file.name} : {routed_pct}% · {n_layers} couches cuivre")

    # ── ② PIPELINE de finition au nombre de couches résolu ──────────────────
    layers_arg = "auto" if n_layers <= 2 else ("6" if n_layers >= 6 else "4")
    print("\n" + "=" * 60)
    print(f"② kct pipeline --layers {layers_arg} --best-effort (finition)")
    print("=" * 60)
    board = out / "5_pipeline.kicad_pcb"
    board.write_bytes(routed_file.read_bytes())
    cmd_pipe = [
        sys.executable, "-m", "kicad_tools.cli", "pipeline",
        str(board), "--layers", layers_arg, "--best-effort",
    ]
    _run(cmd_pipe, timeout_s=_ROUTE_TIMEOUT_S + 120)
    if not board.exists():
        print("  [retry] board disparu en pipeline (fsync Windows) — relance.")
        board.write_bytes(routed_file.read_bytes())
        _run(cmd_pipe, timeout_s=_ROUTE_TIMEOUT_S + 120)

    # ── Rapport ─────────────────────────────────────────────────────────────
    data_dir = _latest_manufacturing_data(out)
    net_status = _load_json(data_dir / "net_status.json") if data_dir else {}
    drc = _load_json(data_dir / "drc_summary.json") if data_dir else {}
    audit = _load_json(data_dir / "audit.json") if data_dir else {}

    report = [
        "ROUTAGE STM32 — kct route --auto-layers (escalade native) + kct pipeline",
        "=" * 60,
        f"Input            : {placed.name} (placement final auto_place)",
        f"① Routé          : {routed_file.name} — {routed_pct}% · {n_layers} couches",
        f"② Finition       : {board.name} (pipeline --layers {layers_arg})",
        "",
        f"Signaux routés   : {net_status.get('signal_completion_percent', '?')}% "
        f"({net_status.get('signal_complete_count', '?')}/{net_status.get('signal_net_count', '?')} nets)",
        f"Connectivité     : {net_status.get('completion_percent', '?')}% "
        f"({net_status.get('complete_count', '?')}/{net_status.get('total_nets', '?')} nets)",
        f"DRC              : {drc.get('error_count', '?')} erreurs / "
        f"{drc.get('warning_count', '?')} warnings (passed={drc.get('passed', '?')})",
        f"Verdict fab      : {audit.get('verdict', '?')}",
    ]
    incomplete = net_status.get("signal_incomplete_net_names") or net_status.get("incomplete_net_names")
    if incomplete:
        report += ["", "Nets signaux incomplets :", "  " + ", ".join(incomplete)]
    (out / "report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    print(f"\n  -> {board.name} : {n_layers} couches · "
          f"{net_status.get('signal_completion_percent', '?')}% signaux · "
          f"DRC {drc.get('error_count', '?')} erreurs · verdict {audit.get('verdict', '?')}")
    print("Rapport : " + str(out / "report.txt"))
    if data_dir:
        print("Audit   : " + str(data_dir.parent / "report.md"))
    print("Ouvrir dans KiCad : " + str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
