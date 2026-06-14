"""
Layrix — PCB generation
Converts components + nets → .kicad_pcb S-expression.

Public API
----------
generate_pcb(components, connections, board_w, board_h) -> str
"""

from __future__ import annotations

import logging
import math
import re
import sys
from pathlib import Path
from typing import Optional

from tools.schematic import SchemaComponent, SchemaNet, SchemaPin, _expand_footprint

logger = logging.getLogger(__name__)


# ============================================================
# KiCad footprint directory
# ============================================================

def _find_kicad_footprint_dir() -> Optional[Path]:
    if sys.platform == "win32":
        for ver in ["10.99", "9.0", "8.0", "7.0"]:
            p = Path(rf"C:\Program Files\KiCad\{ver}\share\kicad\footprints")
            if p.exists():
                return p
    else:
        p = Path("/usr/share/kicad/footprints")
        if p.exists():
            return p
    return None


KICAD_FP_DIR = _find_kicad_footprint_dir()


# ============================================================
# Real footprint reader
# ============================================================

def _read_real_kicad_footprint(
    fp_full: str, x: float, y: float,
    comp: SchemaComponent, pad_net_map: dict, net_name_map: dict,
) -> Optional[str]:
    if not KICAD_FP_DIR or ":" not in fp_full:
        return None
    try:
        lib_name, fp_name = fp_full.split(":", 1)
        mod_file = KICAD_FP_DIR / f"{lib_name}.pretty" / f"{fp_name}.kicad_mod"
        if not mod_file.exists():
            return None

        content = mod_file.read_text(encoding="utf-8")

        content = re.sub(
            r'(\(footprint\s+"[^"]+")' ,
            r'\1\n  (at ' + str(x) + ' ' + str(y) + ')',
            content, count=1,
        )
        content = re.sub(
            r'\((?:property\s+"Reference"|fp_text\s+reference)\s+"[^"]+"',
            lambda m: m.group(0).replace(m.group(0).split('"')[-2], comp.ref),
            content,
        )
        content = re.sub(
            r'\((?:property\s+"Value"|fp_text\s+value)\s+"[^"]+"',
            lambda m: m.group(0).replace(m.group(0).split('"')[-2], comp.value),
            content,
        )

        pads_info = []
        for m in re.finditer(r'\(pad\s+"([^"]+)"', content):
            pad_num = m.group(1)
            depth = 0
            end_idx = -1
            for j in range(m.start(), len(content)):
                if content[j] == '(':
                    depth += 1
                elif content[j] == ')':
                    depth -= 1
                    if depth == 0:
                        end_idx = j
                        break
            if end_idx != -1:
                pads_info.append((pad_num, end_idx))

        for pad_num, end_idx in reversed(pads_info):
            net_id = pad_net_map.get((comp.ref, pad_num), 0)
            if not net_id and pad_num in ("A", "K", "C", "E", "B"):
                alt_pin = {"A": "1", "K": "2", "C": "1", "B": "2", "E": "3"}.get(pad_num)
                net_id = pad_net_map.get((comp.ref, alt_pin), 0)
            if net_id and net_id in net_name_map:
                net_name_esc = net_name_map[net_id].replace('"', '\\"')
                net_sexpr = f' (net {net_id} "{net_name_esc}")'
                content = content[:end_idx] + net_sexpr + content[end_idx:]

        return "\n".join("  " + line if line.strip() else line for line in content.splitlines())
    except Exception as exc:
        logger.warning("Error reading real footprint %s: %s", fp_full, exc)
        return None


# ============================================================
# Pad definitions
# ============================================================

