#!/usr/bin/env python3
"""Choisit le meilleur tirage de chaque carte, et ne livre QUE s'il est meilleur.

## Le partage des rôles

`campagne_banc.sh` produit des tirages dans le conteneur, sans rien juger et
sans rien écrire dans `examples/`. Ce script fait le reste, à froid : il compare,
il choisit, et il refuse de livrer ce qui n'est pas au moins aussi bon.

Séparer les deux tient à une mesure : sur cette machine, le processus qui pilote
une campagne se fait tuer pour mémoire basse — cinq fois le 2026-09-08. Un
pilote qui portait AUSSI la règle de comparaison emportait la règle avec lui.

## La règle

Classement lexicographique sur `(composants perdus, erreurs DRC, -% routé)`,
et **la référence est le board VERSIONNÉ**, lu dans git.

⚠️ **PAS le board du disque.** Une exécution manuelle peut y avoir laissé un
`mesures.json` à `null` : la note de l'ancien devient alors introuvable, la
comparaison passe pour « rien à comparer », et le script accepte N'IMPORTE QUOI.
Mesuré le 2026-09-08 — un board à 97 %/8 erreurs a remplacé un board à
100 %/0 erreur, en annonçant « GARDE ». Un disque se salit, un commit non.

⚠️ **La complétude passe avant le DRC.** `carte-05` sortait « 100 %, 0 erreur »
sans son capteur : un composant absent n'a aucune connexion manquante à
signaler. Classer sur le DRC seul aurait préféré la carte amputée, indéfiniment.

⚠️ **Un tirage sans verdict ne remplace jamais rien.** « Je n'ai pas pu
mesurer » n'est pas « c'est mieux ». Et un tirage EXPIRÉ non plus : le
2026-09-09, un routage de `carte-09` a dépassé 66 minutes et rendu
`AUCUN SUMMARY` — ce n'est pas un mauvais board, c'est un board jamais fini.

Usage :
    python scripts/livrer_campagne.py /tmp/campagne-1788975347
    python scripts/livrer_campagne.py /tmp/campagne-… --appliquer
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_SERVICE = Path(__file__).resolve().parent.parent
_RACINE = _SERVICE.parents[1]
_CONTENEUR = "cirqix-kicad"


def _wsl(commande: str, secondes: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["wsl.exe", "-d", "Ubuntu", "-e", "bash", "-lc", commande],
                          capture_output=True, text=True, timeout=secondes)


def _git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git"] + args, cwd=str(_RACINE),
                          capture_output=True, text=True, timeout=120)


def _refs_du_texte(texte: str) -> list[str]:
    return re.findall(r'\(property\s+"Reference"\s+"([^"]+)"', texte)


def _note_versionnee(carte: str) -> tuple | None:
    """(perdus, erreurs, -pourcentage) du board VERSIONNÉ, lu dans git."""
    rel = "services/kicad/examples/%s/expected" % carte
    m = _git(["show", "HEAD:%s/mesures.json" % rel])
    if m.returncode != 0:
        return None
    try:
        mes = json.loads(m.stdout)
    except Exception:
        return None
    v = mes.get("drc_du_board") or {}
    if "nb_erreurs" not in v or mes.get("routed_percent") is None:
        return None

    perdus = 0
    b = _git(["show", "HEAD:%s/final.kicad_pcb" % rel])
    sch = _SERVICE / "examples" / carte / "input" / "schema.json"
    if b.returncode == 0 and sch.is_file():
        try:
            decl = json.loads(sch.read_text(encoding="utf-8"))["components"]
            perdus = max(0, len(decl) - len(_refs_du_texte(b.stdout)))
        except Exception:
            perdus = 0
    return (perdus, int(v["nb_erreurs"]), -int(mes["routed_percent"]))


def _note_du_tirage(dossier: str, carte: str) -> tuple | None:
    """La note d'un tirage, mesurée DANS le conteneur sur le board produit."""
    q = shlex.quote
    board = "%s/output/6_routed.kicad_pcb" % dossier
    existe = _wsl("docker exec %s test -f %s && echo oui"
                  % (q(_CONTENEUR), q(board)), 120)
    if "oui" not in existe.stdout:
        return None

    # ⚠️ LE VERDICT VIENT DU BOARD, pas du resume du pipeline : le compteur du
    # workflow a deja annonce 26 composants pour un fichier qui en portait 25.
    interne = (
        "cd /app && python3 -c \"import sys,json,base64,urllib.request,os;"
        "sys.path.insert(0,'/app');"
        "b=open('%s','rb').read();"
        "req=urllib.request.Request('http://127.0.0.1:8766/drc/auto',"
        "data=json.dumps({'kicad_pcb_b64':base64.b64encode(b).decode()}).encode(),"
        "headers={'Content-Type':'application/json',"
        "'Authorization':'Bearer '+os.environ['KICAD_SERVICE_TOKEN']});"
        "r=json.load(urllib.request.urlopen(req,timeout=900));"
        "v=r.get('violations') or [];"
        "print(json.dumps({'err':len([x for x in v "
        "if x.get('severity')=='error'])}))\"" % board)
    drc = _wsl("docker exec %s sh -c %s" % (q(_CONTENEUR), q(interne)), 1200)
    err = None
    for ligne in drc.stdout.splitlines():
        if ligne.strip().startswith("{"):
            try:
                err = json.loads(ligne)["err"]
            except Exception:
                pass
    if err is None:
        return None

    resume = _wsl("docker exec %s grep -a SUMMARY %s"
                  % (q(_CONTENEUR), q(dossier + "/journal.txt")), 120)
    m = re.search(r"routed=(\d+)", resume.stdout)
    if not m:
        return None
    pct = int(m.group(1))

    lu = _wsl("docker exec %s cat %s" % (q(_CONTENEUR), q(board)), 300)
    sch = _SERVICE / "examples" / carte / "input" / "schema.json"
    perdus = 0
    if lu.returncode == 0 and sch.is_file():
        try:
            decl = json.loads(sch.read_text(encoding="utf-8"))["components"]
            perdus = max(0, len(decl) - len(_refs_du_texte(lu.stdout)))
        except Exception:
            perdus = 0
    return (perdus, err, -pct)


