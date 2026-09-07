#!/usr/bin/env python3
"""Route UN board place, par la voie HTTP reelle du service.

Ce script s execute DANS le conteneur, la ou vit `KICAD_SERVICE_TOKEN` : le
secret n a donc jamais a passer par l hote ni par une ligne de commande.

⚠️ ON PASSE PAR HTTP, PAS PAR UN IMPORT PYTHON. `banc_exemples.py` importe
`route_auto` et n exerce donc JAMAIS la voie HTTP — les huit cartes « a 100 % »
du 2026-09-03 etaient vertes pendant que cette voie mourait une fois sur deux.
Seuls le worker et l orchestrateur passent par HTTP en production ; c est cette
voie-la qu il faut prouver.

Usage : python3 _router_un.py <entree.kicad_pcb> <sortie.kicad_pcb> <budget_s>
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request

_URL = "http://127.0.0.1:8766/route/auto"


def main(argv: list[str]) -> int:
    entree, sortie, budget = argv[1], argv[2], int(argv[3])

    jeton = os.environ.get("KICAD_SERVICE_TOKEN", "")
    if not jeton:
        # ⚠️ Echouer ferme. Sans jeton la route repond 401, et un 401 lu comme
        # « pas de board » ressemblerait a un routage impossible.
        print(json.dumps({"erreur": "KICAD_SERVICE_TOKEN absent du conteneur"}))
        return 2

    with open(entree, "rb") as f:
        board = f.read()

    corps = json.dumps({
        "kicad_pcb_b64": base64.b64encode(board).decode("ascii"),
        # ⚠️ `layers` est un PLAFOND, jamais le palier vise : le service part
        # toujours de 2 et n escalade que sur preuve d echec, en gardant le
        # MEILLEUR tirage. Lui en offrir 8 ne lui en fait pas vendre 8.
        "layers": 8,
        "timeout_s": budget,
    }).encode("utf-8")

    requete = urllib.request.Request(_URL, data=corps, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + jeton,
    })

    try:
        with urllib.request.urlopen(requete, timeout=budget + 600) as rep:
            resultat = json.loads(rep.read())
    except urllib.error.HTTPError as e:
        print(json.dumps({"erreur": "HTTP %d" % e.code,
                          "detail": e.read()[:400].decode("utf-8", "replace")}))
        return 1
    except Exception as e:  # noqa: BLE001 — on veut la cause, quelle qu elle soit
        print(json.dumps({"erreur": type(e).__name__, "detail": str(e)[:400]}))
        return 1

    b64 = resultat.get("routed_pcb_b64") or resultat.get("kicad_pcb_b64")
    if not b64:
        # Le service peut ne rendre AUCUN board — c est son contrat quand tous
        # les tirages echouent. On le DIT, on n ecrit pas un fichier vide.
        print(json.dumps({"erreur": "aucun board rendu",
                          "reponse": {k: v for k, v in resultat.items()
                                      if not isinstance(v, str) or len(v) < 200}}))
        return 1

    with open(sortie, "wb") as f:
        f.write(base64.b64decode(b64))

    print(json.dumps({
        "routed_percent": resultat.get("routed_percent"),
        "couches": resultat.get("layers"),
        "vias": resultat.get("via_count"),
        "longueur_mm": resultat.get("track_length_mm"),
        "moteur": resultat.get("engine"),
        "note": str(resultat.get("note", ""))[:200],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
