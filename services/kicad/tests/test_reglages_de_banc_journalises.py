"""Un reglage de banc actif se lit au journal, ou il n existe pas.
`{"graine_hierarchique": true}` pose le 2026-09-09 pour un A/B est reste deux
jours dans /tmp/cirqix-reglages.json et a pilote toutes les campagnes."""
from __future__ import annotations

import inspect
import logging
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from tools import reglages_banc as RB  # noqa: E402


def test_les_reglages_actifs_sont_journalises_en_warning(tmp_path, monkeypatch, caplog):
    f = tmp_path / "r.json"
    f.write_text('{"graine_hierarchique": true}', encoding="utf-8")
    monkeypatch.setattr(RB, "_CHEMIN", f)
    with caplog.at_level(logging.WARNING, logger=RB.logger.name):
        assert RB.journaliser_les_reglages("placement") == {"graine_hierarchique": True}
    assert "REGLAGES DE BANC ACTIFS" in caplog.text and "graine_hierarchique" in caplog.text


def test_sans_fichier_rien_n_est_dit(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(RB, "_CHEMIN", tmp_path / "absent.json")
    with caplog.at_level(logging.WARNING, logger=RB.logger.name):
        assert RB.journaliser_les_reglages("routage") == {}
    assert "REGLAGES" not in caplog.text


def test_les_deux_entrees_journalisent():
    from tools import placement as P
    from routers import routing as R
    assert 'journaliser_les_reglages("placement")' in inspect.getsource(P.auto_place)
    assert 'journaliser_les_reglages("routage")' in inspect.getsource(R.route_auto)
