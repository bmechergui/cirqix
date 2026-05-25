"""Pure-Python PCB placement planner.

Pure function: no pcbnew, no filesystem, no network. Both the pcbnew backend
(``tools.placement.auto_place``) and the TypeScript fallback in
``packages/agents/src/engines/placement-fallback.ts`` consume the same algorithm
so positions stay consistent across the agentic pipeline.

Algorithm
---------
1. Classify each ref by designator: ``U*``/``IC*`` → IC, ``R*`` → RES,
   ``C*`` → CAP, ``D*``/``LED*`` → DIODE, ``J*``/``P*`` → CONN, else MISC.
2. Place ICs around the board centroid. With N>1 ICs, spread them on a
   horizontal line through the center using ``min(usable_w/(N+1), IC_SPACING_MM)``.
3. Cluster passives (RES, CAP, DIODE) around the nearest IC on a circle of
   radius ``CLUSTER_RADIUS_BASE_MM + CLUSTER_RADIUS_STEP_MM * cluster_count``.
4. Place CONN on the left/right edges (alternating by index), distributed
   vertically.
5. Place MISC on the remaining row.
6. Clamp every position into ``[MARGIN_MM, board - MARGIN_MM]``.
"""
from __future__ import annotations

import math
import re
from typing import Literal

Kind = Literal["IC", "RES", "CAP", "DIODE", "CONN", "MISC"]

# ----------------------------------------------------------------------------
# Tunable constants — exposed for parity tests
# ----------------------------------------------------------------------------

MARGIN_MM: float = 3.0
IC_SPACING_MM: float = 15.0
CLUSTER_RADIUS_BASE_MM: float = 8.0
CLUSTER_RADIUS_STEP_MM: float = 1.5
EDGE_OFFSET_MM: float = 2.0

_REF_RE = re.compile(r"^([A-Za-z]+)")


# ----------------------------------------------------------------------------
# Kind classification
# ----------------------------------------------------------------------------

def classify_kind(ref: str) -> Kind:
    """Return the placement kind for a KiCad reference designator."""
    match = _REF_RE.match(ref)
    if not match:
        return "MISC"
    prefix = match.group(1).upper()
    # Multi-letter prefixes first (longest match wins)
    if prefix.startswith("LED"):
        return "DIODE"
    if prefix.startswith("IC"):
        return "IC"
    if prefix.startswith("TP"):
        return "MISC"
    # Single-letter prefixes
    head = prefix[0]
    if head == "U":
        return "IC"
    if head == "R":
        return "RES"
    if head == "C":
        return "CAP"
    if head == "D":
        return "DIODE"
    if head in ("J", "P"):
        return "CONN"
    return "MISC"


# ----------------------------------------------------------------------------
# Layout computation
# ----------------------------------------------------------------------------

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _place_ics(
    ic_refs: list[str], board_w: float, board_h: float
) -> dict[str, tuple[float, float, float]]:
    """Place ICs centered horizontally on the mid line."""
    out: dict[str, tuple[float, float, float]] = {}
    if not ic_refs:
        return out
    cy = board_h / 2.0
    if len(ic_refs) == 1:
        out[ic_refs[0]] = (board_w / 2.0, cy, 0.0)
        return out
    usable_w = board_w - 2 * MARGIN_MM
    natural_step = usable_w / (len(ic_refs) + 1)
    step = min(natural_step, IC_SPACING_MM)
    total = step * (len(ic_refs) - 1)
    x0 = (board_w - total) / 2.0
    for i, ref in enumerate(ic_refs):
        x = _clamp(x0 + i * step, MARGIN_MM, board_w - MARGIN_MM)
        out[ref] = (x, cy, 0.0)
    return out


def _nearest_ic_for(
    idx_in_cluster_pool: int,
    cluster_count: int,
    ic_positions: list[tuple[float, float]],
    board_w: float,
    board_h: float,
) -> tuple[float, float]:
    """Pick an anchor for a non-IC component.

    With multiple ICs, evenly split the passives so each cluster gets a roughly
    equal share. With no IC, anchor on the board centroid.
    """
    if not ic_positions:
        return (board_w / 2.0, board_h / 2.0)
    # Distribute passives across ICs by index
    bucket = (idx_in_cluster_pool * len(ic_positions)) // max(1, cluster_count)
    bucket = min(bucket, len(ic_positions) - 1)
    return ic_positions[bucket]


