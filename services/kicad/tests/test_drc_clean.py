"""Tests — chantier DRC-clean des boards routés à 100 % (2026-07-19).

Mesure de référence (runs 7/9 stm32-validation, juge kicad-cli + sidecar tier) :
36/30 ERROR restants sur des boards 100 % routés, en 4 causes racines :

1. Pads NC ``(net 0 "")`` exemptés d'obstacle par le routeur (arbitrage
   upstream #3281) → pistes qui TRAVERSENT le pad 33/43 du LQFP-48 :
   9 shorting_items + 9 solder_mask_bridge + clearances < tier.
   Fix : ``assign_nc_nets`` avant routage (obstacles réels), ``strip_nc_nets``
   après (contrat du board final inchangé).
2. Netclass Default 0,2 mm (défaut KiCad, sidecar muet) alors que le routeur
   route aux règles du tier (0,127 mm) → clearances 0,127-0,2 en faux positif.
   Fix : netclass Default alignée sur le tier dans le sidecar .kicad_pro.
3. Microvias via-in-pad 0,3/0,15 (politique kct escape) vs annular min 0,15
   du profil → 5 annular_width par board sans défaut réel.
   Fix : règle .kicad_dru scopée ``A.Via_Type == 'Micro'`` à l'annular de la
   politique (0,075) — kicad-cli l'honore (validé empiriquement 2026-07-19).
4. Zones GND en thermal relief : 2 rayons infaisables entre les pistes
   d'escape → starved_thermal + pads GND orphelins.
   Fix : ``_solid_connect_zones`` (connect_pads yes) + via-in-pad micro de
   secours vers le plan (boucle auto-fix DRC) pour les pads encerclés.

Gain mesuré des fixes 2+3+4 (expérience scratchpad, runs 7/9) :
36→23 et 30→22 ERROR ; le reste = cause 1 (traité par le routage strict).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

_SERVICE_ROOT = Path(__file__).resolve().parents[1]  # services/kicad
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import kct_route  # noqa: E402
from tools.drc import (  # noqa: E402
    add_zone_via_for_unconnected_pads,
    parse_drc_report,
)
from tools.kct_route import (  # noqa: E402
    _solid_connect_zones,
    assign_nc_nets,
    strip_nc_nets,
)


# ===========================================================================
# Cause 1 — pads NC : nets uniques le temps du routage
# ===========================================================================

_NC_BOARD = (
    '(kicad_pcb\n'
    '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (36 "B.SilkS" user))\n'
    '  (net 0 "")\n'
    '  (net 1 "GND")\n'
    '  (net 2 "SWDIO")\n'
    '  (footprint "LQFP"\n'
    '    (pad "32" smd rect (net 2 "SWDIO"))\n'
    '    (pad "33" smd rect (net 0 ""))\n'
    '    (pad "34" smd rect (net 0 ""))\n'
    '  )\n'
    ')\n'
)


def test_assign_nc_nets_converts_only_pad_refs():
    out, count = assign_nc_nets(_NC_BOARD)
    assert count == 2
    # La déclaration racine (net 0 "") reste intacte…
    assert '  (net 0 "")\n' in out
    # …les pads NC reçoivent chacun un net unique déclaré.
    assert out.count('CIRQIX_NC_') == 4  # 2 déclarations + 2 refs pads
    assert '(pad "33" smd rect (net 3 "CIRQIX_NC_3"))' in out
    assert '(pad "34" smd rect (net 4 "CIRQIX_NC_4"))' in out
    # Déclarations insérées dans la section nets (avant le 1er footprint).
    assert out.index('(net 3 "CIRQIX_NC_3")') < out.index('(footprint')


def test_assign_nc_nets_noop_without_nc_pads():
    board = _NC_BOARD.replace('(net 0 "")', '(net 1 "GND")')
    out, count = assign_nc_nets(board)
    assert count == 0
    assert out == board


def test_strip_nc_nets_roundtrip():
    out, count = assign_nc_nets(_NC_BOARD)
    assert count == 2
    assert strip_nc_nets(out) == _NC_BOARD


def test_strip_nc_nets_survives_renumbering():
    # kct re-sérialise le board : si les numéros changent, le nom CIRQIX_NC_*
    # reste le marqueur — le strip ne doit pas dépendre de numéro == suffixe.
    out, _ = assign_nc_nets(_NC_BOARD)
    renumbered = out.replace('(net 3 "CIRQIX_NC_3")', '(net 9 "CIRQIX_NC_3")')
    stripped = strip_nc_nets(renumbered)
    assert "CIRQIX_NC_" not in stripped
    assert '(pad "33" smd rect (net 0 ""))' in stripped


def test_route_once_routes_with_nc_obstacles_and_strips_after(monkeypatch):
    captured: dict[str, str] = {}

    def fake_run(src, dst, timeout_s):
        captured["src"] = Path(src).read_text(encoding="utf-8")
        Path(dst).write_text(captured["src"], encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="Nets routed: 2/2 (100%)",
                               stderr="")

    monkeypatch.setattr(kct_route, "_run_kct_route", fake_run)
    monkeypatch.setattr(kct_route, "_ensure_gnd_both_planes", lambda b: b)
    out, pct, _ = kct_route.route_kct(_NC_BOARD.encode(), vcc_as_traces=True)

    # Le routeur voit les pads NC comme des nets réels (obstacles normaux)…
    assert "CIRQIX_NC_" in captured["src"]
    # …et le board final rendu au pipeline est débarrassé des nets temporaires.
    text = out.decode("utf-8")
    assert "CIRQIX_NC_" not in text
    assert '(pad "33" smd rect (net 0 ""))' in text
    assert pct == 100


# ===========================================================================
# Cause 4 — zones en connexion solid
# ===========================================================================

_ZONED = (
    '(zone\n\t(net 1)\n\t(net_name "GND")\n\t(layer "B.Cu")\n'
    '\t(connect_pads (clearance 0.3)\n\t)\n'
    '\t(fill yes (thermal_gap 0.3) (thermal_bridge_width 0.4)\n\t)\n)'
)


def test_solid_connect_zones_rewrites_connect_pads():
    out = _solid_connect_zones(_ZONED)
    assert "(connect_pads yes (clearance 0.3)" in out
    assert "(connect_pads (clearance" not in out


def test_solid_connect_zones_idempotent():
    once = _solid_connect_zones(_ZONED)
    assert _solid_connect_zones(once) == once


def test_route_once_applies_solid_connect_to_final_board(monkeypatch):
    board = _NC_BOARD[:-2] + _ZONED + "\n)\n"  # zone injectée avant la ')' finale

    def fake_run(src, dst, timeout_s):
        Path(dst).write_text(Path(src).read_text(encoding="utf-8"), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="Nets routed: 2/2 (100%)",
                               stderr="")

    monkeypatch.setattr(kct_route, "_run_kct_route", fake_run)
    monkeypatch.setattr(kct_route, "_strip_zone_blocks", lambda t: t)
    monkeypatch.setattr(kct_route, "_ensure_gnd_both_planes", lambda b: b)
    out, _, _ = kct_route.route_kct(board.encode(), vcc_as_traces=True)
    assert "(connect_pads yes (clearance" in out.decode("utf-8")


# ===========================================================================
# parse_drc_report — la description de l'item est conservée (le fix
# via-in-pad doit savoir QUEL pad est orphelin, pas juste le message)
# ===========================================================================

_UNCONNECTED_REPORT = """{
  "violations": [],
  "unconnected_items": [
    {
      "type": "unconnected_items",
      "severity": "error",
      "description": "Missing connection between items",
      "items": [
        {"uuid": "u1", "description": "Zone [GND] sur F.Cu, priorité 0",
         "pos": {"x": 100.5, "y": 100.5}},
        {"uuid": "u2", "description": "Pad 8 [GND] de U2 sur F.Cu",
         "pos": {"x": 130.51271, "y": 117.530715}}
      ]
    }
  ]
}"""


def test_parse_drc_report_keeps_item_description():
    parsed = parse_drc_report(_UNCONNECTED_REPORT)
    assert len(parsed) == 2
    pad = next(p for p in parsed if "Pad 8" in p.get("item", ""))
    assert pad["item"] == "Pad 8 [GND] de U2 sur F.Cu"
    assert pad["x_mm"] == 130.51271
    assert pad["type"] == "unconnected_items"


# ===========================================================================
# Cause 4bis — via-in-pad micro de secours vers le plan pour un pad encerclé
# ===========================================================================

_PLANE_BOARD = (
    '(kicad_pcb\n'
    '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
    '  (net 0 "")\n'
    '  (net 1 "GND")\n'
    '  (net 2 "SWDIO")\n'
    '  (footprint "LQFP"\n'
    '    (pad "8" smd rect (net 1 "GND"))\n'
    '  )\n'
    '  (zone\n\t(net 1)\n\t(net_name "GND")\n\t(layer "B.Cu")\n'
    '\t(connect_pads yes (clearance 0.3)\n\t)\n\t(polygon (pts))\n)\n'
    ')\n'
)


def _pad_violation(net: str = "GND", x: float = 130.5, y: float = 117.5) -> dict:
    return {
        "id": "v1", "severity": "error", "type": "unconnected_items",
        "message": "Missing connection between items",
        "item": f"Pad 8 [{net}] de U2 sur F.Cu", "x_mm": x, "y_mm": y,
    }


def test_via_fix_adds_micro_via_on_zone_net_pad():
    out, added = add_zone_via_for_unconnected_pads(_PLANE_BOARD, [_pad_violation()])
    assert added == 1
    assert '(via micro' in out
    assert '(at 130.5 117.5)' in out
    assert '(net 1)' in out
    assert '(layers "F.Cu" "B.Cu")' in out
    # S-expr toujours équilibrée
    assert out.count("(") == out.count(")")


def test_via_fix_skips_net_without_zone():
    out, added = add_zone_via_for_unconnected_pads(
        _PLANE_BOARD, [_pad_violation(net="SWDIO")])
    assert added == 0
    assert out == _PLANE_BOARD


def test_via_fix_skips_non_two_layer_board():
    four = _PLANE_BOARD.replace(
        '(layers (0 "F.Cu" signal) (31 "B.Cu" signal))',
        '(layers (0 "F.Cu" signal) (1 "In1.Cu" power) '
        '(2 "In2.Cu" signal) (31 "B.Cu" signal))')
    out, added = add_zone_via_for_unconnected_pads(four, [_pad_violation()])
    assert added == 0


def test_via_fix_dedupes_same_pad_and_existing_via():
    # Deux violations au même pad (zone↔pad + pad↔pad) → un seul via.
    out, added = add_zone_via_for_unconnected_pads(
        _PLANE_BOARD, [_pad_violation(), _pad_violation()])
    assert added == 1
    # Ré-application (itération suivante de la boucle DRC) → no-op.
    out2, added2 = add_zone_via_for_unconnected_pads(out, [_pad_violation()])
    assert added2 == 0
    assert out2 == out


def test_via_fix_skips_pad_with_foreign_track_underneath():
    # Mesuré (run 7) : un via GND posé aveuglément à un pad orphelin peut
    # court-circuiter une piste d'un autre net passant SOUS le pad en B.Cu
    # (USER_LED) ou frôler des pistes F.Cu (hole_clearance NRST/+3.3V).
    # Le garde-fou géométrique doit refuser la pose — la violation
    # unconnected reste, mais AUCUNE violation nouvelle n'est créée.
    blocked = _PLANE_BOARD.replace(
        "  (zone",
        '  (segment\n    (start 129.5 117.5)\n    (end 131.5 117.5)\n'
        '    (width 0.2)\n    (layer "B.Cu")\n    (net 2)\n  )\n  (zone',
        1)
    out, added = add_zone_via_for_unconnected_pads(blocked, [_pad_violation()])
    assert added == 0
    assert out == blocked


def test_via_fix_allows_pad_with_same_net_track_nearby():
    # Une piste du MÊME net (GND) sous le pad n'est pas un obstacle.
    same_net = _PLANE_BOARD.replace(
        "  (zone",
        '  (segment\n    (start 129.5 117.5)\n    (end 131.5 117.5)\n'
        '    (width 0.2)\n    (layer "B.Cu")\n    (net 1)\n  )\n  (zone',
        1)
    out, added = add_zone_via_for_unconnected_pads(same_net, [_pad_violation()])
    assert added == 1


def test_via_fix_allows_pad_with_distant_foreign_track():
    far = _PLANE_BOARD.replace(
        "  (zone",
        '  (segment\n    (start 129.5 120.0)\n    (end 131.5 120.0)\n'
        '    (width 0.2)\n    (layer "B.Cu")\n    (net 2)\n  )\n  (zone',
        1)
    out, added = add_zone_via_for_unconnected_pads(far, [_pad_violation()])
    assert added == 1


def test_apply_fixes_uses_via_fix_without_pcbnew():
    # routers/drc.py::_apply_fixes doit appliquer le fix texte pur même quand
    # pcbnew est absent (cas local/CI) — la boucle auto-fix ne doit plus
    # s'arrêter à 0 fix sur un unconnected réparable.
    from routers.drc import _apply_fixes

    new_content, fixed = _apply_fixes(_PLANE_BOARD.encode(), [_pad_violation()])
    assert fixed == 1
    assert b"(via micro" in new_content


# ===========================================================================
# Refill zones — compat API pcbnew KiCad 10 (SetIsFilled, pas SetFilled)
# ===========================================================================
# La branche pcbnew de _apply_fixes (refill zones sur unfilled_zone /
# zone_has_empty_net) n'est JAMAIS exercée en local/CI (pas de pcbnew) → le
# bug d'API est passé inaperçu. Le conteneur prod tourne KiCad 10 (10.0.4),
# où ZONE.SetFilled n'existe pas (c'est SetIsFilled ; ZONE_FILLER.Fill masque
# l'effet mais la boucle SetFilled lève AttributeError avant Fill).


class _FakeZoneK10:
    """Zone façon KiCad 10 : SetIsFilled existe, SetFilled N'EXISTE PAS."""

    def __init__(self) -> None:
        self.is_filled = False

    def SetIsFilled(self, value: bool) -> None:
        self.is_filled = value


