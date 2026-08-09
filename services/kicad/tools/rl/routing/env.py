"""Gymnasium RoutingEnv — single-net local router on BoardGrid surrogate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from tools.rl.routing.actions import N_ACTIONS, RouteAction, is_move, move_delta
from tools.rl.routing.board_grid import (
    DEFAULT_NET_ORDER,
    BoardGrid,
    build_board_grid,
    pair_terminals,
)
from tools.rl.routing.reward import (
    REWARD_ABORT,
    REWARD_COLLISION,
    REWARD_REACH_TARGET,
    REWARD_STEP,
    REWARD_VIA,
)

try:
    import gymnasium as gym
    from gymnasium import spaces

    _HAS_GYM = True
except ImportError:  # pragma: no cover
    gym = None  # type: ignore[assignment]
    spaces = None  # type: ignore[assignment]
    _HAS_GYM = False


def _base_env():
    if _HAS_GYM:
        return gym.Env
    return object


class RoutingEnv(_base_env()):  # type: ignore[misc,valid-type]
    """Route one net at a time on a placed board (surrogate grid).

    Observation: flattened multi-channel raster (float32).
    Action: Discrete(N_ACTIONS) — 8 moves + switch_layer + place_via + finish_net.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        pcb_path: str | Path,
        *,
        net_name: str | None = None,
        net_order: list[str] | None = None,
        resolution_mm: float = 0.25,
        max_steps: int = 256,
        seed: int | None = None,
    ) -> None:
        self._pcb_path = Path(pcb_path)
        self._resolution = resolution_mm
        self._max_steps = max_steps
        self._net_order = list(net_order or DEFAULT_NET_ORDER)
        self._forced_net = net_name
        self._np = np.random.default_rng(seed)

        self.board: BoardGrid = build_board_grid(
            self._pcb_path, resolution_mm=resolution_mm
        )
        # observation size from board
        ch, h, w = self.board.observation(
            net_name="GND",
            cursor_xy=(self.board.origin_x, self.board.origin_y),
        ).shape
        self._obs_shape = (ch, h, w)
        self._obs_dim = int(ch * h * w)

        if _HAS_GYM:
            self.observation_space = spaces.Box(
                low=0.0, high=1.0, shape=(self._obs_dim,), dtype=np.float32
            )
            self.action_space = spaces.Discrete(N_ACTIONS)

        self._net_name: str = ""
        self._net_id: int = -1
        self._gx = 0
        self._gy = 0
        self._layer = 0
        self._steps = 0
        self._path: list[tuple[int, int, int]] = []  # gx, gy, layer
        self._source = None
        self._target = None
        self._done = False

    @property
    def obs_dim(self) -> int:
        return self._obs_dim

    def _pick_net(self) -> str:
        if self._forced_net:
            return self._forced_net
        available = [
            n
            for n in self._net_order
            if n in self.board.nets and len(self.board.nets[n].pads) >= 2
        ]
        if not available:
            available = [
                n for n, t in self.board.nets.items() if len(t.pads) >= 2
            ]
        if not available:
            raise RuntimeError("no multi-pad nets on board")
        idx = int(self._np.integers(0, len(available)))
        return available[idx]

    def _obs(self) -> np.ndarray:
        assert self._source is not None and self._target is not None
        cx, cy = self.board.grid_to_world(self._gx, self._gy)
        return self.board.flat_observation(
            net_name=self._net_name,
            cursor_xy=(cx, cy),
            layer=self._layer,
            source_pad=self._source,
            target_pad=self._target,
        )

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ):
        if seed is not None:
            self._np = np.random.default_rng(seed)
        # Reload grid so previous episode copper does not leak (v1: pads only)
        self.board = build_board_grid(
            self._pcb_path, resolution_mm=self._resolution
        )
        self._net_name = self._pick_net()
        term = self.board.terminals_for(self._net_name)
        assert term is not None
        pair = pair_terminals(term)
        if pair is None:
            raise RuntimeError(f"net {self._net_name} needs ≥2 pads")
        self._source, self._target = pair
        self._net_id = term.net_id
        self._gx, self._gy = self.board.world_to_grid(
            self._source.x, self._source.y
        )
        self._layer = 0
        self._steps = 0
        self._path = [(self._gx, self._gy, self._layer)]
        self._done = False
        info = {
            "net": self._net_name,
            "net_id": self._net_id,
            "source": (self._source.ref, self._source.pin),
            "target": (self._target.ref, self._target.pin),
        }
        return self._obs(), info

    def _at_target(self) -> bool:
        assert self._target is not None
        tgx, tgy = self.board.world_to_grid(self._target.x, self._target.y)
        return abs(self._gx - tgx) <= 1 and abs(self._gy - tgy) <= 1

    def step(self, action: int):
        if self._done:
            return self._obs(), 0.0, True, False, {"already_done": True}

        action = int(action)
        reward = 0.0
        terminated = False
        truncated = False
        info: dict[str, Any] = {"action": action, "applied": False}

        if action == int(RouteAction.FINISH_NET):
            if self._at_target():
                reward = REWARD_REACH_TARGET
                terminated = True
                info["success"] = True
            else:
                reward = REWARD_ABORT
                terminated = True
                info["success"] = False
            self._done = True
            return self._obs(), reward, terminated, truncated, info

        if action == int(RouteAction.SWITCH_LAYER):
            self._layer = 1 - self._layer if self.board.n_layers > 1 else 0
            reward = REWARD_STEP
            info["applied"] = True
        elif action == int(RouteAction.PLACE_VIA):
            if self.board.n_layers < 2:
                reward = REWARD_COLLISION
            else:
                self._layer = 1 - self._layer
                reward = REWARD_VIA
                info["applied"] = True
                self._path.append((self._gx, self._gy, self._layer))
        elif is_move(action):
            dgx, dgy = move_delta(action)
            nx, ny = self._gx + dgx, self._gy + dgy
            if self.board.is_blocked(self._layer, nx, ny, self._net_id):
                reward = REWARD_COLLISION
                info["blocked"] = True
            else:
                self._gx, self._gy = nx, ny
                self._path.append((self._gx, self._gy, self._layer))
                reward = REWARD_STEP
                info["applied"] = True
                if self._at_target():
                    # soft success when adjacent — agent should FINISH_NET
                    info["near_target"] = True
        else:
            reward = REWARD_COLLISION

        self._steps += 1
        if self._steps >= self._max_steps and not terminated:
            truncated = True
            reward += REWARD_ABORT
            self._done = True
            info["success"] = False

        info["steps"] = self._steps
        info["gx"] = self._gx
        info["gy"] = self._gy
        info["layer"] = self._layer
        info["path_len"] = len(self._path)
        return self._obs(), float(reward), terminated, truncated, info
