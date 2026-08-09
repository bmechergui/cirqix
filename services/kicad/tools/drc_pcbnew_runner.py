#!/usr/bin/env python3
"""Run the DRC zone-refill pcbnew work in a short-lived isolated process.

Usage (internal): ``python drc_pcbnew_runner.py '<json>'`` with
``{"pcb": <in path>, "output": <out path>}``. All I/O goes through files.

Why a child process at all: ``pcbnew`` keeps global C++ state and is NOT
thread-safe, while ``run_drc_auto`` is a plain ``def`` FastAPI handler and
therefore runs in uvicorn's threadpool -- several requests can hit the same
worker concurrently. The parent owns the timeout, so a hung or crashing
pcbnew cannot take the worker down with it. Same pattern as
``cmaes_runner.py``, which exists in this repository for the same reason.
"""
from __future__ import annotations

import json
import sys


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: drc_pcbnew_runner.py '<json>'", file=sys.stderr)
        return 2
    args = json.loads(argv[1])

    import pcbnew  # noqa: PLC0415 -- deliberately inside the child process

    board = pcbnew.LoadBoard(args["pcb"])
    for zone in board.Zones():
        # KiCad 10: ZONE.SetFilled is gone (renamed SetIsFilled); under KiCad 9
        # both exist. Force the "filled" flag, then ZONE_FILLER.Fill computes
        # the actual fill right after.
        zone.SetIsFilled(True)
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    pcbnew.SaveBoard(args["output"], board)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