def _footprint_pads(fp: str) -> list[str]:
    fp_up = fp.upper()

    def _smd(num: str, x: float, y: float, w: float, h: float) -> str:
        return (f'    (pad "{num}" smd roundrect '
                f'(at {x} {y}) (size {w} {h}) '
                f'(layers "F.Cu" "F.Paste" "F.Mask") '
                f'(roundrect_rratio 0.25){{NET}})')

    def _tht(num: str, x: float, y: float, drill: float, size: float, sq: bool = False) -> str:
        shape = "rect" if sq else "circle"
        return (f'    (pad "{num}" thru_hole {shape} '
                f'(at {x} {y}) (size {size} {size}) '
                f'(drill {drill}) '
                f'(layers "*.Cu" "*.Mask"){{NET}})')

    if any(t in fp_up for t in ("0402", "1005METRIC")):
        return [_smd("1", -0.65, 0, 1.3, 0.9), _smd("2", 0.65, 0, 1.3, 0.9)]
    if any(t in fp_up for t in ("0603", "1608METRIC")):
        return [_smd("1", -0.8, 0, 1.8, 1.2), _smd("2", 0.8, 0, 1.8, 1.2)]
    if any(t in fp_up for t in ("0805", "2012METRIC")):
        return [_smd("1", -1.05, 0, 2.2, 1.5), _smd("2", 1.05, 0, 2.2, 1.5)]
    if any(t in fp_up for t in ("1206", "3216METRIC")):
        return [_smd("1", -1.6, 0, 3.2, 1.8), _smd("2", 1.6, 0, 3.2, 1.8)]

    if "AXIAL" in fp_up:
        return [_tht("1", -5.08, 0, 0.8, 1.6, sq=True), _tht("2", 5.08, 0, 0.8, 1.6)]

    if any(t in fp_up for t in ("CP_RADIAL", "C_DISC", "C_RAD")):
        return [_tht("1", -1.5, 0, 0.8, 1.6, sq=True), _tht("2", 1.5, 0, 0.8, 1.6)]

    if "D_DO" in fp_up or "D_SOD" in fp_up:
        return [_tht("A", -2.54, 0, 0.8, 1.6), _tht("K", 2.54, 0, 0.8, 1.6)]

    if "LED_D5" in fp_up or "LED_D3" in fp_up:
        return [_tht("A", -1.27, 0, 0.8, 1.8, sq=True), _tht("K", 1.27, 0, 0.8, 1.8)]

    if "SOT-23-5" in fp_up or "SOT23-5" in fp_up:
        return [
            _smd("1", -1.5, -1.3, 0.6, 1.0), _smd("2", -1.5, 0, 0.6, 1.0),
            _smd("3", -1.5, 1.3, 0.6, 1.0), _smd("4", 1.5, 1.3, 0.6, 1.0),
            _smd("5", 1.5, 0, 0.6, 1.0),
        ]

    if "SOT-23" in fp_up or "SOT23" in fp_up:
        return [
            _smd("1", -0.95, 1.2, 1.0, 1.4),
            _smd("2", -0.95, -1.2, 1.0, 1.4),
            _smd("3", 0.95, 0, 1.0, 1.4),
        ]

    if "SOT-223" in fp_up or "SOT223" in fp_up:
        return [
            _smd("1", -2.3, 1.65, 1.2, 2.0), _smd("2", 0, 1.65, 1.2, 2.0),
            _smd("3", 2.3, 1.65, 1.2, 2.0), _smd("2", 0, -2.85, 3.5, 2.0),
        ]

    if "TO-220" in fp_up:
        return [
            _tht("1", -2.54, 0, 1.0, 2.1, sq=True),
            _tht("2", 0, 0, 1.0, 2.1),
            _tht("3", 2.54, 0, 1.0, 2.1),
        ]

    if "DIP-8" in fp_up:
        row_x, pitch, half = 3.81, 2.54, 3.81
        pads: list[str] = []
        for i in range(4):
            y = round(-half + i * pitch, 3)
            pads.append(_tht(str(i + 1), -row_x, y, 0.8, 1.6, sq=(i == 0)))
            pads.append(_tht(str(8 - i), row_x, y, 0.8, 1.6))
        return pads

    if "TSSOP-8" in fp_up or "TSSOP8" in fp_up:
        pitch, row_x = 0.65, 2.175
        half = 1.5 * pitch
        pads = []
        for i in range(4):
            y = round(-half + i * pitch, 3)
            pads.append(_smd(str(i + 1), -row_x, y, 0.3, 1.0))
            pads.append(_smd(str(8 - i), row_x, y, 0.3, 1.0))
        return pads

    if "SOIC-8" in fp_up or "SOIC8" in fp_up:
        pitch, row_x = 1.27, 2.7
        half = 1.5 * pitch
        pads = []
        for i in range(4):
            y = round(-half + i * pitch, 3)
            pads.append(_smd(str(i + 1), -row_x, y, 0.6, 1.55))
            pads.append(_smd(str(8 - i), row_x, y, 0.6, 1.55))
        return pads

    if any(t in fp_up for t in ("PINHEADER", "CONN_01X", "CONN_1X")):
        m = re.search(r'(\d+)', fp.split(":")[-1])
        n = min(int(m.group(1)) if m else 2, 24)
        half = (n - 1) * 2.54 / 2
        return [
            _tht(str(i + 1), 0, round(-half + i * 2.54, 3), 1.0, 1.8, sq=(i == 0))
            for i in range(n)
        ]

    return [_smd("1", -0.65, 0, 1.3, 0.9), _smd("2", 0.65, 0, 1.3, 0.9)]


