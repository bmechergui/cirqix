"""RED tests for the ERC report parser.

Parses `kicad-cli sch erc --format json` output into a list of dictionaries
matching the ``ERCViolation`` TypeScript interface in ``@layrix/types``.

Pure function — no subprocess, no filesystem.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow imports from services/kicad/tools without installing the package
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from tools.erc import parse_erc_report  # noqa: E402


REPORT_CLEAN = json.dumps({
    "source": "schematic.kicad_sch",
    "date": "2026-05-16",
    "kicad_version": "8.0.5",
    "violations": [],
})

REPORT_ONE_PIN_NOT_CONNECTED = json.dumps({
    "source": "schematic.kicad_sch",
    "violations": [
        {
            "type": "pin_not_connected",
            "description": "Pin not connected",
            "severity": "warning",
            "items": [
                {
                    "description": "Symbol U1 Pin 5",
                    "uuid": "abc-123",
                    "pos": {"x": 100.5, "y": 50.0},
                }
            ],
        }
    ],
})

REPORT_ERROR_NET_CONFLICT = json.dumps({
    "violations": [
        {
            "type": "different_net_no_marker",
            "description": "Different nets connected without explicit marker",
            "severity": "error",
            "items": [
                {"description": "Symbol U1 Pin VCC", "uuid": "id-1", "pos": {"x": 10, "y": 20}}
            ],
        }
    ],
})


class TestParseErcReport:
    def test_clean_report_returns_empty(self) -> None:
        violations = parse_erc_report(REPORT_CLEAN)
        assert violations == []

    def test_single_pin_not_connected(self) -> None:
        violations = parse_erc_report(REPORT_ONE_PIN_NOT_CONNECTED)
        assert len(violations) == 1
        v = violations[0]
        assert v["severity"] == "warning"
        assert v["type"] == "pin_not_connected"
        assert v["message"] == "Pin not connected"
        assert v["x_mm"] == 100.5
        assert v["y_mm"] == 50.0
        assert v["ref"] == "U1"
        assert v["pin"] == "5"
        assert isinstance(v["id"], str) and len(v["id"]) > 0

    def test_error_severity_preserved(self) -> None:
        violations = parse_erc_report(REPORT_ERROR_NET_CONFLICT)
        assert violations[0]["severity"] == "error"

    def test_invalid_json_returns_empty(self) -> None:
        # Should not crash on malformed input — KiCad version surprises
        assert parse_erc_report("not valid json") == []

    def test_missing_violations_key_returns_empty(self) -> None:
        assert parse_erc_report(json.dumps({})) == []

    def test_multiple_violations(self) -> None:
        report = json.dumps({
            "violations": [
                {
                    "type": "pin_not_connected", "severity": "warning",
                    "items": [{"description": "Symbol R1 Pin 2", "pos": {"x": 5, "y": 5}}],
                },
                {
                    "type": "pin_not_connected", "severity": "warning",
                    "items": [{"description": "Symbol C1 Pin 1", "pos": {"x": 10, "y": 10}}],
                },
            ],
        })
        violations = parse_erc_report(report)
        assert len(violations) == 2
        refs = {v["ref"] for v in violations}
        assert refs == {"R1", "C1"}

    def test_violation_without_items_is_skipped(self) -> None:
        report = json.dumps({
            "violations": [
                {"type": "no_items_violation", "severity": "warning"},
                {
                    "type": "pin_not_connected", "severity": "warning",
                    "items": [{"description": "Symbol R1 Pin 1", "pos": {"x": 0, "y": 0}}],
                },
            ],
        })
        violations = parse_erc_report(report)
        # The one without items is kept but ref/pin/x/y are absent
        assert len(violations) >= 1
        valid = [v for v in violations if v.get("ref") == "R1"]
        assert len(valid) == 1
