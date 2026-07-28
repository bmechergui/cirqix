"""Reward adapter — exact wrapper around kicad-tools ``compute_fom``.

NEVER reimplements FOM terms. Same weights / kwargs as a direct call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from kicad_tools.optim.fom import FOMResult, FOMWeights, compute_fom
from kicad_tools.schema.pcb import PCB


def compute_placement_reward(
    pcb: PCB,
    weights: FOMWeights | None = None,
    *,
    manufacturer: str | None = None,
    drc_report=None,
    erc_report=None,
    lvs_orphan_pads: int | None = None,
    tolerance_allowlist_path: str | Path | None = None,
    pcb_path: str | Path | None = None,
    features=None,
    predictor: Callable[[PCB], float] | None = None,
    beta: float = 0.0,
) -> FOMResult:
    """Return the full :class:`FOMResult` for a placement (kicad-tools only).

    Args mirror :func:`kicad_tools.optim.fom.compute_fom` so the reward
    cannot silently diverge from the production score.
    """
    return compute_fom(
        pcb,
        weights,
        manufacturer=manufacturer,
        drc_report=drc_report,
        erc_report=erc_report,
        lvs_orphan_pads=lvs_orphan_pads,
        tolerance_allowlist_path=tolerance_allowlist_path,
        pcb_path=pcb_path,
        features=features,
        predictor=predictor,
        beta=beta,
    )


def fom_score(
    pcb: PCB,
    weights: FOMWeights | None = None,
    **kwargs,
) -> float:
    """Scalar reward in [0, 1] — ``compute_fom(...).score``."""
    return float(compute_placement_reward(pcb, weights, **kwargs).score)
