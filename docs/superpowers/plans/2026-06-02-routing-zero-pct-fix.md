# Routing 0% Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the KiCad service reliably route simple circuits instead of returning 0%-routed boards.

**Architecture:** Two root causes. **RC1** — `route_auto` returns the kicad-tools A* result for simple circuits even at 0%, never falling through to the higher-quality Freerouting (only an *exception* triggers fallback). **RC2** — the pure-Python A* underperforms because (a) the C++ router backend is never built, (b) the board outline is left oversized (no working board-fit → ~2M-cell grid), and (c) power pours / module-pin escape make a near-empty board unroutable. Fix RC1 first (restores the cascade), then RC2 (makes kicad-tools itself capable).

**Tech Stack:** Python 3.11 (FastAPI), `kicad_tools` (pure-Python + optional C++ A* router), Freerouting (Java REST), pytest, Docker (Ubuntu 22.04 + KiCad 8).

**Diagnostic evidence (2026-06-02):** On `test_full_pipeline.py` (meteo Arduino: 1 routable net `DHT_DATA`, 5 comps), `kct route` returns `0/1 nets — No path found` across fine/coarse grids and 90s per-net timeouts; router verdict "topology, not congestion". Board is 200×160mm @ 0.127mm grid (capped from 0.005mm) ≈ 2M cells; "C++ router backend not installed — using pure Python (10-100× slower)". `route_auto` (`routing.py:460`) returns this 0% for simple circuits without trying Freerouting.

---

## File Structure

- `services/kicad/routers/routing.py` — cascade logic (RC1), power-nets format, `_route_with_kicad_tools`.
- `services/kicad/tools/placement.py` — `_fit_board_outline_to_components` (buggy), `auto_place` (wire board-fit in).
- `services/kicad/Dockerfile` — add C++ toolchain + `kct build-native`.
- `services/kicad/tests/test_route_auto_cascade.py` — NEW pytest unit tests for cascade (RC1).
- `services/kicad/tests/test_board_fit.py` — NEW pytest unit tests for board-fit integrity.
- `services/kicad/tests/test_full_pipeline.py` — end-to-end regression (already self-sufficient).

---

## Phase A — RC1: cascade falls through to Freerouting on low completion

### Task A1: Threshold + fall-through logic in `route_auto`

**Files:**
- Modify: `services/kicad/routers/routing.py` (constants near line 42; `route_auto` lines 435-536)
- Test: `services/kicad/tests/test_route_auto_cascade.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# services/kicad/tests/test_route_auto_cascade.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/kicad && python -m pytest tests/test_route_auto_cascade.py -v`
Expected: `test_low_kicad_tools_falls_through_to_freerouting` FAILS (returns `partial`/0%, not `fr-routed`); `test_low_kicad_tools_kept_when_freerouting_absent` FAILS (re-runs kicad-tools or returns differently).

- [ ] **Step 3: Add threshold constant**

In `routing.py` after line 44 (`_PYTHON_ROUTER_TIMEOUT_S: int = 60`):

```python
# Below this completion %, prefer Freerouting (higher quality) when available.
# Matches kct's own --min-completion 0.95 default.
_MIN_ROUTED_PCT: int = 95
```

- [ ] **Step 4: Rewrite the Niveau 1 + Niveau 4/5 logic in `route_auto`**

Replace the Niveau 1 block (lines 459-471) with:

```python
    # Best kicad-tools partial result so far (reused at Niveau 4 if Freerouting absent)
    kt_partial: Optional[tuple[bytes, int]] = None

    # --- Niveau 1 : kicad-tools A* (circuits simples ≤30 nets/comps) ---
    if is_simple:
        try:
            new_pcb, routed_pct = _route_with_kicad_tools(pcb_bytes)
            logger.info("kicad-tools A*: %d%% routé", routed_pct)
            if routed_pct >= _MIN_ROUTED_PCT:
                return RouteAutoResponse(
                    kicad_pcb_b64=base64.b64encode(new_pcb).decode("ascii"),
                    routed_percent=routed_pct,
                    layers=req.layers,
                    skipped=False,
                )
            # Below threshold: keep it, but try Freerouting for a better result.
            kt_partial = (new_pcb, routed_pct)
            logger.info(
                "kicad-tools %d%% < %d%% — tentative Freerouting",
                routed_pct, _MIN_ROUTED_PCT,
            )
        except Exception as exc:
            logger.warning("kicad-tools A* échoué (%s) — Freerouting API", exc)
```