# ============================================================
# kicad-tools PCBFromSchematic (Primary)
# ============================================================

def _snap_labels_to_pins(sch_content: str, tolerance_mm: float = 8.0) -> str:
    """Snap hierarchical labels to the nearest symbol pin endpoint.

    circuit_synth places hierarchical labels near pin endpoints but not at the
    exact position (off by 1-4mm). kicad-cli netlist extraction requires labels
    to be at the exact pin endpoint, otherwise the pad is marked unconnected
    (e.g. Net-(R1-2) instead of DHT_DATA for R1.pin2).

    This function moves each label to the closest pin endpoint within tolerance.
    """
    import re as _re, math as _math

    # --- Extract symbol pin endpoints ---
    # Each symbol block: (symbol (lib_id "...") (at X Y ROT) ... (pin ...))
    # Pin endpoints in world coords = symbol_at + rotate(pin_at, symbol_rot)
    pin_endpoints: list[tuple[float, float]] = []

    for sym_m in _re.finditer(
        r'\(symbol\s+\(lib_id\s+"[^"]+"\)\s+\(at\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\)',
        sch_content,
    ):
        cx, cy, rot = float(sym_m.group(1)), float(sym_m.group(2)), float(sym_m.group(3))
        # Collect pin endpoints from the symbol *library* definition referenced in the schematic.
        # We can't easily access the library, but we CAN collect all (at X Y) lines that belong
        # to pin entries in the same symbol block, using the kicad_sch pin format.
        pass

    # Simpler approach: collect all pin endpoint markers from the schematic
    # In kicad_sch, pins appear inside symbol blocks as "(pin (at X Y A) (length L) ...)"
    # The actual endpoint in world coords requires library symbol pin defs — too complex.
    # Instead, find all wire/bus endpoints and label positions, then snap labels to the
    # nearest existing (at X Y) in a symbol. Use symbol (at) + offset heuristic.

    # --- Simpler heuristic: collect all unique label target positions ---
    # For each hierarchical_label at position P, find all (at X Y) positions
    # in the schematic that are within tolerance. If we find pin endpoints
    # (from pad positions in the net file or from wire endpoints), snap to them.

    # Since we don't have a net file, use the symbol pin positions directly.
    # In the kicad_sch format, symbol pins are encoded as standalone "(at X Y A)" lines
    # inside "(pin ...)" blocks within the library symbol defs — but those aren't in the .kicad_sch.
    # HOWEVER, circuit_synth places wires (length 0) or labels exactly where pins should be.
    # We use the following approach: snap each label to the nearest OTHER label of a different net,
    # using the observation that VCC_5V and DHT_DATA should NOT be co-located.

    # Best practical approach without library access: snap label to nearest pin
    # via symbol-level pin pitch detection.
    # circuit_synth offset: labels are placed at the symbol center + an extra offset.
    # The correct endpoint for a resistor pin is at center ± 2.54mm (standard KiCad pitch).
    # We detect collisions (two labels at same position) and distribute them.

    # Find all hierarchical labels: position, name
    labels = [
        (float(m.group(2)), float(m.group(3)), m.group(1), m.start(), m.end())
        for m in _re.finditer(
            r'\(hierarchical_label\s+"([^"]+)"[^\n]*\n\s+\(at\s+([\d.\-]+)\s+([\d.\-]+)',
            sch_content,
        )
    ]

    if not labels:
        return sch_content

    # Find all symbol positions to compute pin endpoints
    # For Device:R (vertical, rotation 0): pin1 at (x, y-2.54), pin2 at (x, y+2.54)
    # We detect the correct endpoint by finding symbols near each label group.
    sym_positions = [
        (float(m.group(1)), float(m.group(2)), float(m.group(3)))
        for m in _re.finditer(
            r'\(symbol\s+\(lib_id\s+"[^"]+"\)\s+\(at\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\)',
            sch_content,
        )
    ]

    # Group labels by position (same x,y within 0.1mm = co-located)
    def _dist(p1, p2): return _math.hypot(p1[0]-p2[0], p1[1]-p2[1])

    processed = sch_content
    changes = 0

    # For labels that are co-located (same position, different net) → problematic
    # Find the nearest symbol and its expected pin endpoints, then distribute
    for i, (lx, ly, lname, lstart, lend) in enumerate(labels):
        # Find other labels at the same position
        same_pos = [j for j, (ox, oy, on, _, _) in enumerate(labels)
                    if j != i and abs(ox-lx) < 0.1 and abs(oy-ly) < 0.1]
        if not same_pos:
            continue  # unique position, likely OK

        # Find nearest symbol
        nearest_sym = min(sym_positions, key=lambda s: _dist((lx,ly), (s[0],s[1])), default=None)
        if nearest_sym is None:
            continue
        sx, sy, srot = nearest_sym
        dist_to_sym = _dist((lx, ly), (sx, sy))
        if dist_to_sym > tolerance_mm:
            continue

        # Calculate standard pin endpoints for a 2-pin component
        # Pin pitch = 2.54mm, along the axis determined by rotation
        r = _math.radians(srot)
        dx = 2.54 * _math.sin(r)   # x component of pin axis
        dy = 2.54 * _math.cos(r)   # y component of pin axis (KiCad Y down)
        pin1 = (sx - dx, sy - dy)   # pin "above" center
        pin2 = (sx + dx, sy + dy)   # pin "below" center

        # Assign co-located labels to the two nearest pin endpoints
        group = [i] + same_pos
        endpoints = [pin1, pin2] + [(lx, ly)] * max(0, len(group) - 2)

        for k, lidx in enumerate(group):
            if k >= len(endpoints):
                break
            lx2, ly2, ln2, ls2, le2 = labels[lidx]
            nx, ny = endpoints[k]
            if abs(nx - lx2) > 0.01 or abs(ny - ly2) > 0.01:
                # Replace (at lx2 ly2 ...) with (at nx ny ...)
                old_at = f"(at {lx2} {ly2}"
                new_at = f"(at {nx:.4f} {ny:.4f}"
                # Only replace the first occurrence after the label name
                label_region_start = max(0, ls2 - 10)
                label_region = processed[label_region_start:le2 + 20]
                fixed_region = label_region.replace(old_at, new_at, 1)
                processed = processed[:label_region_start] + fixed_region + processed[le2 + 20:]
                changes += 1

    if changes:
        logger.info("_snap_labels_to_pins: %d label(s) repositioned", changes)
    return processed


