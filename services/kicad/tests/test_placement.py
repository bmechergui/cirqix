"""Tests — auto_place() + helpers (tools/placement.py), TDD.

Placement 100% natif kicad-tools : ``auto_place`` délègue à
``OptimizationWorkflow`` (``kct placement optimize --strategy hybrid --cluster``),
aucun algo custom. Les connecteurs (J*/P*) sont ancrés (``fixed_refs``) et
clampés dans le contour Edge.Cuts AVANT l'optimisation.

Invariants testés :
  - _connector_refs : retourne les refs J*/P*
  - _clamp_fixed_refs_to_outline : ramène un connecteur hors-carte dans le contour
  - auto_place : connecteur hors-carte → ramené dans le contour ;
    connecteur bien placé → reste stable (ancré).
"""
from __future__ import annotations

import base64
from pathlib import Path

import pytest

from kicad_tools.placement.analyzer import DesignRules, PlacementAnalyzer
from kicad_tools.placement.conflict import ConflictSeverity
from kicad_tools.schema.pcb import PCB

from tools.placement import (
    auto_place,
    _connector_refs,
    _clamp_fixed_refs_to_outline,
    _resolve_remaining_conflicts,
)

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


def _resistor_sexp(ref: str, uuid: str, x_abs: float, y_abs: float, net: int) -> str:
    """Footprint mobile minimal (résistance 2 pads SMD) à la position donnée.

    Les deux pads partagent le même ``net`` qu'une autre résistance pour que
    l'optimiseur ait un wirelength à minimiser (composant mobile, non ancré).
    """
    return f"""\
  (footprint "Resistor_SMD:R_0402_1005Metric"
    (layer "F.Cu")
    (uuid "{uuid}")
    (at {x_abs} {y_abs})
    (property "Reference" "{ref}" (at 0 -2 0) (layer "F.SilkS")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Value" "10k" (at 0 2 0) (layer "F.Fab")
      (effects (font (size 1 1) (thickness 0.15))))
    (pad "1" smd roundrect (at -0.5 0) (size 0.6 0.6) (layers "F.Cu" "F.Paste" "F.Mask")
      (net {net} "SIG"))
    (pad "2" smd roundrect (at 0.5 0) (size 0.6 0.6) (layers "F.Cu" "F.Paste" "F.Mask")
      (net 0 ""))
  )
"""


def _board_with_movable_components(tmp_path: Path) -> bytes:
    """Board 60x40mm avec 3 résistances mobiles empilées au centre (overlap).

    Aucune n'est un connecteur → toutes mobiles. Partagent le net 1 (SIG) →
    l'optimiseur a un wirelength à minimiser + un overlap à résoudre. Un
    placement réellement appliqué DOIT les séparer.
    """
    pcb = PCB.create(width=_BOARD_W_MM, height=_BOARD_H_MM, layers=2)
    ox, oy = pcb.board_origin
    board_path = tmp_path / "board.kicad_pcb"
    pcb.save(str(board_path))

    text = board_path.read_text(encoding="utf-8")
    close_idx = text.rstrip().rfind(")")

    inject = ""
    for i, ref in enumerate(("R1", "R2", "R3")):
        uuid = f"3333333{i}-3333-3333-3333-333333333333"
        inject += _resistor_sexp(ref, uuid, ox + 30.0, oy + 20.0, net=1)

    text = text[:close_idx] + inject + text[close_idx:]
    board_path.write_text(text, encoding="utf-8")
    return board_path.read_bytes()


