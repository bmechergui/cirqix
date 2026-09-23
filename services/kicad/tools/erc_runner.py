"""L'ERC de kicad-tools, HORS du worker uvicorn.

⚠️ POURQUOI UN PROCESSUS ENFANT. `Schematic.load` est du Python PUR : il tient
le GIL pendant toute l'analyse du fichier. Or uvicorn tue par SIGKILL tout
worker qui ne repond pas a son ping en 5 s (`supervisors/multiprocess.py:170
process is hung, kill it`). Mesure du 2026-09-23, deux cartes du banc perdues
le meme jour :

    carte-08   HTTP 500 sur /erc   schema de 190 ko
    carte-10   HTTP 500 sur /erc   schema de 141 ko

    Timeout (0:00:04.500000)!
      kicad_tools/sexp/parser.py:1181  _parse_list
      kicad_tools/schematic/models/io_mixin.py:111  load
      tools/erc.py:188  run_kicad_tools_erc

C'est la SŒUR du defaut corrige le 2026-09-10 sur le journal Freerouting
(564 Mo relus en entier, 6 a 9 s de GIL, worker abattu). `CLAUDE.md` l'ecrivait
deja : « NEVER tenir le GIL plus de quelques secondes dans un worker uvicorn
— ou le faire dans un processus enfant ». Le journal avait ete traite ; le
schema, non.

Contrat : un seul argument, un JSON `{"sch": <chemin>, "resultat": <chemin>,
"auto_fix": <bool>}`. Le fichier de schema est MODIFIE SUR PLACE quand
`auto_fix` est vrai — c'est ce que l'appelant relit. Le resultat porte les
violations brutes rendues par `validate`.

⚠️ ON N ECRIT LE RESULTAT QUE SI L ANALYSE A REUSSI. Un fichier absent se lit
« je n'ai pas pu analyser » ; un fichier contenant une liste vide se lirait
« schema propre ». Ce depot a paye cette confusion cinq fois en un jour
(rapport DRC vide lu « 0 erreur », nets KiCad 10 comptes a zero, `via_count`
jamais calcule rendu a zero).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: erc_runner.py '<json>'", file=sys.stderr)
        return 64

    from kicad_tools.schematic.models.schematic import Schematic

    args = json.loads(argv[1])
    chemin = Path(args["sch"])
    auto_fix = bool(args.get("auto_fix", True))

    sch = Schematic.load(chemin)
    issues = sch.validate(fix_auto=auto_fix)
    if auto_fix:
        sch.write(chemin)

    # `issues` porte des objets simples ; on ne garde que ce que l appelant lit,
    # et on le serialise ici plutot que de laisser l appelant deviner.
    propres = []
    for issue in issues:
        if not isinstance(issue, dict):
            issue = dict(getattr(issue, "__dict__", {}) or {})
        propres.append({
            "severity": issue.get("severity", "warning"),
            "message": issue.get("message", ""),
            "type": issue.get("type", ""),
            "reference": issue.get("reference", ""),
            "fix_applied": bool(issue.get("fix_applied", False)),
        })
    Path(args["resultat"]).write_text(
        json.dumps({"issues": propres}, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
