"""POST /place ne doit jamais toucher pcbnew dans le processus uvicorn.

`place_components` importe `pcbnew`, dont l'etat C++ global n'est pas
thread-safe, et le handler `place` est declare en `def` : uvicorn l'execute
dans son threadpool, donc deux requetes concurrentes le partagent sur le meme
worker. L'appel etant INDIRECT (routers/placement.py -> tools.placement), un
grep de « pcbnew » dans routers/ ne le voyait pas -- d'ou ces gardes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from routers import placement as placement_router  # noqa: E402


def test_place_goes_through_a_child_process(monkeypatch, tmp_path):
    """Le handler passe par le runner, jamais par un import pcbnew local."""
    seen: dict[str, object] = {}

    def _fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        payload = json.loads(cmd[2])
        Path(payload["result_path"]).write_text(
            json.dumps({"status": "ok", "path": payload["output_path"],
                        "placed": 1, "errors": []}),
            encoding="utf-8",
        )

        class _P:
            returncode = 0
            stdout = ""
            stderr = ""
        return _P()

    monkeypatch.setattr(placement_router.subprocess, "run", _fake_run)

    result = placement_router._place_components_isolated(
        "in.kicad_pcb", [{"ref": "R1", "x_mm": 1.0, "y_mm": 2.0}], "out.kicad_pcb"
    )

    assert result["placed"] == 1
    # C'est bien un sous-processus sur le runner dedie, pas un appel en direct.
    assert "placement_pcbnew_runner.py" in str(seen["cmd"][1])


def test_missing_pcbnew_is_reported_as_unavailable(monkeypatch):
    """pcbnew absent = defaut d'environnement (503), pas d'echec de requete."""
    def _fake_run(cmd, **kwargs):
        class _P:
            returncode = 1
            stdout = ""
            stderr = "ImportError: pcbnew non disponible - KiCad doit etre installe"
        return _P()

    monkeypatch.setattr(placement_router.subprocess, "run", _fake_run)

    with pytest.raises(placement_router._PcbnewUnavailable):
        placement_router._place_components_isolated("in", [], "out")


def test_child_failure_is_not_silently_swallowed(monkeypatch):
    """Un enfant en echec leve : jamais de placement annonce sans mesure."""
    def _fake_run(cmd, **kwargs):
        class _P:
            returncode = 3
            stdout = ""
            stderr = "boom"
        return _P()

    monkeypatch.setattr(placement_router.subprocess, "run", _fake_run)

    with pytest.raises(RuntimeError):
        placement_router._place_components_isolated("in", [], "out")


def test_child_producing_no_result_is_an_error(monkeypatch):
    """rc=0 mais aucun fichier resultat : on echoue, on n'invente rien."""
    def _fake_run(cmd, **kwargs):
        class _P:
            returncode = 0
            stdout = ""
            stderr = ""
        return _P()

    monkeypatch.setattr(placement_router.subprocess, "run", _fake_run)

    with pytest.raises(RuntimeError):
        placement_router._place_components_isolated("in", [], "out")
