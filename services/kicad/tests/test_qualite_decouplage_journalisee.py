"""Le service journalise la qualite du decouplage qu il livre (moy/max).
2026-09-12 : 3 mm en appel direct, 31 mm par HTTP, et aucune ligne pour le voir."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))
sys.path.insert(0, str(_SERVICE / "kicad-tools" / "src"))

from kicad_tools.schema.pcb import PCB  # noqa: E402
from tools import placement as P  # noqa: E402
from tools.placement_bypass import qualite_decouplage, snap_cluster_members  # noqa: E402
from tests.test_placement_bypass_snap import _board_ic_and_far_bypass  # noqa: E402


def test_la_mesure_baisse_apres_le_snap(tmp_path):
    pcb = PCB.load(str(_board_ic_and_far_bypass(tmp_path)))
    avant = qualite_decouplage(pcb)
    snap_cluster_members(pcb)
    apres = qualite_decouplage(pcb)
    assert avant[2] == apres[2] == 1 and apres[0] < avant[0] and apres[0] <= 3.5


def test_le_service_journalise_apres_le_snap_et_a_la_livraison():
    code = "\n".join(l.split("#")[0] for l in inspect.getsource(P._auto_place_une_fois).splitlines())
    assert '_journaliser_qualite(out, "apres snap")' in code
    assert '_journaliser_qualite(out, "livre")' in code
