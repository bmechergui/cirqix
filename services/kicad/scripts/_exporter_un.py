#!/usr/bin/env python3
"""Exporte UN board livre, par la voie HTTP reelle du service.

S execute DANS le conteneur, la ou vit `KICAD_SERVICE_TOKEN` : le secret ne
transite jamais par l hote.

⚠️ ON PASSE PAR `/export/all`, PAS PAR `kicad-cli` EN DIRECT. C est la voie que
la production emprunte — kicad-tools `kct export --mfr jlcpcb` d abord, puis
`kicad-cli` en repli — et c est donc elle qu il faut prouver. Appeler
`kicad-cli` a la main prouverait que KiCad sait exporter, pas que Cirqix sait.

Usage : python3 _exporter_un.py <board.kicad_pcb> <sortie.zip>
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request

_URL = "http://127.0.0.1:8766/export/all"


def main(argv: list[str]) -> int:
    entree, sortie = argv[1], argv[2]

    jeton = os.environ.get("KICAD_SERVICE_TOKEN", "")
    if not jeton:
        # Echouer ferme : sans jeton la route repond 401, et un 401 lu comme
        # « rien a exporter » ressemblerait a un board vide.
        print(json.dumps({"erreur": "KICAD_SERVICE_TOKEN absent du conteneur"}))
        return 2

    with open(entree, "rb") as f:
        board = f.read()

    corps = json.dumps({
        "kicad_pcb_b64": base64.b64encode(board).decode("ascii"),
    }).encode("utf-8")

    requete = urllib.request.Request(_URL, data=corps, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + jeton,
    })

    try:
        with urllib.request.urlopen(requete, timeout=900) as rep:
            resultat = json.loads(rep.read())
    except urllib.error.HTTPError as e:
        print(json.dumps({"erreur": "HTTP %d" % e.code,
                          "detail": e.read()[:400].decode("utf-8", "replace")}))
        return 1
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"erreur": type(e).__name__, "detail": str(e)[:400]}))
        return 1

    b64 = resultat.get("zip_b64") or resultat.get("gerber_zip_b64")
    if not b64:
        # ⚠️ `PCB_LIVRE` ne peut etre emis que par un export ayant REELLEMENT
        # produit des fichiers. On ne fabrique pas un zip vide pour faire joli.
        print(json.dumps({"erreur": "aucun fichier produit",
                          "reponse": {k: v for k, v in resultat.items()
                                      if not isinstance(v, str) or len(v) < 200}}))
        return 1

    with open(sortie, "wb") as f:
        f.write(base64.b64decode(b64))

    print(json.dumps({
        "fichiers": resultat.get("file_count") or resultat.get("files"),
        "couches_gerber": resultat.get("gerber_layers"),
        "bom_octets": len(resultat.get("bom_csv") or ""),
        "moteur": resultat.get("engine"),
        "note": str(resultat.get("note", ""))[:200],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