def _place_cluster(
    refs_in_cluster: list[str],
    ic_positions: list[tuple[float, float]],
    board_w: float,
    board_h: float,
) -> dict[str, tuple[float, float, float]]:
    """Place passives (RES, CAP, DIODE) on circles around their anchor IC."""
    out: dict[str, tuple[float, float, float]] = {}
    n = len(refs_in_cluster)
    if n == 0:
        return out
    # Bucket refs per IC so we can compute per-cluster radius/angle
    buckets: dict[int, list[str]] = {}
    for i, ref in enumerate(refs_in_cluster):
        idx = (i * max(1, len(ic_positions))) // max(1, n)
        idx = min(idx, max(0, len(ic_positions) - 1))
        buckets.setdefault(idx, []).append(ref)
    for ic_idx, refs in buckets.items():
        if ic_positions:
            ax, ay = ic_positions[ic_idx]
        else:
            ax, ay = board_w / 2.0, board_h / 2.0
        signal_refs = [r for r in refs if classify_kind(r) != "CAP"]
        cap_refs = [r for r in refs if classify_kind(r) == "CAP"]
        signal_radius = CLUSTER_RADIUS_BASE_MM + CLUSTER_RADIUS_STEP_MM * len(signal_refs)
        cap_radius = max(4.0, CLUSTER_RADIUS_BASE_MM / 2)
        for group_refs, radius, rotation in (
            (signal_refs, signal_radius, 0.0),
            (cap_refs, cap_radius, 90.0),
        ):
            for i, ref in enumerate(group_refs):
                # Start at 45° (diagonal) so passives spread nicely.
                # Starting at 90° or 0° creates 1D columns for n=2.
                angle = math.pi / 4 + 2 * math.pi * i / max(1, len(group_refs))
                x = _clamp(ax + radius * math.cos(angle), MARGIN_MM, board_w - MARGIN_MM)
                y = _clamp(ay + radius * math.sin(angle), MARGIN_MM, board_h - MARGIN_MM)
                out[ref] = (x, y, rotation)
    return out


def _place_connectors(
    conn_refs: list[str], board_w: float, board_h: float
) -> dict[str, tuple[float, float, float]]:
    """Connectors alternate left/right edges; y is uniformly distributed."""
    out: dict[str, tuple[float, float, float]] = {}
    if not conn_refs:
        return out
    left = conn_refs[::2]
    right = conn_refs[1::2]
    for refs, x in (
        (left, MARGIN_MM + EDGE_OFFSET_MM),
        (right, board_w - MARGIN_MM - EDGE_OFFSET_MM),
    ):
        if not refs:
            continue
        usable_h = board_h - 2 * MARGIN_MM
        step = usable_h / (len(refs) + 1)
        for i, ref in enumerate(refs):
            y = _clamp(MARGIN_MM + step * (i + 1), MARGIN_MM, board_h - MARGIN_MM)
            out[ref] = (_clamp(x, MARGIN_MM, board_w - MARGIN_MM), y, 90.0)
    return out


def _place_misc(
    misc_refs: list[str], board_w: float, board_h: float
) -> dict[str, tuple[float, float, float]]:
    """Bottom row, evenly distributed."""
    out: dict[str, tuple[float, float, float]] = {}
    if not misc_refs:
        return out
    y = board_h - MARGIN_MM - EDGE_OFFSET_MM
    usable_w = board_w - 2 * MARGIN_MM
    step = usable_w / (len(misc_refs) + 1)
    for i, ref in enumerate(misc_refs):
        x = _clamp(MARGIN_MM + step * (i + 1), MARGIN_MM, board_w - MARGIN_MM)
        out[ref] = (x, _clamp(y, MARGIN_MM, board_h - MARGIN_MM), 0.0)
    return out


def compute_layout(
    refs: list[str],
    board_w_mm: float,
    board_h_mm: float,
) -> dict[str, tuple[float, float, float]]:
    """Return ``{ref: (x_mm, y_mm, rotation_deg)}`` for every ref.

    Pure function — does not mutate ``refs``. Margin is currently fixed at
    ``MARGIN_MM`` to keep parity with the TypeScript fallback.
    """
    if not refs:
        return {}

    # Classify (preserves input order within each bucket)
    buckets: dict[Kind, list[str]] = {
        "IC": [], "RES": [], "CAP": [], "DIODE": [], "CONN": [], "MISC": [],
    }
    for ref in refs:
        buckets[classify_kind(ref)].append(ref)

    out: dict[str, tuple[float, float, float]] = {}
    out.update(_place_ics(buckets["IC"], board_w_mm, board_h_mm))

    ic_positions: list[tuple[float, float]] = [
        (out[r][0], out[r][1]) for r in buckets["IC"]
    ]
    passives = buckets["RES"] + buckets["CAP"] + buckets["DIODE"]
    out.update(_place_cluster(passives, ic_positions, board_w_mm, board_h_mm))

    out.update(_place_connectors(buckets["CONN"], board_w_mm, board_h_mm))
    out.update(_place_misc(buckets["MISC"], board_w_mm, board_h_mm))

    # Center the entire bounding box of components
    if out:
        min_x = min(pos[0] for pos in out.values())
        max_x = max(pos[0] for pos in out.values())
        min_y = min(pos[1] for pos in out.values())
        max_y = max(pos[1] for pos in out.values())
        
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
        
        target_cx = board_w_mm / 2.0
        target_cy = board_h_mm / 2.0
        
        dx = target_cx - center_x
        dy = target_cy - center_y
        
        for ref, (x, y, rot) in out.items():
            new_x = _clamp(x + dx, MARGIN_MM, board_w_mm - MARGIN_MM)
            new_y = _clamp(y + dy, MARGIN_MM, board_h_mm - MARGIN_MM)
            out[ref] = (new_x, new_y, rot)

    return out
