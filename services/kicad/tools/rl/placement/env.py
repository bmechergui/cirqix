"""Gymnasium PlacementEnv — one action moves one non-anchored component.

kicad-tools ``PCB`` only (no pcbnew). Reward = ``fom_score`` (compute_fom).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import numpy as np
from kicad_tools.schema.pcb import PCB

from tools.rl.placement.observation import (
    MAX_COMPONENTS,
    OBS_DIM,
    build_observation,
    is_anchor_ref,
    movable_references,
)
from tools.rl.placement.reward import fom_score

try:
    import gymnasium as gym
    from gymnasium import spaces

    _HAS_GYM = True
except ImportError:  # pragma: no cover — optional until deps installed
    gym = None  # type: ignore[assignment]
    spaces = None  # type: ignore[assignment]
    _HAS_GYM = False

# Discretised step sizes (mm) for dx / dy indices 0..N-1 → symmetric around 0
_STEP_MM: tuple[float, ...] = (-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0)
_N_STEPS = len(_STEP_MM)

# Strong penalty when hard FOM gate fails after a move (proxy for ERROR-ish)
_COLLISION_PENALTY = 1.0


def _base_env():
    if _HAS_GYM:
        return gym.Env
    return object


class PlacementEnv(_base_env()):  # type: ignore[misc,valid-type]
    """Move one non-anchored footprint per step; reward = Δ FOM score.

    Action (MultiDiscrete):
      [component_slot, dx_idx, dy_idx]
    where ``component_slot`` indexes into the sorted movable-ref list
    (padded to MAX_COMPONENTS; invalid slots → no-op + small penalty).
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        pcb_path: str | Path | None = None,
        *,
        pcb: PCB | None = None,
        board_width_mm: float | None = None,
        board_height_mm: float | None = None,
        extra_anchors: Sequence[str] | None = None,
        max_steps: int = 64,
        seed: int | None = None,
    ) -> None:
        if pcb is None and pcb_path is None:
            raise ValueError("PlacementEnv requires pcb_path or pcb")
        if pcb is not None and pcb_path is not None:
            # Prefer explicit PCB object; path kept for re-load on reset
            pass
        self._pcb_path = Path(pcb_path) if pcb_path is not None else None
        self._template: PCB | None = pcb
        self._board_w = board_width_mm
        self._board_h = board_height_mm
        self._extra_anchors = list(extra_anchors or [])
        self._max_steps = max_steps
        self._step_count = 0
        self._pcb: PCB | None = None
        self._prev_score = 0.0
        self._np_random = np.random.default_rng(seed)

        if _HAS_GYM:
            self.observation_space = spaces.Box(
                low=-10.0, high=10.0, shape=(OBS_DIM,), dtype=np.float32
            )
            self.action_space = spaces.MultiDiscrete(
                [MAX_COMPONENTS, _N_STEPS, _N_STEPS]
            )

    def _load_template(self) -> PCB:
        if self._pcb_path is not None:
            return PCB.load(str(self._pcb_path))
        assert self._template is not None
        # Deep copy via save/load would be heavy; re-parse path preferred.
        # For in-memory template: save to bytes is not always available —
        # clone by re-loading if we stored path; else shallow footprint pos copy.
        return self._clone_pcb(self._template)

    @staticmethod
    def _clone_pcb(pcb: PCB) -> PCB:
        """Clone PCB positions by round-trip through a temp path if possible."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "clone.kicad_pcb"
            pcb.save(str(p))
            return PCB.load(str(p))

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ):
        if seed is not None:
            self._np_random = np.random.default_rng(seed)
        self._pcb = self._load_template()
        self._step_count = 0
        self._prev_score = fom_score(
            self._pcb,
            pcb_path=str(self._pcb_path) if self._pcb_path else None,
        )
        obs = build_observation(
            self._pcb,
            extra_anchors=self._extra_anchors,
            board_width_mm=self._board_w,
            board_height_mm=self._board_h,
        )
        info = {
            "fom_score": self._prev_score,
            "movable": movable_references(self._pcb, extra_anchors=self._extra_anchors),
        }
        return obs, info

    def step(self, action):
        assert self._pcb is not None, "call reset() first"
        slot, dx_i, dy_i = int(action[0]), int(action[1]), int(action[2])
        dx = _STEP_MM[max(0, min(dx_i, _N_STEPS - 1))]
        dy = _STEP_MM[max(0, min(dy_i, _N_STEPS - 1))]

        movable = movable_references(self._pcb, extra_anchors=self._extra_anchors)
        reward = 0.0
        applied = False

        if 0 <= slot < len(movable) and (dx != 0.0 or dy != 0.0):
            ref = movable[slot]
            for fp in self._pcb.footprints:
                if fp.reference == ref:
                    if is_anchor_ref(ref, self._extra_anchors):
                        break
                    x, y = float(fp.position[0]), float(fp.position[1])
                    nx, ny = x + dx, y + dy
                    # Soft board clamp if size known
                    if self._board_w and self._board_h:
                        margin = 1.0
                        nx = min(max(nx, margin), self._board_w - margin)
                        ny = min(max(ny, margin), self._board_h - margin)
                    fp.position = (nx, ny)
                    applied = True
                    break
        else:
            reward -= 0.01  # invalid / no-op

        new_score = fom_score(
            self._pcb,
            pcb_path=str(self._pcb_path) if self._pcb_path else None,
        )
        if applied:
            reward += new_score - self._prev_score
            if new_score <= 0.0 and self._prev_score > 0.0:
                reward -= _COLLISION_PENALTY
        self._prev_score = new_score
        self._step_count += 1

        terminated = False
        truncated = self._step_count >= self._max_steps
        obs = build_observation(
            self._pcb,
            extra_anchors=self._extra_anchors,
            board_width_mm=self._board_w,
            board_height_mm=self._board_h,
        )
        info = {
            "fom_score": new_score,
            "applied": applied,
            "step": self._step_count,
        }
        return obs, float(reward), terminated, truncated, info

    @property
    def pcb(self) -> PCB | None:
        return self._pcb
