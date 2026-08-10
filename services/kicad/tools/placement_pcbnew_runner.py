#!/usr/bin/env python3
"""Run explicit component placement (pcbnew) in a short-lived isolated process.

Usage (internal): ``python placement_pcbnew_runner.py '<json>'`` with
``{"pcb_path": ..., "components": [...], "output_path": ..., "result_path": ...}``.
The result dict of ``place_components`` is written as JSON to ``result_path``.

Why a child process: ``place_components`` imports ``pcbnew``, whose global C++
state is NOT thread-safe, and ``POST /place`` is a plain ``def`` FastAPI handler
-- uvicorn runs it in a threadpool, so concurrent requests share one worker.
The parent owns the timeout. Same pattern as ``cmaes_runner.py``.

The call is INDIRECT (`routers/placement.py` -> `tools.placement.place_components`),
which is exactly why a grep for "pcbnew" in `routers/` misses it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: placement_pcbnew_runner.py '<json>'", file=sys.stderr)
        return 2
    args = json.loads(argv[1])

    # Import inside the child: pcbnew must never be loaded by the parent.
    from tools.placement import place_components

    result = place_components(
        args["pcb_path"], args["components"], args["output_path"]
    )
    Path(args["result_path"]).write_text(
        json.dumps(result), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
