"""Fixtures pytest — microservice KiCad Layrix.

Ajoute au sys.path :
- services/kicad        → import des modules `tools.*` / `routers.*`
- kicad-tools/src       → import du package vendoré `kicad_tools`
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[1]          # services/kicad
_KICAD_TOOLS_SRC = _SERVICE_ROOT / "kicad-tools" / "src"

for p in (str(_SERVICE_ROOT), str(_KICAD_TOOLS_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

# kicad_tools.add_symbol() résout les .kicad_sym via KICAD_SYMBOL_DIR (cf. main.py
# au démarrage du service). Sans cette variable, add_symbol() échoue silencieusement
# (warning loggué) pour Device:R/Device:C et les tests ne testent rien de réel.
if not os.environ.get("KICAD_SYMBOL_DIR"):
    for _dir in (
        str(_SERVICE_ROOT / "kicad-symbols"),
        r"C:\Program Files\KiCad\10.99\share\kicad\symbols",
        r"C:\Program Files\KiCad\9.0\share\kicad\symbols",
        r"C:\Program Files\KiCad\8.0\share\kicad\symbols",
        "/usr/share/kicad/symbols",
    ):
        if os.path.isdir(_dir):
            os.environ["KICAD_SYMBOL_DIR"] = _dir
            break


@pytest.fixture(scope="session")
def stm32_board_bytes() -> bytes:
    """Board STM32 de référence (committé dans examples/) — 17 composants, 12 nets."""
    board = _SERVICE_ROOT / "examples" / "stm32-validation" / "expected" / "stm32_final.kicad_pcb"
    return board.read_bytes()
