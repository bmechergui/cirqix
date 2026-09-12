#!/usr/bin/env python3
"""Une vue du PLACEMENT seul, à côté de celles du routage.

Demande de l'utilisateur le 2026-09-10 : « je veux voir avec toi le placement
et le routage à chaque étape de carte ». Les vues existantes
(`apercu_routage.py`) ne montrent que le board routé ; on ne peut pas y juger
le placement, les pistes le masquent.

Produit dans `output/` : `placement-dessus.svg` — empreintes, sérigraphie et
contour, SANS cuivre de piste. C'est ce qu'on regarde pour juger un placement :
l'alignement, les groupes fonctionnels, la distance entre une LED et sa
résistance, le découplage contre les broches d'alimentation.

⚠️ Le board placé est `expected/placement.kicad_pcb` quand il existe (le vrai
témoin), et à défaut `final.kicad_pcb` sans ses couches cuivre — moins fidèle,
et dit comme tel.
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

_EXEMPLES = Path(__file__).resolve().parent.parent / "examples"


def apercu(dossier: Path, conteneur: str) -> str | None:
    place = dossier / "expected" / "placement.kicad_pcb"
    temoin = True
    if not place.is_file():
        place = dossier / "expected" / "final.kicad_pcb"
        temoin = False
    if not place.is_file():
        return None
    q = shlex.quote
    nom = dossier.name
    dist = "/tmp/ap-place-%s.kicad_pcb" % nom
    sortie = dossier / "output"
    sortie.mkdir(parents=True, exist_ok=True)

    r = _wsl("cp %s /tmp/ap-place-in.kicad_pcb && docker cp /tmp/ap-place-in.kicad_pcb %s"
             % (q(_wslifier(place)), q("%s:%s" % (conteneur, dist))), 300)
    if r.returncode != 0:
        return "%-24s copie impossible" % nom

    # ⚠️ `-o` attend un FICHIER : un dossier rend « Failed to create file » puis
    # « Done. » avec rc=0. Piege deja inscrit dans `apercu_routage.py`.
    interne = ("rm -f /tmp/ap-place.svg; kicad-cli pcb export svg -o /tmp/ap-place.svg "
               "--layers F.Silkscreen,F.Fab,F.Courtyard,Edge.Cuts --page-size-mode 2 %s "
               ">/dev/null 2>&1; echo ok" % q(dist))
    _wsl("docker exec %s sh -c %s" % (q(conteneur), q(interne)), 600)
    t = _wsl("docker cp %s /tmp/ap-place-out.svg && cp /tmp/ap-place-out.svg %s"
             % (q("%s:/tmp/ap-place.svg" % conteneur),
                q(_wslifier(sortie / "placement-dessus.svg"))), 300)
    if t.returncode != 0 or not (sortie / "placement-dessus.svg").is_file():
        return "%-24s vue NON produite" % nom
    ko = (sortie / "placement-dessus.svg").stat().st_size // 1024
    return "%-24s placement-dessus.svg %dko%s" % (
        nom, ko, "" if temoin else "  (depuis le board route : pas de temoin)")


def main(argv: list[str]) -> int:
    a = argparse.ArgumentParser()
    a.add_argument("dossier", nargs="?")
    a.add_argument("--conteneur", default="cirqix-kicad")
    o = a.parse_args(argv[1:])
    cibles = ([_EXEMPLES / o.dossier] if o.dossier
              else sorted(d for d in _EXEMPLES.glob("carte-*") if d.is_dir()))
    for d in cibles:
        r = apercu(d, o.conteneur)
        if r:
            print(r, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
