#!/usr/bin/env python3
"""Passe UNE carte du banc « driver LLM » dans la chaine complete, et la mesure.

Le schema n'est PAS genere par l'agent Haiku : il est ecrit par le driver — un
humain ou un assistant qui joue son role. C'est ce que `run_pipeline.py` prevoit
depuis toujours (« ecrit par le driver ») et c'est le seul chemin qui n'appelle
aucun modele.

⚠️ POURQUOI CE BANC EXISTE. Les huit cartes du banc historique partent toutes de
`circuit.json` FIGES : aucune ne part d'une description en langage naturel, qui
est pourtant la promesse du produit. Ce banc-ci commence au schema.

⚠️ NE PAS CONFONDRE AVEC `scripts/driver_llm.py`, qui existe depuis longtemps.
Les deux font jouer le role du modele, mais a des etages differents :

    driver_llm.py       le modele joue le REASONER, sur un board deja place :
                        `state` rend l etat, on decide des commandes, `exec`
                        les applique. Une seule etape de la chaine.

    banc_driver_llm.py  le modele joue l agent SCHEMA — il ECRIT
                        `input/schema.json` — et ce banc passe la carte dans
                        TOUTE la chaine, du schema aux Gerbers, puis la mesure.

Usage :
    python scripts/banc_driver_llm.py <dossier-exemple> [--conteneur cirqix-kicad]

Le dossier doit contenir `input/schema.json`. Le script y ecrit
`expected/final.kicad_pcb` et `expected/mesures.json`.

⚠️ `examples/` n'est PAS monte dans le conteneur : il est cuit dans l'image. Les
artefacts sont donc EXTRAITS aussitot, sans quoi ils partent au premier
redemarrage — la lecon des worktrees vides, transposee.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
_PIPELINE = _SERVICE / "examples" / "led-blinker-full-pipeline" / "run_pipeline.py"
_DELAI_S = 3600


def _wsl(commande: str, delai: int = _DELAI_S) -> subprocess.CompletedProcess:
    """Une commande dans WSL. Docker n'est accessible que par la.

    ⚠️ La racine est passee a `sh` en ARGUMENT, jamais interpolee : ce shell
    tourne en root dans la VM.
    """
    return subprocess.run(["wsl", "-d", "Ubuntu", "-u", "root", "-e", "sh", "-c", commande],
                          capture_output=True, text=True, timeout=delai)


def _wslifier(chemin: Path) -> str:
    """`C:\\x\\y` -> `/mnt/c/x/y`."""
    s = str(chemin.resolve()).replace("\\", "/")
    return "/mnt/" + s[0].lower() + s[2:]


def _mesurer_board(conteneur: str, chemin: str) -> dict:
    """Compte le cuivre reellement pose. Un compteur de progression ment ; un
    board, non — ce depot l'a paye trois fois."""
    sortie = _wsl(
        "docker exec %s sh -c \"for m in segment via zone footprint; do "
        "printf '%%s ' \\$(grep -c \\\"(\\$m\\\" %s); done\"" % (conteneur, chemin), 120)
    try:
        seg, via, zone, fp = (int(x) for x in sortie.stdout.split()[:4])
        return {"segments": seg, "vias": via, "zones": zone, "empreintes": fp}
    except Exception:
        return {"segments": 0, "vias": 0, "zones": 0, "empreintes": 0}


def _drc_du_board(conteneur: str, chemin: str) -> dict:
    """Rejoue `kicad-cli pcb drc` SUR LE BOARD LIVRE, et compte.

    ⚠️ POURQUOI NE PAS CROIRE LE PIPELINE. Mesure du 2026-09-06 sur le MEME
    fichier, `carte-09-tres-dense/output/6_routed.kicad_pcb` :

        kicad-cli direct   :   9 non connectes,  70 violations
        service /drc/auto  :  18 non connectes, 154 violations

    Le double, et jusqu a quatorze fois plus quand `auto_fix` itere. La cause
    de l ecart n est pas etablie ; ce qui l est, c est lequel des deux juge le
    board qu on livre reellement.

    ⚠️ C est la regle deja inscrite trois fois dans ce depot : un compteur
    ment, un board non. Rapport DRC vide lu « 0 erreur », nets KiCad 10 comptes
    a zero, driver annoncant « 0/16 route » sur 62 segments — et maintenant ce
    DRC de service.
    """
    lecture = _wsl(
        "docker exec %s sh -c \"kicad-cli pcb drc --format json -o /tmp/banc_drc.json %s "
        ">/dev/null 2>&1; cat /tmp/banc_drc.json\"" % (conteneur, chemin), 900)
    try:
        rapport = json.loads(lecture.stdout)
    except Exception:
        return {}
    par_type: dict = {}
    erreurs: dict = {}
    for section in ("violations", "unconnected_items"):
        for v in rapport.get(section, []):
            cle = v.get("type", "unconnected_items")
            par_type[cle] = par_type.get(cle, 0) + 1
            # ⚠️ LA SEVERITE VIENT DE KiCad, elle ne se devine pas. Mesure du
            # 2026-09-06 sur `carte-09` : `via_dangling`, `track_dangling`,
            # `silk_overlap` et `silk_over_copper` sont classes **warning** —
            # un via orphelin est perce et plaque, la carte se fabrique. Seul
            # « Missing connection » est classe **error**.
            #
            # Je classais `via_dangling` comme bloquant sur ma propre liste :
            # c etait plus severe que KiCad lui-meme, et cela declarait non
            # fabricables des cartes qui le sont. Lire la severite plutot que
            # de la reconstituer supprime tout jugement de ma part.
            if v.get("severity") == "error":
                erreurs[cle] = erreurs.get(cle, 0) + 1
    manquantes = len(rapport.get("unconnected_items", []))
    return {
        "violations": sum(par_type.values()),
        "non_connectes": manquantes,
        "types": ",".join("%s:%d" % (k, v) for k, v in sorted(par_type.items())),
        "erreurs": sorted(erreurs),
        "nb_erreurs": sum(erreurs.values()),
        "fabricable": not erreurs,
    }


