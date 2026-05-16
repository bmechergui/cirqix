"""RED tests for the ERC auto-fix that inserts no_connect markers.

The auto-fix MUST NEVER touch connectivity — it only appends
``(no_connect (at x y) (uuid ...))`` lines for pins flagged "pin_not_connected".
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow imports from services/kicad/tools without installing the package
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from tools.erc import apply_no_connect_fixes  # noqa: E402


MINIMAL_SCH = """(kicad_sch (version 20231120) (generator "eeschema")
  (paper "A4")
  (lib_symbols
    (symbol "Device:R" (in_bom yes) (on_board yes))
  )
  (symbol (lib_id "Device:R") (at 50 50 0) (unit 1)
    (property "Reference" "R1" (at 50 45 0))
  )
)
"""


class TestApplyNoConnectFixes:
    def test_clean_input_unchanged(self) -> None:
        violations: list[dict] = []
        new_sch, fixed = apply_no_connect_fixes(MINIMAL_SCH, violations)
        assert new_sch == MINIMAL_SCH
        assert fixed == 0

    def test_single_pin_not_connected_adds_marker(self) -> None:
        violations = [
            {
                "id": "v1",
                "type": "pin_not_connected",
                "severity": "warning",
                "message": "Pin not connected",
                "x_mm": 100.5,
                "y_mm": 50.0,
            }
        ]
        new_sch, fixed = apply_no_connect_fixes(MINIMAL_SCH, violations)
        assert fixed == 1
        assert "(no_connect" in new_sch
        assert "100.5" in new_sch
        # Existing content preserved
        assert "(symbol" in new_sch
        assert '"Device:R"' in new_sch

    def test_non_pin_violations_are_ignored(self) -> None:
        violations = [
            {
                "id": "v1",
                "type": "different_net_no_marker",  # NOT pin_not_connected
                "severity": "error",
                "message": "Different nets",
                "x_mm": 10,
                "y_mm": 10,
            }
        ]
        new_sch, fixed = apply_no_connect_fixes(MINIMAL_SCH, violations)
        assert fixed == 0
        # No no_connect added
        assert "(no_connect" not in new_sch

    def test_violation_missing_coordinates_is_skipped(self) -> None:
        violations = [
            {"id": "v1", "type": "pin_not_connected", "severity": "warning"}
        ]
        new_sch, fixed = apply_no_connect_fixes(MINIMAL_SCH, violations)
        assert fixed == 0

    def test_connectivity_preserved_char_level(self) -> None:
        # Append-only invariant: every original line must still appear in output
        violations = [
            {
                "id": "v1",
                "type": "pin_not_connected",
                "x_mm": 25, "y_mm": 25,
            }
        ]
        new_sch, _ = apply_no_connect_fixes(MINIMAL_SCH, violations)
        # Every non-empty line of the original must still exist verbatim
        for line in MINIMAL_SCH.splitlines():
            if line.strip():
                assert line in new_sch, f"Original line missing: {line!r}"

    def test_multiple_violations_add_multiple_markers(self) -> None:
        violations = [
            {"type": "pin_not_connected", "x_mm": 10, "y_mm": 10},
            {"type": "pin_not_connected", "x_mm": 20, "y_mm": 20},
            {"type": "pin_not_connected", "x_mm": 30, "y_mm": 30},
        ]
        new_sch, fixed = apply_no_connect_fixes(MINIMAL_SCH, violations)
        assert fixed == 3
        # Three distinct no_connect markers
        assert new_sch.count("(no_connect") == 3

    def test_returns_new_object_not_mutation(self) -> None:
        violations = [{"type": "pin_not_connected", "x_mm": 10, "y_mm": 10}]
        original_copy = MINIMAL_SCH
        new_sch, _ = apply_no_connect_fixes(MINIMAL_SCH, violations)
        # Input string unchanged (Python strings are immutable but verify pattern)
        assert MINIMAL_SCH == original_copy
        # New string is genuinely new
        assert new_sch is not MINIMAL_SCH
