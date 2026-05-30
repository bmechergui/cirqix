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

def _generate_with_kicad_tools(
    kicad_sch_content: str,
    board_w: float,
    board_h: float,
) -> Optional[str]:
    """kicad-tools PCBFromSchematic → .kicad_pcb. Returns None on failure.

    Reads the .kicad_sch, exports netlist (kicad-cli or pure Python fallback),
    creates a blank PCB, adds footprints, assigns nets.
    """
    import tempfile as _tmp
    from kicad_tools.workflow import PCBFromSchematic

    with _tmp.TemporaryDirectory() as tmp:
        sch_path = Path(tmp) / "schematic.kicad_sch"
        pcb_path = Path(tmp) / "schematic.kicad_pcb"
        sch_path.write_text(kicad_sch_content, encoding="utf-8")

        workflow = PCBFromSchematic(sch_path)
        workflow.create_pcb(width=board_w, height=board_h, layers=2, title="Layrix PCB")
        workflow.place_all_components(spacing=15.0, margin=5.0)
        workflow.assign_nets()
        workflow.save(pcb_path)

        if pcb_path.exists():
            content = pcb_path.read_text(encoding="utf-8")
            logger.info("kicad-tools PCBFromSchematic: %d footprints", len(workflow.get_components()))
            return content
        return None


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


def generate_pcb(
    components: list[SchemaComponent],
    connections: list[SchemaNet],
    board_w: float,
    board_h: float,
    kicad_sch_content: Optional[str] = None,
) -> str:
    """Pipeline génération .kicad_pcb — 3 niveaux :
    1. kicad-tools PCBFromSchematic   — lit .kicad_sch, vrais footprints + nets complets
    2. Python pur depuis .kicad_sch   — Schematic.load() + extract_netlist() + S-expr natif
    3. '' → router success=False      → TypeScript runCircuitSynthEngine() fallback
    """
    # Niveau 1 : kicad-tools PCBFromSchematic
    if kicad_sch_content:
        try:
            content = _generate_with_kicad_tools(kicad_sch_content, board_w, board_h)
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