Replace the Niveau 4 block (lines 511-525) with (reuse `kt_partial` instead of re-running):

```python
    # --- Niveau 4 : kicad-tools negotiated sans limite (tous circuits) ---
    # Reuse the Niveau-1 partial when we already have one (avoid a second expensive run).
    try:
        if kt_partial is not None:
            new_pcb, routed_pct = kt_partial
        else:
            new_pcb, routed_pct = _route_with_kicad_tools(pcb_bytes)
        logger.info("kicad-tools A* (no limit): %d%% routé", routed_pct)
        return RouteAutoResponse(
            kicad_pcb_b64=base64.b64encode(new_pcb).decode("ascii"),
            routed_percent=routed_pct,
            layers=req.layers,
            skipped=False,
            warning=f"Freerouting indisponible — kicad-tools negotiated utilisé ({net_count} nets)",
        )
    except Exception as exc:
        logger.warning("kicad-tools A* (no limit) échoué (%s) — GND plane", exc)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd services/kicad && python -m pytest tests/test_route_auto_cascade.py -v`
Expected: all 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add services/kicad/routers/routing.py services/kicad/tests/test_route_auto_cascade.py
git commit -m "fix(routing): fall through to Freerouting when kicad-tools A* completion < 95%"
```

---

## Phase B — Power-nets `NET:LAYER` format

### Task B1: Build correct `--power-nets` argument

**Files:**
- Modify: `services/kicad/routers/routing.py` — `_route_with_kicad_tools` (lines ~360-374) and `_detect_power_nets` (lines 341-347)
- Test: `services/kicad/tests/test_route_auto_cascade.py` (add)

- [ ] **Step 1: Write the failing test**

```python
def test_power_nets_arg_uses_net_layer_format():
    from routers.routing import _power_nets_arg
    # GND → B.Cu, supply nets → F.Cu (2-layer convention)
    assert _power_nets_arg(["GND", "VCC_5V"]) == "GND:B.Cu,VCC_5V:F.Cu"
    assert _power_nets_arg([]) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/kicad && python -m pytest tests/test_route_auto_cascade.py::test_power_nets_arg_uses_net_layer_format -v`
Expected: FAIL with `ImportError: cannot import name '_power_nets_arg'`.

- [ ] **Step 3: Add `_power_nets_arg` and use it**

Add near `_detect_power_nets` (after line 347):

```python
def _power_nets_arg(power_nets: list[str]) -> str:
    """Format power nets as kct '--power-nets NET:LAYER,...'.

    GND → B.Cu, supply rails → F.Cu (standard 2-layer pour convention).
    """
    layer_for = lambda n: "B.Cu" if n == "GND" else "F.Cu"
    return ",".join(f"{n}:{layer_for(n)}" for n in power_nets)
```

In `_route_with_kicad_tools`, replace (lines ~373-374):

```python
        if power_nets:
            cmd += ["--power-nets", ",".join(power_nets)]
```

with:

```python
        power_arg = _power_nets_arg(power_nets)
        if power_arg:
            cmd += ["--power-nets", power_arg]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/kicad && python -m pytest tests/test_route_auto_cascade.py::test_power_nets_arg_uses_net_layer_format -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/kicad/routers/routing.py services/kicad/tests/test_route_auto_cascade.py
