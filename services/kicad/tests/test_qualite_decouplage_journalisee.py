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


def test_l_inspecteur_apres_le_snap_ancre_les_membres_colles():
    """carte-09 (service, 2026-09-12) : 35 membres ramenes a portee, puis
    l Inspecteur les dispersait a 19 mm pour resoudre UN conflit preexistant."""
    code = "\n".join(l.split("#")[0] for l in inspect.getsource(P._auto_place_une_fois).splitlines())
    i_save = code.find("pcb_snap.save(str(out))")
    i_fix = code.find("_resolve_remaining_conflicts(out, fixes_snap)", i_save)
    assert i_save != -1 and i_fix != -1
    assert "colles = sorted(_footprints_deplaces(positions_avant, out))" in code[i_save:i_fix]


def test_l_inspecteur_apres_le_snap_ancre_aussi_les_puces(tmp_path):
    """Diff des boards traces (carte-09, 2026-09-12) : capas ancrees, le Fixer
    deplacait U1 de 16 mm et U2 de 13 mm ; les capas restaient collees a
    l ancienne place de la puce."""
    from tools.placement_bypass import ancres_des_grappes
    pcb = PCB.load(str(_board_ic_and_far_bypass(tmp_path)))
    assert ancres_des_grappes(pcb) == {"U1"}
    code = "\n".join(l.split("#")[0] for l in inspect.getsource(P._auto_place_une_fois).splitlines())
    i = code.find("puces = sorted(ancres_des_grappes(pcb_snap))")
    j = code.find("_resolve_remaining_conflicts(out, fixes_snap)", i)
    assert i != -1 and j != -1
