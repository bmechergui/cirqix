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


def _fill_zones(pcbnew, args: dict[str, str]) -> None:
    """Remplit les zones de CUIVRE. Sans cela un plan n est qu un contour."""
    board = pcbnew.LoadBoard(args["pcb"])
    # ⚠️ `SetIsFilled(True)` DECLARE la zone remplie sans calculer un seul
    # polygone : le fichier sort avec des zones et zero `filled_polygon`.
    # C est exactement le defaut trouve le 2026-08-23. Seul `ZONE_FILLER.Fill`
    # produit du cuivre ; le drapeau ne sert qu a autoriser le calcul.
    for zone in board.Zones():
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


# Geometrie de l echappement — PURE, sans pcbnew, donc testable.
#
# ⚠️ Pose a l aveugle, le fanout ajoutait 6 ERREURS dont deux courts-circuits
# GND/+3.3V (mesure du 2026-08-23, board STM32). Choisir une direction de
# sortie est de la geometrie : on la separe de la manipulation de board.
_ROTATIONS = tuple(range(0, 360, 15))   # la naturelle d abord, puis on tourne
_ECHANTILLON = 100_000                  # 0,1 mm entre deux points du trajet
# Facteurs de distance essayes, la nominale d abord. Une sortie n est pas
# seulement une DIRECTION : a direction egale, quelques dixiemes de plus ou de
# moins font passer le via entre deux obstacles ou non. Mesure du 2026-08-23 :
# a distance unique, 2 pastilles du LQFP-48 restaient orphelines a chaque
# tirage. Rallonger SEULEMENT (1,2 -> 2,0 mm) avait empire le resultat — il
# faut pouvoir raccourcir aussi.
_FACTEURS = (1.0, 0.8, 1.25, 0.65, 1.5)


def _dist_point_boite(x: float, y: float, boite) -> float:
    """Distance d un point a une boite (gauche, haut, droite, bas). 0 si dedans."""
    gauche, haut, droite, bas = boite
    dx = max(gauche - x, 0.0, x - droite)
    dy = max(haut - y, 0.0, y - bas)
    return (dx * dx + dy * dy) ** 0.5


def _trajet_libre(x0, y0, x1, y1, obstacles, marge, exempt=None) -> bool:
    """Vrai si tout le segment reste a `marge` des obstacles d un autre net.

    ⚠️ `exempt` est la boite du PAD lui-meme, et l exemption est necessaire :
    sur un LQFP-48 les pastilles font 0,3 mm au pas de 0,5 — 0,2 mm d espace
    entre deux voisines. Le long de sa propre pastille, la piste d echappement
    (0,25 mm) reste DANS l empreinte du pad : sa distance aux voisines est
    celle du pad, que la carte accepte deja. Sans cette exemption le controle
    echoue des le point de depart et AUCUNE broche fine-pitch ne peut sortir
    — mesure du 2026-08-23 : 0 broche sortie, 3 connexions manquantes.

    Au-dela du pad, la marge pleine s applique : c est la que le via se pose
    et que les courts-circuits se creaient.
    """
    if not obstacles:
        return True
    dx, dy = x1 - x0, y1 - y0
    longueur = (dx * dx + dy * dy) ** 0.5
    pas = max(2, int(longueur / _ECHANTILLON) + 1)
    for i in range(pas + 1):
        t = i / pas
        px, py = x0 + dx * t, y0 + dy * t
        if exempt is not None and _dist_point_boite(px, py, exempt) == 0:
            continue  # dans sa propre pastille : la clearance est celle du pad
        for boite in obstacles:
            if _dist_point_boite(px, py, boite) < marge:
                return False
    return True