git commit -m "fix(routing): pass --power-nets in NET:LAYER format (GND:B.Cu,VCC:F.Cu)"
```

---

## Phase C — Board-fit: safe outline fit, wired into `auto_place`

### Task C1: Rewrite `_fit_board_outline_to_components` to preserve the PCB

**Problem:** Current helper (placement.py:301) computes bbox from raw `(at …)` lines (catches pad-relative offsets) and removes Edge.Cuts with a greedy `gr_rect` regex that **deletes footprints** (verified: 5→4 footprints, 41→9 pads).

**Files:**
- Modify: `services/kicad/tools/placement.py` (`_fit_board_outline_to_components` lines 301-332)
- Test: `services/kicad/tests/test_board_fit.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# services/kicad/tests/test_board_fit.py
"""Board-fit must shrink the Edge.Cuts outline WITHOUT dropping footprints/pads."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from tools.placement import _fit_board_outline_to_components

PLACED = Path(r"C:\Users\Mechegui\Downloads\Kicadmcptest\test\meteo_arduino_placed.kicad_pcb")


def test_fit_preserves_footprints_and_pads():
    src = PLACED.read_bytes()
    n_fp = len(re.findall(r"\(footprint ", src.decode("utf-8", "replace")))
    n_pad = len(re.findall(r"\(pad ", src.decode("utf-8", "replace")))
    out = _fit_board_outline_to_components(src, margin_mm=5.0).decode("utf-8", "replace")
    assert len(re.findall(r"\(footprint ", out)) == n_fp, "footprints dropped"
    assert len(re.findall(r"\(pad ", out)) == n_pad, "pads dropped"


def test_fit_shrinks_outline_below_original():
    src = PLACED.read_bytes()
    out = _fit_board_outline_to_components(src, margin_mm=5.0).decode("utf-8", "replace")
    rects = re.findall(r'\(gr_rect \(start ([\d.\-]+) ([\d.\-]+)\) \(end ([\d.\-]+) ([\d.\-]+)\)', out)
    assert rects, "no Edge.Cuts rect emitted"
    x0, y0, x1, y1 = map(float, rects[-1])
    assert (x1 - x0) < 200.0 and (y1 - y0) < 160.0
    assert (x1 - x0) > 0 and (y1 - y0) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/kicad && python -m pytest tests/test_board_fit.py -v`
Expected: `test_fit_preserves_footprints_and_pads` FAILS (footprints dropped).

> Prerequisite: `meteo_arduino_placed.kicad_pcb` exists (run `python tests/test_full_pipeline.py` first).

- [ ] **Step 3: Rewrite the helper using the kicad_tools PCB API + scoped outline edit**

Replace `_fit_board_outline_to_components` (lines 301-332) with:

```python
def _fit_board_outline_to_components(pcb_bytes: bytes, margin_mm: float = 10.0) -> bytes:
    """Create an Edge.Cuts rectangle fitted to the placed footprints + margin.

    Uses the kicad_tools PCB model to read real footprint positions (not raw
    ``(at …)`` lines, which also match pad-relative offsets). Only top-level
    ``(gr_line/gr_rect … "Edge.Cuts" …)`` blocks are replaced — footprints are
    never touched. Returns the input unchanged if no footprints are found.
    """
    import uuid as _uuid

    text = pcb_bytes.decode("utf-8", errors="replace")

    try:
        import tempfile as _tmp
        from kicad_tools.schema.pcb import PCB
        with _tmp.NamedTemporaryFile(suffix=".kicad_pcb", mode="wb", delete=False) as _f:
            _f.write(pcb_bytes)
            _p = Path(_f.name)
        pcb = PCB.load(str(_p))
        _p.unlink(missing_ok=True)
        xs = [fp.position[0] for fp in pcb.footprints]
        ys = [fp.position[1] for fp in pcb.footprints]
    except Exception as exc:  # pragma: no cover - API fallback
        logger.warning("_fit_board_outline: PCB API failed (%s) — outline unchanged", exc)
        return pcb_bytes

    if not xs:
        return pcb_bytes

    # Footprint anchors + generous margin to cover body/pad extents (Arduino ≈ 35×91mm).
    x0 = round(min(xs) - margin_mm, 2)
    y0 = round(min(ys) - margin_mm, 2)
    x1 = round(max(xs) + margin_mm, 2)
    y1 = round(max(ys) + margin_mm, 2)

    text = _strip_edge_cuts_graphics(text)
    outline = (
        f'\n  (gr_rect (start {x0} {y0}) (end {x1} {y1})'
        f'\n    (stroke (width 0.1) (type solid)) (fill none) (layer "Edge.Cuts")'
        f'\n    (uuid "{_uuid.uuid4()}"))\n'
    )
    last = text.rfind(")")
    if last >= 0:
        text = text[:last] + outline + text[last:]
    return text.encode("utf-8")


def _strip_edge_cuts_graphics(text: str) -> str:
    """Remove top-level (gr_line …)/(gr_rect …) blocks whose layer is Edge.Cuts.

    Uses balanced-paren scanning (NOT greedy regex) so footprint bodies are
    never consumed. Footprint outlines use (fp_line …) and are left intact.
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("(gr_line", i) or text.startswith("(gr_rect", i):
            depth = 0
            j = i
            while j < n:
                c = text[j]
                if c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
            block = text[i:j]
            if '"Edge.Cuts"' in block:
                i = j  # drop this Edge.Cuts graphic
                continue
            out.append(block)
            i = j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/kicad && python -m pytest tests/test_board_fit.py -v`
Expected: both PASS (footprints/pads preserved, outline shrunk).

- [ ] **Step 5: Commit**

```bash
git add services/kicad/tools/placement.py services/kicad/tests/test_board_fit.py
git commit -m "fix(placement): board-fit preserves footprints (balanced-paren Edge.Cuts strip)"
```

### Task C2: Call board-fit at the end of `auto_place`

**Files:**
- Modify: `services/kicad/tools/placement.py` — `auto_place` return block (lines 262-266)

- [ ] **Step 1: Write the failing test**

```python
# append to services/kicad/tests/test_board_fit.py
import base64
from tools.placement import auto_place


