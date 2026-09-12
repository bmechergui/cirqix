#!/usr/bin/env python3
"""Livre le board PLACE a cote du board ROUTE, et prouve qu ils correspondent.

## Pourquoi

Demande de l utilisateur le 2026-09-08 : « je veux toujours voir le fichier
placement et routage ». Et au-dela du confort, le board place non route est le
TEMOIN : sans lui, on impute au routage des defauts qui preexistaient. Ce depot
a deja paye cette confusion — 204 erreurs DRC sur un board sans la moindre
piste, attribuees au routeur.

## Ce que le script refuse de faire

Il ne livre un placement que s il correspond au routage livre. Un temoin qui ne
correspond pas ment PLUS qu un temoin absent : il donne une explication fausse,
et on la croit.

⚠️ La comparaison se fait avec une TOLERANCE, jamais a l egalite exacte. Le
meme composant s ecrit `134.043534` dans un fichier et `134.0435` dans l autre :
c est une difference de FORMATAGE, pas de position. Une comparaison stricte
annoncait « le placement ne correspond pas » sur un placement identique — la
famille de defauts que ce depot poursuit, appliquee a ma propre sonde.

Usage :
    python scripts/livrer_placements.py                     # toutes les cartes
    python scripts/livrer_placements.py carte-06-io-etendu
"""
from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from banc_driver_llm import _wsl, _wslifier  # noqa: E402

_SERVICE = Path(__file__).resolve().parent.parent
_EXEMPLES = _SERVICE / "examples"
_TOLERANCE_MM = 0.001


def positions(texte: str) -> dict[str, tuple[float, float]]:
    out, i = {}, 0
    while True:
        i = texte.find("(footprint ", i)
        if i < 0:
            return out
        d, j = 0, i
        while j < len(texte):
            if texte[j] == "(":
                d += 1
            elif texte[j] == ")":
                d -= 1
                if d == 0:
                    break
            j += 1
        f = texte[i:j + 1]
        i = j + 1
        r = re.search(r'\(property "Reference" "([^"]+)"', f)
        a = re.search(r'\(at ([-\d.]+) ([-\d.]+)', f)
        if r and a:
            out[r.group(1)] = (float(a.group(1)), float(a.group(2)))


def correspond(place: str, route: str) -> tuple[bool, str]:
    a, b = positions(place), positions(route)
    communs = set(a) & set(b)
    if not communs:
        return False, "aucun composant commun"
    ecarts = [r for r in communs
              if abs(a[r][0] - b[r][0]) > _TOLERANCE_MM
              or abs(a[r][1] - b[r][1]) > _TOLERANCE_MM]
    if ecarts:
        return False, "%d composant(s) deplaces : %s" % (
            len(ecarts), ", ".join(sorted(ecarts)[:5]))
    return True, "%d composants aux memes positions" % len(communs)


def livrer(dossier: Path, conteneur: str) -> str:
    route = dossier / "expected" / "final.kicad_pcb"
    if not route.is_file():
        return "%-26s pas de board route" % dossier.name
    q = shlex.quote
    trouve = _wsl("docker exec %s sh -c %s"
                  % (q(conteneur),
                     q("ls -t /tmp/banc-%s-*/output/5_placed.kicad_pcb 2>/dev/null"
                       % dossier.name)), 120)
    chemins = [l.strip() for l in trouve.stdout.splitlines() if l.strip()]
    if not chemins:
        return "%-26s aucun placement dans le conteneur" % dossier.name

    texte_route = route.read_text(encoding="utf-8", errors="replace")
    for c in chemins:
        lu = _wsl("docker exec %s cat %s" % (q(conteneur), q(c)), 180)
        if lu.returncode != 0 or "(footprint " not in lu.stdout:
            continue
        ok, pourquoi = correspond(lu.stdout, texte_route)
        if not ok:
            continue
        cible = dossier / "expected" / "placement.kicad_pcb"
        cible.write_text(lu.stdout, encoding="utf-8")
        return "%-26s LIVRE — %s" % (dossier.name, pourquoi)

    # ⚠️ On EFFACE plutot que de garder un temoin perime.
    (dossier / "expected" / "placement.kicad_pcb").unlink(missing_ok=True)
    return "%-26s aucun des %d placements ne correspond au routage livre" % (
        dossier.name, len(chemins))


def main(argv: list[str]) -> int:
    a = argparse.ArgumentParser()
    a.add_argument("dossier", nargs="?")
    a.add_argument("--conteneur", default="cirqix-kicad")
    o = a.parse_args(argv[1:])
    cibles = ([_EXEMPLES / o.dossier] if o.dossier
              else sorted(d for d in _EXEMPLES.glob("carte-*") if d.is_dir()))
    for d in cibles:
        print(livrer(d, o.conteneur), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