def _choisir_sortie(x0, y0, vx, vy, distance, obstacles, marge, exempt=None):
    """Premiere direction dont le trajet ENTIER est degage, sinon None.

    La direction naturelle (a l oppose du centre du boitier) est essayee en
    premier : c est le canal que le halo d escape du placement a reserve. On
    ne tourne que si elle est occupee.

    ⚠️ Rendre None est un resultat LEGITIME : ne rien poser vaut mieux qu un
    court-circuit. Une broche orpheline se voit au DRC et bloque la commande ;
    un court-circuit peut partir en fabrication.
    """
    import math
    norme = (vx * vx + vy * vy) ** 0.5
    if norme < 1e-9:
        return None
    base = math.atan2(vy / norme, vx / norme)
    # ⚠️ La DIRECTION prime sur la longueur : on epuise toutes les distances
    # d une direction avant de tourner. Le couloir reserve par le halo
    # d escape du placement vaut mieux qu une deviation — l ordre inverse
    # faisait devier de 45 degres la ou raccourcir de 0,4 mm suffisait.
    for degres in _ROTATIONS:
        for signe in ((1, -1) if degres else (1,)):
            angle = base + math.radians(degres) * signe
            for facteur in _FACTEURS:
                x1 = x0 + math.cos(angle) * distance * facteur
                y1 = y0 + math.sin(angle) * distance * facteur
                if _trajet_libre(x0, y0, x1, y1, obstacles, marge, exempt):
                    return int(x1), int(y1)
    return None


def _obstacles_d_un_autre_net(board, net_code) -> list:
    """Boites englobantes des pistes, vias et pads d un AUTRE net."""
    boites = []
    for item in list(board.GetTracks()) + [
        p for fp in board.GetFootprints() for p in fp.Pads()
    ]:
        try:
            if item.GetNetCode() == net_code:
                continue
            b = item.GetBoundingBox()
            boites.append((b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom()))
        except Exception:
            continue  # un item sans boite ni net ne peut pas etre un obstacle connu
    return boites

def _escape_pads(pcbnew, args: dict[str, str]) -> None:
    """Fanout : une courte piste depuis chaque broche isolee vers un via.

    Le plan ne peut pas atteindre les pattes d un boitier au pas de 0,5 mm.
    On sort donc la patte par une courte piste, puis on traverse par un via.

    ⚠️ La sortie CONSULTE son environnement (`_choisir_sortie`). Posee a
    l aveugle — direction opposee au centre, sans regarder le trajet — elle
    ajoutait 6 ERREURS dont deux courts-circuits GND/+3.3V sur le board STM32
    (mesure du 2026-08-23). Une broche sans sortie degagee est RENONCEE, pas
    forcee : orpheline elle bloque la commande au DRC, court-circuitee elle
    peut partir en fabrication.
    """
    board = pcbnew.LoadBoard(args["pcb"])
    cibles = json.loads(args["pads"])
    largeur = int(float(args.get("trace_mm", "0.25")) * 1_000_000)
    distance = float(args.get("escape_mm", "1.2")) * 1_000_000
    via_d = int(float(args.get("via_mm", "0.6")) * 1_000_000)
    perc_d = int(float(args.get("drill_mm", "0.3")) * 1_000_000)
    # Marge : demi-via + clearance visee. Le DRC fautif mesurait 0,0181 mm.
    marge = via_d / 2 + float(args.get("clearance_mm", "0.2")) * 1_000_000

    poses = 0
    renonces = 0
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
        if (dx * dx + dy * dy) ** 0.5 < 1.0:
            continue  # pad au centre exact : pas de direction de sortie evidente

        obstacles = _obstacles_d_un_autre_net(board, pad.GetNetCode())
        b = pad.GetBoundingBox()
        propre = (b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom())
        sortie = _choisir_sortie(
            pos.x, pos.y, dx, dy, distance, obstacles, marge, propre
        )
        if sortie is None:
            renonces += 1
            continue
        vx, vy = sortie

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
    Path(args["result"]).write_text(
        json.dumps({"escaped": poses, "renonces": renonces}), encoding="utf-8"
    )


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
    elif operation == "fill_zones":
        _fill_zones(pcbnew, args)
    elif operation == "escape_pads":
        _escape_pads(pcbnew, args)
    elif operation == "measure_connectivity":
        _measure_connectivity(pcbnew, args)
    else:
        raise ValueError(f"unsupported operation: {operation!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
