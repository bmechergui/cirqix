#!/usr/bin/env python3
"""Produit un APERÇU VISUEL du routage de chaque carte, dans son `output/`.

## Pourquoi ce script existe

Question posée le 2026-09-08 : « je veux voir la qualité de routage, je ne vois
que des fichiers Gerber ». C'est juste : un Gerber est un format de fabrication,
pas une image. On ne juge pas un routage en lisant du `G01X...Y...D01*`.

Dans `output/`, par carte :

    routage.kicad_pcb     LE BOARD ROUTÉ, à ouvrir dans KiCad
    routage.kicad_pro     le projet, pour qu'un double-clic suffise
    routage-dessus.svg    cuivre F.Cu + contour + sérigraphie
    routage-dessous.svg   cuivre B.Cu + contour, MIROIR (vue de dessous)
    routage-3d.png        rendu réaliste, pour voir la carte finie

⚠️ Le `.kicad_pcb` est le SEUL des cinq qui permette de juger vraiment : on y
mesure une piste, on interroge un net, on relance le DRC. Les images montrent,
KiCad démontre. C'est une COPIE de `expected/final.kicad_pcb`, qui reste la
version versionnée et fait foi.

Le SVG est vectoriel : il s'ouvre dans un navigateur et se zoome sans perdre le
détail des pistes. C'est ce qu'un électronicien regarde pour juger un routage —
la densité, les détours, les vias, la continuité du plan de masse.

⚠️ `output/` est gitignoré, comme les Gerbers : ces fichiers sont là pour être
REGARDÉS, et ce script les régénère depuis le board livré, qui lui est versionné.

⚠️ La vue de dessous est MIROIR (`--mirror`). Sans cela on lirait le cuivre
arrière à l'envers, et un détour qui semble absurde ne l'est que dans la lecture.

Usage :
    python scripts/apercu_routage.py                  # toutes les cartes
    python scripts/apercu_routage.py carte-04-mcu-minimal
"""
from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from banc_driver_llm import _wsl, _wslifier  # noqa: E402

_SCRIPTS = Path(__file__).resolve().parent
_EXEMPLES = _SCRIPTS.parent / "examples"

_BOARDS = ("expected/final.kicad_pcb", "expected/3_route.kicad_pcb",
           "expected/led_blinker_final.kicad_pcb", "expected/stm32_final.kicad_pcb")


def _board_livre(dossier: Path) -> Path | None:
    for nom in _BOARDS:
        if (dossier / nom).is_file():
            return dossier / nom
    return None


def apercu(dossier: Path, conteneur: str) -> str | None:
    board = _board_livre(dossier)
    if board is None:
        return None
    q = shlex.quote
    nom = dossier.name
    dist = "/tmp/ap-%s.kicad_pcb" % nom
    sortie = dossier / "output"
    sortie.mkdir(parents=True, exist_ok=True)

    poser = _wsl("cp %s /tmp/ap-in.kicad_pcb && docker cp /tmp/ap-in.kicad_pcb %s"
                 % (q(_wslifier(board)), q("%s:%s" % (conteneur, dist))), 300)
    if poser.returncode != 0:
        return "%-24s copie impossible" % nom

    # ⚠️ `-o` attend un FICHIER, pas un dossier. Passer un repertoire existant
    # rend « Failed to create file » — et `kicad-cli` termine quand meme sur
    # « Done. » avec rc=0. Un echec qui s annonce comme un succes : on nomme
    # donc explicitement chaque fichier de sortie.
    interne = (
        "rm -f /tmp/ap-d.svg /tmp/ap-b.svg /tmp/ap-3d.png; "
        "kicad-cli pcb export svg -o /tmp/ap-d.svg "
        "--layers F.Cu,F.Silkscreen,Edge.Cuts --page-size-mode 2 %s >/dev/null 2>&1; "
        "kicad-cli pcb export svg -o /tmp/ap-b.svg "
        "--layers B.Cu,Edge.Cuts --mirror --page-size-mode 2 %s >/dev/null 2>&1; "
        "kicad-cli pcb render -o /tmp/ap-3d.png --quality high "
        "--width 1600 --height 1200 %s >/dev/null 2>&1; "
        "echo ok"
    ) % (q(dist), q(dist), q(dist))
    _wsl("docker exec %s sh -c %s" % (q(conteneur), q(interne)), 900)

    rendus = 0
    for source, cible in (("/tmp/ap-d.svg", "routage-dessus.svg"),
                          ("/tmp/ap-b.svg", "routage-dessous.svg")):
        t = _wsl("docker cp %s /tmp/ap-out.svg && cp /tmp/ap-out.svg %s"
                 % (q("%s:%s" % (conteneur, source)),
                    q(_wslifier(sortie / cible))), 300)
        if t.returncode == 0 and (sortie / cible).is_file():
            rendus += 1

    t = _wsl("docker cp %s /tmp/ap-3d.png && cp /tmp/ap-3d.png %s"
             % (q("%s:/tmp/ap-3d.png" % conteneur),
                q(_wslifier(sortie / "routage-3d.png"))), 300)
    if t.returncode == 0:
        rendus += 1

    # ⚠️ LE BOARD LUI-MEME, pas seulement ses images. Une image ne se mesure
    # pas : on n y interroge pas un net, on n y relance pas le DRC. La copie
    # porte un nom parlant et vit a cote des Gerbers, la ou on la cherche.
    import shutil
    shutil.copy2(board, sortie / "routage.kicad_pcb")
    rendus += 1
    # Un fichier projet minimal : sans lui KiCad ouvre le board avec SES
    # defauts de regles, et le DRC porterait alors sur des contraintes que la
    # carte ne suit pas — le piege deja inscrit pour `_rapport_drc`.
    projet = board.with_suffix(".kicad_pro")
    if projet.is_file():
        shutil.copy2(projet, sortie / "routage.kicad_pro")
        rendus += 1

    tailles = " · ".join(
        "%s %dko" % (f.name, f.stat().st_size // 1024)
        for f in sorted(sortie.glob("routage*")) if f.is_file())
    return "%-24s %d vue(s) — %s" % (nom, rendus, tailles or "aucune")


def main(argv: list[str]) -> int:
    a = argparse.ArgumentParser()
    a.add_argument("dossier", nargs="?")
    a.add_argument("--conteneur", default="cirqix-kicad")
    o = a.parse_args(argv[1:])

    cibles = ([_EXEMPLES / o.dossier] if o.dossier
              else sorted(d for d in _EXEMPLES.iterdir()
                          if d.is_dir() and _board_livre(d) is not None))
    for d in cibles:
        r = apercu(d, o.conteneur)
        if r:
            print(r, flush=True)
    print("\nOuvrir les .svg dans un navigateur : ils se zooment sans perdre le")
    print("detail des pistes. `output/` est gitignore — ce script les regenere.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
