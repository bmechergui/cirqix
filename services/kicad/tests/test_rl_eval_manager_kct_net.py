"""Unit tests — eval_manager_kct_net lab arms (injectable backends)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from kicad_tools.schema.pcb import PCB

from tools.rl.routing import eval_manager_kct_net as em
from tools.rl.routing.route_net_api import (
    MockRouterState,
    RouteNetMetrics,
    multi_pad_net_ids,
)


def _minimal_board(tmp_path: Path) -> Path:
    pcb = PCB.create(width=40.0, height=30.0, layers=2)
    path = tmp_path / "board.kicad_pcb"
    pcb.save(str(path))
    return path


def test_pick_best_arm_prefers_higher_pct() -> None:
    a = {"arm": "full_kct", "ok": True, "routed_percent": 90, "board_out": "a"}
    b = {"arm": "greedy_kct_net", "ok": True, "routed_percent": 100, "board_out": "b"}
    w = em.pick_best_arm([a, b])
    assert w["arm"] == "greedy_kct_net"


def test_pick_best_arm_tie_prefers_full_kct() -> None:
    a = {"arm": "full_kct", "ok": True, "routed_percent": 100, "board_out": "a"}
    b = {"arm": "greedy_kct_net", "ok": True, "routed_percent": 100, "board_out": "b"}
    w = em.pick_best_arm([a, b])
    assert w["arm"] == "full_kct"


def test_run_full_kct_writes_board(tmp_path: Path) -> None:
    src = _minimal_board(tmp_path)
    out = tmp_path / "routed.kicad_pcb"

    def fake_route(raw: bytes, timeout_s: int = 120, **kwargs):
        del timeout_s, kwargs
        return raw + b"\n;routed", 100, ""

    rep = em.run_full_kct(src, out, route_fn=fake_route)
    assert rep["ok"] is True
    assert rep["routed_percent"] == 100
    assert out.is_file()
    assert b";routed" in out.read_bytes()


def test_run_greedy_kct_net_calls_each_net(tmp_path: Path, monkeypatch) -> None:
    src = _minimal_board(tmp_path)
    # Patch multi_pad + route_net so we don't need real pads
    monkeypatch.setattr(em, "multi_pad_net_ids", lambda _b: [1, 2, 3])
    called: list[int] = []

    def fake_route_net(pcb_bytes, net_id, strategy, **kwargs):
        state: MockRouterState = kwargs["state"]
        called.append(int(net_id))
        state.routed.add(int(net_id))
        state.kct_reported_pct = int(round(100.0 * state.nets_routed / state.nets_total))
        m = RouteNetMetrics(
            routed_percent=state.routed_percent,
            nets_total=state.nets_total,
            nets_routed=state.nets_routed,
            unrouted_count=state.unrouted_count,
            last_net_id=int(net_id),
            strategy=strategy,
            success=True,
            note="fake",
        )
        return pcb_bytes, m

    out = tmp_path / "greedy.kicad_pcb"
    rep = em.run_greedy_kct_net(src, out, route_net_fn=fake_route_net)
    assert rep["ok"] is True
    assert called == [1, 2, 3]
    assert rep["manager_routed_percent"] == 100
    assert out.is_file()


def test_run_ppo_manager_mock_backend(tmp_path: Path) -> None:
    """PPO load inject: always pick stop after reset — drives real env + API."""
    src = _minimal_board(tmp_path)
    model = tmp_path / "fake_model.zip"
    model.write_bytes(b"not-a-real-zip")

    # stop action for empty PCB fallback nets 1..6
    from tools.rl.routing.manager_env import stop_action_for_slots

    class FakeModel:
        def predict(self, obs, deterministic=True):
            del obs, deterministic
            return stop_action_for_slots(6), None

    out = tmp_path / "ppo.kicad_pcb"
    rep = em.run_ppo_manager_kct_net(
        src,
        out,
        model,
        max_steps=4,
        backend="mock",
        load_ppo=lambda _p: FakeModel(),
    )
    assert rep["ok"] is True
    assert rep["n_actions"] == 1
    assert rep["actions"][0]["stop"] is True
    assert out.is_file()


def test_run_eval_hard_gate_fail_closed_without_drc(tmp_path: Path, monkeypatch) -> None:
    src = _minimal_board(tmp_path)
    out_dir = tmp_path / "run"

    def fake_full(pcb_path, out_path, **kwargs):
        shutil_copy = __import__("shutil").copy2
        shutil_copy(pcb_path, out_path)
        return {
            "arm": "full_kct",
            "ok": True,
            "routed_percent": 100,
            "board_out": str(out_path),
            "elapsed_s": 0.01,
        }

    monkeypatch.setattr(em, "run_full_kct", fake_full)
    monkeypatch.setattr(em, "ensure_place_clean", lambda pcb, out: {
        "board_out": str(__import__("shutil").copy2(pcb, out) or out),
        "error_conflicts_before": 0,
        "error_conflicts_after": 0,
        "fixed": False,
        "ok": True,
    })
    # force ensure_place_clean simpler
    def place_clean(pcb, out):
        __import__("shutil").copy2(pcb, out)
        return {
            "board_out": str(out),
            "error_conflicts_before": 0,
            "error_conflicts_after": 0,
            "fixed": False,
            "ok": True,
        }

    monkeypatch.setattr(em, "ensure_place_clean", place_clean)

    import tools.rl.run_phase_pipeline as rpp

    monkeypatch.setattr(
        rpp, "try_kicad_cli_drc", lambda _p: (None, None, "kicad-cli not found")
    )
    monkeypatch.setattr(rpp, "_count_placement_errors", lambda _p: 0)

    report = em.run_eval(
        pcb=src,
        out_dir=out_dir,
        model=None,
        skip_ppo=True,
        skip_greedy=True,
        skip_full_kct=False,
    )
    assert report["prod_flag"] == "OFF"
    assert report["phase6_ready"] is False
    assert report["hard_gate"]["passed"] is False
    reasons = " ".join(report["hard_gate"].get("reasons") or [])
    assert "drc" in reasons.lower()