def test_auto_place_returns_fitted_board():
    src = PLACED.read_bytes()
    res = auto_place(base64.b64encode(src).decode(), 200.0, 160.0)
    out = base64.b64decode(res["kicad_pcb_b64"]).decode("utf-8", "replace")
    rects = re.findall(r'\(gr_rect \(start ([\d.\-]+) ([\d.\-]+)\) \(end ([\d.\-]+) ([\d.\-]+)\)', out)
    assert rects, "no fitted Edge.Cuts in auto_place output"
    x0, y0, x1, y1 = map(float, rects[-1])
    assert (x1 - x0) < 200.0  # board shrunk to components
    assert res["placed_count"] == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/kicad && python -m pytest tests/test_board_fit.py::test_auto_place_returns_fitted_board -v`
Expected: FAIL (board still 200×160, no shrunk rect).

- [ ] **Step 3: Apply board-fit before returning from `auto_place`**

In `auto_place`, replace the success return (lines 262-266):

```python
            return {
                "kicad_pcb_b64": base64.b64encode(dst.read_bytes()).decode(),
                "placed_count": placed_count,
                "positions": [{"ref": r} for r in result.placed_refs],
            }
```

with:

```python
            fitted = _fit_board_outline_to_components(dst.read_bytes(), margin_mm=10.0)
            return {
                "kicad_pcb_b64": base64.b64encode(fitted).decode(),
                "placed_count": placed_count,
                "positions": [{"ref": r} for r in result.placed_refs],
            }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/kicad && python -m pytest tests/test_board_fit.py::test_auto_place_returns_fitted_board -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/kicad/tools/placement.py services/kicad/tests/test_board_fit.py
git commit -m "feat(placement): fit board outline to components after placement"
```

---

## Phase D — Build the C++ router backend in Docker

### Task D1: Add C++ toolchain + `kct build-native`

**Files:**
- Modify: `services/kicad/Dockerfile` (apt list lines 32-44; after kicad-tools install line 81)

- [ ] **Step 1: Add the C++ toolchain to the apt install list**

In the second `apt-get install` block (after line 40 `openjdk-21-jre-headless \`), add:

```dockerfile
               cmake \
               g++ \
