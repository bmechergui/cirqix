"""RL placement Phase 6a — candidate micro-refinement (kicad-tools only).

See ``docs/rl/placement/PLAN.md``.
"""

from __future__ import annotations

__all__ = [
    "compute_placement_reward",
    "fom_score",
]


def __getattr__(name: str):
    # Lazy import so ``train_placement`` can fix sys.path before kicad_tools loads.
    if name in ("compute_placement_reward", "fom_score"):
        from tools.rl.placement.reward import compute_placement_reward, fom_score

        return compute_placement_reward if name == "compute_placement_reward" else fom_score
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
