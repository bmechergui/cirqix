"""Tests unitaires — strip_nc_escape_stubs (retrait des stubs d'escape NC).

Le routeur kct échappe les pads NC (rendus obstacles par ``assign_nc_nets``
via des nets ``CIRQIX_NC_*``) avec des tracks/vias qui ne transportent aucun
signal. Une fois ``strip_nc_nets`` passé, ces stubs deviennent des pistes
``<no net>`` qui court-circuitent les pads NC (shorting_items +
solder_mask_bridge mesurés sur STM32 LQFP-48 : 20 + 20 → 0 après strip).

``strip_nc_escape_stubs`` les retire AVANT ``strip_nc_nets``, tant qu'ils
sont étiquetés ``CIRQIX_NC_*``. Tests pure-texte (aucune dépendance pcbnew).
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))
sys.path.insert(0, str(_SERVICE_ROOT / "kicad-tools" / "src"))

from tools.kct_route import (  # noqa: E402
    _NC_NET_PREFIX,
    assign_nc_nets,
    strip_nc_escape_stubs,
    strip_nc_nets,
)


def _seg(net_id: int, net_name: str, uid: int = 1) -> str:
    return (f'  (segment (start 1.{uid} 2.0) (end 1.5 2.0) (width 0.2) '
            f'(layer "F.Cu") (net {net_id} "{net_name}") (uuid {uid}))')


def _via(net_id: int, net_name: str, uid: int = 1) -> str:
    return (f'  (via (at 1.{uid} 2.0) (size 0.6) (drill 0.3) '
            f'(layers "F.Cu" "B.Cu") (net {net_id} "{net_name}") (uuid {uid}))')


def test_strip_removes_segment_referencing_nc_net() -> None:
    board = "(kicad_pcb\n" + _seg(15, f"{_NC_NET_PREFIX}15") + "\n)"
    out, n = strip_nc_escape_stubs(board)
    assert n == 1
    assert "(segment" not in out
    assert "CIRQIX_NC_" not in out


def test_strip_keeps_segment_referencing_real_net() -> None:
    board = "(kicad_pcb\n" + _seg(5, "GND") + "\n)"
    out, n = strip_nc_escape_stubs(board)
    assert n == 0
    assert '(net 5 "GND")' in out
    assert "(segment" in out


def test_strip_removes_via_referencing_nc_net() -> None:
    board = "(kicad_pcb\n" + _via(7, f"{_NC_NET_PREFIX}7") + "\n)"
    out, n = strip_nc_escape_stubs(board)
    assert n == 1
    assert "(via" not in out


def test_strip_mixed_board_removes_only_nc_stubs() -> None:
    board = ("\n(kicad_pcb\n"
             + _seg(5, "GND", 1) + "\n"
             + _seg(16, f"{_NC_NET_PREFIX}16", 2) + "\n"
             + _via(7, "SWDIO", 3) + "\n"
             + _via(17, f"{_NC_NET_PREFIX}17", 4) + "\n"
             + _seg(8, "+3.3V", 5) + "\n)")
    out, n = strip_nc_escape_stubs(board)
    assert n == 2
    # real nets preserved
    assert '(net 5 "GND")' in out
    assert '(net 7 "SWDIO")' in out
    assert '(net 8 "+3.3V")' in out
    # NC stubs gone
    assert "CIRQIX_NC_" not in out
    assert out.count("(segment") == 2  # GND + 3.3V
    assert out.count("(via") == 1      # SWDIO


def test_strip_noop_when_no_nc_stubs() -> None:
    board = "(kicad_pcb\n" + _seg(5, "GND") + "\n)"
    out, n = strip_nc_escape_stubs(board)
    assert n == 0
    assert out == board


def test_strip_handles_multiline_block() -> None:
    block = ("  (segment\n"
             "    (start 1.0 2.0)\n"
             "    (end 1.5 2.0)\n"
             '    (layer "F.Cu")\n'
             f'    (net 21 "{_NC_NET_PREFIX}21")\n'
             "    (uuid 9)\n"
             "  )")
    board = "(kicad_pcb\n" + block + "\n)"
    out, n = strip_nc_escape_stubs(board)
    assert n == 1
    assert "CIRQIX_NC_" not in out
    assert "(start" not in out  # block fully removed


def test_strip_idempotent() -> None:
    board = "(kicad_pcb\n" + _seg(5, "GND") + "\n" + _seg(9, f"{_NC_NET_PREFIX}9", 2) + "\n)"
    out1, n1 = strip_nc_escape_stubs(board)
    out2, n2 = strip_nc_escape_stubs(out1)
    assert n1 == 1 and n2 == 0
    assert out1 == out2


def test_strip_does_not_touch_net_declared_strings_with_parens() -> None:
    # Un nom de net contenant une parenthèse ne doit pas casser le scan.
    board = ('(kicad_pcb\n  (net 5 "GND(1)")\n'
             + _seg(5, "GND(1)") + "\n"
             + _seg(6, f"{_NC_NET_PREFIX}6", 2) + "\n)")
    out, n = strip_nc_escape_stubs(board)
    assert n == 1
    assert '(net 5 "GND(1)")' in out  # le segment réel est conservé


def _seg_code_only(net_id: int, uid: int = 1) -> str:
    """Segment au format KiCad réel : net référencé par CODE seul ``(net N)``."""
    return (f'  (segment (start 1.{uid} 2.0) (end 1.5 2.0) (width 0.2) '
            f'(layer "F.Cu") (net {net_id}) (uuid {uid}))')


def _via_code_only(net_id: int, uid: int = 1) -> str:
    return (f'  (via (at 1.{uid} 2.0) (size 0.6) (drill 0.3) '
            f'(layers "F.Cu" "B.Cu") (net {net_id}) (uuid {uid}))')


def test_strip_handles_code_only_net_refs_kicad_format() -> None:
    """Vrai comportement KiCad : segments/vias référencent les nets par CODE
    ``(net N)``, pas par nom. La déclaration ``(net N "CIRQIX_NC_N")`` porte
    le nom ; le stub la référence par code. Le strip doit le retirer."""
    board = (
        "(kicad_pcb\n"
        '  (net 0 "")\n'
        '  (net 2 "GND")\n'
        f'  (net 15 "{_NC_NET_PREFIX}15")\n'   # déclaration NC (porte le nom)
        + _seg_code_only(2, 1) + "\n"          # segment réel (GND) — code 2
        + _seg_code_only(15, 2) + "\n"         # stub NC — code 15, code-only
        + _via_code_only(15, 3) + "\n"
        + _seg_code_only(2, 4) + "\n"
        + ")\n")
    out, n = strip_nc_escape_stubs(board)
    assert n == 2  # le segment + le via NC retirés
    # segments réels (GND, code 2) conservés
    assert out.count("(segment") == 2
    assert out.count("(via") == 0
    # la déclaration NC reste (c'est strip_nc_nets qui la retire, pas ce strip)
    assert f'(net 15 "{_NC_NET_PREFIX}15")' in out


def test_full_roundtrip_assign_route_strip_restores_clean() -> None:
    """assign_nc_nets + strip_nc_escape_stubs + strip_nc_nets : un board avec
    un pad NC et un stub NC ressort sans aucune trace CIRQIX_NC_* ni stub."""
    pad_nc = ('  (footprint "lib:X" (at 0 0)\n'
              '    (pad 1 thru_hole circle (at 0 0) (size 1 1) (drill 0.5)'
              ' (layers "*.Cu") (net 0 ""))\n'
              '  )')
    stub = _seg(3, f"{_NC_NET_PREFIX}3")
    real = _seg(2, "GND", 2)
    board = "(kicad_pcb\n  (net 0 \"\")\n  (net 2 \"GND\")\n" + pad_nc + "\n" + stub + "\n" + real + "\n)"

    assigned, nc = assign_nc_nets(board)
    assert nc == 1  # le pad NC a été converti
    stripped, stubs = strip_nc_escape_stubs(assigned)
    assert stubs == 1  # le stub NC retiré
    final = strip_nc_nets(stripped)
    assert "CIRQIX_NC_" not in final
    assert '(net 2 "GND")' in final  # routage réel intact
    assert '(net 0 "")' in final      # pad NC restauré
