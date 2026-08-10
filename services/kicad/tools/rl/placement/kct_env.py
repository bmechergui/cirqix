"""Gymnasium env whose steps call **kct placement** (not micro-moves).

Phase 1 of docs/rl — same idea as DreamerV3+FR (real EDA as env), with
**kct** as the placement backend.

Default backend = CMA-ES refine via ``tools.placement._refine_with_cmaes``
(prod Géomètre). Inject ``place_fn`` in tests to avoid slow subprocesses.

Action space (Discrete)::

    0 — CMA-ES refine, short budget
    1 — CMA-ES refine, longer budget
    2 — stop episode (no kct call)

If ``force_refine_if_errors`` is True (default), a stop while
``error_conflicts > 0`` is rewritten to action 0 (short CMA). Dense boards
must not "escape" with residual ERROR (Gate A).

Observation: same fixed vector as ``PlacementEnv`` (``OBS_DIM``).
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
from kicad_tools.schema.pcb import PCB

from tools.rl.placement.conflicts import count_error_conflicts
from tools.rl.placement.observation import (
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

# action → CMA-ES time budget (seconds); None = stop
_ACTION_BUDGET_S: dict[int, float | None] = {
    0: 5.0,
    1: 15.0,
    2: None,
}
N_PLACE_ACTIONS = 3

_ERROR_PENALTY = 1.0
_STEP_COST = 0.01


PlaceFn = Callable[[Path, int, list[str]], dict[str, Any]]
"""``place_fn(work_pcb, action, anchors) -> meta``.

