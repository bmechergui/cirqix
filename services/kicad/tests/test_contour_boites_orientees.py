"""Le contour resserré contient les corps TOURNÉS.

Campagne du 2026-09-26, carte-11 : deux en-têtes 2 x 20 couchés à 90° par la
phase A, et un contour resserré de 27 x 108 mm qui les coupait — la boîte non
tournée du footprint était ajoutée à sa position. Routage à 0 % partout.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "kicad-tools" / "src"))

from kicad_tools.schema.pcb import PCB  # noqa: E402

from tools import placement as P  # noqa: E402
from tools import placement_zones as Z  # noqa: E402
from tools.contour_et_bords import ajuster_contour_au_placement  # noqa: E402

CARTE_11 = RACINE / "examples" / "carte-11-croisements" / "expected" / "placement.kicad_pcb"


def test_un_connecteur_couche_reste_dans_le_contour_resserre(tmp_path):
    chemin = tmp_path / "b.kicad_pcb"
    chemin.write_bytes(CARTE_11.read_bytes())
    pcb = PCB.load(str(chemin))
    conn = P._connector_refs(pcb)
    # Comme `auto_place` : couchés, puis collés au bord.
    assert Z.coucher_les_connecteurs(pcb, conn), "carte-11 porte des en-têtes debout"
    P._coller_les_ancrages_au_bord(pcb, conn, margin_mm=Z.MARGE_CONNECTEUR_BORD_MM)
    pcb.save(str(chemin))
    assert ajuster_contour_au_placement(chemin) is not None
    pcb = PCB.load(str(chemin))
    x0, x1, y0, y1 = P._outline_bounds(pcb)
    for fp in pcb.footprints:
        b = Z.boite_absolue(fp)
        assert x0 <= b[0] + 1e-6 and b[2] <= x1 + 1e-6, fp.reference
        assert y0 <= b[1] + 1e-6 and b[3] <= y1 + 1e-6, fp.reference
