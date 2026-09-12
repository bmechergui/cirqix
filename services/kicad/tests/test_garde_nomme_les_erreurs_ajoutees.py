"""La garde « ne peut qu ameliorer » NOMME les erreurs qu un candidat ajoute.
Le 2026-09-11, la repose des vias GND du LQFP a ete refusee toute une soiree
avec « erreurs ajoutees — board conserve », sans jamais dire lesquelles."""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402


def _rap(**types):
    return {"violations": [{"severity": "error", "type": k} for k, n in types.items() for _ in range(n)]
            + [{"severity": "warning", "type": "silk_overlap"}]}


def test_les_types_en_hausse_seulement():
    assert R._erreurs_ajoutees(_rap(clearance=1), _rap(clearance=1, hole_clearance=2)) == {"hole_clearance": 2}
    assert R._erreurs_ajoutees(_rap(clearance=3), _rap(clearance=1)) == {}
    assert R._erreurs_ajoutees({}, {}) == {}


def test_la_garde_journalise_les_types(monkeypatch, caplog):
    rapports = {b"a": _rap(), b"b": _rap(shorting_items=1)}
    monkeypatch.setattr(R, "_rapport_drc", lambda b: rapports[b])
    import logging
    with caplog.at_level(logging.WARNING, logger=R.logger.name):
        assert R._aggrave_le_board(b"a", b"b") is True
    assert "shorting_items" in caplog.text
