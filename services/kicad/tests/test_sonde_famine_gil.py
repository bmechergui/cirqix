"""La sonde de famine du GIL est armee dans chaque worker, et elle tire quand
un thread Python est affame — pas quand il tourne.

Voir `tools/sonde_gil.py` et `docs/DECISIONS.md` (2026-09-10) : un SIGKILL du
superviseur uvicorn ne laisse aucune trace ; la sonde ecrit la pile AVANT.
"""
from __future__ import annotations

import faulthandler
import re
import sys
import time
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from tools import sonde_gil  # noqa: E402


def test_le_minuteur_re_arme_ne_tire_pas(tmp_path):
    # faulthandler ecrit sur un DESCRIPTEUR : un vrai fichier, pas un StringIO.
    with open(tmp_path / "s.txt", "w") as sortie:
        for _ in range(4):
            faulthandler.dump_traceback_later(0.3, repeat=False, file=sortie)
            time.sleep(0.1)
        faulthandler.cancel_dump_traceback_later()
    assert (tmp_path / "s.txt").read_text() == ""


def test_le_minuteur_non_re_arme_tire(tmp_path):
    """Simule la famine : personne ne re-arme pendant plus que le seuil."""
    with open(tmp_path / "s.txt", "w") as sortie:
        faulthandler.dump_traceback_later(0.2, repeat=False, file=sortie)
        time.sleep(0.6)
        faulthandler.cancel_dump_traceback_later()
    texte = (tmp_path / "s.txt").read_text()
    assert "Timeout" in texte and "Thread" in texte


def test_armee_une_seule_fois_par_processus(monkeypatch):
    monkeypatch.setattr(sonde_gil, "_demarree", False)
    assert sonde_gil.armer_la_sonde_de_famine(seuil_s=60.0) is True
    assert sonde_gil.armer_la_sonde_de_famine(seuil_s=60.0) is False
    faulthandler.cancel_dump_traceback_later()


def test_le_seuil_est_sous_les_cinq_secondes_du_superviseur():
    assert 0 < sonde_gil.SEUIL_S < 5.0


def test_main_arme_la_sonde():
    texte = (_SERVICE / "main.py").read_text(encoding="utf-8")
    code = "\n".join(l.split("#")[0] for l in texte.splitlines())
    assert re.search(r"armer_la_sonde_de_famine\(", code), (
        "la sonde n est pas armee dans le service : un prochain SIGKILL "
        "du superviseur restera sans trace")
