#!/usr/bin/env python3
"""Re-mesure les boards deja livres, sans relancer aucun pipeline.

⚠️ Le resume du pipeline SURESTIME les connexions manquantes. Mesure du
2026-09-06 sur le MEME fichier, `carte-09/output/6_routed.kicad_pcb` :

    kicad-cli direct   :   9 non connectes,  70 violations
    service /drc/auto  :  18 non connectes, 154 violations

et jusqu'a 280 quand `auto_fix` itere. La cause de l'ecart n'est pas etablie ;
ce qui l'est, c'est lequel des deux juge le board qu'on livre reellement.

⚠️ Le verdict « fabricable » se lit dans la SEVERITE rendue par KiCad, jamais
dans une liste de types ecrite a la main : `via_dangling`, `track_dangling`,
`silk_overlap` et `silk_over_copper` sont classes **warning** — un via orphelin
est perce et plaque, la carte se fabrique. Seul « Missing connection » est
classe **error**.

Usage : python scripts/remesurer_banc.py [--conteneur cirqix-kicad]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from banc_driver_llm import _drc_du_board, _wsl, _wslifier  # noqa: E402

_EXEMPLES = Path(__file__).resolve().parents[1] / "examples"


def remesurer(dossier: Path, conteneur: str) -> dict | None:
    board = dossier / "expected" / "final.kicad_pcb"
    mesures_p = dossier / "expected" / "mesures.json"
    if not board.is_file() or not mesures_p.is_file():
        return None

    # Le board vit cote Windows : on le pousse dans le conteneur pour que
    # `kicad-cli` le juge, puis on lit son verdict.
    dist = "/tmp/remesure-%s.kicad_pcb" % dossier.name
    r = _wsl("cp '%s' /tmp/rm.kicad_pcb && docker cp /tmp/rm.kicad_pcb %s:%s"
             % (_wslifier(board), conteneur, dist), 300)
    if r.returncode != 0:
        print("%-24s copie impossible" % dossier.name)
        return None

    verdict = _drc_du_board(conteneur, dist)
    mesures = json.loads(mesures_p.read_text(encoding="utf-8"))
    mesures["drc_du_board"] = verdict
    mesures_p.write_text(json.dumps(mesures, indent=2, ensure_ascii=False), encoding="utf-8")
    return mesures


def main(argv: list[str]) -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--conteneur", default="cirqix-kicad")
    o = a.parse_args(argv[1:])

    print("%-24s %5s %7s %6s %s" % ("CARTE", "COMP", "ERREURS", "FABR.", "TYPES"))
    for d in sorted(_EXEMPLES.glob("carte-*")):
        m = remesurer(d, o.conteneur)
        if not m:
            print("%-24s (pas de board livre)" % d.name)
            continue
        v = m.get("drc_du_board") or {}
        print("%-24s %5d %7s %6s %s" % (
            d.name, m["composants"], v.get("nb_erreurs", "?"),
            "oui" if v.get("fabricable") else "NON", (v.get("types") or "")[:46]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