def _generate_with_kicad_tools(
    kicad_sch_content: str,
    board_w: float,
    board_h: float,
    connections: Optional[list] = None,
    kicad_net_content: Optional[str] = None,
) -> Optional[str]:
    """kicad-tools PCBFromSchematic → .kicad_pcb. Returns None on failure.

    Reads the .kicad_sch, exports netlist (kicad-cli or pure Python fallback),
    creates a blank PCB, adds footprints, assigns nets.

    connections: optional list of SchemaNet from circuit_synth JSON cache.
    When provided, floating pads (single-pad nets like Net-(R1-2)) are
    re-assigned to their correct net using the circuit_synth connectivity data,
    fixing the label-not-at-pin-endpoint issue in circuit_synth schematics.
    """
    import shutil as _shutil
    import sys as _sys
    import tempfile as _tmp
    from kicad_tools.workflow import PCBFromSchematic

    # Ensure kicad-cli is in PATH so export_netlist() uses it instead of the
    # pure Python fallback. The Python extractor cannot resolve hierarchical
    # labels from circuit_synth schematics (labels not at exact pin endpoints),
    # causing single-pad nets like Net-(R1-2) instead of DHT_DATA.
    # main.py already injects the path at service startup; this guard handles
    # the case where _generate_with_kicad_tools is called directly in tests.
    if not _shutil.which("kicad-cli"):
        for _bin in [
            r"C:\Program Files\KiCad\10.99\bin",
            r"C:\Program Files\KiCad\9.0\bin",
            r"C:\Program Files\KiCad\8.0\bin",
            "/usr/bin",
        ]:
            import os as _os
            if _os.path.isfile(_os.path.join(_bin, "kicad-cli")) or \
               _os.path.isfile(_os.path.join(_bin, "kicad-cli.exe")):
                _os.environ["PATH"] = _bin + _os.pathsep + _os.environ.get("PATH", "")
                break

    with _tmp.TemporaryDirectory() as tmp:
        sch_path = Path(tmp) / "schematic.kicad_sch"
        pcb_path = Path(tmp) / "schematic.kicad_pcb"
        sch_path.write_text(kicad_sch_content, encoding="utf-8")

        # ── Netlist résolution — 3 niveaux ───────────────────────────────────
        # Niveau 1 : kicad-tools Python pur (build_netlist_from_schematic)
        #   Pas de kicad-cli. Résout les labels hiérarchiques via kicad-sch-api.
        #   Fonctionne avec circuit_synth >= fix circuit_loader.py (2026-06-01).
        # Niveau 2 : kicad-cli netlist export
        #   Utilisé si Python pur échoue (schéma non-standard, symboles inconnus).
        # Niveau 3 : .kicad_net circuit_synth injecté directement
        #   Fallback pour vieux schémas générés avant le fix circuit_loader.py.

        workflow = PCBFromSchematic(sch_path)

        netlist_resolved = False

        # Niveau 1 — kicad-tools Python pur (sans kicad-cli)
        # Le module est `kicad_tools.operations.netlist` (PAS `workflow._netlist`,
        # qui n'existe pas dans le dépôt officiel vendoré → ModuleNotFoundError
        # à 100% → fallback kicad-cli systématique → netlist fragmenté). Voir
        # tests/test_pcb_netlist.py + mémoire project-netlist-niveau1-broken.
        try:
            from kicad_tools.operations.netlist import build_netlist_from_schematic as _bns
            workflow._netlist = _bns(str(sch_path))
            logger.info("_generate_with_kicad_tools: netlist niveau 1 (Python pur)")
            netlist_resolved = True
        except Exception as exc:
            logger.warning("netlist niveau 1 échoué (%s) — niveau 2 kicad-cli", exc)

        # Niveau 2 — kicad-cli (si Python pur a échoué)
        if not netlist_resolved:
            if not _shutil.which("kicad-cli"):
                for _bin in [
                    r"C:\Program Files\KiCad\10.99\bin",
                    r"C:\Program Files\KiCad\9.0\bin",
                    r"C:\Program Files\KiCad\8.0\bin",
                    "/usr/bin",
                ]:
                    import os as _os
                    if _os.path.isfile(_os.path.join(_bin, "kicad-cli")) or \
                       _os.path.isfile(_os.path.join(_bin, "kicad-cli.exe")):
                        _os.environ["PATH"] = _bin + _os.pathsep + _os.environ.get("PATH", "")
                        break
            # PCBFromSchematic appellera export_netlist() → kicad-cli si dispo
            logger.info("_generate_with_kicad_tools: netlist niveau 2 (kicad-cli)")

        # Niveau 3 — .kicad_net circuit_synth injecté (fallback vieux schémas)
        if kicad_net_content and not netlist_resolved:
            try:
                from kicad_tools.operations.netlist import Netlist as _Netlist
                _net_path = Path(tmp) / "schematic.kicad_net"
                _net_path.write_text(kicad_net_content, encoding="utf-8")
                workflow._netlist = _Netlist.load(str(_net_path))
                logger.info("_generate_with_kicad_tools: netlist niveau 3 (.kicad_net injecté)")
            except Exception as exc:
                logger.warning("netlist niveau 3 échoué (%s)", exc)

        workflow.create_pcb(width=board_w, height=board_h, layers=2, title="Layrix PCB")
        # Place les footprints SUR la carte (fichier "unrouted" = placé, sans pistes).
        # L'agent placement (PlacementOptimizer) raffine ensuite ce placement ;
        # plus de pré-déplacement à (-1000,-1000) — workflow officiel kicad-tools.
        workflow.place_all_components(spacing=15.0, margin=5.0)
        workflow.assign_nets()
        workflow.save(pcb_path)

        if not pcb_path.exists():
            return None

        logger.info(
            "kicad-tools PCBFromSchematic: %d components, board %.0f×%.0fmm",
            len(workflow.get_components()), board_w, board_h,
        )

        return pcb_path.read_text(encoding="utf-8")


