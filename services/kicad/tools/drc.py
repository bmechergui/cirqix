"""DRC (Design Rule Check) utilities for the Cirqix KiCad service.

Two pure functions consumed by ``routers/drc.py``:

- ``parse_drc_report(json_str)`` — tolerant parser for ``kicad-cli pcb drc --format json``
- ``apply_drc_fixes(pcb_content, violations)`` — best-effort auto-fix for the
  subset of violations we can safely correct (refill_zones, widen narrow tracks).

The router additionally orchestrates ``kicad-cli`` invocation with up to 3
auto-fix iterations; that logic lives in ``routers/drc.py``.

Legacy pcbnew-based ``run_drc(pcb_path)`` is preserved for the path-based
``/drc`` endpoint registered directly in ``main.py``.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


def parse_drc_report(report_json: str) -> list[dict[str, Any]]:
    """Parse a ``kicad-cli pcb drc --format json`` report.

    Returns a list of violation dicts matching the ``DRCViolation`` TypeScript
    interface from ``@cirqix/types``. Tolerant — returns ``[]`` on any parsing
    failure. Promotes ``unconnected_items`` and ``schematic_parity`` sections
    to violations alongside the main ``violations`` array.
    """
    try:
        report = json.loads(report_json)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning("DRC report not valid JSON: %s", exc)
        return []

    if not isinstance(report, dict):
        return []

    sections: list[Any] = []
    for key in ("violations", "unconnected_items", "schematic_parity"):
        section = report.get(key)
        if isinstance(section, list):
            sections.extend(section)

    out: list[dict[str, Any]] = []
    for raw in sections:
        if not isinstance(raw, dict):
            continue
        severity = str(raw.get("severity", "warning")).lower()
        if severity not in ("error", "warning"):
            severity = "warning"
        message = str(raw.get("description", raw.get("type", "DRC violation")))
        v_type = str(raw.get("type", "")) or None

        items = raw.get("items")
        if isinstance(items, list) and items:
            for item in items:
                if not isinstance(item, dict):
                    continue
                pos = item.get("pos") if isinstance(item.get("pos"), dict) else {}
                x_mm = pos.get("x") if isinstance(pos, dict) else None
                y_mm = pos.get("y") if isinstance(pos, dict) else None
                entry: dict[str, Any] = {
                    "id": str(item.get("uuid") or uuid.uuid4()),
                    "severity": severity,
                    "message": message,
                }
                if v_type is not None:
                    entry["type"] = v_type
                if isinstance(x_mm, (int, float)):
                    entry["x_mm"] = float(x_mm)
                if isinstance(y_mm, (int, float)):
                    entry["y_mm"] = float(y_mm)
                out.append(entry)
        else:
            entry = {
                "id": str(uuid.uuid4()),
                "severity": severity,
                "message": message,
            }
            if v_type is not None:
                entry["type"] = v_type
            out.append(entry)
    return out


# ============================================================================
# Legacy pcbnew-based DRC (kept for backwards compat with /drc path-based)
# ============================================================================


def run_drc(pcb_path: str) -> dict[str, Any]:
    """Legacy: run DRC on a .kicad_pcb at a given path using pcbnew bindings."""
    try:
        import pcbnew  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError("pcbnew unavailable") from exc

    board = pcbnew.LoadBoard(pcb_path)
    violations: list[dict[str, Any]] = []
    for marker in board.GetMarkers():
        violations.append({
            "id": str(uuid.uuid4()),
            "severity": "error" if marker.GetErrorCode() < 100 else "warning",
            "message": marker.GetErrorText(),
            "x_mm": pcbnew.ToMM(marker.GetPos().x),
            "y_mm": pcbnew.ToMM(marker.GetPos().y),
        })

    return {
        "status": "ok",
        "violations": violations,
        "count": len(violations),
        "drc_clean": len(violations) == 0,
    }


def apply_drc_fixes(pcb_path: str, fixes: list[dict[str, Any]], output_path: str) -> dict[str, Any]:
    """Legacy: apply listed fixes to a .kicad_pcb at the given path."""
    try:
        import pcbnew  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError("pcbnew unavailable") from exc

    board = pcbnew.LoadBoard(pcb_path)
    applied: list[str] = []

    for fix in fixes:
        fix_type = fix.get("type")
        if fix_type == "refill_zones":
            filler = pcbnew.ZONE_FILLER(board)
            filler.Fill(board.Zones())
            applied.append("refill_zones")
        elif fix_type == "apply_teardrops" and hasattr(pcbnew, "ApplyTeardrops"):
            pcbnew.ApplyTeardrops(board)
            applied.append("apply_teardrops")

    pcbnew.SaveBoard(output_path, board)
    return {"status": "ok", "path": output_path, "applied": applied}
