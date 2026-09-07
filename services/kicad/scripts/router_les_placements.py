#!/usr/bin/env python3
"""Route les boards PLACÉS des exemples historiques, et livre le résultat.

## Pourquoi ce script existe

`CLAUDE.md` annonce, au « Banc du 2026-09-03 », huit cartes à **100 % routées,
0 erreur, sur deux couches**. Relevé le 2026-09-07 en comptant le cuivre des
boards réellement présents dans le dépôt :

    arduino-uno · esp32-baseline · nucleo-f401
    stm32-30 · stm32-60 · stm32-100 · stm32-baseline
        -> expected/2_placement_valide.kicad_pcb : 0 segment, 0 via

**Le résultat est écrit dans la documentation ; l'artefact n'existe pas.** Les
boards routés sont restés dans le conteneur et sont partis au premier
redémarrage — c'est exactement la faute que ce dépôt s'interdit par écrit :
« `examples/` n'y est pas monté : un board produit par le banc n'existe QUE dans
le conteneur ». La leçon des worktrees vidés, transposée, et payée une fois de
plus.

Un lecteur — humain ou agent — lit ce tableau et en conclut que ces cartes
routent. Il ne peut PAS le vérifier, et il n'a aucun moyen de s'en apercevoir.

## Ce que le script fait

Il repart du board **placé** déjà versionné (donc du même placement que le banc
d'origine), le route par la voie HTTP réelle du service, extrait le résultat
dans `expected/3_route.kicad_pcb` et le mesure avec `kicad-cli pcb drc`.

⚠️ Le verdict est lu dans la SÉVÉRITÉ rendue par KiCad, sur le board livré,
jamais dans le résumé du routeur. Sur un même fichier, `kicad-cli` a compté 9
connexions manquantes là où le service en annonçait 18.

⚠️ Le routage est STOCHASTIQUE : ce dépôt mesure 23 points d'écart entre deux
tirages d'une même carte au même placement. Un tirage qui déçoit ne réfute rien
— d'où `--tirages`, qui garde le meilleur.

Usage :
    python scripts/router_les_placements.py                 # toutes les manquantes
    python scripts/router_les_placements.py nucleo-f401     # une seule
    python scripts/router_les_placements.py --tirages=3
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from pathlib import Path

# ⚠️ La console Windows est en cp1252 : un caractere accentue ou un
# emoji y leve `UnicodeEncodeError` et TUE le script — apres que tout le
# travail a ete fait, donc en donnant l illusion d un echec. On force la
# sortie en UTF-8 avant d ecrire quoi que ce soit.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from banc_driver_llm import _drc_du_board, _wsl, _wslifier  # noqa: E402

_SCRIPTS = Path(__file__).resolve().parent
_EXEMPLES = _SCRIPTS.parent / "examples"
_PLACE = "expected/2_placement_valide.kicad_pcb"
_ROUTE = "expected/3_route.kicad_pcb"

# Budget généreux : `--timeout` du routeur n'est pas une limite de patience mais
# une RESSOURCE — il rend la main dès 100 % atteint et conserve ce qu'il a routé
# à l'échéance. Le relever ne coûte rien sur une carte simple.
_BUDGET_S = 3600


def _compter(board: Path) -> dict:
    """Compte le cuivre DANS le fichier, pas dans un rapport."""
    texte = board.read_text(encoding="utf-8", errors="replace")
    return {
        "segments": texte.count("(segment"),
        "vias": texte.count("(via"),
        "empreintes": texte.count("(footprint"),
    }


def router(dossier: Path, conteneur: str, tirages: int) -> dict | None:
    place = dossier / _PLACE
    if not place.is_file():
        return None

    q = shlex.quote
    nom = dossier.name
    dist_in = "/tmp/rt-%s-in.kicad_pcb" % nom
    dist_out = "/tmp/rt-%s-out.kicad_pcb" % nom

    # Le script d'appel vit DANS le conteneur : c'est là qu'est le jeton.
    poser = _wsl("cp %s /tmp/_router_un.py && docker cp /tmp/_router_un.py %s && "
                 "cp %s /tmp/rt-in.kicad_pcb && docker cp /tmp/rt-in.kicad_pcb %s"
                 % (q(_wslifier(_SCRIPTS / "_router_un.py")),
                    q("%s:/tmp/_router_un.py" % conteneur),
                    q(_wslifier(place)),
                    q("%s:%s" % (conteneur, dist_in))), 300)
    if poser.returncode != 0:
        print("  copie impossible : %s" % (poser.stderr[-200:] or poser.stdout[-200:]))
        return None

    meilleur: dict | None = None
    for n in range(max(1, tirages)):
        debut = time.time()
        r = _wsl("docker exec %s python3 /tmp/_router_un.py %s %s %d"
                 % (q(conteneur), q(dist_in), q(dist_out), _BUDGET_S), _BUDGET_S + 900)
        duree = round(time.time() - debut, 1)
        try:
            rendu = json.loads((r.stdout or "{}").strip().splitlines()[-1])
        except Exception:
            rendu = {"erreur": "sortie illisible", "detail": (r.stdout or r.stderr)[-300:]}

        if "erreur" in rendu:
            print("  tirage %d : ECHEC — %s %s"
                  % (n + 1, rendu["erreur"], str(rendu.get("detail", ""))[:120]))
            continue

        verdict = _drc_du_board(conteneur, dist_out)
        essai = {**rendu, "duree_s": duree, "drc_du_board": verdict, "tirage": n + 1}
        print("  tirage %d : %s%% · %s erreur(s) · %ss"
              % (n + 1, rendu.get("routed_percent"),
                 verdict.get("nb_erreurs", "?"), duree))

        # ⚠️ On garde le MEILLEUR, jamais le dernier — même règle que
        # `_palier_meilleur` : on classe sur (erreurs, puis pourcentage).
        cle = (verdict.get("nb_erreurs", 99), -(rendu.get("routed_percent") or 0))
        if meilleur is None or cle < meilleur["_cle"]:
            _wsl("docker cp %s /tmp/rt-best.kicad_pcb && cp /tmp/rt-best.kicad_pcb %s"
                 % (q("%s:%s" % (conteneur, dist_out)),
                    q(_wslifier(dossier / _ROUTE))), 300)
            essai["_cle"] = cle
            meilleur = essai

    if meilleur is None:
        return None
    meilleur.pop("_cle", None)
    meilleur["tirages"] = max(1, tirages)
    meilleur["board"] = _compter(dossier / _ROUTE)
    (dossier / "expected" / "mesures-routage.json").write_text(
        json.dumps(meilleur, indent=2, ensure_ascii=False), encoding="utf-8")
    return meilleur


def main(argv: list[str]) -> int:
    a = argparse.ArgumentParser()
    a.add_argument("dossier", nargs="?")
    a.add_argument("--conteneur", default="cirqix-kicad")
    a.add_argument("--tirages", type=int, default=1)
    o = a.parse_args(argv[1:])

    cibles = ([_EXEMPLES / o.dossier] if o.dossier
              else sorted(d for d in _EXEMPLES.iterdir()
                          if (d / _PLACE).is_file() and not (d / _ROUTE).is_file()))
    if not cibles:
        print("aucun placement a router (tous ont deja leur board route)")
        return 0

    print("%d carte(s) a router · %d tirage(s) chacune" % (len(cibles), o.tirages))
    resume = []
    for d in cibles:
        print("\n== %s" % d.name)
        m = router(d, o.conteneur, o.tirages)
        if m:
            resume.append((d.name, m))

    print("\n%-24s %6s %6s %9s %6s" % ("CARTE", "ROUTE", "ERR", "SEGMENTS", "VIAS"))
    for nom, m in resume:
        b, v = m["board"], m["drc_du_board"]
        print("%-24s %5s%% %6s %9s %6s"
              % (nom, m.get("routed_percent"), v.get("nb_erreurs", "?"),
                 b["segments"], b["vias"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
