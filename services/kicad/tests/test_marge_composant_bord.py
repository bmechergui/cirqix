"""D-2026-09-15-a (validée) — la COURTYARD d'un composant reste à 2 mm du bord.

Mesure du 2026-09-15 : 5 runs du prompt « diviseur de tension », 2 portant
`silk_edge_clearance`. R2 était à 1,2 mm du bord, ses pastilles dessous : le
contrôle de #201 (pastilles à 0,75 mm) le laissait passer, et `degager_references`
(#202) ne trouvait aucune place pour son texte de 1 mm. La place d'une
référence se réserve au PLACEMENT, pas après.

Les ancrages (connecteurs) restent exemptés : un connecteur posé au bord est un
choix.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))
sys.path.insert(0, str(_SERVICE / "kicad-tools" / "src"))

from tools import placement as P  # noqa: E402

BORNES = (0.0, 9.77, 0.0, 23.57)


def test_la_marge_est_celle_de_la_decision():
    assert P._MARGE_COURTYARD_BORD_MM == 2.0


class TestDetectionParCourtyard:
    @pytest.mark.parametrize("x0", [0.0, 1.0, 1.99])
    def test_courtyard_a_moins_de_2_mm_du_bord_gauche(self, x0):
        assert P._courtyard_trop_pres_du_bord(BORNES, [("R2", (x0, 10.0, x0 + 3.0, 11.5))]) == ["R2"]

    @pytest.mark.parametrize("x0", [2.0, 3.5])
    def test_courtyard_assez_loin(self, x0):
        assert P._courtyard_trop_pres_du_bord(BORNES, [("R2", (x0, 10.0, x0 + 3.0, 11.5))]) == []

    def test_pile_a_la_marge_n_est_pas_signale(self):
        # Banc du 2026-09-15, carte-01 : R1 reposé exactement à 2,0 mm restait
        # signalé à cause de l'arrondi (1,9999).
        assert P._courtyard_trop_pres_du_bord(BORNES, [("R1", (1.9999, 10.0, 4.9999, 11.5))]) == []

    def test_les_quatre_bords(self):
        boites = [
            ("HAUT", (3.0, 1.2, 6.0, 2.7)),       # le cas mesuré : R2 à 1,2 mm du bord haut
            ("DROITE", (5.0, 10.0, 8.0, 11.5)),
            ("BAS", (3.0, 21.0, 6.0, 22.5)),
            ("CENTRE", (3.0, 10.0, 6.0, 11.5)),
        ]
        assert P._courtyard_trop_pres_du_bord(BORNES, boites) == ["HAUT", "DROITE", "BAS"]


_BOARD = _SERVICE / "examples" / "carte-01-diviseur" / "expected" / "placement.kicad_pcb"


@pytest.mark.skipif(not _BOARD.exists(), reason="board de reference absent")
class TestSurUnVraiBoard:
    def test_pastilles_assez_loin_mais_courtyard_trop_pres_puis_repare(self, tmp_path, monkeypatch):
        from kicad_tools.schema.pcb import PCB

        f = tmp_path / "b.kicad_pcb"
        shutil.copy(_BOARD, f)
        pcb = PCB.load(str(f))
        bornes = P._outline_bounds(pcb)
        mobile = next(fp for fp in pcb.footprints if fp.reference and fp.reference[0] not in ("J", "P"))
        bx0, _, _, _ = P._boite_locale_fp(mobile)
        # Courtyard à 1,0 mm du bord gauche : les pastilles, plus à l'intérieur,
        # passent le contrôle de #201 — c'est exactement le cas de R2.
        mobile.position = (bornes[0] + 1.0 - bx0, mobile.position[1])
        pcb.save(str(f))
        ref = mobile.reference
        monkeypatch.setattr(P, "_off_board_refs", lambda path: [])

        assert ref in P._refs_trop_pres_du_bord(f)
        assert ref in P._repair_off_board(f, anchored=[])

        pcb = PCB.load(str(f))
        bornes = P._outline_bounds(pcb)
        fp = next(fp for fp in pcb.footprints if fp.reference == ref)
        bx0, by0, bx1, by1 = P._boite_locale_fp(fp)
        x, y = fp.position
        assert x + bx0 >= bornes[0] + P._MARGE_COURTYARD_BORD_MM - 1e-6
        assert ref not in P._refs_trop_pres_du_bord(f)
