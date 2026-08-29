"""Le pont de masque minimum doit etre JUGE, pas laisse a zero.

`write_mfr_project_sidecar` alignait deja le juge DRC sur les minima
fabricant — pericage, anneau, degagement, largeur, bord de carte. Mesure du
2026-08-29 sur le sidecar reellement ecrit :

    min_through_hole_diameter = 0.3     min_via_annular_width = 0.15
    min_clearance             = 0.127   min_track_width       = 0.127
    min_copper_edge_clearance = 0.3     min_via_diameter      = 0.6
    solder_mask_min_width     = 0.0     <- AUCUN controle
    solder_mask_clearance     = 0.0

⚠️ Les deux zeros n ont PAS le meme sens. `solder_mask_clearance = 0` est
JUSTE : JLCPCB travaille en 1:1, l ouverture de masque egale la pastille.
`solder_mask_min_width = 0` desarme en revanche le controle du PONT de masque
entre pastilles — le risque numero un d un LQFP-48 au pas de 0,5 mm, ou deux
ouvertures voisines peuvent fusionner et court-circuiter a l assemblage.

Valeur publiee par JLCPCB (capabilities, cuivre 1 oz, vernis vert) : 0,10 mm.
Elle vient du fabricant ; le profil `kicad-tools` ne la porte pas.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.drc import write_mfr_project_sidecar, _PONT_DE_MASQUE_MM


_BOARD = """(kicad_pcb (version 20240108) (generator "cirqix")
  (general (thickness 1.6))
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))
)
"""


def _regles(tmp_path: Path) -> dict:
    pcb = tmp_path / "b.kicad_pcb"
    pcb.write_text(_BOARD, encoding="utf-8")
    pro = write_mfr_project_sidecar(pcb, "jlcpcb", 2)
    data = json.loads(Path(pro).read_text(encoding="utf-8"))
    return data["board"]["design_settings"]["rules"]


def test_le_pont_de_masque_est_juge(tmp_path):
    assert _regles(tmp_path)["solder_mask_min_width"] == _PONT_DE_MASQUE_MM


def test_la_valeur_vient_du_fabricant(tmp_path):
    """JLCPCB publie 0,10 mm en 1 oz vernis vert. On ne l invente pas."""
    assert _PONT_DE_MASQUE_MM == pytest.approx(0.10)


def test_le_degagement_de_masque_reste_a_zero(tmp_path):
    """1:1 chez JLCPCB — l ouverture egale la pastille.

    Ce zero-la est un CHOIX du fabricant, pas un controle desarme. Le
    confondre avec l autre conduirait a elargir les ouvertures sans raison.
    """
    assert _regles(tmp_path)["solder_mask_clearance"] == 0.0
