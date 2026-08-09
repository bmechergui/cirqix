"""PCB → fixed-shape observation tensor (kicad-tools ``PCB`` only).

Slots are aligned with **movable** components only (same order as actions).
Each slot carries geometry + a cheap net signature so two boards with the
same XY layout but different connectivity produce different observations.
"""

from __future__ import annotations

import re
from typing import Sequence

import numpy as np
from kicad_tools.schema.pcb import PCB

# Fixed layout — changing OBS_DIM invalidates old PPO checkpoints (expected).
MAX_COMPONENTS: int = 64
# per movable slot:
#   x_norm, y_norm, w_norm, h_norm, n_pads_norm, present, net_sig
_FEATS_PER_FP: int = 7
# trailing globals: board_w, board_h, n_movable, n_anchors, mean_anchor_x, mean_anchor_y
_GLOBAL_FEATS: int = 6

OBS_DIM: int = MAX_COMPONENTS * _FEATS_PER_FP + _GLOBAL_FEATS

_ANCHOR_RE = re.compile(r"^[JP]\d+", re.IGNORECASE)


def is_anchor_ref(reference: str, extra_anchors: Sequence[str] | None = None) -> bool:
    """Connectors J*/P* are fixed; optional extra refs from LLM strategy."""
    if _ANCHOR_RE.match(reference or ""):
        return True
    if extra_anchors and reference in extra_anchors:
        return True
    return False


def _board_size_mm(pcb: PCB) -> tuple[float, float]:
    """Best-effort board size from Edge.Cuts bbox or PCB metadata."""
    w = float(getattr(pcb, "width", 0) or 0)
    h = float(getattr(pcb, "height", 0) or 0)
    if w > 0 and h > 0:
        return w, h
    fps = list(pcb.footprints)
    if not fps:
        return 100.0, 80.0
    xs = [float(fp.position[0]) for fp in fps]
    ys = [float(fp.position[1]) for fp in fps]
    return max(xs) - min(xs) + 20.0, max(ys) - min(ys) + 20.0


def _pad_bbox_mm(fp) -> tuple[float, float]:
    """Axis-aligned pad extent (proxy for courtyard size) in mm."""
    pads = getattr(fp, "pads", None) or []
    if not pads:
        return 1.0, 1.0
    xs: list[float] = []
    ys: list[float] = []
    for pad in pads:
        at = getattr(pad, "position", None) or getattr(pad, "at", None)
        if at is None:
            continue
        if isinstance(at, (list, tuple)) and len(at) >= 2:
            xs.append(float(at[0]))
            ys.append(float(at[1]))
        size = getattr(pad, "size", None)
        if size is not None and isinstance(size, (list, tuple)) and len(size) >= 2:
            # expand by half-size around pad center
            if xs:
                xs[-1]  # keep center; width from size
            pass
    if not xs:
        return 1.0, 1.0
    # Include pad sizes when available
    half_w = 0.3
    half_h = 0.3
    for pad in pads:
        size = getattr(pad, "size", None)
        if size is not None and isinstance(size, (list, tuple)) and len(size) >= 2:
            half_w = max(half_w, float(size[0]) / 2.0)
            half_h = max(half_h, float(size[1]) / 2.0)
    w = (max(xs) - min(xs)) + 2.0 * half_w
    h = (max(ys) - min(ys)) + 2.0 * half_h
    return max(w, 0.5), max(h, 0.5)


def _net_signature(fp) -> float:
    """Stable [0, 1] fingerprint of pad nets (connectivity proxy)."""
    pads = getattr(fp, "pads", None) or []
    if not pads:
        return 0.0
    acc = 0
    for i, pad in enumerate(pads):
        net = getattr(pad, "net", None)
        if net is None:
            name = ""
        elif isinstance(net, (int, float)):
            name = str(int(net))
        else:
            name = str(getattr(net, "name", net) or "")
        for ch in name:
            acc = (acc * 33 + ord(ch)) & 0xFFFFFFFF
        acc = (acc + (i + 1) * 17) & 0xFFFFFFFF
    # map to (0, 1]
    return ((acc % 10_000) + 1) / 10_001.0


def movable_references(
    pcb: PCB,
    *,
    extra_anchors: Sequence[str] | None = None,
) -> list[str]:
    """Sorted list of non-anchored footprint references (action + obs slots)."""
    refs = []
    for fp in sorted(pcb.footprints, key=lambda f: f.reference or ""):
        ref = fp.reference or ""
        if not ref:
            continue
        if is_anchor_ref(ref, extra_anchors):
            continue
        refs.append(ref)
    return refs


def build_observation(
    pcb: PCB,
    *,
    extra_anchors: Sequence[str] | None = None,
    board_width_mm: float | None = None,
    board_height_mm: float | None = None,
) -> np.ndarray:
    """Return float32 vector ``(OBS_DIM,)`` — **one slot per movable**, sorted.

    Slot ``i`` matches action component index ``i`` (same ``movable_references``).
    Anchors are summarized only in the global tail (mean position), not as slots.
    """
    bw, bh = _board_size_mm(pcb)
    if board_width_mm is not None and board_width_mm > 0:
        bw = float(board_width_mm)
    if board_height_mm is not None and board_height_mm > 0:
        bh = float(board_height_mm)
    bw = max(bw, 1.0)
    bh = max(bh, 1.0)

    by_ref = {fp.reference: fp for fp in pcb.footprints if fp.reference}
    movables = movable_references(pcb, extra_anchors=extra_anchors)
    anchors = [
        fp
        for fp in pcb.footprints
        if fp.reference and is_anchor_ref(fp.reference, extra_anchors)
    ]

    obs = np.zeros(OBS_DIM, dtype=np.float32)

    for i, ref in enumerate(movables[:MAX_COMPONENTS]):
        fp = by_ref.get(ref)
        if fp is None:
            continue
        base = i * _FEATS_PER_FP
        x, y = float(fp.position[0]), float(fp.position[1])
        w_mm, h_mm = _pad_bbox_mm(fp)
        n_pads = len(getattr(fp, "pads", None) or [])
        obs[base + 0] = x / bw
        obs[base + 1] = y / bh
        obs[base + 2] = min(w_mm / bw, 1.0)
        obs[base + 3] = min(h_mm / bh, 1.0)
        obs[base + 4] = min(n_pads / 64.0, 1.0)
        obs[base + 5] = 1.0  # present
        obs[base + 6] = _net_signature(fp)

    g = MAX_COMPONENTS * _FEATS_PER_FP
    obs[g + 0] = bw / 200.0
    obs[g + 1] = bh / 200.0
    obs[g + 2] = min(len(movables) / float(MAX_COMPONENTS), 1.0)
    obs[g + 3] = min(len(anchors) / float(MAX_COMPONENTS), 1.0)
    if anchors:
        obs[g + 4] = float(np.mean([float(a.position[0]) for a in anchors])) / bw
        obs[g + 5] = float(np.mean([float(a.position[1]) for a in anchors])) / bh
    return obs
