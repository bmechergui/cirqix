#!/usr/bin/env python3
"""Ecrit le README d'une carte du banc « driver LLM », depuis ses MESURES.

⚠️ Le README est GENERE, jamais redige a la main : un chiffre recopie derive de
son fichier de mesures des la premiere relance, et ce depot a deja paye deux
fois un chiffre faux inscrit dans sa documentation (« un routage coute 6,2 Go »,
« kicad-tools est le Niveau 1 »).

Usage :
    python scripts/readme_banc_driver.py <dossier-exemple>
    python scripts/readme_banc_driver.py --tous
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
_EXEMPLES = _SERVICE / "examples"

# Violations qui ne touchent PAS a la fabricabilite : de la serigraphie qui se
# chevauche ou deborde sur du cuivre. JLCPCB fabrique la carte malgre elles.
_COSMETIQUES = {"silk_overlap", "silk_over_copper", "silk_edge_clearance",
                "track_dangling"}


def _git(dossier: Path) -> tuple[str, str]:
    """SHA court et date du dernier commit touchant ce dossier, ou HEAD."""
    def q(args: list[str]) -> str:
        r = subprocess.run(["git"] + args, cwd=str(_SERVICE),
                           capture_output=True, text=True)
        return r.stdout.strip()
    sha = q(["log", "-1", "--format=%h", "--", str(dossier)]) or q(["rev-parse", "--short", "HEAD"])
    date = q(["log", "-1", "--format=%ci", "--", str(dossier)]) or q(["log", "-1", "--format=%ci"])
    return sha or "inconnu", (date or "")[:10]


def _fabricable(m: dict) -> tuple[bool, str]:
    """Verdict lu dans la SEVERITE rendue par KiCad, sur le BOARD LIVRE.

    ⚠️ DEUX REGLES, chacune payee par une mesure du 2026-09-06 :

    1. Le verdict vient du BOARD, pas du resume du pipeline. Sur le meme
       fichier, `kicad-cli` comptait 9 connexions manquantes la ou
       `/drc/auto` en annoncait 18, et jusqu a 280 quand `auto_fix` iterait.

    2. La severite ne se DEVINE pas. `via_dangling`, `track_dangling`,
       `silk_overlap` et `silk_over_copper` sont classes **warning** par
       KiCad — un via orphelin est perce et plaque, la carte se fabrique.
       Seul « Missing connection » est classe **error**. Je les classais sur
       ma propre liste, plus severe que KiCad lui-meme.
    """
    board = m.get("drc_du_board") or {}
    if "fabricable" in board:
        if board["fabricable"]:
            return True, "aucune violation de severite `error` sur le board livre"
        return False, "%d erreur(s) : %s" % (board.get("nb_erreurs", 0),
                                             ", ".join(board.get("erreurs", [])))
    # ⚠️ PAS DE MESURE = PAS DE VERDICT. Il n'y a AUCUN repli ici.
    #
    # Ce generateur a rendu « fabricable oui » pour `carte-07` alors que son
    # pipeline avait ete tue au placement : `mesures.json` ne portait ni
    # `routed_percent` ni `drc_du_board`, et l'ancien repli — qui cherchait des
    # types de violations dans un champ vide — n'en trouvait aucun, donc
    # concluait au succes. Une ABSENCE de mesure se lisait comme une PREUVE.
    #
    # C'est le defaut le plus cher de ce depot, deja paye trois fois : un
    # rapport DRC vide lu « 0 erreur », des nets KiCad 10 comptes a zero, un
    # `via_count` jamais calcule rendu a zero. On echoue ferme.
    return False, "**non mesure** — le pipeline n'a pas livre de board a juger"


def ecrire(dossier: Path) -> None:
    mesures = json.loads((dossier / "expected" / "mesures.json").read_text(encoding="utf-8"))
    schema = json.loads((dossier / "input" / "schema.json").read_text(encoding="utf-8"))
    sha, date = _git(dossier)
    board = mesures.get("board", {})
    board_drc = mesures.get("drc_du_board") or {}
    fab, motif = _fabricable(mesures)
    w, h = mesures.get("board_mm", [0, 0])

    desc = schema.get("_comment", "").split("Description : ", 1)[-1]
    types = (mesures.get("types_violations") or "").replace(",", " · ") or "aucune"

    lignes = [
        "# %s" % dossier.name,
        "",
        "> **Version git** `%s` (%s) — le schema, le board et ces chiffres viennent" % (sha, date),
        "> tous de ce commit. ⚠️ Un README recopie a la main derive de ses mesures des la",
        "> premiere relance : celui-ci est GENERE par `scripts/readme_banc_driver.py`.",
        "",
        "**1 dossier = 1 cas = 1 question.** Celle-ci : *la chaine tient-elle a %d composants ?*"
        % mesures["composants"],
        "",
        "## Le circuit",
        "",
        "> %s" % (desc or "(description absente)"),
        "",
        "⚠️ **Le schema n'est pas genere par l'agent Haiku** : il est ecrit par le driver —",
        "Claude Code joue son role, comme `run_pipeline.py` le prevoit (« ecrit par le",
        "driver »). C'est le seul chemin qui n'appelle aucun modele, et il repond a un angle",
        "mort du banc historique : ses huit cartes partent toutes de `circuit.json` FIGES,",
        "aucune d'une description en langage naturel — la promesse du produit.",
        "",
        "## Mesures",
        "",
        "| | |",
        "|---|---|",
        "| composants | %d |" % mesures["composants"],
        "| nets | %d |" % mesures["nets"],
        "| surface | %s x %s mm (%.0f mm2 par composant) |" % (w, h, (w * h / max(1, mesures["composants"]))),
        "| **routage** | **%s %%** |" % mesures.get("routed_percent"),
        "| DRC du pipeline | `clean=%s`, %s violation(s) |" % (mesures.get("drc_clean"), mesures.get("drc_violations")),
        "| **DRC du board livre** | **%s erreur(s)**, %s violation(s) au total |" % (
            board_drc.get("nb_erreurs", "?"), board_drc.get("violations", "?")),
        "| types (board livre) | %s |" % ((board_drc.get("types") or types).replace(",", " · ")),
        "| **fabricable** | **%s** — %s |" % ("oui" if fab else "NON", motif),
        "| fichiers exportes | %s |" % mesures.get("fichiers_exportes"),
        "| duree du pipeline | %s s |" % mesures.get("duree_s"),
        "",
        "Cuivre reellement pose sur le board livre :",
        "",
        "| segments | vias | zones | empreintes |",
        "|---|---|---|---|",
        "| %s | %s | %s | %s |" % (board.get("segments"), board.get("vias"),
                                   board.get("zones"), board.get("empreintes")),
        "",
        "⚠️ Ces quatre nombres sont comptes **dans le board**, pas rapportes par un",
        "compteur de progression. Ce depot a paye trois fois la difference : un rapport DRC",
        "vide lu « 0 erreur », des nets KiCad 10 comptes a zero, et un driver annoncant",
        "« 0/16 route » sur un board portant 62 segments.",
        "",
        "## Note de conception",
        "",
        schema.get("_board_size_note", "(aucune)"),
        "",
        "## Rejouer",
        "",
        "```",
        "python scripts/banc_driver_llm.py examples/%s" % dossier.name,
        "python scripts/readme_banc_driver.py examples/%s" % dossier.name,
        "```",
        "",
        "⚠️ `examples/` n'est **pas monte** dans le conteneur : il est cuit dans l'image. Le",
        "banc extrait donc `expected/final.kicad_pcb` aussitot, sans quoi l'artefact part au",
        "premier redemarrage — la lecon des worktrees vides, transposee.",
        "",
        "Artefacts : `expected/final.kicad_pcb`, `expected/journal.txt`,",
        "`expected/mesures.json`.",
    ]
    (dossier / "README.md").write_text("\n".join(lignes) + "\n", encoding="utf-8")
    print("%-26s route %s%% · fabricable %s · git %s"
          % (dossier.name, mesures.get("routed_percent"), "oui" if fab else "NON", sha))


_DEBUT = "<!-- TABLEAU GENERE -->"
_FIN = "<!-- FIN TABLEAU GENERE -->"


def index() -> None:
    """Reecrit le tableau recapitulatif de BANC_DRIVER_LLM.md.

    ⚠️ Il est GENERE pour la meme raison que les README : un tableau recopie a
    la main derive de ses mesures des la premiere relance. Celui-ci portait
    encore « carte-07 : 47 composants » quand la carte en avait 48, et donnait
    des comptes qu aucun fichier de mesures ne confirmait.
    """
    lignes = ["| carte | comp. | nets | routage | erreurs | fabricable |",
              "|---|---|---|---|---|---|"]
    for d in sorted(_EXEMPLES.glob("carte-*")):
        f = d / "expected" / "mesures.json"
        if not f.is_file():
            lignes.append("| `%s` | — | — | — | — | **non mesuree** |" % d.name)
            continue
        m = json.loads(f.read_text(encoding="utf-8"))
        fab, _ = _fabricable(m)
        b = m.get("drc_du_board") or {}
        lignes.append("| `%s` | %s | %s | %s %% | %s | %s |" % (
            d.name, m.get("composants", "—"), m.get("nets", "—"),
            (m.get("routed_percent") if m.get("routed_percent") is not None else "—"), b.get("nb_erreurs", "—"),
            "**oui**" if fab else "**NON**"))

    doc = _EXEMPLES / "BANC_DRIVER_LLM.md"
    t = doc.read_text(encoding="utf-8")
    bloc = _DEBUT + "\n" + "\n".join(lignes) + "\n" + _FIN
    if _DEBUT in t and _FIN in t:
        t = t[:t.index(_DEBUT)] + bloc + t[t.index(_FIN) + len(_FIN):]
    else:
        saut = chr(10)
        t = (t.rstrip() + saut * 2 + "## Resultats mesures" + saut * 2
             + bloc + saut)
    doc.write_text(t, encoding="utf-8")
    print("tableau du banc regenere")


def main(argv: list[str]) -> int:
    a = argparse.ArgumentParser()
    a.add_argument("dossier", nargs="?")
    a.add_argument("--tous", action="store_true")
    a.add_argument("--index", action="store_true")
    o = a.parse_args(argv[1:])
    if o.index and not (o.tous or o.dossier):
        index()
        return 0
    cibles = (sorted(d for d in _EXEMPLES.glob("carte-*")
                     if (d / "expected" / "mesures.json").is_file())
              if o.tous else [Path(o.dossier).resolve()])
    if not cibles:
        print("aucune carte mesuree")
        return 1
    for d in cibles:
        ecrire(d)
    index()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
