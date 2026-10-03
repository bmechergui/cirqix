"""Fixtures pytest — microservice KiCad Cirqix.

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


@pytest.fixture(autouse=True)
def _jamais_attendre_la_vraie_jvm(monkeypatch):
    """Un test ne doit ni attendre ni relancer la JVM Freerouting REELLE.

    `_api_freerouting_prete` patiente puis relance la JVM quand l API se tait
    alors que son processus tourne. Dans le conteneur, une JVM tourne : un test
    qui simule « API absente » attendrait 30 s puis tuerait la JVM du service.
    Les tests de ce mecanisme re-patchent ces deux points eux-memes.
    """
    # Importe ici, et non seulement lu dans sys.modules : un test qui charge le
    # module tard (TestClient, `main`) doit etre protege lui aussi.
    try:
        from routers import routing
    except Exception:  # noqa: BLE001 — un test sans le service n a rien a proteger
        routing = None
    if routing is not None and hasattr(routing, "_jvm_api_lancee"):
        monkeypatch.setattr(routing, "_jvm_api_lancee", lambda: False)
    # Un rapport DRC memorise par un test ne doit pas servir au suivant.
    if routing is not None and hasattr(routing, "_vider_cache_drc"):
        routing._vider_cache_drc()
    yield


@pytest.fixture(scope="session")
def stm32_board_bytes() -> bytes:
    """Board STM32 de référence (committé dans examples/) — 17 composants, 12 nets."""
    board = _SERVICE_ROOT / "examples" / "stm32-validation" / "expected" / "stm32_final.kicad_pcb"
    return board.read_bytes()
