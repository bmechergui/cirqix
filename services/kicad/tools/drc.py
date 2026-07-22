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


def _micro_via_policy() -> tuple[float, float]:
    """Géométrie (size, drill) des microvias via-in-pad posées par kct.

    Même source de vérité que ``kicad_tools.router.escape`` : les env vars
    ``KICAD_TOOLS_MICRO_VIA_SIZE`` / ``KICAD_TOOLS_MICRO_VIA_DRILL`` avec les
    mêmes défauts (0.3/0.15). Le juge et le fix via-in-pad doivent suivre la
    politique du routeur, pas la re-déclarer.
    """
    import os
    try:
        size = float(os.environ.get("KICAD_TOOLS_MICRO_VIA_SIZE", "0.3"))
    except ValueError:
        size = 0.3
    try:
        drill = float(os.environ.get("KICAD_TOOLS_MICRO_VIA_DRILL", "0.15"))
    except ValueError:
        drill = 0.15
    return size, drill


def write_mfr_project_sidecar(
    pcb_path: str | Path, tier: str, layers: int,
    pcb_text: str | None = None,
) -> Path:
    """Écrit ``<board>.kicad_pro`` avec les règles DRC du profil fabricant.

    Piste 4 — alignement du juge : kicad-cli charge le projet adjacent au
    board ; sans lui, les minima PAR DÉFAUT de KiCad (plus stricts que la
    géométrie d'un tier escaladé type via-in-pad) produisent des résiduels
    copper_edge/annular_width sans défaut réel. 100 % natif kicad-tools :
    ``get_profile().get_design_rules()`` + ``apply_manufacturer_rules``.

    Chantier DRC-clean (2026-07-19), deux alignements supplémentaires :

    - **Netclass Default = règles du tier.** Sans ``net_settings`` dans le
      sidecar, kicad-cli retombe sur la netclass Default de KiCad (clearance
      0,2 mm) et juge PLUS STRICT que le routeur (0,127 au tier1) → faux
      positifs garantis sur les escapes fine-pitch (mesuré runs 7/9 : 5+1
      violations clearance éliminées par cet alignement).
    - **Règle .kicad_dru microvia** (si ``pcb_text`` contient des microvias) :
      la politique via-in-pad de kct pose des microvias 0,3/0,15 (annular
      0,075) alors que le profil déclare annular min 0,15 — impossible pour
      sa propre géométrie. La règle est scopée ``A.Via_Type == 'Micro'`` :
      les vias traversants restent jugés à l'annular du profil (validé
      empiriquement : 5 annular_width → 0 sur les runs 7 et 9).

    Lève ValueError si le tier est inconnu (l'appelant décide du fallback).
    """
    from kicad_tools.core.project_file import (
        apply_manufacturer_rules,
        create_minimal_project,
        get_netclass_definitions,
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
    micro_size, micro_drill = _micro_via_policy()
    for netclass in get_netclass_definitions(data):
        if netclass.get("name") == "Default":
            netclass["clearance"] = rules.min_clearance_mm
            netclass["track_width"] = rules.min_trace_width_mm
            netclass["via_diameter"] = rules.min_via_diameter_mm
            netclass["via_drill"] = rules.min_via_drill_mm
            netclass["microvia_diameter"] = micro_size
            netclass["microvia_drill"] = micro_drill
    set_manufacturer_metadata(data, manufacturer_id=profile.id,
                              layers=layers, copper_oz=1.0)
    save_project(data, pro_path)

    if pcb_text and "(via micro" in pcb_text:
        annular = round((micro_size - micro_drill) / 2, 4)
        dru_path = pro_path.with_suffix(".kicad_dru")
        dru_path.write_text(
            '(version 1)\n'
            '(rule "cirqix-microvia-annular"\n'
            "  (condition \"A.Via_Type == 'Micro'\")\n"
            f'  (constraint annular_width (min {annular:g}mm)))\n',
            encoding="utf-8")
        logger.info("DRC: règle .kicad_dru microvia écrite (annular %.3f mm)",
                    annular)

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
                # Description de l'ITEM (≠ message de la violation) : le fix
                # via-in-pad doit savoir QUEL pad est orphelin (« Pad 8 [GND]
                # de U2 sur F.Cu ») — le message seul ne le dit pas.
                item_desc = str(item.get("description", ""))
                if item_desc:
                    entry["item"] = item_desc
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
# Fix via-in-pad — pads d'un net « plan » restés orphelins
# ============================================================================

# « Pad 8 [GND] de U2 sur F.Cu » (FR) / « Pad 8 [GND] of U2 on F.Cu » (EN) —
# seul le préfixe « Pad <n> [<net>] » est exploité, insensible à la locale.
_PAD_ITEM_RE = re.compile(r"^Pad\s+\S+\s+\[([^\]]+)\]")


def _zone_net_names(pcb_text: str) -> set[str]:
    """Noms des nets portés par au moins une zone cuivre du board."""
    names: set[str] = set()
    for m in re.finditer(r"\(zone\b", pcb_text):
        blk = pcb_text[m.start():m.start() + 400]
        name = re.search(r'\(net_name\s+"([^"]*)"', blk) or \
            re.search(r'\(net\s+(?:\d+\s+)?"([^"]*)"', blk)
        if name and name.group(1):
            names.add(name.group(1))
    return names


# Garde-fou géométrique du via-in-pad : marges CONSERVATRICES (indépendantes
# du tier — un via refusé laisse la violation unconnected visible, un via mal
# posé crée un court réel : l'asymétrie justifie la prudence).
_VIA_GUARD_CLEARANCE_MM: float = 0.2       # netclass Default KiCad
_VIA_GUARD_HOLE_CLEARANCE_MM: float = 0.25  # règle hole_clearance par défaut

_SEGMENT_BLOCK_RE = re.compile(
    r"\(segment\s*\n?\s*\(start\s+([-\d.]+)\s+([-\d.]+)\)\s*\n?\s*"
    r"\(end\s+([-\d.]+)\s+([-\d.]+)\)\s*\n?\s*\(width\s+([-\d.]+)\)"
    r"[\s\S]{0,200}?\(net\s+(\d+)\)")
_VIA_BLOCK_RE = re.compile(
    r"\(via[\s\n](?:micro[\s\n])?[\s\S]{0,120}?\(at\s+([-\d.]+)\s+([-\d.]+)\)"
    r"\s*\n?\s*\(size\s+([-\d.]+)\)[\s\S]{0,300}?\(net\s+(\d+)\)")


def _collect_copper_obstacles(pcb_text: str) -> list[tuple[float, float, float, float, float, int]]:
    """(x1, y1, x2, y2, demi-largeur, net) pour chaque segment/via du board.

    Un via est modélisé comme un segment dégénéré (start == end). Les pads ne
    sont PAS inclus (coordonnées relatives au footprint + rotation — hors de
    portée d'un parseur texte sûr) : mesuré runs 7/9, les conflits réels du
    via-in-pad sont des pistes, jamais les pads voisins.
    """
    out: list[tuple[float, float, float, float, float, int]] = []
    for m in _SEGMENT_BLOCK_RE.finditer(pcb_text):
        x1, y1, x2, y2, w, net = m.groups()
        out.append((float(x1), float(y1), float(x2), float(y2),
                    float(w) / 2, int(net)))
    for m in _VIA_BLOCK_RE.finditer(pcb_text):
        x, y, size, net = m.groups()
        out.append((float(x), float(y), float(x), float(y),
                    float(size) / 2, int(net)))
    return out


def _point_segment_distance(px: float, py: float, x1: float, y1: float,
                            x2: float, y2: float) -> float:
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    cx, cy = x1 + t * dx, y1 + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def _via_position_is_safe(
    obstacles: list[tuple[float, float, float, float, float, int]],
    x: float, y: float, via_size: float, via_drill: float, via_net: int,
) -> bool:
    """True si un via (size/drill) posé en (x, y) ne crée ni court ni
    violation hole_clearance contre les pistes/vias d'un AUTRE net."""
    guard = max(via_size / 2 + _VIA_GUARD_CLEARANCE_MM,
                via_drill / 2 + _VIA_GUARD_HOLE_CLEARANCE_MM)
    for x1, y1, x2, y2, half_w, net in obstacles:
        if net == via_net:
            continue
        if _point_segment_distance(x, y, x1, y1, x2, y2) - half_w < guard:
            return False
    return True


def add_zone_via_for_unconnected_pads(
    pcb_text: str, violations: list[dict[str, Any]],
) -> tuple[str, int]:
    """Ajoute un via-in-pad micro sur chaque pad orphelin d'un net « plan ».

    Cause racine (mesurée runs 7/9 stm32-validation) : sur un LQFP fine-pitch,
    les pads GND peuvent être ENCERCLÉS par les pistes d'escape sur leur
    couche — ni frein thermique ni connexion solid ne peuvent les atteindre
    (4-5 unconnected_items par board, insensibles au refill). La réponse
    industrielle du tier via-in-pad : un via micro au centre du pad vers le
    plan de l'autre face (géométrie = politique kct, cf. ``_micro_via_policy``).

    Garde-fous :
    - uniquement les violations ``unconnected_items`` dont l'item est un pad
      ``Pad n [NET]`` avec position, et dont le net porte une zone ;
    - boards 2 couches uniquement (le via écrit F.Cu↔B.Cu ; sur >2 couches
      une microvia F↔B serait illégale) ;
    - garde-fou géométrique (``_via_position_is_safe``) : pose refusée si une
      piste/via d'un autre net passe sous ou près du pad — mesuré run 7, un
      via aveugle courtcircuitait USER_LED en B.Cu et créait des
      hole_clearance contre NRST/+3.3V. Mieux vaut laisser l'unconnected
      visible que créer un court ;
    - dédupe intra-appel ET vs vias existants (ré-application = no-op —
      la boucle auto-fix DRC peut repasser plusieurs fois).
    """
    if copper_layer_count(pcb_text) != 2:
        return pcb_text, 0

    zone_nets = _zone_net_names(pcb_text)
    if not zone_nets:
        return pcb_text, 0

    net_numbers: dict[str, str] = {
        name: num for num, name in re.findall(r'\(net (\d+) "([^"]+)"\)', pcb_text)
    }

    size, drill = _micro_via_policy()
    obstacles = _collect_copper_obstacles(pcb_text)
    additions: list[str] = []
    seen: set[tuple[str, str]] = set()
    for v in violations:
        if v.get("type") != "unconnected_items":
            continue
        m = _PAD_ITEM_RE.match(str(v.get("item", "")))
        if not m:
            continue
        net = m.group(1)
        if net not in zone_nets or net not in net_numbers:
            continue
        x, y = v.get("x_mm"), v.get("y_mm")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            continue
        at = f"(at {x:g} {y:g})"
        if (net, at) in seen or at in pcb_text:
            continue
        if not _via_position_is_safe(obstacles, float(x), float(y), size, drill,
                                     int(net_numbers[net])):
            logger.info("via-in-pad refusé en %s [%s] — cuivre étranger trop "
                        "proche (le pad reste orphelin, pas de court créé)",
                        at, net)
            continue
        seen.add((net, at))
        additions.append(
            f'  (via micro {at} (size {size:g}) (drill {drill:g}) '
            f'(layers "F.Cu" "B.Cu") (net {net_numbers[net]}))')

    if not additions:
        return pcb_text, 0

    stripped = pcb_text.rstrip()
    if not stripped.endswith(")"):
        logger.warning("via-in-pad fix: .kicad_pcb malformé — aucun via ajouté")
        return pcb_text, 0
    out = stripped[:-1].rstrip() + "\n" + "\n".join(additions) + "\n)\n"
    logger.info("DRC auto-fix: %d via(s)-in-pad micro ajoutés vers le plan "
                "(%s)", len(additions),
                ", ".join(sorted({n for n, _ in seen})))
    return out, len(additions)


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
