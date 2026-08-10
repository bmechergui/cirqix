"""Reward scale for RL routing surrogate (docs/rl/routing/README.md)."""

from __future__ import annotations

REWARD_REACH_TARGET = 1000.0
REWARD_STEP = -2.0
REWARD_VIA = -20.0
REWARD_COLLISION = -500.0
REWARD_ABORT = -1000.0
