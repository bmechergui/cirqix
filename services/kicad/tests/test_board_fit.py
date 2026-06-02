"""Board-fit must shrink the Edge.Cuts outline WITHOUT dropping footprints/pads."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from tools.placement import _fit_board_outline_to_components

PLACED = Path(r"C:\Users\Mechegui\Downloads\Kicadmcptest\test\meteo_arduino_placed.kicad_pcb")


def test_fit_preserves_footprints_and_pads():
    src = PLACED.read_bytes()
    n_fp = len(re.findall(r"\(footprint ", src.decode("utf-8", "replace")))
    n_pad = len(re.findall(r"\(pad ", src.decode("utf-8", "replace")))
    out = _fit_board_outline_to_components(src, margin_mm=5.0).decode("utf-8", "replace")
    assert len(re.findall(r"\(footprint ", out)) == n_fp, "footprints dropped"
    assert len(re.findall(r"\(pad ", out)) == n_pad, "pads dropped"


def test_fit_shrinks_outline_below_original():
    src = PLACED.read_bytes()
    out = _fit_board_outline_to_components(src, margin_mm=5.0).decode("utf-8", "replace")
    rects = re.findall(r'\(gr_rect \(start ([\d.\-]+) ([\d.\-]+)\) \(end ([\d.\-]+) ([\d.\-]+)\)', out)
    assert rects, "no Edge.Cuts rect emitted"
    x0, y0, x1, y1 = map(float, rects[-1])
    assert (x1 - x0) < 200.0 and (y1 - y0) < 160.0
    assert (x1 - x0) > 0 and (y1 - y0) > 0
