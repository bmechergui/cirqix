"""auto_place delegates to the official kicad-tools workflow.

Verifies it places footprints on the board (not parked at -1000) via
place_unplaced + kct placement optimize.
"""
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

GENERATED = Path(r"C:\Users\Mechegui\Downloads\Kicadmcptest\test\meteo_arduino.kicad_pcb")

pytestmark = pytest.mark.skipif(
    not GENERATED.exists(),
    reason="run tests/test_full_pipeline.py first to generate meteo_arduino.kicad_pcb",
)


def test_auto_place_places_all_footprints_on_board():
    from tools.placement import auto_place

    src = GENERATED.read_bytes()
    res = auto_place(base64.b64encode(src).decode(), 200.0, 160.0)

    assert res["placed_count"] == 5
    assert len(res["positions"]) == 5
    # All footprints must be on the board, not parked at (-1000, -1000)
    for p in res["positions"]:
        assert p["x"] > -100 and p["y"] > -100, f"{p['ref']} still off-board: {p}"
        assert 0 <= p["x"] <= 250 and 0 <= p["y"] <= 250, f"{p['ref']} out of bounds: {p}"
