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
import re
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Couches cuivre d'un .kicad_pcb : entrées ``(N "X.Cu" signal|power|…)`` de la
# section (layers …). Les couches non-cuivre (SilkS, Mask…) ne matchent pas.
_COPPER_LAYER_RE = re.compile(r'\(\s*\d+\s+"[^"]*\.Cu"\s+(?:signal|power|mixed|jumper)\b')


def copper_layer_count(pcb_text: str) -> int:
    """Nombre de couches cuivre du board (défaut 2 si section illisible)."""
    count = len(_COPPER_LAYER_RE.findall(pcb_text))
    return count if count >= 2 else 2


def write_mfr_project_sidecar(pcb_path: str | Path, tier: str, layers: int) -> Path:
    """Écrit ``<board>.kicad_pro`` avec les règles DRC du profil fabricant.

    Piste 4 — alignement du juge : kicad-cli charge le projet adjacent au
    board ; sans lui, les minima PAR DÉFAUT de KiCad (plus stricts que la
    géométrie d'un tier escaladé type via-in-pad) produisent des résiduels
    copper_edge/annular_width sans défaut réel. 100 % natif kicad-tools :
    ``get_profile().get_design_rules()`` + ``apply_manufacturer_rules``.

    Lève ValueError si le tier est inconnu (l'appelant décide du fallback).
    """
    from kicad_tools.core.project_file import (
        apply_manufacturer_rules,
        create_minimal_project,
        save_project,
        set_manufacturer_metadata,
    )
    from kicad_tools.manufacturers import get_profile

    profile = get_profile(tier)
    rules = profile.get_design_rules(layers, 1.0)

    pro_path = Path(pcb_path).with_suffix(".kicad_pro")
    data = create_minimal_project(pro_path.name)
    apply_manufacturer_rules(
        data,
        min_clearance_mm=rules.min_clearance_mm,
        min_track_width_mm=rules.min_trace_width_mm,
        min_via_diameter_mm=rules.min_via_diameter_mm,
        min_via_drill_mm=rules.min_via_drill_mm,
        min_annular_ring_mm=rules.min_annular_ring_mm,
        min_hole_diameter_mm=rules.min_hole_diameter_mm,
        min_copper_to_edge_mm=rules.min_copper_to_edge_mm,
    )
    set_manufacturer_metadata(data, manufacturer_id=profile.id,
                              layers=layers, copper_oz=1.0)
    save_project(data, pro_path)
    logger.info("DRC: sidecar %s écrit (tier %s, %d couches)",
                pro_path.name, profile.id, layers)
    return pro_path

# Marqueur kicad-cli d'un pad sans net dans items[].description (ex. pin NC).
# Dépendance locale kicad-cli : gettext peut traduire le marqueur. Mesuré :
# kicad-cli 10.99 en locale FR émet quand même « <no net> » (descriptions FR,
# marqueur EN) ; la variante FR est couverte par défense en profondeur.
# Direction de défaillance : conservatrice (marqueur non reconnu → la
# violation reste error, le waiver ne s'active pas).
_NC_PAD_MARKERS = ("<no net>", "<aucun réseau>")


def _is_nc_pad_clearance(violation: dict[str, Any]) -> bool:
    """True si la violation ``clearance`` implique un pad sans net (pin NC).

    Un pad ``<no net>`` ne peut pas créer de court-circuit — la violation est
    électriquement inoffensive (la lib kicad-tools exempte volontairement ce
    cas, carve-out KiCad #3490). Mesure réelle (board STM32 routé, 2026-07-06) :
    17/21 violations « clearance » = pins NC du LQFP-48 vs pistes d'escape.
    Ces violations sont reclassées ``warning`` : visibles mais non bloquantes
    pour ``drc_clean``.

    Opère sur le dict BRUT du rapport kicad-cli (avant aplatissement des
    ``items`` par ``parse_drc_report``, qui perd ``items[].description``).
    """
    if str(violation.get("type", "")) != "clearance":
        return False
    items = violation.get("items")
    if not isinstance(items, list):
        return False
    return any(
        isinstance(item, dict)
        and any(m in str(item.get("description", "")) for m in _NC_PAD_MARKERS)
        for item in items
    )


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
        # Carve-out pads NC : une clearance impliquant un pad <no net> est
        # électriquement inoffensive (pas de court possible) → reclassée
        # warning AVANT le calcul de drc_clean, mais conservée dans la sortie.
        if severity == "error" and _is_nc_pad_clearance(raw):
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
