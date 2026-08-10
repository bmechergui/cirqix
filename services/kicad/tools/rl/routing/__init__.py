"""RL routing Phase 6 — direct net router (candidate vs kct route).

See ``docs/rl/routing/PLAN.md``.
"""

from __future__ import annotations

__all__ = [
    "build_board_grid",
    "BoardGrid",
    "RoutingEnv",
    "RouteAction",
    "N_ACTIONS",
]


def __getattr__(name: str):
    if name in ("build_board_grid", "BoardGrid"):
        from tools.rl.routing.board_grid import BoardGrid, build_board_grid

        return BoardGrid if name == "BoardGrid" else build_board_grid
    if name == "RoutingEnv":
        from tools.rl.routing.env import RoutingEnv

        return RoutingEnv
    if name in ("RouteAction", "N_ACTIONS"):
        from tools.rl.routing.actions import N_ACTIONS, RouteAction

        return RouteAction if name == "RouteAction" else N_ACTIONS
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
