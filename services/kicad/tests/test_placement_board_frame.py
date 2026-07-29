"""Garde : le placement laisse les composants DANS le contour Edge.Cuts.

Régression trouvée le 2026-07-28 (issue #72, correctif B) après le bump
kicad-tools 0.13.0 → 0.18.0 (PR #69).

``OptimizationWorkflow.write_to_pcb()`` a changé de convention de repère : il
écrit désormais les positions en **sheet-absolute** dans un champ que l'API PCB
lit en **board-relative**. Sur la fixture led-blinker (``board_origin`` =
118.5, 82.5), les composants ressortaient à x≈124-147 / y≈88-111 pour un contour
de 60×45 mm — soit exactement ``position + board_origin``.

Mesure comparative (``kct placement check`` 0.18.0) :

* board placé par 0.13.0 → *No placement conflicts found!*
* board placé par 0.18.0 → **7 erreurs off_board sur 8 composants**

Le seul composant épargné était le connecteur ancré ``J1``, dont ``auto_place``
restaure lui-même la position après coup — ce qui confirmait que le décalage
venait de l'écriture et non du calcul.

Conséquence en chaîne : ``kct route`` refusait (« placement invalid »), le repli
Freerouting prenait la main et rendait un board **sans netlist**, rapporté
``routed_percent=100`` (cf. ``test_routing_netlist_guard.py`` pour la garde aval).

Ces tests échouent si le repère régresse à nouveau, dans un sens ou dans l'autre.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from kicad_tools.schema.pcb import PCB  # noqa: E402

from tools.placement import auto_place, _normalize_to_board_frame  # noqa: E402

from tests.test_placement import (  # noqa: E402
    _BOARD_H_MM,
    _BOARD_W_MM,
    _board_with_connector_and_movable,
)


def _outline_board_frame(path: Path) -> tuple[float, float]:
    """Coin bas-droit du contour, ramené en repère board."""
    pcb = PCB.load(str(path))
    ox, oy = pcb.board_origin
    xs, ys = [], []
    for attr in ("graphic_items", "graphics", "lines"):
        for item in getattr(pcb, attr, None) or []:
            if getattr(item, "layer", None) != "Edge.Cuts":
                continue
            for point_attr in ("start", "end"):
                pt = getattr(item, point_attr, None)
                if pt is not None:
                    xs.append(pt[0] - ox)
                    ys.append(pt[1] - oy)
    assert xs and ys, "contour Edge.Cuts introuvable"
    return max(xs), max(ys)


def _outside(path: Path, width: float, height: float) -> dict[str, tuple[float, float]]:
    pcb = PCB.load(str(path))
    return {
        fp.reference: (fp.position[0], fp.position[1])
        for fp in pcb.footprints
        if not (0.0 <= fp.position[0] <= width and 0.0 <= fp.position[1] <= height)
    }


class TestNormalizeToBoardFrame:
    """Le helper corrige un board écrit en sheet-absolute, et ne touche pas un board sain."""

    def test_ramene_un_board_ecrit_en_sheet_absolute(self, tmp_path):
        board = tmp_path / "b.kicad_pcb"
        board.write_bytes(_board_with_connector_and_movable(tmp_path))
        width, height = _outline_board_frame(board)

        # Simule la régression : décale tout de board_origin.
        pcb = PCB.load(str(board))
        ox, oy = pcb.board_origin
        for fp in pcb.footprints:
            fp.position = (fp.position[0] + ox, fp.position[1] + oy)
        pcb.save(str(board))
        assert _outside(board, width, height), "le décalage simulé n'a pas pris"

        moved = _normalize_to_board_frame(board)

        assert moved > 0
        assert not _outside(board, width, height), "positions toujours hors contour"

    def test_ne_touche_pas_un_board_deja_correct(self, tmp_path):
        board = tmp_path / "b.kicad_pcb"
        board.write_bytes(_board_with_connector_and_movable(tmp_path))
        before = {
            fp.reference: fp.position for fp in PCB.load(str(board)).footprints
        }

        moved = _normalize_to_board_frame(board)

        after = {fp.reference: fp.position for fp in PCB.load(str(board)).footprints}
        assert moved == 0, "un board sain ne doit pas être modifié"
        assert after == before

    def test_ne_corrige_pas_un_debordement_partiel_legitime(self, tmp_path):
        """Un seul composant qui dépasse n'est PAS un problème de repère.

        Décaler tout le board dans ce cas déplacerait 7 composants corrects pour
        « réparer » le 8e. La normalisation ne s'applique que si le décalage
        explique l'écart pour TOUS les composants concernés.
        """
        board = tmp_path / "b.kicad_pcb"
        board.write_bytes(_board_with_connector_and_movable(tmp_path))
        width, height = _outline_board_frame(board)

        pcb = PCB.load(str(board))
        target = next(fp for fp in pcb.footprints if fp.reference == "R1")
        target.position = (width + 12.0, 5.0)
        pcb.save(str(board))

        moved = _normalize_to_board_frame(board)

        assert moved == 0, "un dépassement isolé ne relève pas du repère"


class TestAutoPlaceKeepsComponentsOnBoard:
    def test_auto_place_ne_laisse_aucun_composant_hors_contour(self, tmp_path):
        """Invariant de bout en bout — c'est lui qui a cassé avec le bump #69."""
        board = tmp_path / "board.kicad_pcb"
        board.write_bytes(_board_with_connector_and_movable(tmp_path))
        b64 = base64.b64encode(board.read_bytes()).decode("ascii")

        result = auto_place(b64, _BOARD_W_MM, _BOARD_H_MM)

        placed = tmp_path / "placed.kicad_pcb"
        placed.write_bytes(base64.b64decode(result["kicad_pcb_b64"]))
        dehors = _outside(placed, _BOARD_W_MM, _BOARD_H_MM)

        assert not dehors, f"composants hors contour après placement : {dehors}"

    def test_les_positions_rapportees_sont_dans_le_contour(self, tmp_path):
        """`positions` alimente le viewer : des coordonnées sheet-absolute y
        placeraient les composants hors de la carte à l'écran."""
        board = tmp_path / "board.kicad_pcb"
        board.write_bytes(_board_with_connector_and_movable(tmp_path))
        b64 = base64.b64encode(board.read_bytes()).decode("ascii")

        result = auto_place(b64, _BOARD_W_MM, _BOARD_H_MM)

        for pos in result["positions"]:
            assert 0.0 <= pos["x_mm"] <= _BOARD_W_MM, f"{pos['ref']} x={pos['x_mm']}"
            assert 0.0 <= pos["y_mm"] <= _BOARD_H_MM, f"{pos['ref']} y={pos['y_mm']}"
