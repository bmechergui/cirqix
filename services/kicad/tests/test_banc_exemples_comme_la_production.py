"""Le banc des références place comme la production.

2026-09-27 : `banc_exemples.py` appelait `/place/auto` sans `auto_size_board`
— le contour ne se resserrait jamais, Arduino et ESP32 sortaient entassés dans
un coin de cartes de 100 x 80 mm. `run_pipeline.py` avait été corrigé du même
défaut le 2026-09-23 ; son voisin, non.
"""
from __future__ import annotations

from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def test_le_banc_autorise_le_resserrement_comme_handle_placement():
    src = (RACINE / "scripts" / "banc_exemples.py").read_text(encoding="utf-8")
    assert 'auto_size_board=not bool(circuit.get("board_size_imposed", False))' in src


def test_le_driver_de_chaine_aussi():
    src = (RACINE / "scripts" / "driver_chaine.py").read_text(encoding="utf-8")
    assert 'auto_size_board=not bool(circuit.get("board_size_imposed", False))' in src
