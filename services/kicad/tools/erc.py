"""ERC (Electrical Rules Check) utilities for the Cirqix KiCad service.

Two pure functions consumed by ``routers/erc.py``:

- ``parse_erc_report(json_str)`` — tolerant parser for ``kicad-cli sch erc --format json``
- ``apply_no_connect_fixes(sch_content, violations)`` — append-only auto-fix for
  ``pin_not_connected`` violations (NEVER modifies connectivity).

The router additionally orchestrates ``kicad-cli`` invocation with up to 3
auto-fix iterations; that logic lives in ``routers/erc.py``.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# Matches "Symbol <ref> Pin <pin>" — KiCad item.description format
_ITEM_RE = re.compile(r"Symbol\s+(?P<ref>\S+)\s+Pin\s+(?P<pin>\S+)", re.IGNORECASE)


def _extract_ref_pin(description: str) -> tuple[str | None, str | None]:
    """Extract (ref, pin) from a KiCad ERC item description string."""
    if not description:
        return None, None
    match = _ITEM_RE.search(description)
    if not match:
        return None, None
    return match.group("ref"), match.group("pin")


def parse_erc_report(report_json: str) -> list[dict[str, Any]]:
    """Parse a ``kicad-cli sch erc --format json`` report.

    Returns a list of violation dicts matching the ``ERCViolation`` TypeScript
    interface from ``@cirqix/types`` (id, severity, message, type, ref, pin,
    x_mm, y_mm). Tolerant — returns ``[]`` on any parsing failure.
    """
    try:
        report = json.loads(report_json)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning("ERC report not valid JSON: %s", exc)
        return []

    if not isinstance(report, dict):
        return []

    raw_violations = report.get("violations")
    if not isinstance(raw_violations, list):
        return []

    out: list[dict[str, Any]] = []
    for raw in raw_violations:
        if not isinstance(raw, dict):
            continue
        severity = str(raw.get("severity", "warning")).lower()
        if severity not in ("error", "warning"):
            severity = "warning"
        message = str(raw.get("description", raw.get("type", "ERC violation")))
        v_type = str(raw.get("type", "")) or None

        items = raw.get("items")
        if isinstance(items, list) and items:
            for item in items:
                if not isinstance(item, dict):
                    continue
                ref, pin = _extract_ref_pin(str(item.get("description", "")))
                pos = item.get("pos") if isinstance(item.get("pos"), dict) else {}
                x_mm = pos.get("x") if isinstance(pos, dict) else None
                y_mm = pos.get("y") if isinstance(pos, dict) else None
                entry: dict[str, Any] = {
                    "id": str(item.get("uuid") or uuid.uuid4()),
                    "severity": severity,
                    "message": message,
                    "type": v_type,
                }
                if ref is not None:
                    entry["ref"] = ref
                if pin is not None:
                    entry["pin"] = pin
                if isinstance(x_mm, (int, float)):
                    entry["x_mm"] = float(x_mm)
                if isinstance(y_mm, (int, float)):
                    entry["y_mm"] = float(y_mm)
                out.append(entry)
        else:
            # No items — still keep the violation with just metadata
            out.append({
                "id": str(uuid.uuid4()),
                "severity": severity,
                "message": message,
                "type": v_type,
            })
    return out


def run_kicad_tools_erc(
    sch_content: str,
    auto_fix: bool = True,
) -> tuple[list[dict], str, int]:
    """kicad-tools Schematic.validate() — pure Python, no kicad-cli subprocess.

    Returns (violations, updated_sch_content, fixed_count).
    Fixes off-grid symbols and duplicate refs automatically when auto_fix=True.
    """
    import tempfile
    from pathlib import Path as _Path

    from kicad_tools.schematic.models.schematic import Schematic

    with tempfile.TemporaryDirectory() as tmp:
        sch_path = _Path(tmp) / "schematic.kicad_sch"
        sch_path.write_text(sch_content, encoding="utf-8")

        sch = Schematic.load(sch_path)
        issues = sch.validate(fix_auto=auto_fix)

        if auto_fix:
            sch.write(sch_path)
            fixed_content = sch_path.read_text(encoding="utf-8")
        else:
            fixed_content = sch_content

        violations: list[dict] = []
        fixed_count = 0
        for issue in issues:
            if issue.get("fix_applied"):
                fixed_count += 1
            violations.append({
                "id": str(uuid.uuid4()),
                "severity": issue.get("severity", "warning"),
                "message": issue.get("message", ""),
                "type": issue.get("type"),
            })

        return violations, fixed_content, fixed_count


def apply_no_connect_fixes(
    sch_content: str,
    violations: list[dict[str, Any]],
) -> tuple[str, int]:
    """Append-only auto-fix: add ``(no_connect ...)`` markers for unconnected pins.

    Returns ``(new_sch_content, fixed_count)``. The original ``sch_content`` is
    never mutated. ONLY ``pin_not_connected`` violations with both ``x_mm`` and
    ``y_mm`` produce a marker.

    Connectivity (symbols, wires, labels) is preserved char-for-char.
    """
    candidates = [
        v for v in violations
        if v.get("type") == "pin_not_connected"
        and isinstance(v.get("x_mm"), (int, float))
        and isinstance(v.get("y_mm"), (int, float))
    ]
    if not candidates:
        return sch_content, 0

    # Build the no_connect S-expression lines
    new_markers: list[str] = []
    for v in candidates:
        new_uuid = str(uuid.uuid4())
        marker = f'  (no_connect (at {v["x_mm"]} {v["y_mm"]}) (uuid "{new_uuid}"))'
        new_markers.append(marker)

    # Insert before the final closing paren of the top-level (kicad_sch ...) form.
    # Strategy: locate the LAST ")" in the content and inject markers before it.
    last_paren = sch_content.rfind(")")
    if last_paren < 0:
        logger.warning("ERC autofix: malformed .kicad_sch — no closing paren")
        return sch_content, 0

    head = sch_content[:last_paren]
    tail = sch_content[last_paren:]
    inserted = "\n".join(new_markers)
    # Ensure newline separation around the markers
    sep_before = "" if head.endswith("\n") else "\n"
    new_sch = f"{head}{sep_before}{inserted}\n{tail}"
    return new_sch, len(candidates)
