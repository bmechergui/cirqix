"""Placement conflict counts via kicad-tools PlacementAnalyzer (real ERROR gate)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from kicad_tools.placement.analyzer import DesignRules, PlacementAnalyzer
from kicad_tools.placement.conflict import ConflictSeverity
from kicad_tools.schema.pcb import PCB

# Match placement.py courtyard margin for consistent ERROR/WARNING split
_COURTYARD_MARGIN_MM = 0.25


def count_error_conflicts(pcb: PCB, *, pcb_path: str | Path | None = None) -> int:
    """Return number of PlacementAnalyzer ERROR conflicts on ``pcb``.

    If ``pcb_path`` is set, analyze that file (must match ``pcb`` content).
    Otherwise round-trip through a temp file (kicad-tools API is path-based).
    """
    analyzer = PlacementAnalyzer()
    rules = DesignRules(courtyard_margin=_COURTYARD_MARGIN_MM)

    if pcb_path is not None:
        conflicts = analyzer.find_conflicts(str(pcb_path), rules)
    else:
        with tempfile.TemporaryDirectory(prefix="rl_place_drc_") as tmp:
            p = Path(tmp) / "board.kicad_pcb"
            pcb.save(str(p))
            conflicts = analyzer.find_conflicts(str(p), rules)

    return sum(1 for c in conflicts if c.severity == ConflictSeverity.ERROR)


def count_warning_conflicts(pcb: PCB, *, pcb_path: str | Path | None = None) -> int:
    """Return number of PlacementAnalyzer WARNING conflicts."""
    analyzer = PlacementAnalyzer()
    rules = DesignRules(courtyard_margin=_COURTYARD_MARGIN_MM)

    if pcb_path is not None:
        conflicts = analyzer.find_conflicts(str(pcb_path), rules)
    else:
        with tempfile.TemporaryDirectory(prefix="rl_place_drc_") as tmp:
            p = Path(tmp) / "board.kicad_pcb"
            pcb.save(str(p))
            conflicts = analyzer.find_conflicts(str(p), rules)

    return sum(1 for c in conflicts if c.severity == ConflictSeverity.WARNING)
