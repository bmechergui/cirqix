"""circuit_synth timeout must bound the request — not hang the worker thread.

Régression : `fut.result(timeout=20)` + `fut.cancel()` sur une tâche déjà
démarrée, puis sortie du `with ThreadPoolExecutor` → `shutdown(wait=True)`.
Une génération bloquée retenait le thread de requête sans borne.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from tools import schematic as schematic_mod  # noqa: E402
from tools.schematic import (  # noqa: E402
    SchemaComponent,
    SchemaNet,
    SchemaPin,
    generate_schematic,
)


def _minimal() -> tuple[list[SchemaComponent], list[SchemaNet], list[str]]:
    comps = [
        SchemaComponent(
            ref="R1",
            value="10k",
            footprint="Resistor_SMD:R_0805_2012Metric",
        ),
    ]
    nets = [
        SchemaNet(name="GND", pins=[SchemaPin(ref="R1", pin=2)]),
    ]
    return comps, nets, ["GND"]


def test_blocked_circuit_synth_does_not_hang_request(monkeypatch):
    """A blocking circuit_synth call must not suspend generate_schematic.

    Bounds the request: returns (via fallback) within a short multiple of the
    configured timeout, not after the blocker's sleep ends.
    """
    # Block longer than the timeout but short enough that the orphan worker
    # (wait=False leaves it running) does not stall process exit for long.
    block_s = 1.5
    timeout_s = 0.25

    monkeypatch.setattr(schematic_mod, "_circuit_synth_available", lambda: True)
    monkeypatch.setattr(schematic_mod, "_CS_TIMEOUT_S", timeout_s)

    def _blocker(*_args, **_kwargs):
        time.sleep(block_s)
        return "(kicad_sch should-never-return)"

    monkeypatch.setattr(schematic_mod, "_generate_with_cs_lib", _blocker)

    # Avoid depending on kicad-tools in non-Docker env: force fallback to "" .
    monkeypatch.setattr(
        schematic_mod,
        "_generate_with_kicad_tools",
        lambda *_a, **_k: "",
    )

    comps, connections, nets = _minimal()
    t0 = time.monotonic()
    result = generate_schematic(comps, connections, nets, project_id="timeout-test")
    elapsed = time.monotonic() - t0

    # Must finish near the timeout, not near block_s (which would mean wait=True hang).
    assert elapsed < block_s * 0.7, (
        f"request hung for {elapsed:.2f}s (timeout={timeout_s}s, "
        f"blocker={block_s}s) — timeout did not bound the call"
    )
    assert elapsed >= timeout_s * 0.5, (
        f"returned too fast ({elapsed:.2f}s) — timeout path may not have run"
    )
    # All Python paths fail → empty string (TypeScript fallback upstream).
    assert result == ""


def test_circuit_synth_success_still_returns_content(monkeypatch):
    """Timeout fix must not break the happy path."""
    monkeypatch.setattr(schematic_mod, "_circuit_synth_available", lambda: True)
    monkeypatch.setattr(schematic_mod, "_CS_TIMEOUT_S", 5.0)
    monkeypatch.setattr(
        schematic_mod,
        "_generate_with_cs_lib",
        lambda *_a, **_k: '(kicad_sch (version 20230121) (generator "test"))',
    )

    comps, connections, nets = _minimal()
    result = generate_schematic(comps, connections, nets, project_id="ok")
    assert result.startswith("(kicad_sch")
