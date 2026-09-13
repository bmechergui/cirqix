"""`_degager_la_serigraphie` doit S EXECUTER, pas seulement exister.

Mesure du 2026-09-13, run driver a52f12df, journal du service :
« auto_place: serigraphie non degagee (name 'PCB' is not defined) ». La regle
livree la veille etait inerte en production : son test ne verifiait que la
presence de l appel dans la source, et le `except Exception` avalait la
NameError. Une garde qui lit la source ne prouve pas qu un code tourne.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))
sys.path.insert(0, str(_SERVICE / "kicad-tools" / "src"))

from tools import placement as P  # noqa: E402


def test_la_regle_tourne_sur_un_vrai_board_sans_avertissement(tmp_path, caplog):
    board = _SERVICE / "examples" / "carte-04-mcu-minimal" / "expected" / "placement.kicad_pcb"
    copie = tmp_path / "b.kicad_pcb"
    copie.write_bytes(board.read_bytes())
    with caplog.at_level(logging.WARNING, logger="tools.placement"):
        n = P._degager_la_serigraphie(copie)
    assert "serigraphie non degagee" not in caplog.text, caplog.text
    assert isinstance(n, int) and n >= 0
