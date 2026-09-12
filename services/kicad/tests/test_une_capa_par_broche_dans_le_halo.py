"""Sur une ancre fine-pitch, UNE capa par broche d alimentation entre dans le
halo d escape ; les capas supplementaires de la meme broche restent a la
marge du halo.

Mesure du 2026-09-12 (carte-10, LQFP-48 a 3 broches VDD et 22 decouplages) :
les 22 capas collees a 2-8 mm formaient un mur autour de la puce et le
routage s effondrait (53-85 % de 2 a 8 couches). Une capa contre la broche
suffit a la regle de decouplage ; les autres n ont rien a faire dans les
couloirs de sortie des signaux.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))
sys.path.insert(0, str(_SERVICE / "kicad-tools" / "src"))

from kicad_tools.schema.pcb import PCB  # noqa: E402
from tools.placement_bypass import snap_cluster_members  # noqa: E402
from tests.test_placement_bypass_snap import _board_ic_et_trois_capas, _xy  # noqa: E402

_VCC_LOCAL = (-1.9, -2.54)


def _distances_a_la_broche(pcb: PCB) -> list[float]:
    ux, uy = _xy(pcb, "U1")
    px, py = ux + _VCC_LOCAL[0], uy + _VCC_LOCAL[1]
    return sorted(math.hypot(_xy(pcb, r)[0] - px, _xy(pcb, r)[1] - py) for r in ("C1", "C2", "C3"))


def test_ancre_dense_une_seule_capa_dans_le_halo(tmp_path):
    pcb = PCB.load(str(_board_ic_et_trois_capas(tmp_path)))
    assert snap_cluster_members(pcb, denses={"U1"}, marge_dense_mm=5.0) >= 1
    d = _distances_a_la_broche(pcb)
    assert d[0] <= 3.5, "la premiere capa doit couvrir la broche (%.1f mm)" % d[0]
    assert d[1] >= 5.0 and d[2] >= 5.0, (
        "les capas supplementaires doivent rester hors du halo : %s" % [round(v, 1) for v in d])


def test_ancre_non_dense_les_trois_capas_s_approchent(tmp_path):
    pcb = PCB.load(str(_board_ic_et_trois_capas(tmp_path)))
    assert snap_cluster_members(pcb) >= 1
    d = _distances_a_la_broche(pcb)
    assert d[2] < 5.0, "sans halo, rien n eloigne les capas supplementaires : %s" % [round(v, 1) for v in d]
