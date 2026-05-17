"""RED tests for the DRC report parser.

Parses `kicad-cli pcb drc --format json` output into a list of dictionaries
matching the ``DRCViolation`` TypeScript interface in ``@layrix/types``.

Pure function — no subprocess, no filesystem.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow imports from services/kicad/tools without installing the package
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from tools.drc import parse_drc_report  # noqa: E402


REPORT_CLEAN = json.dumps({
    "source": "board.kicad_pcb",
    "violations": [],
    "unconnected_items": [],
    "schematic_parity": [],
})

REPORT_CLEARANCE_VIOLATION = json.dumps({
    "violations": [
        {
            "type": "clearance",
            "description": "Clearance violation between tracks",
            "severity": "error",
            "items": [
                {"description": "Track on F.Cu", "pos": {"x": 25.5, "y": 12.0}},
            ],
        }
    ],
})

REPORT_TRACK_WIDTH_WARNING = json.dumps({
    "violations": [
        {
            "type": "track_width",
            "description": "Track too narrow",
            "severity": "warning",
            "items": [{"description": "Track on F.Cu", "pos": {"x": 10, "y": 10}}],
        }
    ],
})


class TestParseDrcReport:
    def test_clean_report_returns_empty(self) -> None:
        assert parse_drc_report(REPORT_CLEAN) == []

    def test_clearance_error(self) -> None:
        violations = parse_drc_report(REPORT_CLEARANCE_VIOLATION)
        assert len(violations) == 1
        v = violations[0]
        assert v["severity"] == "error"
        assert v["type"] == "clearance"
        assert v["x_mm"] == 25.5
        assert v["y_mm"] == 12.0

    def test_track_width_warning(self) -> None:
        violations = parse_drc_report(REPORT_TRACK_WIDTH_WARNING)
        assert violations[0]["severity"] == "warning"
        assert violations[0]["type"] == "track_width"

    def test_invalid_json_returns_empty(self) -> None:
        assert parse_drc_report("not json") == []

    def test_missing_violations_key_returns_empty(self) -> None:
        assert parse_drc_report(json.dumps({})) == []

    def test_unconnected_items_promoted_to_violations(self) -> None:
        report = json.dumps({
            "violations": [],
            "unconnected_items": [
                {
                    "type": "unconnected",
                    "description": "Unconnected track end",
                    "severity": "error",
                    "items": [{"description": "Track on F.Cu", "pos": {"x": 0, "y": 0}}],
                }
            ],
        })
        violations = parse_drc_report(report)
        assert len(violations) == 1
        assert violations[0]["severity"] == "error"

    def test_each_violation_has_id(self) -> None:
        violations = parse_drc_report(REPORT_CLEARANCE_VIOLATION)
        assert all(isinstance(v["id"], str) and len(v["id"]) > 0 for v in violations)
