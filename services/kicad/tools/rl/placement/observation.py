"""PCB → fixed-shape observation tensor (kicad-tools ``PCB`` only)."""

from __future__ import annotations

import re
from typing import Sequence

import numpy as np
from kicad_tools.schema.pcb import PCB

# Fixed layout — must stay stable across train / inference checkpoints.
MAX_COMPONENTS: int = 64
# per footprint: x_norm, y_norm, n_pads_norm, present, anchored
_FEATS_PER_FP: int = 5
# trailing globals: board_w_mm, board_h_mm, n_components, n_movable
_GLOBAL_FEATS: int = 4

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
    # Fallback: footprint extent + margin
    fps = list(pcb.footprints)
    if not fps:
        return 100.0, 80.0
    xs = [float(fp.position[0]) for fp in fps]
    ys = [float(fp.position[1]) for fp in fps]
    return max(xs) - min(xs) + 20.0, max(ys) - min(ys) + 20.0


def build_observation(
    pcb: PCB,
    *,
    extra_anchors: Sequence[str] | None = None,
    board_width_mm: float | None = None,
    board_height_mm: float | None = None,
) -> np.ndarray:
    """Return a float32 vector of shape ``(OBS_DIM,)``.

    Deterministic for a given PCB + anchor set (stable sort by reference).
    """
    bw, bh = _board_size_mm(pcb)
    if board_width_mm is not None and board_width_mm > 0:
        bw = float(board_width_mm)
    if board_height_mm is not None and board_height_mm > 0:
        bh = float(board_height_mm)
    bw = max(bw, 1.0)
    bh = max(bh, 1.0)

    fps = sorted(pcb.footprints, key=lambda f: f.reference or "")
    obs = np.zeros(OBS_DIM, dtype=np.float32)
    n_movable = 0

    for i, fp in enumerate(fps[:MAX_COMPONENTS]):
        base = i * _FEATS_PER_FP
        x, y = float(fp.position[0]), float(fp.position[1])
        n_pads = len(getattr(fp, "pads", None) or [])
        anchored = 1.0 if is_anchor_ref(fp.reference or "", extra_anchors) else 0.0
        if anchored < 0.5:
            n_movable += 1
        obs[base + 0] = x / bw
        obs[base + 1] = y / bh
        obs[base + 2] = min(n_pads / 64.0, 1.0)
        obs[base + 3] = 1.0  # present
        obs[base + 4] = anchored

    g = MAX_COMPONENTS * _FEATS_PER_FP
    obs[g + 0] = bw / 200.0  # scale ~typical max board
    obs[g + 1] = bh / 200.0
    obs[g + 2] = min(len(fps) / float(MAX_COMPONENTS), 1.0)
    obs[g + 3] = min(n_movable / float(MAX_COMPONENTS), 1.0)
    return obs


def movable_references(
    pcb: PCB,
    *,
    extra_anchors: Sequence[str] | None = None,
) -> list[str]:
    """Sorted list of non-anchored footprint references (action targets)."""
    refs = []
    for fp in sorted(pcb.footprints, key=lambda f: f.reference or ""):
        ref = fp.reference or ""
        if not ref:
            continue
        if is_anchor_ref(ref, extra_anchors):
            continue
        refs.append(ref)
    return refs