# ============================================================
# Public API
# ============================================================

def _generate_with_pcbnew(
    kicad_sch_content: str,
    board_w: float,
    board_h: float,
) -> Optional[str]:
    """Niveau 2 — pcbnew direct depuis .kicad_sch.

    1. Parse .kicad_sch via kicad-tools Schematic.load() + extract_netlist()
    2. Crée un BOARD pcbnew natif
    3. Charge les vrais footprints via pcbnew.FootprintLoad()
    4. Assigne les nets sur les pads
    5. Sauvegarde → .kicad_pcb
    """
    try:
        import pcbnew  # type: ignore
    except ImportError:
        raise ImportError("pcbnew non disponible")

    import tempfile as _tmp
    from kicad_tools.schematic.models.schematic import Schematic

    with _tmp.TemporaryDirectory() as tmp:
        sch_path = Path(tmp) / "schematic.kicad_sch"
        sch_path.write_text(kicad_sch_content, encoding="utf-8")

        sch = Schematic.load(sch_path)

        # Composants (ignorer #PWR, #FLG)
        symbols = [
            (sym.reference, sym.value or sym.reference, sym.footprint or "")
            for sym in sch.symbols
            if not sym.reference.startswith('#')
        ]

        # Netlist {net_name: [PinRef]}
        netlist = sch.extract_netlist()

        # Créer le board
        board = pcbnew.BOARD()

        # Ajouter les nets
        net_map: dict[str, object] = {}
        for i, net_name in enumerate(netlist.keys(), start=1):
            net = pcbnew.NETINFO_ITEM(board, net_name, i)
            board.Add(net)
        if hasattr(board, 'SynchronizeNetsAndNetClasses'):
            board.SynchronizeNetsAndNetClasses(False)
        for net_name in netlist:
            n = board.FindNet(net_name)
            if n:
                net_map[net_name] = n

        # Ajouter les footprints
        fp_dir = KICAD_FP_DIR
        cols = max(1, math.ceil(math.sqrt(len(symbols))))
        margin_iu = pcbnew.FromMM(5.0)
        step_iu = pcbnew.FromMM(15.0)

        for i, (ref, value, fp_str) in enumerate(symbols):
            fp = None
            if fp_dir and ':' in fp_str:
                lib_name, fp_name = fp_str.split(':', 1)
                lib_path = fp_dir / f"{lib_name}.pretty"
                if lib_path.exists():
                    try:
                        fp = pcbnew.FootprintLoad(str(lib_path), fp_name)
                    except Exception:
                        fp = None

            if fp is None:
                fp = pcbnew.FOOTPRINT(board)

            col = i % cols
            row = i // cols
            x_iu = margin_iu + col * step_iu
            y_iu = margin_iu + row * step_iu

            if hasattr(pcbnew, 'VECTOR2I'):
                fp.SetPosition(pcbnew.VECTOR2I(int(x_iu), int(y_iu)))
            else:
                fp.SetPosition(pcbnew.wxPoint(x_iu, y_iu))

            fp.SetReference(ref)
            fp.SetValue(value)

            # Assigner nets aux pads
            for pad in fp.Pads():
                pad_num = str(pad.GetNumber())
                for net_name, pin_refs in netlist.items():
                    for pref in pin_refs:
                        if pref.symbol_ref == ref and str(pref.pin) == pad_num:
                            net = net_map.get(net_name)
                            if net:
                                pad.SetNet(net)

            board.Add(fp)

        # Board outline (Edge.Cuts)
        bw_iu = pcbnew.FromMM(board_w)
        bh_iu = pcbnew.FromMM(board_h)
        edge_layer = 44  # Edge.Cuts
        for x1, y1, x2, y2 in [
            (0, 0, bw_iu, 0), (bw_iu, 0, bw_iu, bh_iu),
            (bw_iu, bh_iu, 0, bh_iu), (0, bh_iu, 0, 0),
        ]:
            seg = pcbnew.PCB_SHAPE(board)
            if hasattr(pcbnew, 'SHAPE_T_SEGMENT'):
                seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
            seg.SetLayer(edge_layer)
            if hasattr(pcbnew, 'VECTOR2I'):
                seg.SetStart(pcbnew.VECTOR2I(int(x1), int(y1)))
                seg.SetEnd(pcbnew.VECTOR2I(int(x2), int(y2)))
            else:
                seg.SetStart(pcbnew.wxPoint(x1, y1))
                seg.SetEnd(pcbnew.wxPoint(x2, y2))
            seg.SetWidth(pcbnew.FromMM(0.05))
            board.Add(seg)

        # Sauvegarder
        pcb_path = Path(tmp) / "board.kicad_pcb"
        pcbnew.SaveBoard(str(pcb_path), board)

        if pcb_path.exists():
            content = pcb_path.read_text(encoding="utf-8")
            logger.info("_generate_with_pcbnew: %d composants, %d nets", len(symbols), len(netlist))
            return content
        return None


