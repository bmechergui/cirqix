#!/usr/bin/env python3
"""A/B : plan de masse sur les DEUX faces, ou sur B.Cu seule ?

⚠️ Question ouverte, listee « en attente » dans `docs/DECISIONS.md`. Elle est
posee par une mesure repetee : sur `stm32-100` comme sur `nucleo-f401`, le
DERNIER pourcent manquant est toujours GND, et toujours un seul net.

    stm32-100   tirage a 99 %   « 1 net incomplet sur 79 ; net(s) : GND »
    nucleo-f401 remesure 98 %   1 connexion manquante, 0 erreur

Hypothese a tester : un plan sur F.Cu, sous un boitier fine-pitch, coute plus
qu il ne rapporte — les pistes de signal le decoupent, et les broches que le
plan devait prendre en charge ne sont plus atteignables. Sur B.Cu seule, le
routeur dispose de toute la face composants.

⚠️ **CRITERE DE SUCCES : `unconnected_items` sur GND au DRC. PAS le compte
d ilots.** Mesure du 2026-08-30 sur le board `stm32-100` LIVRE a 100 %, 0
connexion manquante, 0 erreur :

    GND  F.Cu  6 ilots  ·  B.Cu  1 ilot  ·  25 vias GND, 0 borgne

Une carte parfaitement connectee porte six ilots. Le compte d ilots reste
releve, en INDICATEUR DE QUALITE de la reference de retour — jamais en verdict.

⚠️ **On part d un board DEJA PLACE, et du MEME pour les deux conditions.** Le
placement est stochastique (6, 8 et 12 connexions manquantes selon le tirage
sur une meme carte) : re-placer entre les deux conditions ferait mesurer le
placement au lieu de l empilage.

Usage :
    python3 scripts/ab_plan_de_masse.py <board_place.kicad_pcb> [budget_s]
"""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402
from routers.routing import RouteAutoRequest, route_auto  # noqa: E402

# Les deux conditions. T0 est l existant, et sert de TEMOIN : sans lui on
# attribuerait a l empilage un ecart qui appartient au tirage.
_CONDITIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("T0  F.Cu + B.Cu  (existant)", ("F.Cu", "B.Cu")),
    ("T1  B.Cu seule", ("B.Cu",)),
)


def _gnd_manquantes(rapport: dict) -> tuple[int, int]:
    """(connexions manquantes GND, total) — le critere, et son contexte."""
    items = rapport.get("unconnected_items", []) or []
    gnd = 0
    for it in items:
        blob = json.dumps(it).upper()
        if "GND" in blob:
            gnd += 1
    return gnd, len(items)


def _mesurer(board: bytes, budget: float) -> dict:
    t0 = time.time()
    res = route_auto(RouteAutoRequest(kicad_pcb_b64=base64.b64encode(board).decode(),
                                      layers=8, timeout_s=budget))
    duree = time.time() - t0
    if not res.kicad_pcb_b64:
        return {"erreur": res.warning or "aucun board rendu", "duree": duree}
    final = base64.b64decode(res.kicad_pcb_b64)
    rapport = R._rapport_drc(final)
    violations = rapport.get("violations", []) or []
    gnd, total = _gnd_manquantes(rapport)
    return {
        "pct": res.routed_percent,
        "couches": res.layers,
        "gnd_manquantes": gnd,
        "manquantes": total,
        "erreurs": sum(1 for v in violations if v.get("severity") == "error"),
        # Indicateur de qualite seulement — jamais un verdict.
        "ilots": R._compte_ilots_de_plan(final),
        "duree": duree,
        "board": final,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    entree = Path(argv[1])
    if not entree.is_file():
        print("board introuvable : %s" % entree, file=sys.stderr)
        return 2
    budget = float(argv[2]) if len(argv) > 2 else 1800.0
    board = entree.read_bytes()

    print("A/B plan de masse — board place : %s" % entree)
    print("budget par condition : %.0f s\n" % budget)
    print("%-28s %5s %8s %6s %6s %5s %9s" % (
        "condition", "%", "couches", "GNDmq", "mq", "err", "duree"))

    memoire = R._GROUND_PLANE_LAYERS
    resultats = {}
    try:
        for nom, couches in _CONDITIONS:
            R._GROUND_PLANE_LAYERS = couches
            r = _mesurer(board, budget)
            resultats[nom] = r
            if "erreur" in r:
                print("%-28s ECHEC %s" % (nom, r["erreur"][:50]))
                continue
            print("%-28s %5d %8d %6d %6d %5d %8.1fs" % (
                nom, r["pct"], r["couches"], r["gnd_manquantes"],
                r["manquantes"], r["erreurs"], r["duree"]))
            sortie = entree.parent / ("ab_%s.kicad_pcb" % nom.split()[0].lower())
            sortie.write_bytes(r.pop("board"))
    finally:
        R._GROUND_PLANE_LAYERS = memoire

    print("\nilots de plan (INDICATEUR de reference de retour, pas un verdict) :")
    for nom, r in resultats.items():
        if "ilots" in r:
            print("   %-28s %s" % (nom, r["ilots"]))

    bons = {n: r for n, r in resultats.items() if "erreur" not in r}
    if len(bons) == 2:
        t0, t1 = (bons[n] for n, _ in _CONDITIONS)
        print("\nVERDICT sur le critere (connexions GND manquantes) :")
        if t1["gnd_manquantes"] < t0["gnd_manquantes"]:
            print("   T1 (B.Cu seule) fait MIEUX : %d contre %d."
                  % (t1["gnd_manquantes"], t0["gnd_manquantes"]))
            print("   -> l empilage devient un arbitrage produit a soumettre.")
        elif t1["gnd_manquantes"] > t0["gnd_manquantes"]:
            print("   T0 (existant) fait mieux : %d contre %d — hypothese refutee."
                  % (t0["gnd_manquantes"], t1["gnd_manquantes"]))
        else:
            print("   EGALITE (%d chacune) — l empilage n est pas le levier."
                  % t0["gnd_manquantes"])
        print("\n⚠️ UN SEUL TIRAGE PAR CONDITION. Freerouting est stochastique")
        print("   (65, 77 et 91 % sur le meme board) : un ecart de quelques")
        print("   points ne prouve rien. Seul un ecart NET, ou repete, compte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
