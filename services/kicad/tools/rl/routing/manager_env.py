"""Manager routing env — Dreamer/PPO chooses net + strategy; operator routes.

Phase 1b/1c lab: discrete action space over (net_slot, strategy) + stop.
Uses ``route_net_api`` (mock by default). Not the legacy 3-action selector.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from tools.rl.routing.route_net_api import (
    N_STRATEGIES,
    STRATEGIES,
    MockRouterState,
    multi_pad_net_ids,
    route_net,
    strategy_from_index,
)

try:
    import gymnasium as gym
    from gymnasium import spaces

    _HAS_GYM = True
except ImportError:  # pragma: no cover
    gym = None  # type: ignore[assignment]
    spaces = None  # type: ignore[assignment]
    _HAS_GYM = False

# Slots for net indices in observation / actions (pad with zeros if fewer nets)
MAX_NET_SLOTS = 32
# Legacy full action space (max slots). Prefer env.n_actions / env.stop_action.
N_MANAGER_ACTIONS = MAX_NET_SLOTS * N_STRATEGIES + 1
STOP_ACTION = N_MANAGER_ACTIONS - 1

# obs: pct, unrouted_norm, steps_norm, last_ok, done_flag + one-hot-ish net routed flags
MANAGER_OBS_DIM = 5 + MAX_NET_SLOTS

_STEP_COST = 0.01
_NET_DONE_BONUS = 0.15
_COMPLETE_BONUS = 0.5


def n_manager_actions(n_slots: int) -> int:
    """Action count for ``n_slots`` nets: net×strategy + stop."""
    slots = max(1, min(MAX_NET_SLOTS, int(n_slots)))
    return slots * N_STRATEGIES + 1


def stop_action_for_slots(n_slots: int) -> int:
    return n_manager_actions(n_slots) - 1


def _base_env():
    if _HAS_GYM:
        return gym.Env
    return object


def decode_manager_action(
    action: int,
    *,
    n_slots: int = MAX_NET_SLOTS,
) -> tuple[int | None, int | None, bool]:
    """Return (net_slot, strategy_idx, is_stop).

    ``n_slots`` sizes the discrete space (board multi-pad nets, capped at
    ``MAX_NET_SLOTS``). Default keeps the legacy full 32-slot layout so
    ``STOP_ACTION`` still decodes as stop.
    """
    a = int(action)
    n_act = n_manager_actions(n_slots)
    stop = n_act - 1
    if a < 0 or a > stop:
        return None, None, True
    if a == stop:
        return None, None, True
    net_slot = a // N_STRATEGIES
    strat_idx = a % N_STRATEGIES
    if net_slot >= max(1, min(MAX_NET_SLOTS, int(n_slots))):
        return None, None, True
    return net_slot, strat_idx, False


class ManagerRoutingEnv(_base_env()):  # type: ignore[misc,valid-type]
    """Sequential net+strategy manager env (mock operator by default)."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        pcb_path: str | Path,
        *,
        net_ids: Sequence[int] | None = None,
        backend: str = "mock",
        max_steps: int = 64,
        seed: int | None = None,
        work_dir: str | Path | None = None,
    ) -> None:
        self._pcb_path = Path(pcb_path)
        if not self._pcb_path.is_file():
            raise FileNotFoundError(f"PCB not found: {self._pcb_path}")
        # Prefer multi-pad nets from the board (single-pad nets are unroutable
        # by kct). Explicit ``net_ids`` still wins. Fallback 1..6 for empty PCBs.
        if net_ids is not None:
            self._default_net_ids = list(net_ids)
        else:
            try:
                board_bytes = self._pcb_path.read_bytes()
                detected = multi_pad_net_ids(board_bytes)
            except OSError:
                detected = []
            self._default_net_ids = detected if detected else list(range(1, 7))
        # Action space sized to this board's net count (not 32 empty slots).
        # Fixes PPO v1 collapse onto invalid high slots (16/21) on 6-net LED.
        self._n_slots = max(1, min(MAX_NET_SLOTS, len(self._default_net_ids)))
        self._n_actions = n_manager_actions(self._n_slots)
        self._stop_action = self._n_actions - 1
        self._backend = backend
        self._max_steps = max(1, int(max_steps))
        self._np = np.random.default_rng(seed)
        self._owned_tmp: tempfile.TemporaryDirectory[str] | None = None
        if work_dir is not None:
            self._work_root = Path(work_dir)
            self._work_root.mkdir(parents=True, exist_ok=True)
        else:
            self._owned_tmp = tempfile.TemporaryDirectory(prefix="rl_mgr_route_")
            self._work_root = Path(self._owned_tmp.name)

        self._work_pcb: Path | None = None
        self._pcb_bytes: bytes = b""
        self._state: MockRouterState | None = None
        self._step_count = 0
        self._last_success = 0.0

        if _HAS_GYM:
            self.observation_space = spaces.Box(
                low=0.0, high=1.0, shape=(MANAGER_OBS_DIM,), dtype=np.float32
            )
            self.action_space = spaces.Discrete(self._n_actions)

    @property
    def n_slots(self) -> int:
        return self._n_slots

    @property
    def n_actions(self) -> int:
        return self._n_actions

    @property
    def stop_action(self) -> int:
        return self._stop_action

    def close(self) -> None:
        if self._owned_tmp is not None:
            self._owned_tmp.cleanup()
            self._owned_tmp = None

    def _obs(self) -> np.ndarray:
        o = np.zeros((MANAGER_OBS_DIM,), dtype=np.float32)
        st = self._state
        if st is None:
            return o
        o[0] = min(1.0, st.routed_percent / 100.0)
        o[1] = min(1.0, st.unrouted_count / float(st.nets_total))
        o[2] = min(1.0, self._step_count / float(self._max_steps))
        o[3] = self._last_success
        o[4] = 1.0 if st.unrouted_count == 0 else 0.0
        for i, nid in enumerate(st.net_ids[:MAX_NET_SLOTS]):
            o[5 + i] = 1.0 if nid in st.routed else 0.0
        return o

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ):
        if seed is not None:
            self._np = np.random.default_rng(seed)
        self._work_pcb = self._work_root / f"{self._pcb_path.stem}_mgr.kicad_pcb"
        shutil.copy2(self._pcb_path, self._work_pcb)
        self._pcb_bytes = self._work_pcb.read_bytes()
        net_ids = list(self._default_net_ids)
        if options and options.get("net_ids"):
            net_ids = list(options["net_ids"])
        self._state = MockRouterState.from_net_ids(net_ids)
        # Optional: start with some nets already routed (partial resume)
        if options and options.get("pre_routed"):
            for n in options["pre_routed"]:
                if int(n) in self._state.net_ids:
                    self._state.routed.add(int(n))
        self._step_count = 0
        self._last_success = 0.0
        info = {
            "env": "manager_routing",
            "backend": self._backend,
            "nets_total": self._state.nets_total,
            "routed_percent": self._state.routed_percent,
            "net_ids": list(self._state.net_ids),
        }
        return self._obs(), info

    def step(self, action: int | np.ndarray):
        assert self._state is not None and self._work_pcb is not None
        reward = -_STEP_COST
        terminated = False
        truncated = False
        meta: dict[str, Any] = {}

        net_slot, strat_idx, is_stop = decode_manager_action(
            int(action), n_slots=self._n_slots
        )
        if is_stop:
            terminated = True
            meta = {"stop": True, "action": int(action)}
        else:
            assert net_slot is not None and strat_idx is not None
            nets = self._state.net_ids
            if net_slot >= len(nets):
                reward -= 0.05
                meta = {"invalid_net_slot": net_slot, "action": int(action)}
                self._last_success = 0.0
            else:
                net_id = nets[net_slot]
                strategy = strategy_from_index(strat_idx)
                prev_routed = self._state.nets_routed
                prev_pct = self._state.routed_percent
                try:
                    self._pcb_bytes, metrics = route_net(
                        self._pcb_bytes,
                        net_id,
                        strategy,
                        backend=self._backend,  # type: ignore[arg-type]
                        state=self._state,
                    )
                    self._work_pcb.write_bytes(self._pcb_bytes)
                    meta = metrics.as_dict()
                    if metrics.success and self._state.nets_routed > prev_routed:
                        reward += _NET_DONE_BONUS
                        self._last_success = 1.0
                    else:
                        self._last_success = 1.0 if metrics.success else 0.0
                    reward += (self._state.routed_percent - prev_pct) / 100.0
                    # mild strategy costs
                    reward -= 0.001 * max(0, metrics.vias_delta)
                    reward -= 0.001 * max(0.0, metrics.length_mm_delta)
                    if self._state.unrouted_count == 0:
                        terminated = True
                        reward += _COMPLETE_BONUS
                except Exception as exc:
                    reward -= 0.5
                    meta = {"error": str(exc), "net_id": net_id, "strategy": strategy}
                    self._last_success = 0.0

        self._step_count += 1
        if self._step_count >= self._max_steps:
            truncated = True

        st = self._state
        info = {
            "env": "manager_routing",
            "routed_percent": st.routed_percent if st else 0,
            "unrouted_count": st.unrouted_count if st else 0,
            "nets_routed": st.nets_routed if st else 0,
            "nets_total": st.nets_total if st else 0,
            "step_meta": meta,
            "steps": self._step_count,
        }
        return self._obs(), float(reward), terminated, truncated, info