def _board_with_connectors(
    tmp_path: Path,
    j1_board_xy: tuple[float, float],
    j2_board_xy: tuple[float, float] | None = None,
) -> bytes:
    """Board 60x40mm centré sur feuille A4 (PCB.create(center=True), défaut prod).

    ``j1_board_xy`` / ``j2_board_xy`` sont board-relative ; convertis en
    sheet-absolute (+ pcb.board_origin) pour l'injection S-expr.
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


# ---------------------------------------------------------------------------
# Tests unitaires — _connector_refs
# ---------------------------------------------------------------------------

def test_connector_refs_detects_j_and_p(tmp_path):
    """Les refs J*/P* sont détectées comme connecteurs."""
    pcb_bytes = _board_with_connectors(tmp_path, j1_board_xy=(30.0, 20.0))
    board_path = tmp_path / "b.kicad_pcb"
    board_path.write_bytes(pcb_bytes)
    pcb = PCB.load(str(board_path))
    assert "J1" in _connector_refs(pcb)


# ---------------------------------------------------------------------------
# Tests unitaires — _clamp_fixed_refs_to_outline
# ---------------------------------------------------------------------------

def test_clamp_brings_connector_inside_outline(tmp_path):
    """J1 hors du contour (y=135mm board-relative) → clampé dans [0, H]."""
    pcb_bytes = _board_with_connectors(tmp_path, j1_board_xy=(30.0, 135.0))
    board_path = tmp_path / "b.kicad_pcb"
    board_path.write_bytes(pcb_bytes)
    pcb = PCB.load(str(board_path))

    clamped = _clamp_fixed_refs_to_outline(pcb, ["J1"])

    assert "J1" in clamped
    j1 = next(fp for fp in pcb.footprints if fp.reference == "J1")
    # le clamp ramène la position dans les bornes du contour (board-relative)
    assert 0.0 <= j1.position[1] <= _BOARD_H_MM


def test_clamp_leaves_connector_inside_unchanged(tmp_path):
    """J2 déjà dans le contour → non modifié."""
    pcb_bytes = _board_with_connectors(
        tmp_path, j1_board_xy=(30.0, 135.0), j2_board_xy=(30.0, 20.0),
    )
    board_path = tmp_path / "b.kicad_pcb"
    board_path.write_bytes(pcb_bytes)
    pcb = PCB.load(str(board_path))

    clamped = _clamp_fixed_refs_to_outline(pcb, ["J1", "J2"])

    assert "J2" not in clamped


# ---------------------------------------------------------------------------
# Tests intégration — auto_place (commande native)
# ---------------------------------------------------------------------------

def test_auto_place_actually_moves_movable_components(tmp_path):
    """Régression : auto_place DOIT appliquer les positions optimisées.

    3 résistances mobiles empilées au même point (overlap) doivent être
    séparées par l'optimiseur. Sans ``write_to_pcb()`` (bug d43ab8b),
    ``run()`` calcule mais n'écrit jamais → les positions sortent identiques
    à l'entrée → ce test échoue (RED).
    """
    pcb_bytes = _board_with_movable_components(tmp_path)
    b64 = base64.b64encode(pcb_bytes).decode()

    result = auto_place(b64, _BOARD_W_MM, _BOARD_H_MM)

    pos = {p["ref"]: (p["x"], p["y"]) for p in result["positions"]
           if p["ref"] in ("R1", "R2", "R3")}
    # au moins un composant doit avoir quitté le point de départ (30, 20)
    moved = [r for r, (x, y) in pos.items()
             if abs(x - 30.0) > 0.5 or abs(y - 20.0) > 0.5]
    assert moved, f"aucune résistance déplacée — positions={pos} (write_to_pcb manquant ?)"
    # les 3 ne doivent plus être empilées au même point
    assert len(set(pos.values())) > 1, f"composants toujours empilés : {pos}"


def test_auto_place_clamps_connector_outside_outline(tmp_path):
    """J1 ancré hors du contour Edge.Cuts doit être ramené dedans (clamp natif)."""
    pcb_bytes = _board_with_connectors(tmp_path, j1_board_xy=(30.0, 135.0))
    b64 = base64.b64encode(pcb_bytes).decode()

    result = auto_place(b64, _BOARD_W_MM, _BOARD_H_MM)

    j1 = next(p for p in result["positions"] if p["ref"] == "J1")
    assert 0.0 <= j1["x"] <= _BOARD_W_MM, f"J1.x={j1['x']} hors contour [0,{_BOARD_W_MM}]"
    assert 0.0 <= j1["y"] <= _BOARD_H_MM, f"J1.y={j1['y']} hors contour [0,{_BOARD_H_MM}]"


def test_auto_place_does_not_move_connector_inside_outline(tmp_path):
    """J2 déjà bien placé (30,20) reste à sa position : ancré (fixed_refs natif)."""
    pcb_bytes = _board_with_connectors(
        tmp_path, j1_board_xy=(30.0, 135.0), j2_board_xy=(30.0, 20.0),
    )
    b64 = base64.b64encode(pcb_bytes).decode()

    result = auto_place(b64, _BOARD_W_MM, _BOARD_H_MM)

    j2 = next(p for p in result["positions"] if p["ref"] == "J2")
    assert j2["x"] == pytest.approx(30.0, abs=0.5)
    assert j2["y"] == pytest.approx(20.0, abs=0.5)


# ---------------------------------------------------------------------------
# Tests — _resolve_remaining_conflicts (kct placement fix natif)
# ---------------------------------------------------------------------------

def test_resolve_remaining_conflicts_removes_pad_clearance_errors(tmp_path):
    """_resolve_remaining_conflicts (kct placement fix natif) doit éliminer les
    conflits ERROR (pad clearance / hole ≤0 — risque de court-circuit réel).

    L'optimiseur ``hybrid+cluster`` est stochastique (pas de seed fixe) : sur le
    board STM32 réel, un benchmark de 5 runs a donné 8/0/3/0/5 conflits selon le
    tirage. Ce test ne dépend PAS du GA — il construit directement un board en
    conflit (3 résistances empilées) pour vérifier que la passe de réparation
    native (PlacementFixer.iterative_fix, ~0.05s, pas de ré-exécution GA) est
    déterministe et efficace.
    """
    pcb_bytes = _board_with_movable_components(tmp_path)
    board_path = tmp_path / "overlap.kicad_pcb"
    board_path.write_bytes(pcb_bytes)

    before, after = _resolve_remaining_conflicts(board_path, anchored=[])

    assert before > 0, "le board de test devrait avoir des conflits ERROR au départ"
    assert after == 0, f"conflits ERROR (court-circuit) non résolus : {after}"


def test_auto_place_result_has_no_error_conflicts(tmp_path):
    """Régression : le board renvoyé par auto_place ne doit JAMAIS contenir de
    conflit ERROR (pad clearance / hole ≤0), même quand le GA stochastique en
    laisse — la réparation native est chaînée automatiquement dans auto_place.
    """
    pcb_bytes = _board_with_movable_components(tmp_path)
    b64 = base64.b64encode(pcb_bytes).decode()

    result = auto_place(b64, _BOARD_W_MM, _BOARD_H_MM)

    out_path = tmp_path / "result.kicad_pcb"
    out_path.write_bytes(base64.b64decode(result["kicad_pcb_b64"]))

    conflicts = PlacementAnalyzer().find_conflicts(str(out_path), DesignRules())
    errors = [c for c in conflicts if c.severity == ConflictSeverity.ERROR]
    assert not errors, f"conflits ERROR restants après auto_place : {errors}"