def _lister(file_: str) -> dict[str, list[str]]:
    r = _wsl("docker exec %s sh -c %s"
             % (shlex.quote(_CONTENEUR),
                shlex.quote("ls -d %s/*-t* 2>/dev/null" % file_)), 120)
    par_carte: dict[str, list[str]] = {}
    for chemin in (l.strip() for l in r.stdout.splitlines() if l.strip()):
        nom = Path(chemin).name
        carte = re.sub(r"-t\d+$", "", nom)
        par_carte.setdefault(carte, []).append(chemin)
    return par_carte


def main(argv: list[str]) -> int:
    a = argparse.ArgumentParser()
    a.add_argument("file")
    a.add_argument("--appliquer", action="store_true",
                   help="ecrit dans examples/ ; sans ce drapeau on ne fait que dire")
    o = a.parse_args(argv[1:])

    par_carte = _lister(o.file)
    if not par_carte:
        print("aucun tirage dans %s" % o.file)
        return 1

    for carte in sorted(par_carte):
        avant = _note_versionnee(carte)
        notes = []
        for d in sorted(par_carte[carte]):
            n = _note_du_tirage(d, carte)
            notes.append((n, d))

        valides = [(n, d) for n, d in notes if n is not None]
        vus = " · ".join("%s" % ("%d%%/%derr/%dperdu" % (-n[2], n[1], n[0])
                                 if n else "non mesure") for n, _ in notes)
        if not valides:
            print("%-24s AUCUN tirage mesurable — conserve · vus : %s" % (carte, vus))
            continue

        valides.sort(key=lambda x: x[0])
        meilleur, dossier = valides[0]

        if avant is None:
            # ⚠️ On ne livre PAS sur une reference introuvable : c est ainsi
            # qu on finit par preferer le vide.
            print("%-24s reference versionnee ILLISIBLE — conserve · vus : %s"
                  % (carte, vus))
            continue
        if meilleur > avant:
            print("%-24s aucun tirage n egale %d%%/%derr/%dperdu — conserve · vus : %s"
                  % (carte, -avant[2], avant[1], avant[0], vus))
            continue

        etat = "MIEUX que" if meilleur < avant else "a egalite avec"
        print("%-24s %d%% · %d err · %d perdu — %s %d%%/%derr%s"
              % (carte, -meilleur[2], meilleur[1], meilleur[0], etat,
                 -avant[2], avant[1], "  [LIVRE]" if o.appliquer else "  [a livrer]"))

        if not o.appliquer:
            continue

        exp = _SERVICE / "examples" / carte / "expected"
        exp.mkdir(parents=True, exist_ok=True)
        q = shlex.quote
        for source, cible in (("output/6_routed.kicad_pcb", "final.kicad_pcb"),
                              ("output/5_placed.kicad_pcb", "placement.kicad_pcb"),
                              ("journal.txt", "journal.txt")):
            t = _wsl("docker cp %s /tmp/liv.tmp && cp /tmp/liv.tmp %s"
                     % (q("%s:%s/%s" % (_CONTENEUR, dossier, source)),
                        q(str(exp / cible).replace("C:", "/mnt/c").replace("\\", "/"))),
                     300)
            if t.returncode != 0 and cible == "final.kicad_pcb":
                print("   ⚠️ copie du board ECHOUEE — rien n a ete ecrit")
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
