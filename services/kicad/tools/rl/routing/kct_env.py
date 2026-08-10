"""Gymnasium envs whose steps call **kicad-tools** ``kct route`` only.

Phase 1 of docs/rl — real EDA as environment (Dreamer manager + KCT operator).

* ``KctRoutingEnv`` — principal (``route_kct``, vcc traces policy)
* ``FrRoutingEnv`` — secondary arm name (legacy label); default is still
  ``route_kct`` with planes policy — **no pcbnew / FreeRouting**

Default backends call ``tools.kct_route``; inject callables for unit tests.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

try:
    import gymnasium as gym
    from gymnasium import spaces

    _HAS_GYM = True
except ImportError:  # pragma: no cover
    gym = None  # type: ignore[assignment]
    spaces = None  # type: ignore[assignment]
    _HAS_GYM = False

# Observation: fixed small vector (no BoardGrid) — enough for MLP / Dreamer vector encoder
# [pct_norm, steps_norm, last_delta_pct, is_done_flag, vcc_mode_hint, zeros...]
ROUTING_OBS_DIM = 8

# Kct actions
# 0 — route_kct vcc_as_traces=True
# 1 — route_kct vcc_as_traces=False (power planes fallback policy)
# 2 — stop episode
N_KCT_ROUTE_ACTIONS = 3

# FR actions
# 0 — run FreeRouting once
# 1 — stop
N_FR_ROUTE_ACTIONS = 2

_STEP_COST = 0.01
_FAIL_PENALTY = 0.5

RouteFn = Callable[[bytes, int], tuple[bytes, int, str]]
"""``route_fn(pcb_bytes, action) -> (routed_bytes, routed_percent, analysis)``."""


def _default_kct_route_fn(pcb_bytes: bytes, action: int) -> tuple[bytes, int, str]:
    from tools.kct_route import route_kct

    if int(action) == 1:
        return route_kct(pcb_bytes, vcc_as_traces=False)
    # action 0 (and any other non-stop handled by env)
    return route_kct(pcb_bytes, vcc_as_traces=True)


def _default_fr_route_fn(pcb_bytes: bytes, action: int) -> tuple[bytes, int, str]:
    """Secondary lab arm — **kicad-tools only** (never pcbnew / FreeRouting).

    Historical env name ``FrRoutingEnv`` kept for paper-parity labels; the
    operator is ``route_kct`` with ``vcc_as_traces=False`` (planes policy).
    """
    del action  # single-run alternate policy
    from tools.kct_route import route_kct

    return route_kct(pcb_bytes, vcc_as_traces=False)


def _base_env():
    if _HAS_GYM:
        return gym.Env
    return object


def _zero_obs() -> np.ndarray:
    return np.zeros((ROUTING_OBS_DIM,), dtype=np.float32)


class _BaseRouteEnv(_base_env()):  # type: ignore[misc,valid-type]
    """Shared working-copy + metrics plumbing for kct / FR routing envs."""

    metadata = {"render_modes": []}
    env_name: str = "route_base"
    n_actions: int = 2

    def __init__(
        self,
        pcb_path: str | Path | None = None,
        *,
        pcb_paths: Sequence[str | Path] | None = None,
        route_fn: RouteFn | None = None,
        max_steps: int = 2,
        seed: int | None = None,
        work_dir: str | Path | None = None,
        stop_action: int = 1,
    ) -> None:
        paths: list[Path] = []
        if pcb_paths:
            paths = [Path(p) for p in pcb_paths]
        elif pcb_path is not None:
            paths = [Path(pcb_path)]
        if not paths:
            raise ValueError(f"{type(self).__name__} requires pcb_path or pcb_paths")
        for p in paths:
            if not p.is_file():
                raise FileNotFoundError(f"PCB fixture not found: {p}")

        self._pcb_paths = paths
        self._route_fn = route_fn
        self._max_steps = max(1, int(max_steps))
        self._stop_action = int(stop_action)
        self._np = np.random.default_rng(seed)
        self._owned_tmp: tempfile.TemporaryDirectory[str] | None = None
        if work_dir is not None:
            self._work_root = Path(work_dir)
            self._work_root.mkdir(parents=True, exist_ok=True)
        else:
            self._owned_tmp = tempfile.TemporaryDirectory(prefix="rl_kct_route_")
            self._work_root = Path(self._owned_tmp.name)

        self._source_path: Path | None = None
        self._work_pcb: Path | None = None
        self._pcb_bytes: bytes = b""
        self._step_count = 0
        self._prev_pct = 0
        self._last_delta = 0.0
        self._active_board_id: str | None = None
        self._last_analysis = ""

        if _HAS_GYM:
            self.observation_space = spaces.Box(
                low=0.0, high=1.0, shape=(ROUTING_OBS_DIM,), dtype=np.float32
            )
            self.action_space = spaces.Discrete(self.n_actions)

    def close(self) -> None:
        if self._owned_tmp is not None:
            self._owned_tmp.cleanup()
            self._owned_tmp = None

    def _pick_source(self) -> Path:
        if len(self._pcb_paths) == 1:
            return self._pcb_paths[0]
        idx = int(self._np.integers(0, len(self._pcb_paths)))
        return self._pcb_paths[idx]

    def _obs(self) -> np.ndarray:
        o = _zero_obs()
        o[0] = min(1.0, max(0.0, self._prev_pct / 100.0))
        o[1] = min(1.0, self._step_count / float(self._max_steps))
        o[2] = min(1.0, max(-1.0, self._last_delta / 100.0)) * 0.5 + 0.5
        o[3] = 1.0 if self._prev_pct >= 100 else 0.0
        return o

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
        self._pcb_bytes = self._work_pcb.read_bytes()
        self._step_count = 0
        self._prev_pct = 0
        self._last_delta = 0.0
        self._last_analysis = ""
        # Optional initial percent from options (partial board resume)
        if options and "initial_routed_percent" in options:
            self._prev_pct = int(options["initial_routed_percent"])
        info = {
            "env": self.env_name,
            "routed_percent": self._prev_pct,
            "board_id": self._active_board_id,
            "pcb_path": str(self._work_pcb),
            "source_path": str(self._source_path),
            "n_dataset_boards": len(self._pcb_paths),
        }
        return self._obs(), info

    def _call_route(self, action: int) -> tuple[bytes, int, str]:
        assert self._route_fn is not None
        return self._route_fn(self._pcb_bytes, action)

    def step(self, action: int | np.ndarray):
        assert self._work_pcb is not None
        action_i = int(action)
        if action_i < 0 or action_i >= self.n_actions:
            action_i = self._stop_action

        reward = -_STEP_COST
        terminated = False
        truncated = False
        meta: dict[str, Any] = {"action": action_i}

        if action_i == self._stop_action:
            terminated = True
            meta["stop"] = True
            meta["applied"] = False
        else:
            try:
                out_bytes, pct, analysis = self._call_route(action_i)
                pct_i = int(pct)
                delta = float(pct_i - self._prev_pct)
                self._last_delta = delta
                reward += delta / 100.0
                # Prefer non-regression of copper already present
                if pct_i < self._prev_pct:
                    reward -= _FAIL_PENALTY
                self._pcb_bytes = out_bytes
                self._work_pcb.write_bytes(out_bytes)
                self._prev_pct = pct_i
                self._last_analysis = analysis or ""
                meta.update(
                    {
                        "applied": True,
                        "routed_percent": pct_i,
                        "delta_pct": delta,
                        "analysis_preview": (analysis or "")[:200],
                    }
                )
                if pct_i >= 100:
                    terminated = True
                    reward += 0.5
            except Exception as exc:
                reward -= _FAIL_PENALTY
                meta.update({"applied": False, "error": str(exc)})

        self._step_count += 1
        if self._step_count >= self._max_steps:
            truncated = True

        info = {
            "env": self.env_name,
            "routed_percent": self._prev_pct,
            "board_id": self._active_board_id,
            "pcb_path": str(self._work_pcb),
            "step_meta": meta,
            "steps": self._step_count,
            "analysis_preview": self._last_analysis[:200],
        }
        return self._obs(), float(reward), terminated, truncated, info

    @property
    def work_pcb_path(self) -> Path | None:
        return self._work_pcb

    @property
    def pcb_bytes(self) -> bytes:
        return self._pcb_bytes


class KctRoutingEnv(_BaseRouteEnv):
    """Principal routing env — steps invoke kct route (injectable)."""

    env_name = "kct_routing"
    n_actions = N_KCT_ROUTE_ACTIONS

    def __init__(
        self,
        pcb_path: str | Path | None = None,
        *,
        pcb_paths: Sequence[str | Path] | None = None,
        route_fn: RouteFn | None = None,
        max_steps: int = 2,
        seed: int | None = None,
        work_dir: str | Path | None = None,
    ) -> None:
        super().__init__(
            pcb_path,
            pcb_paths=pcb_paths,
            route_fn=route_fn or _default_kct_route_fn,
            max_steps=max_steps,
            seed=seed,
            work_dir=work_dir,
            stop_action=2,
        )


class FrRoutingEnv(_BaseRouteEnv):
    """Fallback routing env — kicad-tools alternate (``route_kct`` planes).

    Name kept for report/legacy; default operator is **not** FreeRouting/pcbnew.
    Inject ``route_fn`` in tests.
    """

    env_name = "fr_routing"
    n_actions = N_FR_ROUTE_ACTIONS

    def __init__(
        self,
        pcb_path: str | Path | None = None,
        *,
        pcb_paths: Sequence[str | Path] | None = None,
        route_fn: RouteFn | None = None,
        max_steps: int = 2,
        seed: int | None = None,
        work_dir: str | Path | None = None,
    ) -> None:
        super().__init__(
            pcb_path,
            pcb_paths=pcb_paths,
            route_fn=route_fn or _default_fr_route_fn,
            max_steps=max_steps,
            seed=seed,
            work_dir=work_dir,
            stop_action=1,
        )
