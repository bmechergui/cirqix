"""Régressions : Freerouting ne vaut 100 % qu'après mesure pcbnew isolée."""
from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402
from tools import routing_pcbnew_runner  # noqa: E402


def _board(*, two_pad_nets: int, single_pad_nets: int = 0) -> bytes:
    lines = ["(kicad_pcb", '(version 20240108)', '(generator "test")']
    net_code = 1
    for _ in range(two_pad_nets):
        lines.extend([
            f'(net {net_code} "N{net_code}")',
            f'(pad "1" thru_hole circle (net {net_code} "N{net_code}"))',
            f'(pad "2" thru_hole circle (net {net_code} "N{net_code}"))',
        ])
        net_code += 1
    for _ in range(single_pad_nets):
        lines.extend([
            f'(net {net_code} "N{net_code}")',
            f'(pad "1" thru_hole circle (net {net_code} "N{net_code}"))',
        ])
        net_code += 1
    lines.append(")")
    return "\n".join(lines).encode()


def _run_freerouting_api(monkeypatch, board: bytes, measurement: tuple[int, int]):
    monkeypatch.setattr(routing_router, "_count_footprints", lambda _pcb: 31)
    monkeypatch.setattr(routing_router, "_find_freerouting_api", lambda: "http://freerouting")
    monkeypatch.setattr(routing_router, "_route_with_freerouting_api", lambda *_a: board)
    monkeypatch.setattr(routing_router, "_measure_routing", lambda _pcb: measurement)
    req = routing_router.RouteAutoRequest(
        kicad_pcb_b64=base64.b64encode(board).decode("ascii"), layers=2
    )
    return routing_router.route_auto(req)


def test_completed_freerouting_job_with_unrouted_net_is_not_100(monkeypatch):
    board = _board(two_pad_nets=2)
    response = _run_freerouting_api(monkeypatch, board, (2, 1))
    assert response.routed_percent == 50
    assert response.routed_percent != 100


def test_completed_freerouting_job_with_complete_board_is_100(monkeypatch):
    board = _board(two_pad_nets=2)
    response = _run_freerouting_api(monkeypatch, board, (2, 0))
    assert response.routed_percent == 100


def test_partial_netlist_loss_cannot_be_measured_as_100(monkeypatch):
    output = _board(two_pad_nets=1)
    monkeypatch.setattr(routing_router, "_measure_routing", lambda _pcb: (1, 0))
    with pytest.raises(RuntimeError, match="routable net count changed"):
        routing_router._measured_routed_percent(output, expected_routable_nets=2)


def test_single_pad_nets_are_not_routable():
    board = _board(two_pad_nets=2, single_pad_nets=3)
    assert routing_router._count_routable_nets(board) == 2


def test_pcbnew_operations_use_the_bounded_child_process(monkeypatch, tmp_path):
    calls: list[tuple[list[str], dict]] = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        payload = json.loads(cmd[-1])
        if payload["operation"] == "export_specctra":
            Path(payload["dsn"]).write_text("DSN", encoding="utf-8")
        elif payload["operation"] == "specctra_roundtrip":
            Path(payload["output"]).write_bytes(b"ROUTED")
        else:
            Path(payload["result"]).write_text(
                json.dumps({"unrouted_nets": 1}), encoding="utf-8"
            )
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(routing_router.subprocess, "run", fake_run)
    dsn = tmp_path / "board.dsn"
    ses = tmp_path / "board.ses"
    ses.write_text("SES", encoding="utf-8")

    routing_router._export_specctra(_board(two_pad_nets=2), dsn)
    assert routing_router._specctra_roundtrip(_board(two_pad_nets=2), ses) == b"ROUTED"
    assert routing_router._measure_routing(_board(two_pad_nets=2)) == (2, 1)

    assert [json.loads(cmd[-1])["operation"] for cmd, _ in calls] == [
        "export_specctra", "specctra_roundtrip", "measure_connectivity"
    ]
    assert all(cmd[0] == sys.executable for cmd, _ in calls)
    assert all(cmd[1].endswith("routing_pcbnew_runner.py") for cmd, _ in calls)
    assert all(kwargs["timeout"] > 0 for _, kwargs in calls)


def test_measurement_uses_transitive_connectivity_and_ignores_single_pad(tmp_path):
    class Uuid:
        def __init__(self, value):
            self.value = value

        def AsString(self):
            return self.value

    class Pad:
        def __init__(self, uid, net):
            self.m_Uuid = Uuid(uid)
            self.net = net

        def GetNetCode(self):
            return self.net

        def Type(self):
            # Le mock doit modeler l API qu il imite : sous KiCad 10,
            # `GetConnectedItems` rend TOUS les items relies et l appelant
            # filtre par `Type()`. Sans cette methode, le faux validait un code
            # qui plante en production.
            return FakePcbnew.PCB_PAD_T

    complete_a, complete_b = Pad("a", 1), Pad("b", 1)
    incomplete_a, incomplete_b = Pad("c", 2), Pad("d", 2)
    single = Pad("e", 3)
    pads = [complete_a, complete_b, incomplete_a, incomplete_b, single]

    class Footprint:
        def Pads(self):
            return pads

    class Connectivity:
        def RecalculateRatsnest(self):
            pass

        def GetConnectedPads(self, _pad):
            raise AssertionError("direct neighbours are not a connectivity proof")

        def GetConnectedItems(self, pad, *args):
            # ⚠️ Signature CHANGEE sous KiCad 10 :
            #     GetConnectedItems(self, aItem, int aFlags=0)
            # La liste de types a disparu — KiCad 10 rend tous les items relies
            # et le filtrage revient a l appelant. Ce mock figeait l ancienne
            # forme, donc il aurait valide un code qui plante en production.
            # Il accepte desormais les deux, comme l appelant.
            if pad is complete_a:
                return [complete_a, complete_b]
            if pad is incomplete_a:
                return [incomplete_a]
            return [pad]

    class Board:
        def BuildConnectivity(self):
            return True

        def GetConnectivity(self):
            return Connectivity()

        def GetFootprints(self):
            return [Footprint()]

    class FakePcbnew:
        PCB_PAD_T = 7

        @staticmethod
        def LoadBoard(_path):
            return Board()

    result = tmp_path / "connectivity.json"
    routing_pcbnew_runner._measure_connectivity(
        FakePcbnew, {"pcb": "board.kicad_pcb", "result": str(result)}
    )
    assert json.loads(result.read_text(encoding="utf-8")) == {"unrouted_nets": 1}


def test_pcbnew_child_timeout_fails_closed(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("routing_pcbnew_runner.py", timeout=60)

    monkeypatch.setattr(routing_router.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="timed out"):
        routing_router._run_pcbnew_operation({"operation": "measure_connectivity"})
