"""D-2026-09-27-b : un connecteur se colle au bord qui fait face aux broches
FIXES qu il relie (module, empreinte verrouillée), masse exclue."""
from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace as NS

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "kicad-tools" / "src"))

from tools import placement as P  # noqa: E402


def _pad(net, x=0.0, y=0.0):
    return NS(net_name=net, position=(x, y), rotation=0.0)


def _board(module_xy):
    j1 = NS(reference="J1", position=(10.0, 10.0), rotation=0.0,
            pads=[_pad("VIN"), _pad("GND", 2.54, 0.0)])
    a1 = NS(reference="A1", position=module_xy, rotation=0.0,
            pads=[_pad("VIN", 0.0, 0.0), _pad("GND", 5.0, 0.0), _pad("D2", 10.0, 0.0)])
    return NS(footprints=[j1, a1]), j1


def test_la_direction_vise_la_broche_vin_du_module():
    pcb, j1 = _board((90.0, 50.0))            # module à droite du centre (50, 50)
    a = P._direction_vers_les_fixes(pcb, j1, {"A1"}, (50.0, 50.0))
    assert a is not None and abs(a) < 1e-6    # vers la droite


def test_la_masse_ne_compte_pas_et_sans_fixe_rien():
    pcb, j1 = _board((50.0, 90.0))
    j1.pads = [_pad("GND")]
    assert P._direction_vers_les_fixes(pcb, j1, {"A1"}, (50.0, 50.0)) is None
    pcb, j1 = _board((50.0, 90.0))
    assert P._direction_vers_les_fixes(pcb, j1, set(), (50.0, 50.0)) is None


def test_le_connecteur_se_couche_le_long_du_bord_vise(tmp_path):
    from kicad_tools.schema.pcb import PCB
    source = RACINE / "examples" / "carte-07-multi-io" / "expected" / "placement.kicad_pcb"
    pcb = PCB.load(str(source))
    j = next(f for f in pcb.footprints if f.reference in P._connector_refs(pcb))
    b = P._boite_orientee_fp(j)
    horizontal = (b[2] - b[0]) >= (b[3] - b[1])
    P._coucher_face_a(j, math.pi / 2 if not horizontal else 0.0)    # bord opposé à son axe
    b = P._boite_orientee_fp(j)
    assert ((b[2] - b[0]) >= (b[3] - b[1])) != horizontal


def test_le_collage_utilise_la_direction():
    src = (RACINE / "tools" / "placement.py").read_text(encoding="utf-8")
    corps = src[src.index("def _coller_les_ancrages_au_bord"):]
    assert "direction = _direction_vers_les_fixes(pcb, fp, ignores, centre)" in corps
    assert "_coucher_face_a(fp, direction)" in corps
    assert "_aligner_en_face(fp, direction, _barycentre_des_fixes(pcb, fp, ignores))" in corps


def test_le_connecteur_se_pose_en_face_de_la_broche_visee():
    """Campagne du 2026-09-28 : J1 collé au bon bord mais loin de VIN."""
    from kicad_tools.schema.pcb import PCB
    source = RACINE / "examples" / "carte-07-multi-io" / "expected" / "placement.kicad_pcb"
    pcb = PCB.load(str(source))
    j = next(f for f in pcb.footprints if f.reference in P._connector_refs(pcb))
    P._aligner_en_face(j, math.pi, (0.0, 70.0))            # bord gauche, broche à y = 70
    b = P._boite_orientee_fp(j)
    assert abs(j.position[1] + (b[1] + b[3]) / 2 - 70.0) < 1e-6
    P._aligner_en_face(j, math.pi / 2, (33.0, 99.0))       # bord bas, broche à x = 33
    b = P._boite_orientee_fp(j)
    assert abs(j.position[0] + (b[0] + b[2]) / 2 - 33.0) < 1e-6
