"""Sort du conteneur les boards finaux du banc et les range dans `examples/`.

⚠️ `examples/` n est PAS monte dans le conteneur — il est cuit dans l image, et
le banc travaille sur une racine explicite (`/tmp/ex`). Un board produit par le
banc n existe donc QUE dans le conteneur : sans cette extraction, il disparait
au premier redemarrage, comme les quatre handoffs perdus des worktrees.

Usage :  python scripts/livrer_boards.py [--conteneur cirqix-banc] [--racine /tmp/ex]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
_EXEMPLES = _SERVICE / "examples"


_DELAI_S = 120  # wsl/docker peuvent geler au demarrage de la VM : jamais pendre sans mot


def _cartes(conteneur: str, racine: str) -> list[str]:
    """Les cartes dont le banc a produit un board final.

    ``racine`` est transmis a ``sh`` comme ARGUMENT positionnel (``$1``), jamais
    interpole dans la commande : ce shell tourne en root dans le conteneur, une
    valeur contenant ``;`` ou des backticks s executerait telle quelle.
    """
    vu = subprocess.run(
        ["wsl", "-d", "Ubuntu", "-u", "root", "-e", "docker", "exec", conteneur,
         "sh", "-c", 'ls -d "$1"/*/output/final.kicad_pcb 2>/dev/null', "_", racine],
        capture_output=True, text=True, timeout=_DELAI_S)
    if vu.returncode != 0 and not vu.stdout.strip():
        # `ls` rend 2 quand rien ne correspond : ce cas est legitime et son
        # stderr est muet (redirige). Toute autre panne (conteneur absent, WSL
        # eteint) porte un stderr qu il faut MONTRER au lieu de le confondre
        # avec « aucun board ».
        err = vu.stderr.strip()
        if err:
            raise SystemExit("docker exec a echoue (rc=%d) : %s" % (vu.returncode, err[:200]))
    return [l.split("/")[-3] for l in vu.stdout.splitlines() if l.strip()]


def main(argv: list[str]) -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--conteneur", default="cirqix-banc")
    a.add_argument("--racine", default="/tmp/ex")
    o = a.parse_args(argv[1:])

    cartes = _cartes(o.conteneur, o.racine)
    if not cartes:
        print("aucun board final trouve — le banc a-t-il tourne ?")
        return 1
    for carte in cartes:
        dest = _EXEMPLES / carte / "output"
        dest.mkdir(parents=True, exist_ok=True)
        cible = dest / "final.kicad_pcb"
        r = subprocess.run(
            ["wsl", "-d", "Ubuntu", "-u", "root", "-e", "docker", "cp",
             "%s:%s/%s/output/final.kicad_pcb" % (o.conteneur, o.racine, carte),
             "/mnt/" + str(cible).replace("\\", "/").replace("C:", "c")],
            capture_output=True, text=True, timeout=_DELAI_S)
        etat = "ok" if r.returncode == 0 else "ECHEC : " + r.stderr.strip()[:60]
        print("%-28s %s" % (carte, etat))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