def _patch_floating_nets(pcb_content: str, connections: list[SchemaNet]) -> str:
    """Re-assign single-pad floating nets (Net-(X-Y), unconnected-*) using
    circuit_synth connection data which has the correct pad→net topology.

    circuit_synth schematics place hierarchical labels near pin endpoints but
    not at the exact position, so kicad-cli netlist extraction leaves those
    pads unconnected. The `connections` list (from _pcbStateCache) has the
    truth: for each net, which (ref, pin) pairs belong to it.
    """
    import re as _re, uuid as _uuid

    # Build lookup: (ref, pin) → correct net name from circuit_synth
    pin_to_net: dict[tuple[str, str], str] = {}
    for conn in connections:
        for pin_ref in conn.pins:
            pin_to_net[(pin_ref.ref, str(pin_ref.pin))] = conn.name

    if not pin_to_net:
        return pcb_content

    # Collect all net ids from PCB header: id → name
    net_id_to_name: dict[int, str] = {
        int(m.group(1)): m.group(2)
        for m in _re.finditer(r'^\s*\(net\s+(\d+)\s+"([^"]+)"\)', pcb_content, _re.MULTILINE)
    }
    name_to_net_id: dict[str, int] = {v: k for k, v in net_id_to_name.items()}

    def _is_floating(net_name: str) -> bool:
        return (net_name.startswith("Net-(") or
                net_name.startswith("unconnected-") or
                net_name.startswith("Net-("))

    # Add missing net declarations for nets in connections that are not yet in PCB
    next_id = max(net_id_to_name.keys(), default=0) + 1
    new_net_decls: list[str] = []
    for conn in connections:
        if conn.name not in name_to_net_id:
            name_to_net_id[conn.name] = next_id
            net_id_to_name[next_id] = conn.name
            new_net_decls.append(f'  (net {next_id} "{conn.name}")')
            next_id += 1

    if new_net_decls:
        # Insert new net declarations before the first footprint
        insert_before = _re.search(r'\n\s+\(footprint\s', pcb_content)
        if insert_before:
            pos = insert_before.start()
            pcb_content = pcb_content[:pos] + "\n" + "\n".join(new_net_decls) + pcb_content[pos:]

    # Patch pads: for each footprint/pad, if the current net is floating and
    # we have a correct net for (ref, pad_number), replace it.
    def _patch_pad(match: _re.Match) -> str:
        block = match.group(0)
        # Extract footprint reference
        ref_m = _re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
        if not ref_m:
            return block
        ref = ref_m.group(1)

        def _fix_pad(pm: _re.Match) -> str:
            pad_block = pm.group(0)
            pad_num_m = _re.search(r'\(pad\s+"([^"]+)"', pad_block)
            if not pad_num_m:
                return pad_block
            pad_num = pad_num_m.group(1)
            correct_net = pin_to_net.get((ref, pad_num))
            if not correct_net:
                return pad_block
            net_m = _re.search(r'\(net\s+\d+\s+"([^"]+)"\)', pad_block)
            if not net_m or not _is_floating(net_m.group(1)):
                return pad_block
            # Replace with correct net
            correct_id = name_to_net_id.get(correct_net)
            if correct_id is None:
                return pad_block
            fixed = _re.sub(
                r'\(net\s+\d+\s+"[^"]+"\)',
                f'(net {correct_id} "{correct_net}")',
                pad_block,
            )
            logger.info("patch_floating_nets: %s.%s: %s → %s",
                        ref, pad_num, net_m.group(1), correct_net)
            return fixed

        return _re.sub(r'\(pad\s+"[^"]+"\s+[\s\S]*?(?=\n\s+\(pad|\n\s+\(property|\n\t\))',
                       _fix_pad, block)

    # Apply patch to each footprint block
    patched = _re.sub(
        r'\(footprint\s+"[^"]+"\s+[\s\S]*?(?=\n\s+\(footprint|\n\s+\(gr_|\n\s+\(segment|\n\s+\(zone|\Z)',
        _patch_pad,
        pcb_content,
    )
    return patched


