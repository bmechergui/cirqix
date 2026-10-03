"""Un même board n'est jugé qu'une fois par kicad-cli.

Banc du 2026-10-01 : les finitions font 50 % du temps de routage (4705 s sur
33 tirages) et réinterrogent souvent le DRC sur un board inchangé (gardes
« jamais pire », comparaisons des replis). Avis de Codex : mémoriser le rapport
par contenu exact du board ET règles du projet ; ne garder que des rapports
valides ; rendre des copies.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from routers import routing as R  # noqa: E402


class FauxCli:
    def __init__(self, rapport):
        self.appels = 0
        self.rapport = rapport

    def __call__(self, cmd, **kw):
        self.appels += 1
        sortie = Path(cmd[cmd.index("-o") + 1])
        if self.rapport is not None:
            sortie.write_text(json.dumps(self.rapport), encoding="utf-8")
        return type("R", (), {"stdout": "", "stderr": "", "returncode": 0})()


def _armer(monkeypatch, rapport):
    R._vider_cache_drc()
    cli = FauxCli(rapport)
    monkeypatch.setattr(R.shutil, "which", lambda n: "kicad-cli")
    monkeypatch.setattr(R.subprocess, "run", cli)
    return cli


def test_meme_board_un_seul_drc(monkeypatch):
    cli = _armer(monkeypatch, {"violations": [], "unconnected_items": []})
    R._rapport_drc(b"(kicad_pcb A)")
    R._rapport_drc(b"(kicad_pcb A)")
    assert cli.appels == 1


def test_autre_board_nouveau_drc(monkeypatch):
    cli = _armer(monkeypatch, {"violations": [], "unconnected_items": []})
    R._rapport_drc(b"(kicad_pcb A)")
    R._rapport_drc(b"(kicad_pcb B)")
    assert cli.appels == 2


def test_rapport_rendu_est_une_copie(monkeypatch):
    _armer(monkeypatch, {"violations": [{"type": "x"}], "unconnected_items": []})
    premier = R._rapport_drc(b"(kicad_pcb A)")
    premier["violations"].clear()
    assert R._rapport_drc(b"(kicad_pcb A)")["violations"] == [{"type": "x"}]


def test_un_echec_n_est_pas_memorise(monkeypatch):
    cli = _armer(monkeypatch, None)  # kicad-cli n ecrit pas de rapport
    assert R._sans_verdict(R._rapport_drc(b"(kicad_pcb A)"))
    R._rapport_drc(b"(kicad_pcb A)")
    assert cli.appels == 2


def test_des_regles_differentes_ne_partagent_pas_le_rapport(monkeypatch):
    cli = _armer(monkeypatch, {"violations": [], "unconnected_items": []})
    regles = iter([{"a": 1}, {"a": 2}])
    monkeypatch.setattr(R, "_projet_kicad", lambda b: next(regles))
    R._rapport_drc(b"(kicad_pcb A)")
    R._rapport_drc(b"(kicad_pcb A)")
    assert cli.appels == 2
