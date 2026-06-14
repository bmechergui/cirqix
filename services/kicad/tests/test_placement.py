"""Tests — auto_place() (tools/placement.py), TDD.

Bug trouvé par examples/stm32-full-pipeline (2026-06-11) : call_agent_gen_pcb
peut poser un connecteur (J*/P*) hors du contour Edge.Cuts (ex: J1 à y=135 sur
un board 60x40mm). _connector_refs() le passe ensuite à PlacementOptimizer en
fixed_refs → l'optimiseur le traite comme un ancrage FIXE et le laisse
hors-carte → nets inroutables (routage 22% mesuré).

Le board de test est construit avec PCB.create() (contour Edge.Cuts gr_rect,
aucune dépendance KiCad/KICAD_FOOTPRINT_DIR) + des footprints minimaux injectés
en texte S-expr. ``center=True`` (défaut, chemin de prod PCBFromSchematic.
create_pcb()) est utilisé : le contour est alors en coordonnées sheet-absolute
décalées de ``pcb.board_origin`` par rapport à ``fp.position`` (board-relative)
— _clamp_fixed_refs_to_outline() doit convertir entre les deux repères.
"""
from __future__ import annotations

import base64
from pathlib import Path

import pytest

from kicad_tools.schema.pcb import PCB

from tools.placement import auto_place

_BOARD_W_MM, _BOARD_H_MM = 60.0, 40.0


def _footprint_sexp(ref: str, uuid: str, x_abs: float, y_abs: float) -> str:
    """Footprint minimal (connecteur 2 broches) à la position sheet-absolute donnée."""
    return f"""\
  (footprint "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
    (layer "F.Cu")
    (uuid "{uuid}")
    (at {x_abs} {y_abs})
    (property "Reference" "{ref}" (at 0 -2 0) (layer "F.SilkS")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Value" "Conn" (at 0 2 0) (layer "F.Fab")
      (effects (font (size 1 1) (thickness 0.15))))
    (pad "1" thru_hole circle (at 0 0) (size 1.7 1.7) (drill 1)
      (layers "*.Cu" "*.Mask") (net 0 ""))
    (pad "2" thru_hole circle (at 0 2.54) (size 1.7 1.7) (drill 1)
      (layers "*.Cu" "*.Mask") (net 0 ""))
  )
"""


def _board_with_connectors(
    tmp_path: Path,
    j1_board_xy: tuple[float, float],
    j2_board_xy: tuple[float, float] | None = None,
) -> bytes:
    """Board 60x40mm centré sur feuille A4 (PCB.create(center=True), défaut prod).

    ``j1_board_xy`` / ``j2_board_xy`` sont des coordonnées board-relative ;
    converties en sheet-absolute (+ pcb.board_origin) pour l'injection S-expr.
    """
    pcb = PCB.create(width=_BOARD_W_MM, height=_BOARD_H_MM, layers=2)
    ox, oy = pcb.board_origin
    board_path = tmp_path / "board.kicad_pcb"
    pcb.save(str(board_path))

    text = board_path.read_text(encoding="utf-8")
    close_idx = text.rstrip().rfind(")")

    inject = _footprint_sexp("J1", "11111111-1111-1111-1111-111111111111",
                              ox + j1_board_xy[0], oy + j1_board_xy[1])
    if j2_board_xy is not None:
        inject += _footprint_sexp("J2", "22222222-2222-2222-2222-222222222222",
                                   ox + j2_board_xy[0], oy + j2_board_xy[1])

    text = text[:close_idx] + inject + text[close_idx:]
    board_path.write_text(text, encoding="utf-8")
    return board_path.read_bytes()


def test_auto_place_clamps_connector_outside_outline(tmp_path):
    """J1 ancré (fixed_refs) hors du contour Edge.Cuts doit être ramené dedans
    AVANT l'optimisation — sinon PlacementOptimizer le laisse hors-carte."""
    pcb_bytes = _board_with_connectors(tmp_path, j1_board_xy=(30.0, 135.0))
    b64 = base64.b64encode(pcb_bytes).decode()

    result = auto_place(b64, _BOARD_W_MM, _BOARD_H_MM)

    j1 = next(p for p in result["positions"] if p["ref"] == "J1")
    assert 0.0 <= j1["x"] <= _BOARD_W_MM, f"J1.x={j1['x']} hors contour [0,{_BOARD_W_MM}]"
    assert 0.0 <= j1["y"] <= _BOARD_H_MM, f"J1.y={j1['y']} hors contour [0,{_BOARD_H_MM}]"


def test_auto_place_does_not_move_connector_inside_outline(tmp_path):
    """J2 déjà bien placé (board-relative (30,20), dans [0,60]x[0,40]) ne doit PAS
    être déplacé — non-régression coordonnées sheet-absolute (contour) vs
    board-relative (fp.position) sur un board centré (PCB.create(center=True),
    chemin de prod PCBFromSchematic.create_pcb())."""
    pcb_bytes = _board_with_connectors(
        tmp_path, j1_board_xy=(30.0, 135.0), j2_board_xy=(30.0, 20.0),
    )
    b64 = base64.b64encode(pcb_bytes).decode()

    result = auto_place(b64, _BOARD_W_MM, _BOARD_H_MM)

    j2 = next(p for p in result["positions"] if p["ref"] == "J2")
    assert j2["x"] == pytest.approx(30.0, abs=0.01)
    assert j2["y"] == pytest.approx(20.0, abs=0.01)