class _FakeZoneFiller:
    def __init__(self, board: "_FakeBoardK10") -> None:
        self._board = board

    def Fill(self, zones: list[_FakeZoneK10]) -> None:
        for z in zones:
            z.is_filled = True


class _FakeBoardK10:
    def __init__(self) -> None:
        self._zones = [_FakeZoneK10()]

    def Zones(self) -> list[_FakeZoneK10]:
        return self._zones


def _install_fake_pcbnew_k10(monkeypatch) -> None:
    mod = types.ModuleType("pcbnew")
    mod.LoadBoard = lambda path: _FakeBoardK10()  # type: ignore[attr-defined]
    mod.ZONE_FILLER = _FakeZoneFiller             # type: ignore[attr-defined]

    def _save(path: str, board: _FakeBoardK10) -> None:
        Path(path).write_bytes(b"(kicad_pcb (filled))\n")

    mod.SaveBoard = _save                          # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pcbnew", mod)


def test_apply_fixes_refills_zone_with_kicad10_api(monkeypatch):
    # Régression : avec l'API KiCad 10 (SetFilled absent), la branche refill
    # ne doit PAS lever AttributeError. Échoue contre l'ancien SetFilled(True).
    _install_fake_pcbnew_k10(monkeypatch)
    from routers.drc import _apply_fixes

    unfilled = {"id": "z1", "severity": "error", "type": "unfilled_zone",
                "message": "Zone non remplie"}
    new_content, fixed = _apply_fixes(_PLANE_BOARD.encode(), [unfilled])
    assert fixed == 1
    assert new_content == b"(kicad_pcb (filled))\n"
