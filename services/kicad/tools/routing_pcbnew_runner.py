#!/usr/bin/env python3
"""Run routing-related pcbnew work in a short-lived isolated process.

Usage (internal): ``python routing_pcbnew_runner.py '<json>'``.
All inputs and outputs are file paths.  The parent process owns the timeout and
temporary directory, so a hung or crashing pcbnew instance cannot corrupt an
uvicorn worker that is concurrently serving other routing requests.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def _export_specctra(pcbnew, args: dict[str, str]) -> None:
    board = pcbnew.LoadBoard(args["pcb"])
    for track in list(board.GetTracks()):
        board.Remove(track)
    pcbnew.ExportSpecctraDSN(board, args["dsn"])


def _specctra_roundtrip(pcbnew, args: dict[str, str]) -> None:
    board = pcbnew.LoadBoard(args["pcb"])
    # Freerouting's SES replaces every old route; retaining stale tracks can
    # create dangling ends after placement changes.
    for track in list(board.GetTracks()):
        board.Remove(track)
    pcbnew.ImportSpecctraSES(board, args["ses"])
    for zone in board.Zones():
        # KiCad 10 : ZONE.SetFilled a disparu (renomme SetIsFilled) ; sous
        # KiCad 9 les deux existent. La boucle ne s executait JAMAIS —
        # aucun board de la chaine ne portait de zone — donc l erreur est
        # restee invisible jusqu au 2026-08-21, ou les plans de masse
        # coules avant le routage l ont declenchee : le processus enfant
        # sortait en AttributeError et Freerouting echouait aux deux
        # niveaux. Garde : tests/test_zone_setisfilled.py.
        zone.SetIsFilled(True)
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    pcbnew.SaveBoard(args["output"], board)


def _measure_connectivity(pcbnew, args: dict[str, str]) -> None:
    board = pcbnew.LoadBoard(args["pcb"])
    if not board.BuildConnectivity():
        raise RuntimeError("pcbnew failed to build board connectivity")
    connectivity = board.GetConnectivity()
    connectivity.RecalculateRatsnest()

    pads_by_net: dict[int, list] = defaultdict(list)
    for footprint in board.GetFootprints():
        for pad in footprint.Pads():
            net_code = int(pad.GetNetCode())
            if net_code > 0:
                pads_by_net[net_code].append(pad)

    unrouted_nets = 0
    for net_pads in pads_by_net.values():
        if len(net_pads) < 2:
            continue
        first_pad = net_pads[0]
        # GetConnectedPads() only returns directly touching pads.  A routed net
        # normally crosses a transitive pad -> tracks/vias -> pad chain, so use
        # KiCad's cluster search and ask it specifically for pad items.
        connected = {
            str(pad.m_Uuid.AsString())
            for pad in connectivity.GetConnectedItems(
                first_pad, [pcbnew.PCB_PAD_T], False
            )
            if int(pad.GetNetCode()) == int(first_pad.GetNetCode())
        }
        # Some KiCad versions omit the source item from GetConnectedItems().
        connected.add(str(first_pad.m_Uuid.AsString()))
        expected = {str(pad.m_Uuid.AsString()) for pad in net_pads}
        if not expected.issubset(connected):
            unrouted_nets += 1

    Path(args["result"]).write_text(
        json.dumps({"unrouted_nets": unrouted_nets}), encoding="utf-8"
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: routing_pcbnew_runner.py '<json>'", file=sys.stderr)
        return 64

    import pcbnew  # type: ignore[import-not-found]

    args = json.loads(argv[1])
    operation = args.get("operation")
    if operation == "export_specctra":
        _export_specctra(pcbnew, args)
    elif operation == "specctra_roundtrip":
        _specctra_roundtrip(pcbnew, args)
    elif operation == "measure_connectivity":
        _measure_connectivity(pcbnew, args)
    else:
        raise ValueError(f"unsupported operation: {operation!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
