"""Aucune pastille ne doit finir contre ou au-delà du bord — même après la grille.

Mesure du 2026-09-15, run dashboard `dae0a32f` (« diviseur de tension 5 V vers
3,3 V », schéma écrit par Claude Code) : routé à 100 %, puis DRC refusé —
4 `copper_edge_clearance` (0,40 et 0,10 mm pour 0,5 exigés) — et le run
s'arrêtait à ROUTING_DONE, « non-billable state ». Le journal du service donne
la séquence :

    10:43:43  réparation hors-carte : R1 (1.26,4.57) -> (3.23,7.07)       ← bien rentré
    10:43:50  2 footprint(s) alignés sur la grille, puis l'Inspecteur       ← SANS R1 ancré
    final     R1 en (1.33, 8.89) : pastille à -0,18 mm du bord              ← ressorti

Deux défauts, mesurés sur le service :

1. `PlacementAnalyzer` ne signale OFF_BOARD que si le CENTRE est dehors :
   R1 aux centres x = 0,9 (pastilles à -0,33), 1,33 (0,105) et 1,5 (0,275)
   n'était PAS signalé.
2. Le filet hors-carte passait AVANT la grille, dont l'Inspecteur n'ancre que
   les connecteurs et n'a aucune notion de contour : il repoussait R1 dehors,
   et plus rien ne vérifiait.
"""
from __future__ import annotations

import inspect
import shutil
import sys
from pathlib import Path

import pytest

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))
sys.path.insert(0, str(_SERVICE / "kicad-tools" / "src"))

from tools import placement as P  # noqa: E402

BORNES = (0.0, 9.77, 0.0, 23.57)
PORTEE_0603 = 1.225


class TestDetectionGeometrique:
    @pytest.mark.parametrize("x", [0.9, 1.33, 1.5])
    def test_pastilles_contre_ou_au_dela_du_bord_gauche(self, x):
        assert P._trop_pres_du_bord(BORNES, [("R1", x, 10.0, PORTEE_0603)]) == ["R1"]

    @pytest.mark.parametrize("x", [2.0, 3.3, 5.0])
    def test_pastilles_bien_a_l_interieur(self, x):
        assert P._trop_pres_du_bord(BORNES, [("R1", x, 10.0, PORTEE_0603)]) == []

    def test_les_quatre_bords(self):
        empreintes = [
            ("DROITE", 9.0, 10.0, PORTEE_0603),
            ("HAUT", 5.0, 0.8, PORTEE_0603),
            ("BAS", 5.0, 23.0, PORTEE_0603),
            ("CENTRE", 5.0, 12.0, PORTEE_0603),
        ]
        assert P._trop_pres_du_bord(BORNES, empreintes) == ["DROITE", "HAUT", "BAS"]


_BOARD = _SERVICE / "examples" / "carte-01-diviseur" / "expected" / "placement.kicad_pcb"


@pytest.mark.skipif(not _BOARD.exists(), reason="board de reference absent")
class TestReparationSurUnVraiBoard:
    def _board_avec_debord(self, tmp_path):
        from kicad_tools.schema.pcb import PCB

        f = tmp_path / "b.kicad_pcb"
        shutil.copy(_BOARD, f)
        pcb = PCB.load(str(f))
        bornes = P._outline_bounds(pcb)
        mobile = next(fp for fp in pcb.footprints if fp.reference and fp.reference[0] not in ("J", "P"))
        portee = P._footprint_reach_mm(mobile)
        # Centre DANS la carte, pastilles 0,3 mm au-delà du bord gauche : le cas
        # que l'analyseur ne signale pas.
        mobile.position = (bornes[0] + portee - 0.3, mobile.position[1])
        pcb.save(str(f))
        return f, mobile.reference

    def test_le_debord_partiel_est_detecte_et_repare(self, tmp_path, monkeypatch):
        from kicad_tools.schema.pcb import PCB

        f, ref = self._board_avec_debord(tmp_path)
        monkeypatch.setattr(P, "_off_board_refs", lambda path: [])  # l'analyseur ne le voit pas
        assert ref in P._refs_trop_pres_du_bord(f)

        assert ref in P._repair_off_board(f, anchored=[])
        pcb = PCB.load(str(f))
        bornes = P._outline_bounds(pcb)
        fp = next(fp for fp in pcb.footprints if fp.reference == ref)
        assert fp.position[0] - P._footprint_reach_mm(fp) >= bornes[0] + P._DEGAGEMENT_BORD_MM
        assert ref not in P._refs_trop_pres_du_bord(f)

    def test_un_ancrage_n_est_pas_deplace_par_la_detection_geometrique(self, tmp_path, monkeypatch):
        f, ref = self._board_avec_debord(tmp_path)
        monkeypatch.setattr(P, "_off_board_refs", lambda path: [])
        # Un connecteur ancré au bord est un choix : seule l'autorité de
        # l'analyseur (centre dehors) peut le faire bouger.
        # ⚠️ ON TESTE LA REF ANCRÉE, PAS LA LISTE ENTIÈRE. Cette assertion
        # exigeait `== []`, ce qui supposait que RIEN d'autre du board de
        # référence ne soit près d'un bord. Depuis le 2026-09-23 les cartes
        # sont resserrées sur leur circuit — `carte-01` passe de 25 × 20 à
        # 20,1 × 13,6 mm — et ses connecteurs sont donc LÉGITIMEMENT contre le
        # bord : c'est la règle « toujours les connecteurs à l'extrémité ».
        # La liste n'est plus vide, et elle n'a pas à l'être ; ce que ce test
        # prouve est qu'un ANCRAGE n'y figure pas.
        deplaces = P._repair_off_board(f, anchored=[ref])
        assert ref not in deplaces, (
            "un ancrage ne doit jamais être déplacé par la seule détection "
            "géométrique, quels que soient les autres composants")


class TestCablage:
    """Une règle jamais appelée — ou appelée trop tôt — est indistinguable d'une règle absente."""

    def test_le_filet_repasse_APRES_la_derniere_etape_qui_deplace(self):
        source = inspect.getsource(P._auto_place_une_fois)
        code = "\n".join(l for l in source.splitlines() if not l.lstrip().startswith("#"))
        grille = code.index("aligner_sur_grille(")
        dernier_filet = code.rindex("_garder_dans_le_contour(")
        serigraphie = code.index("_degager_la_serigraphie(")
        assert grille < dernier_filet < serigraphie

    def test_la_reparation_consulte_la_detection_geometrique(self):
        assert "_refs_trop_pres_du_bord(" in inspect.getsource(P._repair_off_board)
