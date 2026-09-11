#!/usr/bin/env python3
"""Regenere `examples/VUES.md` : une ligne par carte du banc, avec les mesures
et les liens vers `output/vue-placement.png` et `output/vue-final.png`.

Les PNG viennent de `kicad-cli pcb render` sur `expected/placement.kicad_pcb`
et `expected/final.kicad_pcb` (voir `apercu_placement.py` / `apercu_routage.py`
pour les SVG). Le tableau, lui, est versionne : c est l index que l utilisateur
ouvre pour juger le placement et le routage carte par carte (demande du
2026-09-10 : « je n ai aucune sortie pour evaluer »).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_SERVICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SERVICE / "scripts"))
sys.path.insert(0, str(_SERVICE))
sys.path.insert(0, str(_SERVICE / "kicad-tools" / "src"))

from comparer_a_la_reference import mesurer  # noqa: E402

_ENTETE = """# Vues des cartes du banc — placement et routage

Pour chaque carte : `output/vue-placement.png` (board place, avant routage) et
`output/vue-final.png` (board route, plan GND coule), rendus par `kicad-cli pcb
render` depuis `expected/placement.kicad_pcb` et `expected/final.kicad_pcb`.
`output/` n est pas versionne ; regenerer avec `scripts/vues_index.py --rendre`.

Perimetre (decision utilisateur du 2026-09-10) : on traite TOUTES les cartes —
`carte-01` a `carte-11`, `stm32-30`, `stm32-60`, `stm32-100`, `stm32-baseline`,
`esp32-baseline` — SAUF deux REFERENCES intouchables : `stm32-validation`
(fixture pytest) et `STM32-Test-2026-09-10` (carte Astra/Codex).

Regle de lecture (docs/methodologie-routage.md) : decouplage corps->broche 1-3 mm,
grille = part des empreintes sur le pas 0,5 mm, paires = distance moyenne LED/resistance.
Une carte est FABRICABLE a 100 % route ET 0 erreur DRC ; les violations restantes
sont des avertissements de serigraphie.

| carte | livree le | route | err DRC | violations | couches | decouplage moy / max | grille | paires | placement | routage |
|---|---|---|---|---|---|---|---|---|---|---|
"""


def _date_git(chemin: Path) -> str:
    r = subprocess.run(["git", "log", "-1", "--format=%cd", "--date=short", "--", str(chemin)],
                       capture_output=True, text=True, cwd=str(_SERVICE))
    date = r.stdout.strip() or "non commite"
    sale = subprocess.run(["git", "status", "--short", "--", str(chemin)],
                          capture_output=True, text=True, cwd=str(_SERVICE)).stdout.strip()
    return date + (" (modifie)" if sale else "")


def _rendre(src: Path, png: Path) -> None:
    exe = next((p for p in (Path(r"C:\Program Files\KiCad\10.99\bin\kicad-cli.exe"),
                            Path("/usr/bin/kicad-cli")) if p.is_file()), None)
    if exe is None:
        return
    png.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(exe), "pcb", "render", "--output", str(png), "--side", "top",
                    "--quality", "basic", "--background", "default", str(src)],
                   capture_output=True)
    for prl in src.parent.glob("*.kicad_prl"):
        prl.unlink(missing_ok=True)


def ligne(dossier: Path, rendre: bool) -> str | None:
    exp = dossier / "expected"
    fin = exp / "final.kicad_pcb"
    if not fin.is_file():
        return None
    place = exp / "placement.kicad_pcb"
    m = json.loads((exp / "mesures.json").read_text(encoding="utf-8")) if (exp / "mesures.json").is_file() else {}
    q = mesurer(place if place.is_file() else fin)
    if rendre:
        if place.is_file():
            _rendre(place, dossier / "output" / "vue-placement.png")
        _rendre(fin, dossier / "output" / "vue-final.png")
    drc = m.get("drc_du_board") or {}
    texte = fin.read_text(encoding="utf-8", errors="replace")
    couches = q.get("couches") or 0
    dec = ("%.1f / %.1f" % (q["decouplage_moy"], q["decouplage_max"])) if q.get("decouplage_n") else "-"
    paires = ("%.1f" % q["paire_moyenne"]) if q.get("paire_moyenne") is not None else "-"
    pl = ("[placement](%s/output/vue-placement.png)" % dossier.name) if place.is_file() else "pas de temoin"
    return "| %s | %s | %s %% | %s | %s | %s | %s | %.0f %% | %s | %s | [routage](%s/output/vue-final.png) |" % (
        dossier.name, _date_git(fin), m.get("routed_percent", "?"), drc.get("nb_erreurs", "?"),
        m.get("drc_violations", "?"), couches, dec, 100.0 * q["sur_grille"] / q["empreintes"], paires,
        pl, dossier.name)


def main(argv: list[str]) -> int:
    rendre = "--rendre" in argv
    lignes = [_ENTETE]
    for d in sorted((_SERVICE / "examples").glob("carte-*")):
        l = ligne(d, rendre)
        if l:
            lignes.append(l + "\n")
    (_SERVICE / "examples" / "VUES.md").write_text("".join(lignes), encoding="utf-8")
    print("".join(lignes[1:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
