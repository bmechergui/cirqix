#!/usr/bin/env python3
"""Rejoue les cartes du banc et ne GARDE que ce qui n'est pas moins bon.

## Pourquoi ce script existe

Un rejeu écrase `expected/`. Or le placement et le routage sont STOCHASTIQUES :
ce dépôt mesure 23 points d'écart entre deux tirages d'une même carte au même
placement, et `carte-08` a rendu 100 %, puis 98 %, puis 69 % le même jour. Un
rejeu naïf remplace donc régulièrement un bon board par un moins bon, en
silence.

C'est exactement la règle que le routeur s'applique déjà à ses paliers
(`_palier_meilleur`) : **on garde le meilleur, jamais le dernier.** On la
transpose ici.

## Le critère

Classement lexicographique sur `(composants perdus, erreurs, -routed_percent)`,
lu dans `expected/mesures.json` et dans le board :

  - **un board COMPLET l'emporte toujours** sur un board amputé, quel que soit
    son DRC. Mesuré le 2026-09-08 : `carte-05` sortait à « 100 %, 0 erreur »
    SANS son capteur BME280, et à « 100 %, 7 erreurs » avec lui. Le premier
    n'est pas meilleur, il est faux — un composant absent n'a simplement aucune
    connexion manquante à signaler. Classer sur le DRC seul aurait préféré la
    carte incomplète, indéfiniment ;
  - à complétude égale, moins d'erreurs gagne ;
  - à erreurs égales, le plus routé gagne ;
  - à égalité STRICTE, on prend le NOUVEAU.

⚠️ Ce dernier point mérite d'être justifié, parce qu'il inverse la prudence
habituelle. Ailleurs — `_palier_meilleur`, `_couture_acceptable` — on garde
l'ancien à égalité, pour ne pas remplacer sans gain. Ici le nouveau board porte
quelque chose que l'ancien n'a pas : les RÉFÉRENCES du schéma, corrigées le
2026-09-08. À qualité de routage égale, il est donc strictement préférable.

La protection reste entière : on ne remplace jamais par un board plus mauvais.

## Pourquoi `--essais`

Ces deux objectifs se contredisent en l'état. Le routage est stochastique —
`carte-01` a rendu 0 erreur, puis 2, le même jour — donc un tirage unique est
souvent REJETÉ, et la carte garde alors ses anciennes références : on ne
corrige rien. Sacrifier la qualité pour les références serait aussi mauvais que
l'inverse.

On re-tire donc jusqu'à égaler l'ancien, au lieu de choisir entre les deux. Le
nombre d'essais est un budget, pas un seuil de qualité : il borne le temps, il
ne décide de rien.

⚠️ Un rejeu qui échoue (pas de mesures, board absent) ne remplace jamais rien :
« je n'ai pas pu mesurer » n'est pas « c'est mieux ».

Usage :
    python scripts/regenerer_le_banc.py                 # toutes les cartes
    python scripts/regenerer_le_banc.py carte-04-mcu-minimal
    python scripts/regenerer_le_banc.py --recreer       # conteneur neuf entre chaque
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_SCRIPTS = Path(__file__).resolve().parent
_SERVICE = _SCRIPTS.parent
_EXEMPLES = _SERVICE / "examples"
_RACINE = _SERVICE.parents[1]


def _perdus(dossier: Path) -> int:
    """Combien de composants declares n ont PAS ete poses sur le board.

    ⚠️ On lit le BOARD, pas un compteur. Et on compare des COMPTES, pas des
    noms : les references ont pu etre renumerotees (defaut corrige le
    2026-09-08), auquel cas comparer les noms rendrait un faux positif.
    """
    s = dossier / "input" / "schema.json"
    b = dossier / "expected" / "final.kicad_pcb"
    if not (s.is_file() and b.is_file()):
        return 0
    try:
        decl = json.loads(s.read_text(encoding="utf-8"))["components"]
        txt = b.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return 0
    poses = re.findall(r'\(property\s+"Reference"\s+"([^"]+)"', txt)
    return max(0, len(decl) - len(poses))


def _note(dossier: Path) -> tuple | None:
    """(perdus, erreurs, -pourcentage) — plus petit est meilleur."""
    f = dossier / "expected" / "mesures.json"
    if not f.is_file():
        return None
    try:
        m = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None
    v = m.get("drc_du_board") or {}
    if "nb_erreurs" not in v or m.get("routed_percent") is None:
        # ⚠️ Pas de verdict = pas de note. On ne compare pas une mesure a une
        # absence de mesure : c est ainsi qu on finit par preferer le vide.
        return None
    return (_perdus(dossier), int(v["nb_erreurs"]), -int(m["routed_percent"]))


def _note_versionnee(dossier: Path) -> tuple | None:
    """La note du board VERSIONNE, lue dans git — jamais dans le disque.

    ⚠️ MESURE DU 2026-09-08. `_note` lit le repertoire de travail. Si une
    execution manuelle y a laisse un `mesures.json` a `null` — c est
    exactement ce qui vient d arriver, en diagnostiquant une panne de jeton —
    la note de l ANCIEN devient `None`, la comparaison `avant is None` passe
    pour « rien a comparer », et le script accepte alors N IMPORTE QUOI.

    Constate : un board a 97 % / 8 erreurs a remplace le board versionne a
    100 % / 0 erreur, en annoncant « GARDE ».

    C est la famille de defauts que ce depot poursuit : une mesure absente
    lue comme un feu vert. La protection existait deja cote APRES (« pas de
    verdict = pas de note ») et manquait cote AVANT.

    Le remede : la reference est ce que git contient, pas ce que le disque
    montre. Un disque se salit, un commit non.
    """
    rel = (str((dossier / "expected" / "mesures.json").relative_to(_RACINE))
           .replace("\\", "/"))
    r = _git(["show", "HEAD:" + rel])
    if r.returncode != 0:
        return None
    try:
        m = json.loads(r.stdout)
    except Exception:
        return None
    v = m.get("drc_du_board") or {}
    if "nb_erreurs" not in v or m.get("routed_percent") is None:
        return None
    # Les composants perdus se comptent sur le board versionne lui-meme.
    b = _git(["show", "HEAD:" + str((dossier / "expected" / "final.kicad_pcb")
                                    .relative_to(_RACINE)).replace("\\", "/")])
    perdus = 0
    sch = dossier / "input" / "schema.json"
    if b.returncode == 0 and sch.is_file():
        try:
            decl = json.loads(sch.read_text(encoding="utf-8"))["components"]
            poses = re.findall(r'\(property\s+"Reference"\s+"([^"]+)"', b.stdout)
            perdus = max(0, len(decl) - len(poses))
        except Exception:
            perdus = 0
    return (perdus, int(v["nb_erreurs"]), -int(m["routed_percent"]))


def _git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git"] + args, cwd=str(_RACINE),
                          capture_output=True, text=True, timeout=120)


def _un_essai(dossier: Path, recreer: bool, conteneur: str) -> None:
    if recreer:
        subprocess.run(
            ["wsl.exe", "-e", "bash", "-lc",
             "bash /mnt/c/Users/Mechegui/Desktop/dev/cirqix/services/kicad/"
             "scripts/recreer_kicad.sh"],
            capture_output=True, text=True, timeout=900)

    subprocess.run([sys.executable, str(_SCRIPTS / "banc_driver_llm.py"),
                    str(dossier.relative_to(_SERVICE)),
                    "--conteneur", conteneur],
                   cwd=str(_SERVICE), capture_output=True, text=True,
                   timeout=7200)


def rejouer(dossier: Path, recreer: bool, essais: int,
            conteneur: str = "cirqix-kicad") -> str:
    # ⚠️ La reference est le board VERSIONNE, pas le disque : voir
    # `_note_versionnee`. Un `mesures.json` sali par une execution
    # manuelle faisait accepter n importe quel remplacant.
    avant = _note_versionnee(dossier) or _note(dossier)
    rel = str(dossier.relative_to(_RACINE)).replace("\\", "/")
    vus = []

    for n in range(max(1, essais)):
        _un_essai(dossier, recreer, conteneur)
        apres = _note(dossier)
        if apres is None:
            vus.append("non mesure")
            _git(["checkout", "--", rel])
            continue
        vus.append("%s%%/%serr/%sperdu" % (-apres[2], apres[1], apres[0]))
        if avant is None or apres <= avant:
            mention = ("rien a comparer" if avant is None
                       else ("mieux que" if apres < avant else "a egalite avec")
                       + " %s%%/%serr/%sperdu" % (-avant[2], avant[1], avant[0]))
            return "%-24s %s%% · %s err · %s perdu(s) — GARDE apres %d essai(s) (%s)" % (
                dossier.name, -apres[2], apres[1], apres[0], n + 1, mention)
        # ⚠️ On restaure AVANT le prochain essai : sinon `avant` serait compare
        # au tirage rate, et la barre baisserait a chaque tour.
        _git(["checkout", "--", rel])

    return "%-24s aucun essai n egale l ancien (%s%%/%serr/%sperdu) — conserve · vus : %s" % (
        dossier.name, -avant[2], avant[1], avant[0], ", ".join(vus))


def main(argv: list[str]) -> int:
    a = argparse.ArgumentParser()
    a.add_argument("dossier", nargs="?")
    a.add_argument("--essais", type=int, default=3,
                   help="tirages maximum par carte avant d abandonner")
    a.add_argument("--recreer", action="store_true",
                   help="recree le conteneur avant chaque carte (memoire)")
    # ⚠️ Viser un SECOND conteneur permet de rejouer deux cartes en parallele.
    # Le verrou de routage est un fichier dans /tmp du conteneur : deux
    # conteneurs ont donc deux verrous, et la garantie « un seul routage sur
    # toute la machine » ne tient plus. C est un choix, pas un oubli — il se
    # borne par la memoire allouee au second conteneur, pour qu un depassement
    # tue le nouveau venu et jamais celui qui travaille.
    a.add_argument("--conteneur", default="cirqix-kicad",
                   help="conteneur KiCad a utiliser (cirqix-kicad-2 pour le second)")
    o = a.parse_args(argv[1:])

    cibles = ([_EXEMPLES / o.dossier] if o.dossier
              else sorted(d for d in _EXEMPLES.glob("carte-*")
                          if (d / "input" / "schema.json").is_file()))
    print("%d carte(s) a rejouer\n" % len(cibles))
    for d in cibles:
        print(rejouer(d, o.recreer, o.essais, o.conteneur), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