Must update ``work_pcb`` on disk when a refine is applied.
Expected keys: ``applied`` (bool), optional ``refined``, ``elapsed_s``, ``error``.
"""


def _default_place_fn(work_pcb: Path, action: int, anchors: list[str]) -> dict[str, Any]:
    """Call prod CMA-ES refine (kct optimize-placement path)."""
    budget = _ACTION_BUDGET_S.get(int(action))
    if budget is None:
        return {"applied": False, "refined": False, "elapsed_s": 0.0, "action": action}

    from tools.placement import _refine_with_cmaes

    meta = _refine_with_cmaes(work_pcb, anchors, time_budget_s=float(budget))
    return {
        "applied": True,
        "refined": bool(meta.get("refined")),
        "elapsed_s": float(meta.get("elapsed_s") or 0.0),
        "action": action,
        "budget_s": budget,
    }


def _base_env():
    if _HAS_GYM:
        return gym.Env
    return object


class KctPlacementEnv(_base_env()):  # type: ignore[misc,valid-type]
    """One (or few) kct placement calls per episode on a working copy of the board."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        pcb_path: str | Path | None = None,
        *,
        pcb_paths: Sequence[str | Path] | None = None,
        place_fn: PlaceFn | None = None,
        max_steps: int = 2,
        seed: int | None = None,
        extra_anchors: Sequence[str] | None = None,
        board_width_mm: float | None = None,
        board_height_mm: float | None = None,
        work_dir: str | Path | None = None,
        force_refine_if_errors: bool = True,
    ) -> None:
        paths: list[Path] = []
        if pcb_paths:
            paths = [Path(p) for p in pcb_paths]
        elif pcb_path is not None:
            paths = [Path(pcb_path)]
        if not paths:
            raise ValueError("KctPlacementEnv requires pcb_path or pcb_paths")
        for p in paths:
            if not p.is_file():
                raise FileNotFoundError(f"PCB fixture not found: {p}")

        self._pcb_paths = paths
        self._place_fn: PlaceFn = place_fn or _default_place_fn
        self._max_steps = max(1, int(max_steps))
        self._extra_anchors = list(extra_anchors or [])
        self._board_w = board_width_mm
        self._board_h = board_height_mm
        self._force_refine_if_errors = bool(force_refine_if_errors)
        self._np = np.random.default_rng(seed)
        self._owned_tmp: tempfile.TemporaryDirectory[str] | None = None
        if work_dir is not None:
            self._work_root = Path(work_dir)
            self._work_root.mkdir(parents=True, exist_ok=True)
        else:
            self._owned_tmp = tempfile.TemporaryDirectory(prefix="rl_kct_place_")
            self._work_root = Path(self._owned_tmp.name)

        self._source_path: Path | None = None
        self._work_pcb: Path | None = None
        self._pcb: PCB | None = None
        self._step_count = 0
        self._prev_fom = 0.0
        self._prev_errors = 0
        self._active_board_id: str | None = None

        if _HAS_GYM:
            self.observation_space = spaces.Box(
                low=-10.0, high=10.0, shape=(OBS_DIM,), dtype=np.float32
            )
            self.action_space = spaces.Discrete(N_PLACE_ACTIONS)

    def close(self) -> None:
        if self._owned_tmp is not None:
            self._owned_tmp.cleanup()
            self._owned_tmp = None

    def _pick_source(self) -> Path:
        if len(self._pcb_paths) == 1:
            return self._pcb_paths[0]
        idx = int(self._np.integers(0, len(self._pcb_paths)))
        return self._pcb_paths[idx]

    def _anchors(self, pcb: PCB) -> list[str]:
        refs = [fp.reference for fp in pcb.footprints if fp.reference]
        return [r for r in refs if is_anchor_ref(r, self._extra_anchors)]

    def _metrics(self, pcb: PCB, path: Path) -> tuple[float, int]:
        fom = fom_score(pcb, pcb_path=str(path))
        errors = count_error_conflicts(pcb, pcb_path=path)
        return float(fom), int(errors)

    def _obs(self) -> np.ndarray:
        assert self._pcb is not None
        return build_observation(
            self._pcb,
            extra_anchors=self._extra_anchors,
            board_width_mm=self._board_w,
            board_height_mm=self._board_h,
        )

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ):
        if seed is not None:
            self._np = np.random.default_rng(seed)
        self._source_path = self._pick_source()
        self._active_board_id = self._source_path.stem
        self._work_pcb = self._work_root / f"{self._active_board_id}_work.kicad_pcb"
        shutil.copy2(self._source_path, self._work_pcb)
        self._pcb = PCB.load(str(self._work_pcb))
        self._step_count = 0
        self._prev_fom, self._prev_errors = self._metrics(self._pcb, self._work_pcb)
        info = {
            "env": "kct_placement",
            "fom_score": self._prev_fom,
            "error_conflicts": self._prev_errors,
            "board_id": self._active_board_id,
            "pcb_path": str(self._work_pcb),
            "source_path": str(self._source_path),
            "movable": movable_references(self._pcb, extra_anchors=self._extra_anchors),
            "n_dataset_boards": len(self._pcb_paths),
        }
        return self._obs(), info

    def step(self, action: int | np.ndarray):
        assert self._pcb is not None and self._work_pcb is not None
        action_i = int(action)
        if action_i < 0 or action_i >= N_PLACE_ACTIONS:
            action_i = N_PLACE_ACTIONS - 1  # treat invalid as stop

        forced_refine = False
        # Dense / dirty boards: never allow stop while ERROR remain
        if (
            self._force_refine_if_errors
            and _ACTION_BUDGET_S.get(action_i) is None
            and self._prev_errors > 0
        ):
            action_i = 0  # short CMA refine
            forced_refine = True

        reward = -_STEP_COST
        meta: dict[str, Any] = {
            "action": action_i,
            "forced_refine": forced_refine,
        }
        terminated = False
        truncated = False

        budget = _ACTION_BUDGET_S.get(action_i)
        if budget is None:
            terminated = True
            meta["applied"] = False
            meta["stop"] = True
        else:
            anchors = self._anchors(self._pcb)
            try:
                meta = dict(self._place_fn(self._work_pcb, action_i, anchors))
                meta.setdefault("action", action_i)
                meta["forced_refine"] = forced_refine
            except Exception as exc:
                meta = {
                    "applied": False,
                    "error": str(exc),
                    "action": action_i,
                    "forced_refine": forced_refine,
                }
                reward -= _ERROR_PENALTY

            self._pcb = PCB.load(str(self._work_pcb))
            new_fom, new_errors = self._metrics(self._pcb, self._work_pcb)
            if meta.get("applied", True):
                reward += new_fom - self._prev_fom
                if new_errors > self._prev_errors:
                    reward -= _ERROR_PENALTY * float(new_errors - self._prev_errors)
            self._prev_fom = new_fom
            self._prev_errors = new_errors

        self._step_count += 1
        if self._step_count >= self._max_steps:
            truncated = True

        info = {
            "env": "kct_placement",
            "fom_score": self._prev_fom,
            "error_conflicts": self._prev_errors,
            "board_id": self._active_board_id,
            "pcb_path": str(self._work_pcb),
            "step_meta": meta,
            "steps": self._step_count,
        }
        return self._obs(), float(reward), terminated, truncated, info

    @property
    def pcb(self) -> PCB | None:
        return self._pcb

    @property
    def work_pcb_path(self) -> Path | None:
        return self._work_pcb
