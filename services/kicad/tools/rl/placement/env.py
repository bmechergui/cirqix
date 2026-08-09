"""Gymnasium PlacementEnv — one action moves one non-anchored component.

kicad-tools ``PCB`` only (no pcbnew).

Reward = Δ FOM + strong penalty when PlacementAnalyzer ERROR count rises
(real overlap / pad clearance — not the optional FOM hard gate alone).

Observation slots and action component indices share the same ordering:
``movable_references()`` (sorted non-anchored refs).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import numpy as np
from kicad_tools.schema.pcb import PCB

from tools.rl.placement.conflicts import count_error_conflicts
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
except ImportError:  # pragma: no cover
    gym = None  # type: ignore[assignment]
    spaces = None  # type: ignore[assignment]
    _HAS_GYM = False

_STEP_MM: tuple[float, ...] = (-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0)
_N_STEPS = len(_STEP_MM)

# Per new ERROR conflict introduced by a move
_ERROR_PENALTY = 1.0
_INVALID_ACTION_PENALTY = 0.01


def _base_env():
    if _HAS_GYM:
        return gym.Env
    return object


class PlacementEnv(_base_env()):  # type: ignore[misc,valid-type]
    """Move one non-anchored footprint per step.

    Action (MultiDiscrete): ``[component_slot, dx_idx, dy_idx]`` where
    ``component_slot`` indexes ``movable_references`` (same as observation slots).
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        pcb_path: str | Path | None = None,
        *,
        pcb_paths: Sequence[str | Path] | None = None,
        pcb: PCB | None = None,
        board_width_mm: float | None = None,
        board_height_mm: float | None = None,
        extra_anchors: Sequence[str] | None = None,
        max_steps: int = 64,
        seed: int | None = None,
        check_conflicts: bool = True,
    ) -> None:
        paths: list[Path] = []
        if pcb_paths:
            paths = [Path(p) for p in pcb_paths]
        elif pcb_path is not None:
            paths = [Path(pcb_path)]
        if not paths and pcb is None:
            raise ValueError("PlacementEnv requires pcb_path, pcb_paths, or pcb")
        for p in paths:
            if not p.is_file():
                raise FileNotFoundError(f"PCB fixture not found: {p}")
        self._pcb_paths = paths
        self._pcb_path: Path | None = paths[0] if paths else None
        self._template: PCB | None = pcb
        self._board_w = board_width_mm
        self._board_h = board_height_mm
        self._extra_anchors = list(extra_anchors or [])
        self._max_steps = max_steps
        self._check_conflicts = check_conflicts
        self._step_count = 0
        self._pcb: PCB | None = None
        self._prev_score = 0.0
        self._prev_errors = 0
        self._np_random = np.random.default_rng(seed)
        self._active_board_id: str | None = None

        if _HAS_GYM:
            self.observation_space = spaces.Box(
                low=-10.0, high=10.0, shape=(OBS_DIM,), dtype=np.float32
            )
            self.action_space = spaces.MultiDiscrete(
                [MAX_COMPONENTS, _N_STEPS, _N_STEPS]
            )

    def _pick_path(self) -> Path | None:
        if not self._pcb_paths:
            return None
        if len(self._pcb_paths) == 1:
            return self._pcb_paths[0]
        idx = int(self._np_random.integers(0, len(self._pcb_paths)))
        return self._pcb_paths[idx]

    def _load_template(self) -> PCB:
        path = self._pick_path()
        if path is not None:
            self._pcb_path = path
            self._active_board_id = path.stem
            return PCB.load(str(path))
        assert self._template is not None
        self._active_board_id = "in_memory"
        return self._clone_pcb(self._template)

    @staticmethod
    def _clone_pcb(pcb: PCB) -> PCB:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "clone.kicad_pcb"
            pcb.save(str(p))
            return PCB.load(str(p))

    def _score_and_errors(self, pcb: PCB) -> tuple[float, int]:
        score = fom_score(
            pcb,
            pcb_path=str(self._pcb_path) if self._pcb_path else None,
        )
        errors = 0
        if self._check_conflicts:
            errors = count_error_conflicts(pcb)
        return score, errors

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
        self._prev_score, self._prev_errors = self._score_and_errors(self._pcb)
        obs = build_observation(
            self._pcb,
            extra_anchors=self._extra_anchors,
            board_width_mm=self._board_w,
            board_height_mm=self._board_h,
        )
        movables = movable_references(self._pcb, extra_anchors=self._extra_anchors)
        info = {
            "fom_score": self._prev_score,
            "error_conflicts": self._prev_errors,
            "movable": movables,
            "n_obs_slots": min(len(movables), MAX_COMPONENTS),
            "board_id": self._active_board_id,
            "pcb_path": str(self._pcb_path) if self._pcb_path else None,
            "n_dataset_boards": len(self._pcb_paths),
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

        # Slot must match observation: only first MAX_COMPONENTS movables exist in obs
        if (
            0 <= slot < len(movable)
            and slot < MAX_COMPONENTS
            and (dx != 0.0 or dy != 0.0)
        ):
            ref = movable[slot]
            for fp in self._pcb.footprints:
                if fp.reference == ref:
                    if is_anchor_ref(ref, self._extra_anchors):
                        break
                    x, y = float(fp.position[0]), float(fp.position[1])
                    nx, ny = x + dx, y + dy
                    if self._board_w and self._board_h:
                        margin = 1.0
                        nx = min(max(nx, margin), self._board_w - margin)
                        ny = min(max(ny, margin), self._board_h - margin)
                    fp.position = (nx, ny)
                    applied = True
                    break
        else:
            reward -= _INVALID_ACTION_PENALTY

        new_score, new_errors = self._score_and_errors(self._pcb)
        if applied:
            reward += new_score - self._prev_score
            # Real collision signal: PlacementAnalyzer ERROR delta
            if new_errors > self._prev_errors:
                reward -= _ERROR_PENALTY * float(new_errors - self._prev_errors)
            # Keep FOM-collapse penalty as secondary hard signal
            if new_score <= 0.0 and self._prev_score > 0.0:
                reward -= _ERROR_PENALTY

        self._prev_score = new_score
        self._prev_errors = new_errors
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
            "error_conflicts": new_errors,
            "applied": applied,
            "step": self._step_count,
        }
        return obs, float(reward), terminated, truncated, info

    @property
    def pcb(self) -> PCB | None:
        return self._pcb