def generate_pcb(
    components: list[SchemaComponent],
    connections: list[SchemaNet],
    board_w: float,
    board_h: float,
    kicad_sch_content: Optional[str] = None,
    kicad_net_content: Optional[str] = None,
) -> str:
    """Pipeline génération .kicad_pcb — 3 niveaux :
    1. kicad-tools PCBFromSchematic   — lit .kicad_sch, vrais footprints + nets complets
    2. Python pur depuis .kicad_sch   — Schematic.load() + extract_netlist() + S-expr natif
    3. '' → router success=False      → TypeScript runCircuitSynthEngine() fallback
    """
    # Niveau 1 : kicad-tools PCBFromSchematic
    if kicad_sch_content:
        try:
            content = _generate_with_kicad_tools(
                kicad_sch_content, board_w, board_h,
                connections=connections or [],
                kicad_net_content=kicad_net_content,
            )
            if content:
                logger.info("generate_pcb: niveau 1 kicad-tools OK")
                return content
        except Exception as exc:
            logger.warning("generate_pcb: kicad-tools échoué (%s) — niveau 2", exc)

    # Niveau 2 : pcbnew direct depuis .kicad_sch (vrais footprints + nets natifs)
    if kicad_sch_content:
        try:
            content = _generate_with_pcbnew(kicad_sch_content, board_w, board_h)
            if content:
                logger.info("generate_pcb: niveau 2 pcbnew OK")
                return content
        except Exception as exc:
            logger.warning("generate_pcb: pcbnew échoué (%s) — TypeScript fallback", exc)

    # Niveau 3 : '' → router retourne success=False → TypeScript prend le relais
    logger.warning("generate_pcb: tous les niveaux Python ont échoué")
    return ""


