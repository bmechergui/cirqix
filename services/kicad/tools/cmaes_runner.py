#!/usr/bin/env python3
"""Exécute ``run_optimize_placement`` dans un PROCESSUS dédié.

Pourquoi un processus et pas un simple appel
--------------------------------------------
``run_optimize_placement`` installe des handlers de signal
(``signal.signal(SIGINT/SIGTERM, …)``) dès son entrée. Or ``signal.signal`` n'est
autorisé que dans le thread principal de l'interpréteur principal, et uvicorn
exécute ``auto_place`` dans un thread de worker : l'appel lève donc
``ValueError: signal only works in main thread of the main interpreter`` AVANT la
moindre itération d'optimisation.

Constaté en conteneur le 2026-07-27 : le filet de sécurité de ``auto_place``
rattrapait l'exception et conservait le board pré-CMA-ES, si bien que l'étape
« Géomètre » ne s'exécutait **jamais** en production — alors que ses tests, eux,
tournaient dans le thread principal de pytest et passaient.

Un processus enfant a un vrai thread principal : les handlers s'installent, le
CMA-ES tourne.

Pourquoi pas le CLI ``kct optimize-placement``
----------------------------------------------
Le parseur du CLI n'accepte que ``--seed force-directed|random``. Le seeding sur
la position courante (``seed_method="current"``) est un patch Cirqix exposé
UNIQUEMENT côté API Python. Or c'est lui qui fait du CMA-ES un *raffinement* et
non un replacement depuis zéro — sans lui, la garde de déplacement
(``_CMAES_MAX_DISPLACEMENT_MM``) se déclencherait à chaque run. On appelle donc
l'API Python, mais depuis un processus enfant.

Usage (interne, appelé par ``tools/placement.py``) :
    python cmaes_runner.py '<json>'

JSON attendu : ``{"pcb", "output", "max_iterations", "time_budget"}``.
Code de sortie = celui de ``run_optimize_placement`` (0 = OK, 2 = interrompu
avec résultat partiel sauvegardé, autre = échec).
"""
from __future__ import annotations

import json
import sys


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: cmaes_runner.py '<json>'", file=sys.stderr)
        return 64

    from kicad_tools.cli.optimize_placement_cmd import run_optimize_placement

    args = json.loads(argv[1])
    return run_optimize_placement(
        args["pcb"],
        strategy_name="cmaes",
        seed_method="current",
        output_path=args["output"],
        max_iterations=args["max_iterations"],
        time_budget=args["time_budget"],
        quiet=True,
        allow_infeasible=True,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
