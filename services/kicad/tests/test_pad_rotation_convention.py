"""Non-régression patch Cirqix #8 — convention de rotation des pads (io.py).

Le repère fichier KiCad a Y vers le BAS : la rotation des offsets locaux de
pads se fait avec l'angle NÉGUÉ. La matrice standard (ancien code upstream)
inversait les pads de tout footprint tourné à ±90° → le routeur terminait les
pistes au centre du pad voisin (25-32 shorting_items au DRC officiel sur le
board STM32 de référence, DRC interne aveugle car auto-cohérent).

Référence mesurée (kicad-cli 10.99, board réel) : R1 à (148.029049,
114.906515) rot 90, pad2 local (1, 0) → KiCad le place à (148.029049,
113.906515) = fp + (0, -1).
"""
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]  # services/kicad
sys.path.insert(0, str(_SERVICE_ROOT))
sys.path.insert(0, str(_SERVICE_ROOT / "kicad-tools" / "src"))

from kicad_tools.router.io import load_pads_for_analysis  # noqa: E402

_BOARD_ROT90 = """(kicad_pcb
  (version 20240108)
  (generator "test")
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))
  (net 0 "")
  (net 1 "A")
  (net 2 "B")
  (gr_rect (start 100 100) (end 120 120) (layer "Edge.Cuts") (stroke (width 0.1) (type default)) (fill none))
  (footprint "R_0805"
    (layer "F.Cu")
    (at 110 110 90)
    (property "Reference" "R1" (at 0 -1.5) (layer "F.SilkS"))
    (pad "1" smd roundrect (at -1 0 90) (size 1 1.3) (layers "F.Cu") (net 1 "A"))
    (pad "2" smd roundrect (at 1 0 90) (size 1 1.3) (layers "F.Cu") (net 2 "B"))
  )
)
"""


def test_rot90_pad_positions_match_kicad_convention(tmp_path):
    # KiCad (Y vers le bas, angle négué) : local (-1,0) @ 90° → fp + (0, +1) ;
    # local (1,0) @ 90° → fp + (0, -1). La matrice standard donnait l'inverse
    # (pads échangés) — c'est le bug corrigé par le patch Cirqix #8.
    board = tmp_path / "rot90.kicad_pcb"
    board.write_text(_BOARD_ROT90, encoding="utf-8")
    pads = load_pads_for_analysis(str(board))
    by_net = {p.net_name: (round(float(p.x), 3), round(float(p.y), 3)) for p in pads}
    ax, ay = by_net["A"]  # pad 1, local (-1, 0)
    bx, by = by_net["B"]  # pad 2, local (1, 0)
    assert (round(ax, 3), round(ay, 3)) == (110.0, 111.0), \
        f"pad 1 (local -1,0 @90°) attendu à (110,111), obtenu ({ax},{ay})"
    assert (round(bx, 3), round(by, 3)) == (110.0, 109.0), \
        f"pad 2 (local 1,0 @90°) attendu à (110,109), obtenu ({bx},{by})"
