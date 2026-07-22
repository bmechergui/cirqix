"""Tests — Brique 2 : protections escape fine-pitch GATÉES (tools/kct_route.py).

Mesuré (iso-prod Docker 2026-07-22) : sur un board avec boîtier fine-pitch dense
(LQFP-48 0,5 mm), le routage sans protections pose des vias in-pad qui frôlent
les pads voisins → courts réels au juge kicad-cli. Les flags escape
(`--strict-in-pad-clearance`, `--micro-via-in-pad-fallback`,
`--fine-pitch-clearance`) préviennent ces courts, MAIS coûtent de la complétion
s'ils sont appliqués sans nécessité → on ne les active que si le board contient
un composant dense (≥16 pads). `--strict-in-pad-clearance` désactivant
`--auto-layers`, on force `--starting-layers 4` pour les boards fine-pitch (qui
requièrent de toute façon 4 couches — un LQFP dense n'est jamais 2 couches clean).
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))
sys.path.insert(0, str(_SERVICE_ROOT / "kicad-tools" / "src"))

from tools import kct_route  # noqa: E402
from tools.kct_route import (  # noqa: E402
    _build_route_cmd,
    _has_dense_footprint,
)


def _footprint(ref: str, n_pads: int) -> str:
    pads = "\n".join(
        f'    (pad "{i + 1}" smd rect (at 0 {i * 0.5}) (size 0.3 0.3) '
        f'(layers "F.Cu") (net 0 ""))' for i in range(n_pads))
    return f'  (footprint "P:{ref}" (layer "F.Cu") (at 10 10)\n{pads}\n  )'


_DENSE_BOARD = "(kicad_pcb\n" + _footprint("U1", 20) + "\n" + _footprint("R1", 2) + "\n)"
_SIMPLE_BOARD = "(kicad_pcb\n" + _footprint("R1", 2) + "\n" + _footprint("C1", 2) + "\n)"


# --- détection dense -------------------------------------------------------

def test_has_dense_footprint_true_for_high_pad_count():
    assert _has_dense_footprint(_DENSE_BOARD) is True


def test_has_dense_footprint_false_for_simple_board():
    assert _has_dense_footprint(_SIMPLE_BOARD) is False


# --- gating des flags escape ----------------------------------------------

_ESCAPE_FLAGS = ("--strict-in-pad-clearance", "--micro-via-in-pad-fallback",
                 "--fine-pitch-clearance")


def test_build_route_cmd_adds_escape_flags_when_fine_pitch():
    cmd = _build_route_cmd(Path("in.kicad_pcb"), Path("out.kicad_pcb"), 300, fine_pitch=True)
    for flag in _ESCAPE_FLAGS:
        assert flag in cmd
    # sous-bug auto-layers : on force le départ 4 couches sur fine-pitch
    assert "--starting-layers" in cmd
    assert cmd[cmd.index("--starting-layers") + 1] == "4"


def test_build_route_cmd_no_escape_flags_when_not_fine_pitch():
    cmd = _build_route_cmd(Path("in.kicad_pcb"), Path("out.kicad_pcb"), 300, fine_pitch=False)
    for flag in _ESCAPE_FLAGS:
        assert flag not in cmd
    assert "--starting-layers" not in cmd
    # le routage normal (auto-layers depuis 2) reste inchangé
    assert "--auto-layers" in cmd


# --- intégration : _route_once détecte et transmet le flag -----------------

def test_route_once_enables_escape_on_dense_board(monkeypatch):
    captured = {}

    def fake_run(src, dst, timeout_s, fine_pitch=False):
        captured["fine_pitch"] = fine_pitch
        Path(dst).write_text(Path(src).read_text(encoding="utf-8"), encoding="utf-8")
        from types import SimpleNamespace
        return SimpleNamespace(returncode=0, stdout="Nets routed: 1/1 (100%)", stderr="")

    monkeypatch.setattr(kct_route, "_run_kct_route", fake_run)
    monkeypatch.setattr(kct_route, "_ensure_gnd_both_planes", lambda b: b)
    monkeypatch.setattr(kct_route, "_strip_zone_blocks", lambda t: t)

    kct_route.route_kct(_DENSE_BOARD.encode(), timeout_s=10, vcc_as_traces=False)
    assert captured["fine_pitch"] is True


def test_route_once_keeps_escape_off_on_simple_board(monkeypatch):
    captured = {}

    def fake_run(src, dst, timeout_s, fine_pitch=False):
        captured["fine_pitch"] = fine_pitch
        Path(dst).write_text(Path(src).read_text(encoding="utf-8"), encoding="utf-8")
        from types import SimpleNamespace
        return SimpleNamespace(returncode=0, stdout="Nets routed: 1/1 (100%)", stderr="")

    monkeypatch.setattr(kct_route, "_run_kct_route", fake_run)
    monkeypatch.setattr(kct_route, "_ensure_gnd_both_planes", lambda b: b)
    monkeypatch.setattr(kct_route, "_strip_zone_blocks", lambda t: t)

    kct_route.route_kct(_SIMPLE_BOARD.encode(), timeout_s=10, vcc_as_traces=False)
    assert captured["fine_pitch"] is False
