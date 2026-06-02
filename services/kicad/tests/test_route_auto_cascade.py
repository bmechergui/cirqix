"""Unit tests for route_auto cascade — RC1: low kicad-tools completion must
fall through to Freerouting; partial result must be kept when Freerouting absent."""
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import routers.routing as routing
from routers.routing import route_auto, RouteAutoRequest


def _req() -> RouteAutoRequest:
    return RouteAutoRequest(kicad_pcb_b64=base64.b64encode(b"PCB").decode(), layers=2)


def _patch(monkeypatch, *, kt, fr_api_url=None, fr_api_result=None):
    monkeypatch.setattr(routing, "_count_routable_nets", lambda b: 1)
    monkeypatch.setattr(routing, "_count_footprints", lambda b: 5)
    monkeypatch.setattr(routing, "_route_with_kicad_tools", lambda b: kt)
    monkeypatch.setattr(routing, "_find_freerouting_api", lambda: fr_api_url)
    monkeypatch.setattr(routing, "_route_with_freerouting_api", lambda b, t: fr_api_result)
    monkeypatch.setattr(routing, "_find_freerouting", lambda: None)


def test_low_kicad_tools_falls_through_to_freerouting(monkeypatch):
    _patch(monkeypatch, kt=(b"partial", 0), fr_api_url="http://x", fr_api_result=b"fr-routed")
    resp = route_auto(_req())
    assert resp.routed_percent == 100
    assert base64.b64decode(resp.kicad_pcb_b64) == b"fr-routed"


def test_full_kicad_tools_result_is_kept(monkeypatch):
    _patch(monkeypatch, kt=(b"full", 100), fr_api_url="http://x", fr_api_result=b"should-not-be-used")
    resp = route_auto(_req())
    assert resp.routed_percent == 100
    assert base64.b64decode(resp.kicad_pcb_b64) == b"full"


def test_low_kicad_tools_kept_when_freerouting_absent(monkeypatch):
    _patch(monkeypatch, kt=(b"partial", 40), fr_api_url=None, fr_api_result=None)
    resp = route_auto(_req())
    # Freerouting absent everywhere → keep the kicad-tools partial, do NOT skip
    assert resp.skipped is False
    assert resp.routed_percent == 40
    assert base64.b64decode(resp.kicad_pcb_b64) == b"partial"


def test_power_nets_arg_uses_net_layer_format():
    from routers.routing import _power_nets_arg
    # GND → B.Cu, supply nets → F.Cu (2-layer convention)
    assert _power_nets_arg(["GND", "VCC_5V"]) == "GND:B.Cu,VCC_5V:F.Cu"
    assert _power_nets_arg([]) == ""
