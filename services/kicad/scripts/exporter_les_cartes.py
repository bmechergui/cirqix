#!/usr/bin/env python3
"""Produit les fichiers de FABRICATION de chaque carte, dans son `output/`.

## Pourquoi ce script existe

Question posée le 2026-09-07 : « les dix cartes, leur sortie est où ? »

La réponse honnête tient en deux points, et le second était un vrai manque :

1. Le board routé EST livré — `expected/final.kicad_pcb`, de 17 à 620 segments
   de cuivre. C'est le résultat, et il est versionné.

2. Les **Gerbers ne l'étaient pas.** Le banc les produisait dans le conteneur —
   « 22 fichiers exportés » — et n'en extrayait que le board. Ils partaient au
   premier redémarrage. C'est, une fois de plus, la leçon inscrite dans
   `CLAUDE.md` : « `examples/` n'est pas monté dans le conteneur ; un board
   produit par le banc n'existe QUE dans le conteneur ».

Ce script régénère ces fichiers depuis le board livré, par la voie HTTP réelle
du service, et les dépose dans `examples/<carte>/output/`.

⚠️ `output/` est **gitignoré** (`.gitignore`, `services/kicad/examples/*/output/`)
et c'est voulu : la règle du dépôt dit que « les outputs intermédiaires
régénérables ne sont jamais committés ; seuls `input/`, `README.md` et
`expected/` le sont ». Ces fichiers sont là pour être REGARDÉS, pas versionnés —
et ce script est la garantie qu'on peut les refaire à tout moment.

Usage :
    python scripts/exporter_les_cartes.py            # toutes les cartes
    python scripts/exporter_les_cartes.py carte-07-multi-io
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
import zipfile
from pathlib import Path

# ⚠️ La console Windows est en cp1252 : un caractere accentue ou un
# emoji y leve `UnicodeEncodeError` et TUE le script — apres que tout le
# travail a ete fait, donc en donnant l illusion d un echec. On force la
# sortie en UTF-8 avant d ecrire quoi que ce soit.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from banc_driver_llm import _wsl, _wslifier  # noqa: E402

_SCRIPTS = Path(__file__).resolve().parent
_EXEMPLES = _SCRIPTS.parent / "examples"

# Les boards livrés portent des noms différents selon l'époque du dossier.
_BOARDS = ("expected/final.kicad_pcb", "expected/3_route.kicad_pcb",
           "expected/led_blinker_final.kicad_pcb", "expected/stm32_final.kicad_pcb")


def _board_livre(dossier: Path) -> Path | None:
    for nom in _BOARDS:
        if (dossier / nom).is_file():
            return dossier / nom
    return None


def exporter(dossier: Path, conteneur: str) -> dict | None:
    board = _board_livre(dossier)
    if board is None:
        return None

    q = shlex.quote
    nom = dossier.name
    dist_in = "/tmp/ex-%s.kicad_pcb" % nom
    dist_zip = "/tmp/ex-%s.zip" % nom
    sortie = dossier / "output"
    sortie.mkdir(parents=True, exist_ok=True)

    poser = _wsl("cp %s /tmp/_exporter_un.py && docker cp /tmp/_exporter_un.py %s && "
                 "cp %s /tmp/ex-in.kicad_pcb && docker cp /tmp/ex-in.kicad_pcb %s"
                 % (q(_wslifier(_SCRIPTS / "_exporter_un.py")),
                    q("%s:/tmp/_exporter_un.py" % conteneur),
                    q(_wslifier(board)), q("%s:%s" % (conteneur, dist_in))), 300)
    if poser.returncode != 0:
        print("  copie impossible : %s" % (poser.stderr[-200:] or poser.stdout[-200:]))
        return None

    r = _wsl("docker exec %s python3 /tmp/_exporter_un.py %s %s"
             % (q(conteneur), q(dist_in), q(dist_zip)), 1200)
    try:
        rendu = json.loads((r.stdout or "{}").strip().splitlines()[-1])
    except Exception:
        rendu = {"erreur": "sortie illisible", "detail": (r.stdout or r.stderr)[-300:]}

    if "erreur" in rendu:
        print("  ECHEC — %s %s" % (rendu["erreur"], str(rendu.get("detail", ""))[:140]))
        return None

    archive = sortie / "fabrication.zip"
    tirer = _wsl("docker cp %s /tmp/ex-out.zip && cp /tmp/ex-out.zip %s"
                 % (q("%s:%s" % (conteneur, dist_zip)), q(_wslifier(archive))), 300)
    if tirer.returncode != 0 or not archive.is_file():
        print("  archive non recuperee")
        return None

    # On DÉPLIE : un zip ne se lit pas, et la question posée était « où est la
    # sortie », pas « où est l'archive ».
    with zipfile.ZipFile(archive) as z:
        noms = z.namelist()
        z.extractall(sortie)

    rendu["archive_octets"] = archive.stat().st_size
    rendu["fichiers_deplies"] = len(noms)
    (sortie / "mesures-export.json").write_text(
        json.dumps(rendu, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  %d fichier(s) · %d ko" % (len(noms), archive.stat().st_size // 1024))
    return rendu


def main(argv: list[str]) -> int:
    a = argparse.ArgumentParser()
    a.add_argument("dossier", nargs="?")
    a.add_argument("--conteneur", default="cirqix-kicad")
    o = a.parse_args(argv[1:])

    cibles = ([_EXEMPLES / o.dossier] if o.dossier
              else sorted(d for d in _EXEMPLES.iterdir()
                          if d.is_dir() and _board_livre(d) is not None))
    if not cibles:
        print("aucun board livre a exporter")
        return 1

    print("%d carte(s) a exporter" % len(cibles))
    resume = []
    for d in cibles:
        print("\n== %s" % d.name)
        m = exporter(d, o.conteneur)
        if m:
            resume.append((d.name, m))

    print("\n%-32s %9s %9s %s" % ("CARTE", "FICHIERS", "TAILLE", "MOTEUR"))
    for nom, m in resume:
        print("%-32s %9s %8dko %s"
              % (nom, m.get("fichiers_deplies"), m["archive_octets"] // 1024,
                 m.get("moteur") or ""))
    print("\n⚠️ `output/` est gitignoré : ces fichiers sont là pour être regardés,")
    print("   pas versionnés. Ce script les régénère depuis le board livré.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
