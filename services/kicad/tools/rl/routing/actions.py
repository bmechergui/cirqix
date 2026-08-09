"""Discrete actions for RL local router (PLAN §2)."""

from __future__ import annotations

from enum import IntEnum


class RouteAction(IntEnum):
    NORTH = 0
    SOUTH = 1
    EAST = 2
    WEST = 3
    NE = 4
    NW = 5
    SE = 6
    SW = 7
    SWITCH_LAYER = 8
    PLACE_VIA = 9
    FINISH_NET = 10


N_ACTIONS = len(RouteAction)

# (dgx, dgy) in grid cells — y increases north in world; grid row is y index
# RoutingGrid: gy increases with world y typically via world_to_grid
_DELTA: dict[RouteAction, tuple[int, int]] = {
    RouteAction.NORTH: (0, 1),
    RouteAction.SOUTH: (0, -1),
    RouteAction.EAST: (1, 0),
    RouteAction.WEST: (-1, 0),
    RouteAction.NE: (1, 1),
    RouteAction.NW: (-1, 1),
    RouteAction.SE: (1, -1),
    RouteAction.SW: (-1, -1),
}


def is_move(action: int | RouteAction) -> bool:
    a = RouteAction(int(action))
    return a in _DELTA


def move_delta(action: int | RouteAction) -> tuple[int, int]:
    """Return (dgx, dgy) for move actions; (0,0) otherwise."""
    a = RouteAction(int(action))
    return _DELTA.get(a, (0, 0))
