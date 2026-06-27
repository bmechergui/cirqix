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

import tools.placement as placement_module

from kicad_tools.placement.analyzer import DesignRules, PlacementAnalyzer
from kicad_tools.placement.conflict import ConflictSeverity, ConflictType
from kicad_tools.schema.pcb import PCB

from tools.placement import (
    auto_place,
    _connector_refs,
    _clamp_fixed_refs_to_outline,
    _resolve_remaining_conflicts,
    _refine_with_cmaes,
    _max_displacement_mm,
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


def _board_with_courtyard_overlap(tmp_path: Path) -> bytes:
    """Board 60x40mm avec R1/R2 espacés de façon à ce que SEUL le courtyard
    chevauche (WARNING), SANS chevauchement de pads (0 ERROR).

    Reproduit le cas réel R1-R2 du board STM32 (courtyard_overlap ~0.2-0.3mm) :
    pads R_0402 à ±0.5mm (size 0.6) → pads_bbox large de 1.6mm, courtyard
    (pads_bbox + 0.25mm) large de 2.1mm. À 1.9mm d'écart entre centres, les
    pads sont séparés de 0.3mm (pas d'ERROR) mais les courtyards se chevauchent
    de ~0.2mm (courtyard_overlap WARNING). Composants same-net (SIG) → le
    courtyard_overlap est net-agnostique, déclenché de toute façon.
    """
    pcb = PCB.create(width=_BOARD_W_MM, height=_BOARD_H_MM, layers=2)
    ox, oy = pcb.board_origin
    board_path = tmp_path / "board.kicad_pcb"
    pcb.save(str(board_path))

    text = board_path.read_text(encoding="utf-8")
    close_idx = text.rstrip().rfind(")")

    inject = _resistor_sexp("R1", "44444441-4444-4444-4444-444444444441", ox + 30.0, oy + 20.0, net=1)
    inject += _resistor_sexp("R2", "44444442-4444-4444-4444-444444444442", ox + 31.9, oy + 20.0, net=1)

    text = text[:close_idx] + inject + text[close_idx:]
    board_path.write_text(text, encoding="utf-8")
    return board_path.read_bytes()


def _board_with_connector_and_movable(tmp_path: Path) -> bytes:
    """Board 60x40mm avec 1 connecteur ancré (J1) + 3 résistances mobiles empilées.

    Sert à vérifier que le micro-raffinement CMA-ES (_refine_with_cmaes) sépare
    les composants mobiles SANS jamais déplacer J1 (ancrage mécanique).
    """
    pcb = PCB.create(width=_BOARD_W_MM, height=_BOARD_H_MM, layers=2)
    ox, oy = pcb.board_origin
    board_path = tmp_path / "board.kicad_pcb"
    pcb.save(str(board_path))

    text = board_path.read_text(encoding="utf-8")
    close_idx = text.rstrip().rfind(")")

    inject = _footprint_sexp("J1", "11111111-1111-1111-1111-111111111111", ox + 5.0, oy + 5.0)
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


def test_resolve_remaining_conflicts_also_clears_courtyard_warnings(tmp_path):
    """Régression : _resolve_remaining_conflicts doit AUSSI éliminer les conflits
    WARNING (courtyard_overlap), pas seulement les ERROR.

    Avant ce fix, la passe de réparation retournait immédiatement (0, 0) dès
    qu'il n'y avait aucun ERROR, ignorant les chevauchements de courtyard — le
    cas R1-R2 du board STM32 qui sortait en « 0 ERROR / 1 WARNING ».

    Board construit avec R1/R2 espacés : SEUL le courtyard chevauche (WARNING),
    aucun chevauchement de pads (0 ERROR). Le fixer natif (PlacementFixer.
    iterative_fix → _calc_courtyard_fix) doit écarter les composants et ramener
    le board à 0 ERROR ET 0 WARNING — 100% natif, zéro algo custom.
    """
    pcb_bytes = _board_with_courtyard_overlap(tmp_path)
    board_path = tmp_path / "courtyard.kicad_pcb"
    board_path.write_bytes(pcb_bytes)

    # Pré-condition : ≥1 courtyard_overlap WARNING, 0 ERROR.
    conflicts_before = PlacementAnalyzer().find_conflicts(str(board_path), DesignRules())
    warns_before = [c for c in conflicts_before if c.severity == ConflictSeverity.WARNING]
    errors_before = [c for c in conflicts_before if c.severity == ConflictSeverity.ERROR]
    assert any(c.type == ConflictType.COURTYARD_OVERLAP for c in warns_before), \
        "le board de test devrait avoir un courtyard_overlap WARNING au départ"
    assert not errors_before, "le board de test ne doit pas avoir d'ERROR (pads non chevauchants)"

    _resolve_remaining_conflicts(board_path, anchored=[])

    conflicts_after = PlacementAnalyzer().find_conflicts(str(board_path), DesignRules())
    warns_after = [c for c in conflicts_after if c.severity == ConflictSeverity.WARNING]
    errors_after = [c for c in conflicts_after if c.severity == ConflictSeverity.ERROR]
    assert not errors_after, f"conflits ERROR restants : {errors_after}"
    assert not warns_after, f"conflits WARNING (courtyard_overlap) restants : {warns_after}"


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
    warnings = [c for c in conflicts if c.severity == ConflictSeverity.WARNING]
    assert not errors, f"conflits ERROR restants après auto_place : {errors}"
    assert not warnings, f"conflits WARNING restants après auto_place : {warnings}"


# ---------------------------------------------------------------------------
# Tests — _refine_with_cmaes (kct optimize-placement --strategy cmaes natif)
# ---------------------------------------------------------------------------

def test_refine_with_cmaes_separates_overlap_and_preserves_anchored(tmp_path):
    """_refine_with_cmaes (CMA-ES seed=current, micro-raffinement natif) doit
    séparer les composants mobiles empilés SANS jamais déplacer un ref ancré.

    Le CLI natif (kct optimize-placement) n'a pas de notion de verrouillage par
    position — il traite tous les footprints comme mobiles. La fonction doit
    donc restaurer la position pré-CMA-ES des refs ``anchored`` après l'appel.
    """
    pcb_bytes = _board_with_connector_and_movable(tmp_path)
    board_path = tmp_path / "board.kicad_pcb"
    board_path.write_bytes(pcb_bytes)

    j1_before = next(
        fp.position for fp in PCB.load(str(board_path)).footprints if fp.reference == "J1"
    )

    _refine_with_cmaes(board_path, anchored=["J1"], time_budget_s=5.0)

    pcb_after = PCB.load(str(board_path))
    pos = {fp.reference: fp.position for fp in pcb_after.footprints}

    assert pos["J1"] == pytest.approx(j1_before, abs=1e-6), "connecteur ancré déplacé par le CMA-ES"
    moved = [r for r in ("R1", "R2", "R3")
             if abs(pos[r][0] - 30.0) > 0.5 or abs(pos[r][1] - 20.0) > 0.5]
    assert moved, f"aucune résistance affinée par le CMA-ES — positions={pos}"


def test_refine_with_cmaes_passes_bounded_max_iterations_kwarg(tmp_path, monkeypatch):
    """Vérifie le câblage de l'appel : ``max_iterations`` est passé
    explicitement à ``run_optimize_placement`` (test de wiring — ne fait
    pas tourner le vrai CMA-ES, voir le test comportemental suivant pour la
    mesure de déplacement réelle, seule garante d'une régression du réglage).
    """
    pcb_bytes = _board_with_connector_and_movable(tmp_path)
    board_path = tmp_path / "board.kicad_pcb"
    board_path.write_bytes(pcb_bytes)

    captured: dict = {}

    def fake_run_optimize_placement(*args, **kwargs):
        captured.update(kwargs)
        return 1  # échec forcé — on n'a besoin que des kwargs passés

    monkeypatch.setattr(
        "kicad_tools.cli.optimize_placement_cmd.run_optimize_placement",
        fake_run_optimize_placement,
    )

    _refine_with_cmaes(board_path, anchored=["J1"], time_budget_s=5.0)

    assert "max_iterations" in captured, "max_iterations doit être passé explicitement"
    assert captured["max_iterations"] <= 30, (
        f"max_iterations={captured['max_iterations']} trop élevé pour un micro-raffinement"
    )


def test_refine_with_cmaes_keeps_displacement_small(tmp_path):
    """Test comportemental (vrai CMA-ES, pas de mock) : sur le board fixture,
    le déplacement des résistances mobiles reste petit avec le plafond actuel.

    Garde de régression pour le bug du 2026-06-19 : sans plafond explicite de
    ``max_iterations`` (défaut lib = 1000), ``seed_method="current"`` seede
    bien la moyenne initiale sur la position Architecte (vérifié dans
    kicad_tools/placement/cmaes_strategy.py) mais l'optimiseur a largement le
    temps, dans le budget de 20s, de dériver loin de ce seed — sur ce board
    fixture, max_iterations=1000 déplace les résistances de ~8-9mm contre
    ~3-5mm avec le plafond de 30 (board STM32 réel : 7.5mm moyen/68mm max
    contre 2.1mm moyen/4.0mm). Si ce test casse après une hausse de
    ``_CMAES_MAX_ITERATIONS``, re-mesurer le déplacement avant d'augmenter
    le seuil ci-dessous.
    """
    pcb_bytes = _board_with_connector_and_movable(tmp_path)
    board_path = tmp_path / "board.kicad_pcb"
    board_path.write_bytes(pcb_bytes)

    before = {fp.reference: fp.position for fp in PCB.load(str(board_path)).footprints}

    _refine_with_cmaes(board_path, anchored=["J1"], time_budget_s=20.0)

    after = {fp.reference: fp.position for fp in PCB.load(str(board_path)).footprints}
    displacements = [
        ((before[r][0] - after[r][0]) ** 2 + (before[r][1] - after[r][1]) ** 2) ** 0.5
        for r in ("R1", "R2", "R3")
    ]
    assert max(displacements) < 6.0, (
        f"déplacement trop important pour un micro-raffinement : {displacements} "
        "(la version sans plafond max_iterations atteint ~9mm sur ce board)"
    )


def test_auto_place_keeps_connector_anchored_with_cmaes_step(tmp_path):
    """Régression : avec le micro-raffinement CMA-ES chaîné dans auto_place,
    un connecteur déjà bien placé (ancrage mécanique) ne doit toujours pas bouger.
    """
    pcb_bytes = _board_with_connectors(
        tmp_path, j1_board_xy=(30.0, 135.0), j2_board_xy=(30.0, 20.0),
    )
    b64 = base64.b64encode(pcb_bytes).decode()

    result = auto_place(b64, _BOARD_W_MM, _BOARD_H_MM)

    j2 = next(p for p in result["positions"] if p["ref"] == "J2")
    assert j2["x"] == pytest.approx(30.0, abs=0.5)
    assert j2["y"] == pytest.approx(20.0, abs=0.5)


def test_auto_place_reverts_cmaes_if_unresolved_conflicts_remain(tmp_path, monkeypatch):
    """Filet de sécurité — benchmark réel (board STM32, 17 composants) : le
    CLI natif CMA-ES (sans verrouillage de position) peut introduire plus de
    chevauchements que l'Inspecteur (PlacementFixer, 10 passes) ne peut en
    résorber (observé : 17 conflits -> oscillation -> 3 ERROR restants).

    auto_place doit alors REJETER le résultat du CMA-ES et conserver le board
    Architecte (hybrid+cluster + fix), déjà garanti 0 erreur — jamais livrer
    un board avec des conflits ERROR non résolus.

    Note : ce test exerce le MÉCANISME de revert (snapshot/restore) en pilotant
    `_resolve_remaining_conflicts` par compteur d'appels, pas la détection réelle
    des conflits introduits par le CMA-ES — celle-ci est validée séparément par le
    benchmark manuel sur le board STM32 réel (voir docs/notefinal.md 2026-06-18).
    """
    pcb_bytes = _board_with_movable_components(tmp_path)
    b64 = base64.b64encode(pcb_bytes).decode()

    calls = {"n": 0}

    def fake_refine(pcb_path, anchored, time_budget_s=20.0):
        pcb = PCB.load(str(pcb_path))
        for fp in pcb.footprints:
            if fp.reference == "R1":
                fp.position = (1.0, 1.0)
        pcb.save(str(pcb_path))
        return {"refined": True, "elapsed_s": 0.1}

    def fake_resolve(pcb_path, anchored):
        calls["n"] += 1
        return (0, 0) if calls["n"] == 1 else (5, 3)

    monkeypatch.setattr(placement_module, "_refine_with_cmaes", fake_refine)
    monkeypatch.setattr(placement_module, "_resolve_remaining_conflicts", fake_resolve)

    result = auto_place(b64, _BOARD_W_MM, _BOARD_H_MM)

    r1 = next(p for p in result["positions"] if p["ref"] == "R1")
    assert (r1["x"], r1["y"]) != (1.0, 1.0), "board CMA-ES non-résolu livré malgré conflits ERROR restants"


def test_auto_place_reverts_cmaes_if_displacement_exceeds_threshold(tmp_path, monkeypatch):
    """Filet de sécurité Option B (défense en profondeur, 2026-06-19) — un
    Géomètre qui rapporte 0 ERROR mais déplace un composant non-ancré de
    plus de ``_CMAES_MAX_DISPLACEMENT_MM`` doit aussi déclencher le revert.

    Le revert existant (test ci-dessus) ne se déclenche que sur un compte
    d'ERROR > 0. Le bug du 2026-06-19 (max_iterations CMA-ES non plafonné)
    produisait un board 0 ERROR / 0 WARNING mais avec des déplacements de
    15-68mm — un revert basé uniquement sur le compte d'ERROR ne l'aurait
    jamais détecté. Ce test simule ce symptôme précis : `_resolve_remaining_
    conflicts` retourne toujours ``(0, 0)`` (aucune ERROR, jamais), mais
    `_refine_with_cmaes` déplace R1 de 30mm — au-delà du seuil.
    """
    pcb_bytes = _board_with_movable_components(tmp_path)
    b64 = base64.b64encode(pcb_bytes).decode()

    captured: dict = {}

    def fake_refine(pcb_path, anchored, time_budget_s=20.0):
        pcb = PCB.load(str(pcb_path))
        for fp in pcb.footprints:
            if fp.reference == "R1":
                x, y = fp.position
                captured["pre_x"] = x  # position pré-CMA-ES, telle que snapshotée par auto_place
                fp.position = (x + 30.0, y)
        pcb.save(str(pcb_path))
        return {"refined": True, "elapsed_s": 0.1}

    def fake_resolve(pcb_path, anchored):
        return (0, 0)  # jamais d'ERROR — simule le symptôme "0 ERROR mais dérive excessive"

    monkeypatch.setattr(placement_module, "_refine_with_cmaes", fake_refine)
    monkeypatch.setattr(placement_module, "_resolve_remaining_conflicts", fake_resolve)

    result = auto_place(b64, _BOARD_W_MM, _BOARD_H_MM)

    r1 = next(p for p in result["positions"] if p["ref"] == "R1")
    assert r1["x"] == pytest.approx(captured["pre_x"], abs=0.01), (
        "le board livré inclut le déplacement de 30mm du CMA-ES malgré 0 ERROR — "
        "le filet de sécurité Option B (déplacement) ne s'est pas déclenché"
    )


def test_max_displacement_mm_treats_unmatched_ref_as_infinite(tmp_path):
    """Filet de sécurité — une référence présente sur le board mais absente du
    snapshot ``before_positions`` (renommage/ajout inattendu côté CLI natif)
    ne doit JAMAIS être ignorée silencieusement : un filet de sécurité dont le
    seul rôle est de détecter une dérive ne peut pas se permettre de sauter
    un footprint qu'il ne sait pas comparer. Doit renvoyer un déplacement
    infini (donc toujours > _CMAES_MAX_DISPLACEMENT_MM) plutôt que de
    l'exclure du calcul du max.
    """
    pcb_bytes = _board_with_movable_components(tmp_path)
    pcb_path = tmp_path / "board.kicad_pcb"
    pcb_path.write_bytes(pcb_bytes)

    # before_positions ne connaît qu'une partie des refs du board — simule
    # un ref renommé/ajouté par le CLI natif entre les deux snapshots.
    before_positions = {"R1": (0.0, 0.0)}

    max_disp = _max_displacement_mm(before_positions, pcb_path, exclude=[])

    assert max_disp == float("inf")


def test_max_displacement_mm_empty_before_positions_with_tracked_refs_is_unsafe(tmp_path):
    """Un snapshot ``before_positions`` vide alors que le board a des
    footprints non-exclus doit être traité comme non-vérifiable (infini),
    pas comme "aucune dérive" — sinon un snapshot dégénéré ferait passer le
    filet de sécurité silencieusement.
    """
    pcb_bytes = _board_with_movable_components(tmp_path)
    pcb_path = tmp_path / "board.kicad_pcb"
    pcb_path.write_bytes(pcb_bytes)

    max_disp = _max_displacement_mm({}, pcb_path, exclude=[])

    assert max_disp == float("inf")


def test_auto_place_survives_cmaes_exception(tmp_path, monkeypatch):
    """Filet de sécurité — si le CLI natif CMA-ES LÈVE une exception (pas
    seulement un code retour non-zéro), auto_place ne doit pas planter :
    le board pré-CMA-ES (Architecte + Inspecteur, déjà garanti 0 erreur) doit
    être livré tel quel, comme si le CMA-ES avait simplement échoué.
    """
    pcb_bytes = _board_with_movable_components(tmp_path)
    b64 = base64.b64encode(pcb_bytes).decode()

    def fake_refine_raises(pcb_path, anchored, time_budget_s=20.0):
        raise RuntimeError("CMA-ES natif a crashé")

    monkeypatch.setattr(placement_module, "_refine_with_cmaes", fake_refine_raises)

    result = auto_place(b64, _BOARD_W_MM, _BOARD_H_MM)

    assert result["placed_count"] > 0
