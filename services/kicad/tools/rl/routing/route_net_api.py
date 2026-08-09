"""Incremental KCT routing API for Dreamer/PPO manager (Phase 1b).

Target contract (docs/rl)::

    route_net(board, net_id, strategy) -> (new_board, metrics)

Backends:

* ``mock`` — deterministic TDD / PPO-transition smoke
* ``kct_net`` — **real per-net geometry** via kicad-tools ``kct route --nets``
* ``kct_full`` — temporary full-board proxy (lab-only; not incremental)

Taxonomy strategies are Cirqix-proposed; only a subset maps to kct flags today.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

# Taxonomie proposée Cirqix — non extraite de l'article DreamerV3+FR
STRATEGIES: tuple[str, ...] = (
    "shortest",
    "low_vias",
    "low_congestion",
    "preferred_layer",
    "power",
    "ripup_retry",
    "balanced",
    "vcc_traces",
    "vcc_planes",
)
N_STRATEGIES: int = len(STRATEGIES)

StrategyName = str
BackendName = Literal["mock", "kct_full", "kct_net"]

_NET_DECL_RE = re.compile(r'\(net\s+(\d+)\s+"([^"]*)"')


@dataclass(frozen=True)
class RouteNetMetrics:
    """Metrics returned after one manager step."""

    routed_percent: int
    nets_total: int
    nets_routed: int
    unrouted_count: int
    last_net_id: int
    strategy: str
    success: bool
    note: str = ""
    vias_delta: int = 0
    length_mm_delta: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MockRouterState:
    """Tracks which net slots are considered routed (all backends).

    For ``backend=mock``, ``routed`` is the source of truth.
    For ``kct_net`` / ``kct_full``, helpers update ``routed`` and optional
    ``kct_reported_pct`` so ManagerRoutingEnv observation/reward progress.
    """

    net_ids: list[int] = field(default_factory=list)
    routed: set[int] = field(default_factory=set)
    steps: int = 0
    kct_reported_pct: int | None = None

    @classmethod
    def from_net_ids(cls, net_ids: list[int]) -> MockRouterState:
        ids = sorted({int(n) for n in net_ids if int(n) != 0})
        return cls(net_ids=ids, routed=set(), steps=0)

    @property
    def nets_total(self) -> int:
        return max(1, len(self.net_ids))

    @property
    def nets_routed(self) -> int:
        return len(self.routed & set(self.net_ids))

    @property
    def unrouted_count(self) -> int:
        return self.nets_total - self.nets_routed

    @property
    def routed_percent(self) -> int:
        net_pct = int(round(100.0 * self.nets_routed / self.nets_total))
        if self.kct_reported_pct is None:
            return net_pct
        # Prefer real KCT % when higher; never hide net-level progress.
        return max(int(self.kct_reported_pct), net_pct)

    def apply_kct_full_result(self, net_id: int, pct: int, *, success: bool) -> None:
        """Sync manager state after a full-board kct call (proxy)."""
        self.kct_reported_pct = int(pct)
        if not success:
            return
        nid = int(net_id)
        if int(pct) >= 100:
            self.routed = set(self.net_ids)
            return
        # Partial full-board result: still credit the requested net so the
        # manager sees per-step progress (proxy until true route_net exists).
        if nid in self.net_ids:
            self.routed.add(nid)

    def apply_kct_net_result(self, net_id: int, *, success: bool) -> None:
        """Sync after a true per-net kct call."""
        if success and int(net_id) in self.net_ids:
            self.routed.add(int(net_id))
        # Board-level % from net slots (authoritative for manager progress).
        self.kct_reported_pct = int(
            round(100.0 * self.nets_routed / self.nets_total)
        )


def strategy_index(name: str) -> int:
    try:
        return STRATEGIES.index(name)
    except ValueError as exc:
        raise ValueError(f"unknown strategy {name!r}; valid={STRATEGIES}") from exc


def strategy_from_index(idx: int) -> str:
    if idx < 0 or idx >= len(STRATEGIES):
        raise ValueError(f"strategy index {idx} out of range 0..{len(STRATEGIES)-1}")
    return STRATEGIES[idx]


def parse_net_id_name_map(pcb_bytes: bytes) -> dict[int, str]:
    """Map net id → name from board-level ``(net N \"name\")`` decls."""
    text = pcb_bytes.decode("utf-8", errors="replace")
    out: dict[int, str] = {}
    for m in _NET_DECL_RE.finditer(text):
        nid = int(m.group(1))
        if nid == 0:
            continue
        out[nid] = m.group(2)
    return out


def resolve_net_name(pcb_bytes: bytes, net_id: int) -> str:
    """Resolve KiCad net name for ``net_id`` or raise ValueError."""
    names = parse_net_id_name_map(pcb_bytes)
    nid = int(net_id)
    if nid not in names:
        raise ValueError(
            f"net_id {nid} not found in board net table; known={sorted(names)}"
        )
    name = names[nid]
    if not name:
        raise ValueError(f"net_id {nid} has empty name")
    return name


def pad_count_by_net_id(pcb_bytes: bytes) -> dict[int, int]:
    """Count pad hits per net id (simplified S-expr scan).

    KiCad pads use ``(net N \"name\")`` (name present), not bare ``(net N)``.
    """
    text = pcb_bytes.decode("utf-8", errors="replace")
    hits: dict[int, int] = {}
    # ``(pad "1" …`` — avoid matching ``(pad_to_mask_clearance …)``
    for m in re.finditer(r'\(pad\s+"', text):
        window = text[m.start() : m.start() + 800]
        nm = re.search(r"\(net\s+(\d+)\s+", window)
        if not nm:
            continue
        nid = int(nm.group(1))
        if nid == 0:
            continue
        hits[nid] = hits.get(nid, 0) + 1
    return hits


def multi_pad_net_ids(pcb_bytes: bytes, *, min_pads: int = 2) -> list[int]:
    """Net ids with ≥ ``min_pads`` pads (routable for manager kct_net).

    Single-pad nets (e.g. ``Net-(U1-5)``) are skipped by kct as unroutable.
    """
    names = parse_net_id_name_map(pcb_bytes)
    counts = pad_count_by_net_id(pcb_bytes)
    out = [
        nid
        for nid in sorted(names)
        if counts.get(nid, 0) >= int(min_pads)
    ]
    return out


def net_id_has_copper(pcb_bytes: bytes, net_id: int) -> bool:
    """True if segment/via **or filled zone** copper exists for ``net_id``.

    Power nets (GND/VCC) are often pour-only: no ``(segment)`` but a
    ``(zone … (net N) … filled_polygon …)``. Manager reward must credit those.
    """
    text = pcb_bytes.decode("utf-8", errors="replace")
    nid = int(net_id)
    for m in re.finditer(r"\((?:segment|via)\b", text):
        window = text[m.start() : m.start() + 800]
        nm = re.search(r"\(net\s+(\d+)\)", window)
        if nm and int(nm.group(1)) == nid:
            return True
    # Zones: net id near zone head + filled copper body
    for m in re.finditer(r"\(zone\b", text):
        window = text[m.start() : m.start() + 4000]
        nm = re.search(r"\(net\s+(\d+)\)", window)
        if not nm or int(nm.group(1)) != nid:
            continue
        if "filled_polygon" in window or "fill_segments" in window:
            return True
    return False


def strategy_uses_vcc_traces(strategy: str) -> bool:
    """Map Cirqix strategy → route_kct vcc_as_traces policy."""
    if strategy in ("vcc_planes", "power"):
        return False
    return True


def mock_route_net(
    pcb_bytes: bytes,
    net_id: int,
    strategy: str,
    *,
    state: MockRouterState,
    preferred_layer: str | None = None,
    ripup: bool = False,
) -> tuple[bytes, RouteNetMetrics]:
    """Deterministic incremental router for tests.

    Marks ``net_id`` as routed if it belongs to ``state.net_ids``.
    Does not parse PCB geometry; returns input bytes unchanged.
    """
    del preferred_layer  # reserved for future mock behaviour
    _ = strategy_index(strategy)  # validate
    state.steps += 1
    nid = int(net_id)
    success = False
    note = ""

    if ripup and nid in state.routed:
        state.routed.discard(nid)
        note = "ripup"
        success = True
    elif nid in state.net_ids:
        state.routed.add(nid)
        success = True
        note = "mock_routed"
    else:
        note = "unknown_net"

    metrics = RouteNetMetrics(
        routed_percent=state.routed_percent,
        nets_total=state.nets_total,
        nets_routed=state.nets_routed,
        unrouted_count=state.unrouted_count,
        last_net_id=nid,
        strategy=strategy,
        success=success,
        note=note,
        vias_delta=0 if strategy == "low_vias" else 1,
        length_mm_delta=0.5 if strategy == "shortest" else 1.0,
    )
    return pcb_bytes, metrics


def route_net(
    pcb_bytes: bytes,
    net_id: int,
    strategy: str,
    *,
    backend: BackendName = "mock",
    state: MockRouterState | None = None,
    preferred_layer: str | None = None,
    ripup: bool = False,
    timeout_s: int = 120,
) -> tuple[bytes, RouteNetMetrics]:
    """Public entry: mock, per-net kct, or full-board kct proxy.

    Parameters
    ----------
    backend:
        ``mock`` — deterministic TDD backend (requires ``state``).
        ``kct_net`` — ``kct route --nets <name>`` (true per-net geometry).
        ``kct_full`` — full-board ``route_kct`` (lab proxy; not incremental).
    """
    if backend == "mock":
        if state is None:
            raise ValueError("mock backend requires MockRouterState")
        return mock_route_net(
            pcb_bytes,
            net_id,
            strategy,
            state=state,
            preferred_layer=preferred_layer,
            ripup=ripup,
        )

    if backend == "kct_net":
        return _route_net_kct_net(
            pcb_bytes,
            net_id,
            strategy,
            state=state,
            timeout_s=timeout_s,
            ripup=ripup,
        )

    if backend == "kct_full":
        from tools.kct_route import route_kct

        if state is None:
            raise ValueError(
                "kct_full backend requires MockRouterState so manager obs/reward progress"
            )

        vcc_traces = strategy_uses_vcc_traces(strategy)
        # ripup ignored on full-board proxy (not per-net geometry)
        routed, pct, analysis = route_kct(
            pcb_bytes, timeout_s=timeout_s, vcc_as_traces=vcc_traces
        )
        success = int(pct) > 0
        state.steps += 1
        state.apply_kct_full_result(int(net_id), int(pct), success=success)

        note = "kct_full_proxy_not_per_net"
        if analysis:
            note = f"{note}; {analysis[:80]}"
        metrics = RouteNetMetrics(
            routed_percent=state.routed_percent,
            nets_total=state.nets_total,
            nets_routed=state.nets_routed,
            unrouted_count=state.unrouted_count,
            last_net_id=int(net_id),
            strategy=strategy,
            success=success,
            note=note,
        )
        return routed, metrics

    raise ValueError(f"unknown backend {backend!r}")


def _route_net_kct_net(
    pcb_bytes: bytes,
    net_id: int,
    strategy: str,
    *,
    state: MockRouterState | None,
    timeout_s: int,
    ripup: bool,
) -> tuple[bytes, RouteNetMetrics]:
    """True per-net geometry via kicad-tools ``route_kct_net``."""
    from tools.kct_route import route_kct_net

    if state is None:
        raise ValueError(
            "kct_net backend requires MockRouterState so manager obs/reward progress"
        )

    _ = strategy_index(strategy)
    nid = int(net_id)
    net_name = resolve_net_name(pcb_bytes, nid)
    vcc_traces = strategy_uses_vcc_traces(strategy)

    # Best-effort ripup: re-route without deleting copper (kct --nets preserves
    # other nets; full ripup of one net is not exposed as a separate kct API).
    del ripup

    had_copper_before = net_id_has_copper(pcb_bytes, nid)
    routed, _kct_pct, analysis = route_kct_net(
        pcb_bytes,
        net_name,
        timeout_s=timeout_s,
        vcc_as_traces=vcc_traces,
    )
    has_copper = net_id_has_copper(routed, nid)
    # Success = copper present after call (new or preserved on re-route).
    success = has_copper
    state.steps += 1
    state.apply_kct_net_result(nid, success=success)

    note = f"kct_net:{net_name}"
    if had_copper_before and has_copper:
        note = f"{note}; already_or_rerouted"
    if analysis:
        note = f"{note}; {analysis[:80]}"

    metrics = RouteNetMetrics(
        routed_percent=state.routed_percent,
        nets_total=state.nets_total,
        nets_routed=state.nets_routed,
        unrouted_count=state.unrouted_count,
        last_net_id=nid,
        strategy=strategy,
        success=success,
        note=note,
        vias_delta=0 if strategy == "low_vias" else 1,
        length_mm_delta=0.5 if strategy == "shortest" else 1.0,
    )
    return routed, metrics


def estimate_routed_percent_from_pcb(pcb_bytes: bytes) -> int:
    """Estimate routing completion from S-expr copper (segments/vias).

    Multi-pad nets: net id appears on ≥2 pads. A net counts as routed if it
    appears on at least one ``(segment …)`` or ``(via …)`` copper item.
    Returns 0–100. Not a substitute for official unconnected_items DRC.
    """
    text = pcb_bytes.decode("utf-8", errors="replace")
    # Net declarations at board level: (net N "name")
    declared = {int(n) for n in re.findall(r'\(net\s+(\d+)\s+"', text)}
    declared.discard(0)

    # Pad net refs — KiCad: (net N "name") inside pad blocks
    pad_net_hits = pad_count_by_net_id(pcb_bytes)

    multi_pad = {n for n, c in pad_net_hits.items() if c >= 2}
    if not multi_pad and declared:
        multi_pad = set(declared)
    if not multi_pad:
        # No nets to route → treat as complete
        return 100

    copper_nets: set[int] = set()
    for m in re.finditer(r"\((?:segment|via)\b", text):
        window = text[m.start() : m.start() + 800]
        nm = re.search(r"\(net\s+(\d+)\)", window)
        if nm:
            nid = int(nm.group(1))
            if nid != 0:
                copper_nets.add(nid)

    routed = multi_pad & copper_nets
    return int(round(100.0 * len(routed) / len(multi_pad)))