```

- [ ] **Step 2: Build the native router after kicad-tools is installed**

After line 81 (`pip3 install … "/tmp/kicad_tools[...]"`), add:

```dockerfile
# Build the C++ A* router extension (10-100× faster than pure Python).
# Non-fatal: if the build fails the router falls back to pure Python at runtime.
RUN kct build-native || echo "WARNING: kct build-native failed — router will use pure Python"
RUN kct build-native --check || true
```

- [ ] **Step 3: Verify the build locally (best effort)**

Run: `cd services/kicad && docker build -t cirqix-kicad-test .`
Expected: build succeeds; `kct build-native --check` line prints that the C++ router is available. If Docker is unavailable in this environment, document that this step must be verified in CI/deploy.

- [ ] **Step 4: Commit**

```bash
git add services/kicad/Dockerfile
git commit -m "build(kicad): compile C++ A* router backend in Docker (cmake+g++)"
```

---

## Phase E — Validate end-to-end & investigate residual Arduino-pin escape

### Task E1: Re-run the full local pipeline and measure routing

**Files:**
- Run: `services/kicad/tests/test_full_pipeline.py`

- [ ] **Step 1: Run the pipeline**

Run: `cd services/kicad && python tests/test_full_pipeline.py`
Expected: Étape 4 reports a routed percent. Record the value.

- [ ] **Step 2: Decision gate**

- If `DHT_DATA` now routes (segments > 0): RC2 resolved by board-fit + power-nets (C++ backend only builds in Docker). Proceed to Step 4.
- If still 0% locally (pure Python on Windows, no C++): re-test the routability on the **fitted** board with `_route_with_kicad_tools` directly to confirm board-fit shrank the grid enough. If it routes → fixed in Docker (C++) and on smaller boards; document the local-Windows limitation. If still "No path found" on the fitted board → continue to Step 3.

- [ ] **Step 3: Investigate Arduino-pin escape (only if still failing on fitted board)**

Add diagnostic instrumentation: route the fitted board with `--export-failed-nets failed.txt -v` and inspect whether the `U1` (Arduino `D2`) pad reports `BLOCKED_BY_COMPONENT`. If so, evaluate one of:
- `--fine-pitch-clearance` for header escape, or
- `--placement-feedback` (nudges non-anchored components; connectors auto-anchored), or
- treating `Module:Arduino_UNO_R3` as a connector (anchor) and ensuring its courtyard is not a hard keepout for its own net.

Document findings in `docs/notefinal.md` (decision log) before any further code change — this sub-step is investigative and may spawn a follow-up plan.

- [ ] **Step 4: Update docs + memory**

Update `CLAUDE.md` routing cascade section: Niveau 1 now falls through to Freerouting below 95%; board is fitted after placement; C++ router built in Docker. Append a decision-log entry to `docs/notefinal.md`. Update memory `project_routing_zero_pct.md` with the resolution.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/notefinal.md
git commit -m "docs(routing): document cascade fallback + board-fit + C++ backend"
```

---

## Self-Review

**Spec coverage:** RC1 cascade (Phase A) ✓ · power-nets format (Phase B) ✓ · board-fit rewrite + wire-in (Phase C) ✓ · C++ Docker build (Phase D) ✓ · Arduino escape investigation (Phase E) ✓.

**Placeholders:** Phase E Step 3 is intentionally investigative (root cause not yet pinned) — gated behind a measured decision (Step 2) per systematic-debugging; it documents findings before code, not a code placeholder.

**Type consistency:** `_power_nets_arg(list[str]) -> str`, `_fit_board_outline_to_components(bytes, margin_mm) -> bytes`, `_strip_edge_cuts_graphics(str) -> str`, `kt_partial: tuple[bytes,int] | None`, `_MIN_ROUTED_PCT: int` — names consistent across tasks. `auto_place` return dict keys (`kicad_pcb_b64`, `placed_count`, `positions`) unchanged.

**Risk notes:** Phase A is the highest-value, lowest-risk change and is independently shippable. Phases C/D are independent of A/B. Phase D can only be fully verified where Docker builds. Board-fit margin (10mm) must cover footprint extents beyond anchors; the integrity test guards against PCB corruption.