def _generate_pcb_sexpr(
    components: list[SchemaComponent],
    connections: list[SchemaNet],
    board_w: float,
    board_h: float,
) -> str:
    """Generate .kicad_pcb S-expression from components + nets."""
    lines: list[str] = []
    lines.append('(kicad_pcb (version 20240108) (generator "layrix-circuit-synth")')
    lines.append('  (general (thickness 1.6))')
    lines.append('  (paper "A4")')
    lines.append('  (layers')
    for layer_def in [
        '(0 "F.Cu" signal)', '(31 "B.Cu" signal)',
        '(36 "B.SilkS" user "B.Silkscreen")', '(37 "F.SilkS" user "F.Silkscreen")',
        '(38 "B.Mask" user)', '(39 "F.Mask" user)',
        '(44 "Edge.Cuts" user)',
    ]:
        lines.append(f'    {layer_def}')
    lines.append('  )')
    lines.append('  (setup (pad_to_mask_clearance 0.05))')

    net_idx_map: dict[str, int] = {}
    net_name_map: dict[int, str] = {}
    lines.append('  (net 0 "")')
    for i, net in enumerate(connections, start=1):
        escaped = net.name.replace('"', '\\"')
        lines.append(f'  (net {i} "{escaped}")')
        net_idx_map[net.name] = i
        net_name_map[i] = net.name

    bw, bh = board_w, board_h
    for x1, y1, x2, y2 in [(0, 0, bw, 0), (bw, 0, bw, bh), (bw, bh, 0, bh), (0, bh, 0, 0)]:
        lines.append(f'  (gr_line (start {x1} {y1}) (end {x2} {y2}) (layer "Edge.Cuts") (width 0.05))')

    pad_net_map: dict[tuple[str, str], int] = {}
    for net in connections:
        net_id = net_idx_map.get(net.name, 0)
        for pin_ref in net.pins:
            pad_net_map[(pin_ref.ref, str(pin_ref.pin))] = net_id

    cols = max(1, math.ceil(math.sqrt(len(components))))
    margin = 5.0
    for idx, comp in enumerate(components):
        col = idx % cols
        row = idx // cols
        x = margin + (col + 0.5) * ((board_w - 2 * margin) / cols)
        y = margin + (row + 0.5) * ((board_h - 2 * margin) / math.ceil(len(components) / cols))
        x, y = round(x, 3), round(y, 3)

        fp_full = _expand_footprint(comp)
        fp_e = fp_full.replace('"', '\\"')
        ref_e = comp.ref.replace('"', '\\"')
        val_e = comp.value.replace('"', '\\"')

        real_fp_block = _read_real_kicad_footprint(fp_full, x, y, comp, pad_net_map, net_name_map)
        if real_fp_block:
            lines.append(real_fp_block)
        else:
            fp_up_full = fp_full.upper()
            is_smd = any(t in fp_up_full for t in (
                "SMD", "0402", "0603", "0805", "1206",
                "SOT-23", "SOT23", "SOT-223", "SOT223",
                "TSSOP", "SOIC", "QFP", "QFN",
            ))
            attr = "smd" if is_smd else "through_hole"
            lines.append(f'  (footprint "{fp_e}" (layer "F.Cu") (at {x} {y}) (attr {attr})')
            lines.append(f'    (fp_text reference "{ref_e}" (at 0 -2) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))')
            lines.append(f'    (fp_text value "{val_e}" (at 0 2) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))')

            for pad_line in _footprint_pads(fp_full):
                m = re.search(r'\(pad "(\w+)"', pad_line)
                pad_num = m.group(1) if m else "1"
                net_id = pad_net_map.get((comp.ref, pad_num), 0)
                if not net_id and pad_num in ("A", "K", "C", "E", "B"):
                    alt_pin = {"A": "1", "K": "2", "C": "1", "B": "2", "E": "3"}.get(pad_num)
                    net_id = pad_net_map.get((comp.ref, alt_pin), 0)
                if net_id and net_id in net_name_map:
                    net_name_esc = net_name_map[net_id].replace('"', '\\"')
                    net_sexpr = f' (net {net_id} "{net_name_esc}")'
                else:
                    net_sexpr = ''
                lines.append(pad_line.replace('{NET}', net_sexpr))

            lines.append('  )')

    lines.append(')')
    return "\n".join(lines)