def _sha_git() -> str:
    r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                       cwd=str(_SERVICE), capture_output=True, text=True)
    return r.stdout.strip() or "inconnu"


def executer(dossier: Path, conteneur: str) -> dict:
    schema_local = dossier / "input" / "schema.json"
    if not schema_local.is_file():
        raise SystemExit("schema absent : %s" % schema_local)
    schema = json.loads(schema_local.read_text(encoding="utf-8"))
    nom = dossier.name

    # Le script lit `input/schema.json` A COTE DE LUI : on reconstitue cette
    # structure dans le conteneur.
    # ⚠️ Chemin UNIQUE par execution : un `rm -rf` du dossier precedent a
    # echoue en « Operation not permitted » cote WSL, et bloquait toute
    # relance. Un nom neuf coute moins cher qu un nettoyage capricieux.
    dist = "/tmp/banc-%s-%d" % (nom, int(time.time()))
    prep = (
        "rm -rf {d} && mkdir -p {d}/input && "
        "cp '{s}' {d}/input/schema.json && cp '{p}' {d}/run_pipeline.py && "
        "docker exec {c} rm -rf {d} && docker cp {d} {c}:{d} && "
        # ⚠️ Le conteneur tourne en `cirqix` (uid 10001) et un dossier copie
        # appartient a root : sans ceci, la creation de `output/` echoue.
        "docker exec -u root {c} chmod -R 777 {d}"
    ).format(d=dist, s=_wslifier(schema_local), p=_wslifier(_PIPELINE), c=conteneur)
    r = _wsl(prep, 300)
    if r.returncode != 0:
        raise SystemExit("preparation echouee : %s" % (r.stderr[-400:] or r.stdout[-400:]))

    debut = time.time()
    # ⚠️ Le journal est ECRIT DANS LE CONTENEUR avant d etre lu. Une carte
    # dense depasse dix minutes ; si la commande qui attend est interrompue,
    # le pipeline CONTINUE cote conteneur mais sa sortie est perdue — mesure
    # du 2026-09-06 sur `carte-06`, dont les artefacts existaient sans
    # verdict. Un `tee` coute une redirection et rend le banc reprenable.
    r = _wsl("docker exec %s sh -c 'cd /app && python3 %s/run_pipeline.py "
             "%s/output 2>&1 | tee %s/journal.txt'" % (conteneur, dist, dist, dist))
    duree = time.time() - debut
    journal = "\n".join(l for l in (r.stdout + r.stderr).splitlines()
                        if "PROPERTY_ENUM" not in l)

    if "SUMMARY" not in journal:
        # Reprise : la sortie directe est perdue, le journal du conteneur non.
        repris = _wsl("docker exec %s cat %s/journal.txt" % (conteneur, dist), 180)
        if "SUMMARY" in repris.stdout:
            journal = chr(10).join(
                l for l in repris.stdout.splitlines()
                if "PROPERTY_ENUM" not in l)

    resume = re.search(r"SUMMARY routed=(\d+) drc_violations=(\d+) "
                       r"drc_clean=(\w+) files=(\d+)(?: types=(\S+))?", journal)
    mesures = {
        "exemple": nom,
        "composants": len(schema.get("components", [])),
        "nets": len(schema.get("connections", [])),
        "board_mm": [schema.get("board_width_mm"), schema.get("board_height_mm")],
        "duree_s": round(duree),
        "git": _sha_git(),
        "routed_percent": int(resume.group(1)) if resume else None,
        "drc_violations": int(resume.group(2)) if resume else None,
        "drc_clean": (resume.group(3) == "True") if resume else None,
        "fichiers_exportes": int(resume.group(4)) if resume else None,
        "types_violations": resume.group(5) if resume and resume.group(5) else "",
        "abouti": "PIPELINE COMPLET OK" in journal,
    }

    (dossier / "expected").mkdir(parents=True, exist_ok=True)
    board = "%s/output/6_routed.kicad_pcb" % dist
    extrait = _wsl("docker cp %s:%s /tmp/f.kicad_pcb && cp /tmp/f.kicad_pcb '%s'"
                   % (conteneur, board, _wslifier(dossier / "expected" / "final.kicad_pcb")), 300)
    if extrait.returncode == 0:
        mesures["board"] = _mesurer_board(conteneur, board)
        # ⚠️ LE VERDICT VIENT DU BOARD, pas du resume du pipeline.
        mesures["drc_du_board"] = _drc_du_board(conteneur, board)

    (dossier / "expected" / "journal.txt").write_text(journal, encoding="utf-8")
    (dossier / "expected" / "mesures.json").write_text(
        json.dumps(mesures, indent=2, ensure_ascii=False), encoding="utf-8")
    return mesures


def main(argv: list[str]) -> int:
    a = argparse.ArgumentParser()
    a.add_argument("dossier")
    a.add_argument("--conteneur", default="cirqix-kicad")
    o = a.parse_args(argv[1:])
    m = executer(Path(o.dossier).resolve(), o.conteneur)
    print(json.dumps(m, indent=2, ensure_ascii=False))
    return 0 if m.get("abouti") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
