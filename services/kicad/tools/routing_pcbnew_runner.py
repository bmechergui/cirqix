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
        # ⚠️ Selon le board, `board.Zones()` rend des `ZONE` types ou de
        # simples `SwigPyObject` sans methodes — constate le 2026-08-21 sur
        # un board issu de `kct stitch` :
        #     AttributeError: 'SwigPyObject' object has no attribute
        #                     'SetIsFilled'
        # On ne force le drapeau que s il est atteignable : `ZONE_FILLER.Fill`
        # le pose de toute facon. Le nom differe aussi entre KiCad 9
        # (`SetFilled`) et 10 (`SetIsFilled`).
        marque = getattr(zone, "SetIsFilled", None) or getattr(zone, "SetFilled", None)
        if marque is not None:
            marque(True)
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    pcbnew.SaveBoard(args["output"], board)


def _connected_pads(connectivity, pad, pcbnew):
    """Pads relies au pad donne, quelle que soit la version de KiCad.

    ⚠️ `GetConnectedItems()` a change de signature. Lue dans la bibliotheque
    du conteneur (KiCad 10) :

        GetConnectedItems(self, aItem, int aFlags=0)

    La liste de types a disparu : KiCad 10 rend TOUS les items relies, et le
    filtrage revient a l appelant. KiCad 9, lui, exigeait cette liste. On
    tente donc la forme recente puis l ancienne, et on filtre en Python dans
    les deux cas — un filtre local est correct partout.

    Defaut reste invisible : cette mesure ne sert qu aux chemins FREEROUTING,
    morts jusqu au 2026-08-21. Garde : tests/test_mesure_connectivite.py.
    """
    try:
        # KiCad 10 : rend TOUS les items relies, le filtrage revient a l appelant.
        items = connectivity.GetConnectedItems(pad)
        return [i for i in items if i.Type() == pcbnew.PCB_PAD_T]
    except TypeError:
        # KiCad 9 : la liste de types est exigee, et le filtrage est fait par
        # la bibliotheque — inutile de refiltrer ici.
        return connectivity.GetConnectedItems(pad, [pcbnew.PCB_PAD_T])


def _escape_pads(pcbnew, args: dict[str, str]) -> None:
    """Fanout : une courte piste depuis chaque broche isolee vers un via.

    Le plan ne peut pas atteindre les pattes d un boitier au pas de 0,5 mm, et
    le routeur ne les route pas non plus puisqu il tient le net pour « pris en
    charge par le plan ». La reponse standard est le fanout : sortir la patte
    par une courte piste, puis traverser par un via jusqu au plan de l autre
    face.

    La direction pointe a l OPPOSE du centre du boitier — c est le canal que le
    halo d escape du placement a justement reserve.

    ⚠️ Reparation, jamais regression : chaque via est pose independamment, et un
    pad introuvable est ignore sans faire echouer les autres.
    """
    board = pcbnew.LoadBoard(args["pcb"])
    cibles = json.loads(args["pads"])
    largeur = int(float(args.get("trace_mm", "0.25")) * 1_000_000)
    distance = float(args.get("escape_mm", "1.2")) * 1_000_000
    via_d = int(float(args.get("via_mm", "0.6")) * 1_000_000)
    perc_d = int(float(args.get("drill_mm", "0.3")) * 1_000_000)

    poses = 0
    for ref, nom_pad in cibles:
        fp = board.FindFootprintByReference(str(ref))
        if fp is None:
            continue
        pad = next((p for p in fp.Pads() if str(p.GetPadName()) == str(nom_pad)), None)
        if pad is None:
            continue

        centre = fp.GetPosition()
        pos = pad.GetPosition()
        dx = float(pos.x - centre.x)
        dy = float(pos.y - centre.y)
        norme = (dx * dx + dy * dy) ** 0.5
        if norme < 1.0:
            continue  # pad au centre exact : pas de direction de sortie evidente
        vx = int(pos.x + dx / norme * distance)
        vy = int(pos.y + dy / norme * distance)

        piste = pcbnew.PCB_TRACK(board)
        piste.SetStart(pos)
        piste.SetEnd(pcbnew.VECTOR2I(vx, vy))
        piste.SetWidth(largeur)
        piste.SetLayer(pad.GetLayer())
        piste.SetNetCode(pad.GetNetCode())
        board.Add(piste)

        via = pcbnew.PCB_VIA(board)
        via.SetPosition(pcbnew.VECTOR2I(vx, vy))
        via.SetWidth(via_d)
        via.SetDrill(perc_d)
        via.SetNetCode(pad.GetNetCode())
        board.Add(via)
        poses += 1

    pcbnew.SaveBoard(args["output"], board)
    Path(args["result"]).write_text(json.dumps({"escaped": poses}), encoding="utf-8")


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
            for pad in _connected_pads(connectivity, first_pad, pcbnew)
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
    elif operation == "escape_pads":
        _escape_pads(pcbnew, args)
    elif operation == "measure_connectivity":
        _measure_connectivity(pcbnew, args)
    else:
        raise ValueError(f"unsupported operation: {operation!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
