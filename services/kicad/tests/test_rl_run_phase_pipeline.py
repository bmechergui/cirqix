"""Unit tests — lab pipeline best-of + hard gate wiring."""

from __future__ import annotations

from pathlib import Path

from kicad_tools.schema.pcb import PCB

from tools.rl import run_phase_pipeline as rpp
from tools.rl.run_phase_pipeline import _best_of_route, evaluate_final_hard_gate, main


def test_best_of_prefers_higher_pct() -> None:
    a = {"arm": "kct", "routed_percent": 90, "preferred": True}
    b = {"arm": "ppo", "routed_percent": 95, "preferred": False}
    w = _best_of_route(a, b)
    assert w["arm"] == "ppo"
    assert w["selected"] is True


def test_best_of_tie_prefers_kct() -> None:
    a = {"arm": "kct", "routed_percent": 100, "preferred": True}
    b = {"arm": "ppo", "routed_percent": 100, "preferred": False}
    w = _best_of_route(a, b)
    assert w["arm"] == "kct"


def test_pipeline_skip_route(tmp_path: Path) -> None:
    pcb = PCB.create(width=40.0, height=30.0, layers=2)
    path = tmp_path / "in.kicad_pcb"
    pcb.save(str(path))
    out_dir = tmp_path / "run"
    out_json = tmp_path / "r.json"
    rc = main(
        [
            "--pcb",
            str(path),
            "--out-dir",
            str(out_dir),
            "--out-json",
            str(out_json),
            "--place-algo",
            "off",
            "--skip-route",
        ]
    )
    assert rc == 0
    assert (out_dir / "01_placed.kicad_pcb").is_file()
    payload = out_json.read_text(encoding="utf-8")
    assert "prod_flag" in payload
    assert "OFF" in payload
    assert "hard_gate" in payload


def test_evaluate_final_hard_gate_fail_closed_without_drc(
    tmp_path: Path, monkeypatch
) -> None:
    """Missing kicad-cli DRC → hard gate NO-GO even at 100% route."""
    pcb = PCB.create(width=40.0, height=30.0, layers=2)
    path = tmp_path / "board.kicad_pcb"
    pcb.save(str(path))

    monkeypatch.setattr(
        rpp,
        "try_kicad_cli_drc",
        lambda _p: (None, None, "kicad-cli not found"),
    )
    monkeypatch.setattr(rpp, "_count_placement_errors", lambda _p: 0)

    rep = evaluate_final_hard_gate(
        final_pcb=path,
        routed_percent=100,
        baseline_arm={"routed_percent": 100, "arm": "kct"},
    )
    assert rep["passed"] is False
    assert "drc" in rep["hard_gate"]["verdict"].lower() or any(
        "drc" in r.lower() for r in rep["hard_gate"]["reasons"]
    )
    assert rep["baseline_compare"] is not None
    assert rep["baseline_compare"]["route_ok"] is True


def test_evaluate_final_hard_gate_pass_when_all_clean(
    tmp_path: Path, monkeypatch
) -> None:
    pcb = PCB.create(width=40.0, height=30.0, layers=2)
    path = tmp_path / "board.kicad_pcb"
    pcb.save(str(path))

    monkeypatch.setattr(rpp, "try_kicad_cli_drc", lambda _p: (0, 0, None))
    monkeypatch.setattr(rpp, "_count_placement_errors", lambda _p: 0)

    rep = evaluate_final_hard_gate(
        final_pcb=path,
        routed_percent=100,
        baseline_arm={"routed_percent": 100},
    )
    assert rep["passed"] is True
    assert rep["hard_gate"]["passed"] is True


def test_fr_fallback_uses_kct_not_pcbnew(tmp_path: Path) -> None:
    """Secondary arm is kicad-tools route_kct — never tools.routing/pcbnew."""
    pcb = PCB.create(width=40.0, height=30.0, layers=2)
    path = tmp_path / "in.kicad_pcb"
    pcb.save(str(path))
    out = tmp_path / "out.kicad_pcb"

    def fake_kct(pcb_bytes: bytes, timeout_s: int = 120):
        del timeout_s
        return pcb_bytes + b"\n;alt", 100, "ok"

    result = rpp._run_fr_fallback(path, out, route_fn=fake_kct)
    assert result["ok"] is True
    assert result["arm"] == "kct_alt"
    assert result["routed_percent"] == 100
    assert "kicad-tools" in result.get("note", "")
    assert out.read_bytes().endswith(b";alt")


def test_fr_fallback_reports_kct_partial_pct(tmp_path: Path) -> None:
    """Partial kct % is forwarded as-is (no 50% hardcode, no pcbnew)."""
    pcb = PCB.create(width=40.0, height=30.0, layers=2)
    path = tmp_path / "in.kicad_pcb"
    pcb.save(str(path))
    out = tmp_path / "out.kicad_pcb"

    def fake_kct(pcb_bytes: bytes, timeout_s: int = 120):
        del timeout_s
        return pcb_bytes, 50, "partial"

    result = rpp._run_fr_fallback(path, out, route_fn=fake_kct)
    assert result["ok"] is True
    assert result["routed_percent"] == 50
    assert result["arm"] == "kct_alt"


def test_pipeline_exit_uses_hard_gate(tmp_path: Path, monkeypatch) -> None:
    """With mocked route 100% but no DRC → exit 3 (hard gate authority)."""
    pcb = PCB.create(width=40.0, height=30.0, layers=2)
    path = tmp_path / "in.kicad_pcb"
    pcb.save(str(path))

    def fake_kct(pcb_path: Path, out_pcb: Path, timeout_s: int) -> dict:
        del timeout_s
        out_pcb.write_bytes(pcb_path.read_bytes())
        return {
            "ok": True,
            "arm": "kct",
            "preferred": True,
            "routed_percent": 100,
            "elapsed_s": 0.01,
            "board_out": str(out_pcb),
        }

    monkeypatch.setattr(rpp, "_run_route_kct", fake_kct)
    monkeypatch.setattr(
        rpp, "try_kicad_cli_drc", lambda _p: (None, None, "kicad-cli not found")
    )
    monkeypatch.setattr(rpp, "_count_placement_errors", lambda _p: 0)

    out_json = tmp_path / "out.json"
    rc = main(
        [
            "--pcb",
            str(path),
            "--out-dir",
            str(tmp_path / "run"),
            "--out-json",
            str(out_json),
            "--place-algo",
            "off",
            "--route-fallback",
            "off",
        ]
    )
    assert rc == 3
    data = out_json.read_text(encoding="utf-8")
    assert "hard_gate" in data
    assert "phase6_ready" in data
