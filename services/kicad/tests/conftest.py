"""Fixtures pytest — microservice KiCad Layrix.

Ajoute au sys.path :
- services/kicad        → import des modules `tools.*` / `routers.*`
- kicad-tools/src       → import du package vendoré `kicad_tools`
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[1]          # services/kicad
_KICAD_TOOLS_SRC = _SERVICE_ROOT / "kicad-tools" / "src"

for p in (str(_SERVICE_ROOT), str(_KICAD_TOOLS_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture(scope="session")
def stm32_board_bytes() -> bytes:
    """Board STM32 de référence (committé dans examples/) — 17 composants, 12 nets."""
    board = _SERVICE_ROOT / "examples" / "stm32-validation" / "expected" / "stm32_final.kicad_pcb"
    return board.read_bytes()
