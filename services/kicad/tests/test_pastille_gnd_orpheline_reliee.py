"""Une broche GND orpheline SEULE est reliee au plan par une courte piste.

Mesure du 2026-09-30, carte-07 : apres un routage a 100 %, la coulee laisse
2 ou 3 broches GND isolees (U1-8, C20-2). Le fanout ne trouve « aucune sortie
degagee », le raccord des amas « aucun chemin » : il ne vise que des ILOTS
portant une pastille, jamais une broche nue dont l ilot a ete retire. Les
replis Freerouting prennent alors ~5 min par tirage, pour rien.

Avis concordant de Codex, Grok, GLM et OpenCode : une courte piste GND vers le
plan principal, sur la face de la broche, avec la meme mecanique que les amas
(A*, couloir verifie, degagement), et la garde « jamais pire ».
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from routers import routing as R  # noqa: E402


def _faux_runner(monkeypatch, bilan, sortie=b"RELIE", vu=None):
    def run(payload):
        if vu is not None:
            vu.append(payload)
        Path(payload["output"]).write_bytes(sortie)
        Path(payload["result"]).write_text(json.dumps(bilan), encoding="utf-8")
    monkeypatch.setattr(R, "_run_pcbnew_operation", run)


def _contexte(monkeypatch, orphelines):
    monkeypatch.setattr(R, "_NETS_CONFIES_AU_PLAN", ("GND",))
    monkeypatch.setattr(R, "_rapport_drc", lambda b: {"unconnected_items": []})
    monkeypatch.setattr(R, "_pads_isolees_du_plan", lambda rap, b=None: list(orphelines))
    monkeypatch.setattr(R, "_fill_zones", lambda b: b)


def test_sans_orpheline_rien_n_est_lance(monkeypatch):
    _contexte(monkeypatch, [])
    vu = []
    _faux_runner(monkeypatch, {"relies": 1}, vu=vu)
    assert R._relier_les_pastilles_orphelines(b"BOARD") == b"BOARD"
    assert vu == []


def test_orpheline_reliee_le_board_est_rendu(monkeypatch):
    _contexte(monkeypatch, [("U1", "8"), ("C20", "2")])
    vu = []
    _faux_runner(monkeypatch, {"relies": 2, "examinees": 2}, vu=vu)
    monkeypatch.setattr(R, "_aggrave_le_board", lambda a, b: False)
    assert R._relier_les_pastilles_orphelines(b"BOARD") == b"RELIE"
    assert vu[0]["operation"] == "relier_pastilles"
    assert json.loads(vu[0]["pads"]) == [["U1", "8"], ["C20", "2"]]


def test_jamais_pire(monkeypatch):
    _contexte(monkeypatch, [("U1", "8")])
    _faux_runner(monkeypatch, {"relies": 1, "examinees": 1})
    monkeypatch.setattr(R, "_aggrave_le_board", lambda a, b: True)
    assert R._relier_les_pastilles_orphelines(b"BOARD") == b"BOARD"


def test_aucune_reliee_on_le_dit_et_on_garde(monkeypatch, caplog):
    _contexte(monkeypatch, [("U1", "8")])
    _faux_runner(monkeypatch, {"relies": 0, "examinees": 1, "echecs": {"sans_chemin": 1}})
    with caplog.at_level("WARNING"):
        assert R._relier_les_pastilles_orphelines(b"BOARD") == b"BOARD"
    assert "AUCUNE" in caplog.text


def test_place_dans_les_reparations_locales():
    src = inspect.getsource(R._reparations_locales_gnd)
    amas = src.index("_relier_les_amas_orphelins(final)")
    pastilles = src.index("_relier_les_pastilles_orphelines(final)")
    retrait = src.index("_retirer_ilots_flottants(final)")
    assert amas < pastilles < retrait


def test_le_runner_connait_l_operation():
    runner = (RACINE / "tools" / "routing_pcbnew_runner.py").read_text(encoding="utf-8")
    assert 'operation == "relier_pastilles"' in runner
    assert "def _relier_les_pastilles_orphelines(pcbnew" in runner
