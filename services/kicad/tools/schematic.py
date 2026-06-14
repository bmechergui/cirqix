"""
Layrix — Schematic generation
Primary  : circuit_synth pip (_generate_with_cs_lib)
Fallback : S-expression hand-written generator (_generate_schematic_fallback)

Public API
----------
generate_schematic(components, connections, board_w, board_h, project_id) -> str
execute_cs_code(code, project_id, board_w, board_h) -> tuple[str, str]
validate_symbols(components) -> tuple[list[dict], list[SchemaComponent], bool]
"""

from __future__ import annotations

import concurrent.futures
import logging
import math
import os
import re
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Optional, Union

from pydantic import BaseModel

logger = logging.getLogger(__name__)

os.environ.setdefault("PYTHONUTF8", "1")


# ============================================================
# Domain types (imported by router + tools/pcb.py)
# ============================================================

class SchemaPin(BaseModel):
    ref: str
    pin: Union[int, str]


class SchemaNet(BaseModel):
    name: str
    pins: list[SchemaPin]


class SchemaComponent(BaseModel):
    ref: str
    value: str
    footprint: str
    symbol: Optional[str] = None
    lcsc: Optional[str] = None


# ============================================================
# Symbol mapping (JSON → KiCad symbol id)
# ============================================================

_SYMBOL_RULES: list[tuple[tuple[str, str], str]] = [
    (("NE555", ""), "Timer:NE555P"),
    (("LM555", ""), "Timer:NE555P"),
    (("NA555", ""), "Timer:NE555P"),
    (("SA555", ""), "Timer:NE555P"),
    (("TLC555", ""), "Timer:NE555P"),
    (("ICM7555", ""), "Timer:NE555P"),
    (("LM7805", ""), "Regulator_Linear:L7805"),
    (("L7805", ""), "Regulator_Linear:L7805"),
    (("LM7812", ""), "Regulator_Linear:L7812"),
    (("LM317", ""), "Regulator_Linear:LM317_TO-220"),
    (("LM1117", "3.3"), "Regulator_Linear:LM1117T-3.3"),
    (("LM1117", "5"), "Regulator_Linear:LM1117T-5.0"),
    (("LM1117", ""), "Regulator_Linear:LM1117T-3.3"),
    (("LM358", ""), "Amplifier_Operational:LM358"),
    (("LM741", ""), "Amplifier_Operational:LM741"),
    (("1N4148", ""), "Diode:1N4148"),
    (("1N4001", ""), "Diode:1N4001"),
    (("1N4007", ""), "Diode:1N4007"),
    (("BC547", ""), "Transistor_BJT:BC547"),
    (("BC557", ""), "Transistor_BJT:BC557"),
    (("2N3904", ""), "Transistor_BJT:2N3904"),
    (("2N3906", ""), "Transistor_BJT:2N3906"),
    (("BC337", ""), "Transistor_BJT:BC337"),
    (("", "CONN_01X01"), "Connector_Generic:Conn_01x01"),
    (("", "CONN_01X02"), "Connector_Generic:Conn_01x02"),
    (("", "CONN_01X03"), "Connector_Generic:Conn_01x03"),
    (("", "CONN_01X04"), "Connector_Generic:Conn_01x04"),
    (("", "PINHEADER_1X02"), "Connector_Generic:Conn_01x02"),
    (("", "PINHEADER_1X03"), "Connector_Generic:Conn_01x03"),
    (("", "PINHEADER_1X04"), "Connector_Generic:Conn_01x04"),
    (("", "PINHEADER_2X"), "Connector_Generic:Conn_02x02"),
    (("LED", ""), "Device:LED"),
    (("", "LED_THT"), "Device:LED"),
    (("", "LED_SMD"), "Device:LED"),
    (("1N4148", ""), "Device:D"),
    (("1N4001", ""), "Device:D"),
    (("", "DIODE"), "Device:D"),
    (("BC547", ""), "Device:Q_NPN_BCE"),
    (("BC557", ""), "Device:Q_PNP_BCE"),
    (("2N3904", ""), "Device:Q_NPN_BCE"),
    (("2N3906", ""), "Device:Q_PNP_BCE"),
    (("", "SOT-23-3"), "Device:Q_NPN_BCE"),
    (("", "SOT-23_3"), "Device:Q_NPN_BCE"),
    (("", "C_POLARIZED"), "Device:C_Polarized"),
    (("", "CP_"), "Device:C_Polarized"),
    (("", "CPOL"), "Device:C_Polarized"),
    (("", "C_0402"), "Device:C"),
    (("", "C_0603"), "Device:C"),
    (("", "C_0805"), "Device:C"),
    (("", "C_1206"), "Device:C"),
    (("", "CAP_"), "Device:C"),
    (("", "R_0402"), "Device:R"),
    (("", "R_0603"), "Device:R"),
    (("", "R_0805"), "Device:R"),
    (("", "R_1206"), "Device:R"),
    (("", "R_AXIAL"), "Device:R"),
]

_SYMBOL_FALLBACKS: dict[str, str] = {
    "Regulator_Linear": "Device:R",
    "Timer": "Device:R",
    "Amplifier_Operational": "Device:R",
    "Transistor_BJT": "Device:Q_NPN_BCE",
    "Diode": "Device:D",
    "Connector_Generic": "Connector_Generic:Conn_01x02",
}

_symbol_cache: set[str] = set()
_symbol_cache_loaded: bool = False


def _load_symbol_cache() -> None:
    global _symbol_cache, _symbol_cache_loaded
    if _symbol_cache_loaded:
        return
    sym_dir = os.environ.get("KICAD_SYMBOL_DIR", "")
    if not sym_dir:
        _symbol_cache_loaded = True
        return
    sym_path = Path(sym_dir)
    if not sym_path.is_dir():
        logger.warning("KICAD_SYMBOL_DIR not found: %s", sym_dir)
        _symbol_cache_loaded = True
        return
    pattern = re.compile(r'\(symbol\s+"([^"]+)"')
    for sym_file in sym_path.glob("*.kicad_sym"):
        lib = sym_file.stem
        try:
            text = sym_file.read_text(encoding="utf-8", errors="ignore")
            for m in pattern.finditer(text):
                name = m.group(1)
                if not re.search(r'_\d+$', name):
                    _symbol_cache.add(f"{lib}:{name}")
        except OSError as e:
            logger.warning("Could not read %s: %s", sym_file, e)
    logger.info("Symbol cache loaded: %d symbols from %s", len(_symbol_cache), sym_dir)
    _symbol_cache_loaded = True


def _symbol_exists(symbol: str) -> bool:
    _load_symbol_cache()
    if not _symbol_cache:
        return True
    return symbol in _symbol_cache


def _safe_symbol(symbol: str) -> str:
    if _symbol_exists(symbol):
        return symbol
    lib = symbol.split(":")[0] if ":" in symbol else ""
    fallback = _SYMBOL_FALLBACKS.get(lib, "Device:R")
    logger.warning("Symbol '%s' not found — using '%s'", symbol, fallback)
    return fallback


# ============================================================
# Footprint expansion: key → full KiCad footprint path
# ============================================================

_SMD_RESISTOR: dict[str, str] = {
    "0402": "Resistor_SMD:R_0402_1005Metric",
    "0603": "Resistor_SMD:R_0603_1608Metric",
    "0805": "Resistor_SMD:R_0805_2012Metric",
    "1206": "Resistor_SMD:R_1206_3216Metric",
}
_SMD_CAPACITOR: dict[str, str] = {
    "0402": "Capacitor_SMD:C_0402_1005Metric",
    "0603": "Capacitor_SMD:C_0603_1608Metric",
    "0805": "Capacitor_SMD:C_0805_2012Metric",
    "1206": "Capacitor_SMD:C_1206_3216Metric",
}

_SMD_SIZE_RE = re.compile(r"(?<!\d)(0402|0603|0805|1206)(?!\d)")


def _expand_footprint(comp: SchemaComponent) -> str:
    fp = comp.footprint.strip()
    symbol = (comp.symbol or "").upper()
    fp_up = fp.upper()
    val_up = comp.value.upper()

    if ":" in fp:
        return fp

    def matches(*keywords: str) -> bool:
        return any(kw in fp_up or kw in symbol or kw in val_up for kw in keywords)

    m_size = _SMD_SIZE_RE.search(fp_up)
    bare_size = m_size.group(1) if m_size else None

    if matches("DEVICE:C", "CAPACITOR") or fp_up.startswith("C"):
        if bare_size and bare_size in _SMD_CAPACITOR:
            return _SMD_CAPACITOR[bare_size]
        if fp_up in _SMD_CAPACITOR:
            return _SMD_CAPACITOR[fp_up]
        if matches("POLARIZED", "CPOL", "ELCO"):
            return "Capacitor_THT:CP_Radial_D8.0mm_P3.50mm"
        if not bare_size and matches("10UF", "100UF", "1000UF"):
            return "Capacitor_THT:CP_Radial_D8.0mm_P3.50mm"
        if not bare_size:
            return "Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P2.50mm"

    if bare_size and bare_size in _SMD_RESISTOR:
        return _SMD_RESISTOR[bare_size]
    if fp_up in _SMD_RESISTOR:
        return _SMD_RESISTOR[fp_up]
    if matches("DEVICE:R", "RESISTOR") and not bare_size:
        return "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal"

    if matches("DIODE", "1N4148", "1N4007"):
        return "Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal"
    if matches("LED"):
        return "LED_THT:LED_D5.0mm"
    if matches("DEVICE:Q", "TRANSISTOR", "BC547", "2N3904"):
        if matches("SOT-23"):
            return "Package_TO_SOT_SMD:SOT-23"
        return "Package_TO_SOT_THT:TO-92_Inline"

    m_dip = re.search(r'DIP-?(\d+)', fp_up)
    if m_dip:
        pins = int(m_dip.group(1))
        width = "7.62mm" if pins <= 8 else "15.24mm"
        return f"Package_DIP:DIP-{pins}_{width}"

    if matches("SOIC"):
        m_so = re.search(r'SOIC-?(\d+)', fp_up)
        pins = int(m_so.group(1)) if m_so else 8
        return f"Package_SO:SOIC-{pins}_3.9x4.9mm_P1.27mm"

    if matches("TSSOP"):
        m_ts = re.search(r'TSSOP-?(\d+)', fp_up)
        pins = int(m_ts.group(1)) if m_ts else 8
        return f"Package_SO:TSSOP-{pins}_4.4x3mm_P0.65mm"

    if matches("TO-220", "TO220", "LM7805", "7805", "LM317"):
        return "Package_TO_SOT_THT:TO-220-3_Vertical"
    if matches("SOT-223", "SOT223", "1117"):
        return "Package_TO_SOT_SMD:SOT-223-3_TabPin2"
    if matches("SOT-23-5", "SOT23-5"):
        return "Package_TO_SOT_SMD:SOT-23-5"
    if matches("SOT-23", "SOT23"):
        return "Package_TO_SOT_SMD:SOT-23"
    if matches("TO-92", "TO92", "2N3904", "BC547"):
        return "Package_TO_SOT_THT:TO-92_Inline"

    return fp


def _map_symbol(comp: SchemaComponent) -> str:
    if comp.symbol:
        return comp.symbol
    val = comp.value.upper()
    fp = comp.footprint.upper()
    for (val_kw, fp_kw), symbol in _SYMBOL_RULES:
        if val_kw and val_kw not in val:
            continue
        if fp_kw and fp_kw not in fp:
            continue
        if val_kw or fp_kw:
            return symbol
    if any(x in fp for x in ["R_0", "R_1", "R_AXIAL"]):
        return "Device:R"
    if any(x in fp for x in ["C_0", "C_1", "C_POLARIZED"]):
        return "Device:C"
    if "LED" in fp or "LED" in val:
        return "Device:LED"
    if "CONN" in fp or "PINHEADER" in fp:
        return "Connector_Generic:Conn_01x02"
    return "Device:R"


# ============================================================
# circuit_synth helpers
# ============================================================

def _circuit_synth_available() -> bool:
    if not os.environ.get("KICAD_SYMBOL_DIR"):
        return False
    try:
        import circuit_synth  # noqa: F401
        return True
    except ImportError:
        return False


def _resolve_pin(comp_obj: object, pin_name: object, comp_ref: str, net: object) -> bool:
    _first_err: Exception | None = None
    try:
        comp_obj[pin_name] += net  # type: ignore[index]
        return True
    except Exception as e:
        _first_err = e

    available: list[str] = []
    err_str = str(_first_err) if _first_err else ""
    m = re.search(r"Available:\s*(.+)$", err_str)
    if m:
        available = re.findall(r"'([^']+)'", m.group(1))

    if not available:
        logger.warning("Pin %s[%s]: no available-pin info in error, skipping", comp_ref, pin_name)
        return False

    pin_str = str(pin_name).upper().strip("~{}")

    if str(pin_name).isdigit():
        try:
            comp_obj[int(pin_name)] += net  # type: ignore[index]
            return True
        except Exception:
            pass

    for avail in available:
        segments = [s.upper().strip("~{}") for s in avail.split("/")]
        if pin_str in segments:
            try:
                comp_obj[avail] += net  # type: ignore[index]
                return True
            except Exception:
                pass

    for avail in available:
        if pin_str in avail.upper().strip("~{}"):
            try:
                comp_obj[avail] += net  # type: ignore[index]
                return True
            except Exception:
                pass

    logger.warning("Pin %s[%s] → no match among %s", comp_ref, pin_name, available[:8])
    return False


def _generate_with_cs_lib(
    components: list[SchemaComponent],
    connections: list[SchemaNet],
    nets: list[str],
    board_w: float,
    board_h: float,
    project_id: str,
    output_dir: Path,
) -> Optional[str]:
    """circuit_synth pip → .kicad_sch. Returns None on failure."""
    from circuit_synth import circuit as cs_circuit, Component as CSComponent, Net as CSNet

    project_name = project_id or "layrix_pcb"
    output_dir.mkdir(parents=True, exist_ok=True)

    @cs_circuit(name=project_name)
    def _build() -> None:
        net_objs: dict[str, CSNet] = {name: CSNet(name) for name in nets}
        comps: dict[str, CSComponent] = {}
        for comp in components:
            symbol = _safe_symbol(_map_symbol(comp))
            ref_prefix = comp.ref.rstrip("0123456789") or comp.ref
            c = CSComponent(
                symbol=symbol,
                ref=ref_prefix,
                value=comp.value,
                footprint=_expand_footprint(comp),
            )
            comps[comp.ref] = c

        connected = skipped = 0
        for conn in connections:
            net = net_objs.get(conn.name)
            if net is None:
                continue
            for pin in conn.pins:
                comp_obj = comps.get(pin.ref)
                if comp_obj is None:
                    continue
                if _resolve_pin(comp_obj, pin.pin, pin.ref, net):
                    connected += 1
                else:
                    skipped += 1
        logger.info("circuit_synth pins: %d connected, %d skipped", connected, skipped)

    circ = _build()
    project_path = str(output_dir / project_name)
    circ.generate_kicad_project(
        project_path,
        force_regenerate=True,
        generate_pcb=False,
    )

    sch_files = list(output_dir.rglob("*.kicad_sch"))
    return sch_files[0].read_text(encoding="utf-8") if sch_files else None


def _parse_net_file(net_content: str) -> tuple[list[SchemaComponent], list[str], list[SchemaNet]]:
    components: list[SchemaComponent] = []
    net_names: list[str] = []
    connections: list[SchemaNet] = []

    for m in re.finditer(
        r'\(comp\s+\(ref\s+"([^"]+)"\)\s+\(value\s+"([^"]+)"\)(?:[^)]*\(footprint\s+"([^"]*)"\))?',
        net_content, re.DOTALL,
    ):
        components.append(SchemaComponent(ref=m.group(1), value=m.group(2), footprint=m.group(3) or ""))

    for m in re.finditer(
        r'\(net\s+\(code\s+"[^"]*"\)\s+\(name\s+"([^"]+)"\)(.*?)(?=\s*\(net\s|\s*\)\s*$)',
        net_content, re.DOTALL,
    ):
        name = m.group(1)
        net_names.append(name)
        pins: list[SchemaPin] = []
        for pm in re.finditer(r'\(node\s+\(ref\s+"([^"]+)"\)\s+\(pin\s+"([^"]+)"\)', m.group(2)):
            pins.append(SchemaPin(ref=pm.group(1), pin=pm.group(2)))
        if pins:
            connections.append(SchemaNet(name=name, pins=pins))

    return components, net_names, connections


def _parse_circuit_synth_json(data: dict) -> tuple[list[SchemaComponent], list[str], list[SchemaNet]]:
    components: list[SchemaComponent] = []
    comps_data = data.get("components", {})
    if not isinstance(comps_data, dict):
        return [], [], []
    for ref, comp_data in comps_data.items():
        if not isinstance(comp_data, dict):
            continue
        if ref.startswith("#") or ref.startswith("$"):
            continue
        components.append(SchemaComponent(
            ref=ref,
            value=comp_data.get("value", ref),
            footprint=comp_data.get("footprint", ""),
            symbol=comp_data.get("symbol") or None,
        ))
    return components, [], []


# ============================================================
# S-expression fallback generator
# ============================================================

def _uuid4() -> str:
    import uuid
    return str(uuid.uuid4())


_IC_PIN_OFFSETS: dict[int, tuple[float, float]] = {
    1: (-5.08, -3.81), 2: (-5.08, -1.27), 3: (-5.08, 1.27), 4: (-5.08, 3.81),
    5: (5.08, 3.81),   6: (5.08, 1.27),   7: (5.08, -1.27), 8: (5.08, -3.81),
}
_VREG_PIN_OFFSETS: dict[int, tuple[float, float]] = {
    1: (-5.08, 0.0), 2: (0.0, 3.81), 3: (5.08, 0.0),
}

_GND_NETS: frozenset[str] = frozenset({"GND", "VSS", "AGND", "DGND", "PGND", "GROUND"})
_VCC_NETS: frozenset[str] = frozenset({"VCC", "VDD", "VBUS", "VBAT"})


def _is_power_net(name: str) -> bool:
    if not name:
        return False
    upper = name.upper().strip()
    if upper in _GND_NETS or upper in _VCC_NETS:
        return True
    if upper.startswith("+") and len(upper) >= 2:
        return True
    return False


def _power_lib_id(name: str) -> str:
    upper = name.upper().strip()
    return "power:GND" if upper in _GND_NETS else "power:VCC"


def _pin_offset(lib_id: str, pin_num: int) -> tuple[float, float]:
    if lib_id in ("Device:IC", "Timer:NE555P"):
        return _IC_PIN_OFFSETS.get(pin_num, (0.0, 0.0))
    if lib_id == "Device:VReg_3Pin":
        return _VREG_PIN_OFFSETS.get(pin_num, (0.0, 0.0))
    if pin_num == 1:
        return (-3.81, 0.0)
    return (3.81, 0.0)


def _today_iso() -> str:
    return date.today().isoformat()


def _derive_title(components: list[SchemaComponent]) -> str:
    if not components:
        return "Layrix Project"
    primary = next((c for c in components if c.ref.upper().startswith("U")), components[0])
    raw = (primary.value or "Layrix Project").strip().replace('"', "")
    if len(raw) > 60:
        raw = raw[:57] + "..."
    return f"Layrix — {raw}"


def _simple_lib_id(comp: SchemaComponent) -> str:
    ref = comp.ref.upper()
    val = comp.value.upper()
    if any(x in val for x in ["NE555", "LM555", "NA555", "SA555", "TLC555", "ICM7555", "TS555"]):
        return "Timer:NE555P"
    if any(x in val for x in ["LM78", "LM79", "LM317", "LM1117", "LM2596",
                               "LM2940", "LD33", "AMS1117", "L78", "L79"]):
        return "Device:VReg_3Pin"
    if ref.startswith("R"):
        return "Device:R"
    if ref.startswith("C"):
        return "Device:C"
    if ref.startswith("LED") or ref.startswith("D"):
        return "Device:LED"
    if ref.startswith("J") or ref.startswith("P") or ref.startswith("CONN"):
        return "Connector_Generic:Conn_01x02"
    return "Device:IC"


def _is_power_net_name(name: str) -> bool:
    return _is_power_net(name)


def _compute_logical_coords(
    components: list[SchemaComponent],
    connections: list[SchemaNet],
) -> list[tuple[int, int]]:
    if not components:
        return []
    from collections import defaultdict, Counter

    connectors, ics, passives = [], [], []
    for c in components:
        if c.ref.startswith(("J", "P", "CONN")):
            connectors.append(c)
        elif c.ref.startswith("U"):
            ics.append(c)
        else:
            passives.append(c)

    ic_refs = {ic.ref for ic in ics}
    passive_ic_counts: dict = defaultdict(Counter)
    for net in connections:
        if _is_power_net(net.name):
            continue
        refs = {p.ref for p in net.pins}
        net_ics = refs.intersection(ic_refs)
        net_passives = refs.intersection({p.ref for p in passives})
        for p_ref in net_passives:
            for ic_ref in net_ics:
                passive_ic_counts[p_ref][ic_ref] += 1

    ic_to_passives: dict = defaultdict(list)
    unassigned_passives = []
    for p in passives:
        if p.ref in passive_ic_counts and passive_ic_counts[p.ref]:
            best_ic = passive_ic_counts[p.ref].most_common(1)[0][0]
            ic_to_passives[best_ic].append(p)
        else:
            unassigned_passives.append(p)

    logical_coords: dict = {}
    col = 0

    for row, c in enumerate(connectors):
        logical_coords[c.ref] = (col, row)
    if connectors:
        col += 1

    for ic in ics:
        logical_coords[ic.ref] = (col, 0)
        p_list = ic_to_passives[ic.ref]
        max_rows_per_col = 4
        for i, p in enumerate(p_list):
            p_col = col + 1 + (i // max_rows_per_col)
            p_row = i % max_rows_per_col
            logical_coords[p.ref] = (p_col, p_row)
        cols_used = (len(p_list) + max_rows_per_col - 1) // max_rows_per_col if p_list else 0
        col += 1 + max(1, cols_used)

    for i, p in enumerate(unassigned_passives):
        logical_coords[p.ref] = (col + (i // 4), i % 4)

    return [logical_coords[c.ref] for c in components]


_INLINE_LIB_SYMBOLS = """
  (symbol "power:GND"
    (power) (pin_names (offset 0)) (in_bom no) (on_board yes)
    (property "Reference" "#PWR" (at 0 -6.35 0) (effects (font (size 1.27 1.27)) hide))
    (property "Value" "GND" (at 0 -3.81 0) (effects (font (size 1.27 1.27))))
    (symbol "GND_0_1"
      (polyline (pts (xy 0 0) (xy 0 -1.27) (xy 1.27 -1.27) (xy 0 -2.54) (xy -1.27 -1.27) (xy 0 -1.27))
        (stroke (width 0) (type default)) (fill (type none))))
    (symbol "GND_1_1"
      (pin power_in line (at 0 0 270) (length 0)
        (name "GND" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))))
  (symbol "power:VCC"
    (power) (pin_names (offset 0)) (in_bom no) (on_board yes)
    (property "Reference" "#PWR" (at 0 -3.81 0) (effects (font (size 1.27 1.27)) hide))
    (property "Value" "VCC" (at 0 3.81 0) (effects (font (size 1.27 1.27))))
    (symbol "VCC_0_1"
      (polyline (pts (xy -0.762 1.27) (xy 0 2.54) (xy 0.762 1.27))
        (stroke (width 0) (type default)) (fill (type none)))
      (circle (center 0 1.27) (radius 0.635)
        (stroke (width 0) (type default)) (fill (type none))))
    (symbol "VCC_1_1"
      (pin power_in line (at 0 0 90) (length 1.27)
        (name "VCC" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))))
  (symbol "Device:R"
    (pin_numbers hide) (pin_names (offset 0)) (in_bom yes) (on_board yes)
    (property "Reference" "R" (at 0 -2.5 0) (effects (font (size 1.27 1.27))))
    (property "Value" "R" (at 0 2.5 0) (effects (font (size 1.27 1.27))))
    (symbol "R_0_1"
      (rectangle (start -2.032 -0.762) (end 2.032 0.762)
        (stroke (width 0.254) (type default)) (fill (type none))))
    (symbol "R_1_1"
      (pin passive line (at -3.81 0 0) (length 1.778)
        (name "~" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 3.81 0 180) (length 1.778)
        (name "~" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))))
  (symbol "Device:C"
    (pin_numbers hide) (pin_names (offset 0)) (in_bom yes) (on_board yes)
    (property "Reference" "C" (at 0 -2.5 0) (effects (font (size 1.27 1.27))))
    (property "Value" "C" (at 0 2.5 0) (effects (font (size 1.27 1.27))))
    (symbol "C_0_1"
      (polyline (pts (xy -2.032 0.381) (xy 2.032 0.381))
        (stroke (width 0.508) (type default)) (fill (type none)))
      (polyline (pts (xy -2.032 -0.381) (xy 2.032 -0.381))
        (stroke (width 0.508) (type default)) (fill (type none))))
    (symbol "C_1_1"
      (pin passive line (at -3.81 0 0) (length 1.778)
        (name "+" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 3.81 0 180) (length 1.778)
        (name "-" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))))
  (symbol "Device:LED"
    (pin_numbers hide) (pin_names (offset 0)) (in_bom yes) (on_board yes)
    (property "Reference" "D" (at 0 -2.5 0) (effects (font (size 1.27 1.27))))
    (property "Value" "LED" (at 0 2.5 0) (effects (font (size 1.27 1.27))))
    (symbol "LED_0_1"
      (polyline (pts (xy -1.778 -1.778) (xy -1.778 1.778) (xy 1.778 0) (xy -1.778 -1.778))
        (stroke (width 0.254) (type default)) (fill (type none)))
      (polyline (pts (xy 1.778 -1.778) (xy 1.778 1.778))
        (stroke (width 0.254) (type default)) (fill (type none))))
    (symbol "LED_1_1"
      (pin passive line (at -3.81 0 0) (length 2.032)
        (name "A" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 3.81 0 180) (length 2.032)
        (name "K" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))))
  (symbol "Connector_Generic:Conn_01x02"
    (pin_numbers hide) (pin_names (offset 1.016)) (in_bom yes) (on_board yes)
    (property "Reference" "J" (at 0 -2.5 0) (effects (font (size 1.27 1.27))))
    (property "Value" "Conn_01x02" (at 0 2.5 0) (effects (font (size 1.27 1.27))))
    (symbol "Conn_01x02_0_1"
      (rectangle (start -1.524 -0.762) (end 1.524 0.762)
        (stroke (width 0.254) (type default)) (fill (type none))))
    (symbol "Conn_01x02_1_1"
      (pin passive line (at -3.81 0 0) (length 2.286)
        (name "Pin_1" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 3.81 0 180) (length 2.286)
        (name "Pin_2" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))))
  (symbol "Device:IC"
    (pin_numbers hide) (pin_names (offset 0.254)) (in_bom yes) (on_board yes)
    (property "Reference" "U" (at 0 -6 0) (effects (font (size 1.27 1.27))))
    (property "Value" "IC" (at 0 6 0) (effects (font (size 1.27 1.27))))
    (symbol "IC_0_1"
      (rectangle (start -4 -4.5) (end 4 4.5)
        (stroke (width 0.254) (type default)) (fill (type none))))
    (symbol "IC_1_1"
      (pin input line (at -5.08 -3.81 0) (length 1.016)
        (name "1" (effects (font (size 1.016 1.016)))) (number "1" (effects (font (size 1.016 1.016)))))
      (pin input line (at -5.08 -1.27 0) (length 1.016)
        (name "2" (effects (font (size 1.016 1.016)))) (number "2" (effects (font (size 1.016 1.016)))))
      (pin input line (at -5.08 1.27 0) (length 1.016)
        (name "3" (effects (font (size 1.016 1.016)))) (number "3" (effects (font (size 1.016 1.016)))))
      (pin input line (at -5.08 3.81 0) (length 1.016)
        (name "4" (effects (font (size 1.016 1.016)))) (number "4" (effects (font (size 1.016 1.016)))))
      (pin output line (at 5.08 3.81 180) (length 1.016)
        (name "5" (effects (font (size 1.016 1.016)))) (number "5" (effects (font (size 1.016 1.016)))))
      (pin output line (at 5.08 1.27 180) (length 1.016)
        (name "6" (effects (font (size 1.016 1.016)))) (number "6" (effects (font (size 1.016 1.016)))))
      (pin output line (at 5.08 -1.27 180) (length 1.016)
        (name "7" (effects (font (size 1.016 1.016)))) (number "7" (effects (font (size 1.016 1.016)))))
      (pin output line (at 5.08 -3.81 180) (length 1.016)
        (name "8" (effects (font (size 1.016 1.016)))) (number "8" (effects (font (size 1.016 1.016)))))))
  (symbol "Timer:NE555P"
    (pin_numbers hide) (pin_names (offset 0.254)) (in_bom yes) (on_board yes)
    (property "Reference" "U" (at 0 -6 0) (effects (font (size 1.27 1.27))))
    (property "Value" "NE555P" (at 0 6 0) (effects (font (size 1.27 1.27))))
    (symbol "NE555P_0_1"
      (rectangle (start -4 -4.5) (end 4 4.5)
        (stroke (width 0.254) (type default)) (fill (type none))))
    (symbol "NE555P_1_1"
      (pin passive line (at -5.08 -3.81 0) (length 1.016)
        (name "GND" (effects (font (size 1.016 1.016)))) (number "1" (effects (font (size 1.016 1.016)))))
      (pin input line (at -5.08 -1.27 0) (length 1.016)
        (name "TRIG" (effects (font (size 1.016 1.016)))) (number "2" (effects (font (size 1.016 1.016)))))
      (pin output line (at -5.08 1.27 0) (length 1.016)
        (name "OUT" (effects (font (size 1.016 1.016)))) (number "3" (effects (font (size 1.016 1.016)))))
      (pin input line (at -5.08 3.81 0) (length 1.016)
        (name "RST" (effects (font (size 1.016 1.016)))) (number "4" (effects (font (size 1.016 1.016)))))
      (pin input line (at 5.08 3.81 180) (length 1.016)
        (name "CTRL" (effects (font (size 1.016 1.016)))) (number "5" (effects (font (size 1.016 1.016)))))
      (pin input line (at 5.08 1.27 180) (length 1.016)
        (name "THR" (effects (font (size 1.016 1.016)))) (number "6" (effects (font (size 1.016 1.016)))))
      (pin output line (at 5.08 -1.27 180) (length 1.016)
        (name "DIS" (effects (font (size 1.016 1.016)))) (number "7" (effects (font (size 1.016 1.016)))))
      (pin power_in line (at 5.08 -3.81 180) (length 1.016)
        (name "VCC" (effects (font (size 1.016 1.016)))) (number "8" (effects (font (size 1.016 1.016)))))))
  (symbol "Device:VReg_3Pin"
    (pin_numbers hide) (pin_names (offset 0.254)) (in_bom yes) (on_board yes)
    (property "Reference" "U" (at 0 -3.5 0) (effects (font (size 1.27 1.27))))
    (property "Value" "VReg" (at 0 3.5 0) (effects (font (size 1.27 1.27))))
    (symbol "VReg_3Pin_0_1"
      (rectangle (start -3 -1.5) (end 3 1.5)
        (stroke (width 0.254) (type default)) (fill (type none))))
    (symbol "VReg_3Pin_1_1"
      (pin input line (at -5.08 0 0) (length 2.032)
        (name "IN" (effects (font (size 1.016 1.016)))) (number "1" (effects (font (size 1.016 1.016)))))
      (pin passive line (at 0 3.81 90) (length 2.286)
        (name "GND" (effects (font (size 1.016 1.016)))) (number "2" (effects (font (size 1.016 1.016)))))
      (pin output line (at 5.08 0 180) (length 2.032)
        (name "OUT" (effects (font (size 1.016 1.016)))) (number "3" (effects (font (size 1.016 1.016)))))))
"""


def _generate_schematic_fallback(
    components: list[SchemaComponent],
    connections: list[SchemaNet],
) -> str:
    n = len(components)
    logical_coords = _compute_logical_coords(components, connections)
    cols = max((c[0] for c in logical_coords), default=0) + 1 if n else 1
    rows = max((c[1] for c in logical_coords), default=0) + 1 if n else 1
    col_step = 55
    row_step = 35
    stub_len = 2.54

    TITLE_BLOCK_HEIGHT = 44
    TITLE_PADDING = 15
    margin_top = 25
    margin_side = 38
    comp_h_span = 18
    comp_w_span = 20

    component_bottom_y = margin_top + (rows - 1) * row_step + comp_h_span
    component_right_x = margin_side + (cols - 1) * col_step + comp_w_span
    paper_w = max(80, component_right_x + margin_side)
    paper_h = max(80, component_bottom_y + TITLE_PADDING + TITLE_BLOCK_HEIGHT)
    origin_x = margin_side
    origin_y = margin_top

    lines: list[str] = []
    lines.append(f'(kicad_sch (version 20230121) (generator "layrix-circuit-synth") (uuid "{_uuid4()}")')
    lines.append(f'  (paper "User" {paper_w} {paper_h})')

    title_str = _derive_title(components)
    today_iso = _today_iso()
    lines.append('  (title_block')
    lines.append(f'    (title "{title_str}")')
    lines.append(f'    (date "{today_iso}")')
    lines.append('    (rev "1.0")')
    lines.append('    (company "Layrix.ai")')
    lines.append('  )')
    lines.append(f'  (lib_symbols{_INLINE_LIB_SYMBOLS}  )')

    positions: list[tuple[float, float]] = [
        (origin_x + coord[0] * col_step, origin_y + coord[1] * row_step)
        for coord in logical_coords
    ]
    lib_ids: list[str] = [_simple_lib_id(c) for c in components]

    for i, comp in enumerate(components):
        x, y = positions[i]
        lib_id = lib_ids[i]
        ref_e = comp.ref.replace('"', '\\"')
        val_e = comp.value.replace('"', '\\"')
        fp_e = comp.footprint.replace('"', '\\"')
        lines.append(f'  (symbol (lib_id "{lib_id}") (at {x} {y} 0) (unit 1) (in_bom yes) (on_board yes)')
        lines.append(f'    (uuid "{_uuid4()}")')
        lines.append(f'    (property "Reference" "{ref_e}" (at {x} {y - 7} 0) (effects (font (size 1.27 1.27))))')
        lines.append(f'    (property "Value" "{val_e}" (at {x} {y + 7} 0) (effects (font (size 1.27 1.27))))')
        lines.append(f'    (property "Footprint" "{fp_e}" (at {x} {y + 10} 0) (effects (font (size 1.27 1.27)) (hide yes)))')
        lines.append('  )')

    comp_idx_by_ref = {c.ref: i for i, c in enumerate(components)}
    for net in connections:
        if not net.pins:
            continue
        name_e = net.name.replace('"', '\\"')
        is_power = _is_power_net(net.name)
        power_id = _power_lib_id(net.name) if is_power else ""
        for p in net.pins:
            idx = comp_idx_by_ref.get(p.ref)
            if idx is None:
                continue
            sx, sy = positions[idx]
            dx, dy = _pin_offset(lib_ids[idx], p.pin)
            px = round(sx + dx, 3)
            py = round(sy + dy, 3)

            if abs(dx) >= abs(dy):
                sign = -1 if dx < 0 else 1
                ex = round(px + sign * stub_len, 3)
                ey = py
                langle = 180 if dx < 0 else 0
            else:
                ex = px
                ey = round(py + stub_len, 3)
                langle = 90

            lines.append(
                f'  (wire (pts (xy {px} {py}) (xy {ex} {ey})) '
                f'(stroke (width 0.1524) (type default)) (uuid "{_uuid4()}"))'
            )
            if is_power:
                rot = 0
                _value_y_offset = -3.81 if power_id == "power:GND" else 3.81
                lines.append(f'  (symbol (lib_id "{power_id}") (at {ex} {ey} {rot}) (unit 1) (in_bom no) (on_board yes)')
                lines.append(f'    (uuid "{_uuid4()}")')
                lines.append(f'    (property "Reference" "#PWR" (at {ex} {ey - 6.35} 0) (effects (font (size 1.27 1.27)) hide))')
                lines.append(f'    (property "Value" "{name_e}" (at {ex} {ey + _value_y_offset} 0) (effects (font (size 1.27 1.27))))')
                lines.append('  )')
            else:
                lines.append(
                    f'  (label "{name_e}" (at {ex} {ey} {langle}) '
                    f'(effects (font (size 1.27 1.27))) (uuid "{_uuid4()}"))'
                )

    lines.append('  (sheet_instances (path "/" (page "1")))')
    lines.append(')')
    return "\n".join(lines)


# ============================================================
# Public API
# ============================================================

def _generate_with_kicad_tools(
    components: list[SchemaComponent],
    connections: list[SchemaNet],
) -> Optional[str]:
    """kicad-tools Schematic class → .kicad_sch. Returns None on failure.

    ``title`` est positionnel-obligatoire depuis le dépôt officiel kicad-tools
    (vendoré 2026-06-03) — ``Schematic()`` nu → TypeError (bug trouvé par
    examples/stm32-validation/run_full_pipeline.py le 2026-06-11).
    """
    from kicad_tools.schematic.models.schematic import Schematic

    sch = Schematic(title=_derive_title(components))

    col_step = 55.0
    row_step = 35.0
    margin_x = 38.0
    margin_y = 25.0
    cols = max(1, math.ceil(math.sqrt(len(components))))

    # SymbolInstance expose pin_position(pin) → endpoint absolu après placement.
    sym_instances: dict[str, object] = {}

    for i, comp in enumerate(components):
        x = margin_x + (i % cols) * col_step
        y = margin_y + (i // cols) * row_step
        lib_id = _safe_symbol(_map_symbol(comp))
        try:
            sym_instances[comp.ref] = sch.add_symbol(
                lib_id=lib_id,
                x=x, y=y,
                ref=comp.ref,
                value=comp.value,
                footprint=_expand_footprint(comp),
                snap=True,
            )
        except Exception as exc:
            logger.warning("kicad-tools add_symbol %s (%s): %s", comp.ref, lib_id, exc)

    # Poser chaque label de net À LA POSITION EXACTE de la pin (pin_position).
    # Un offset arbitraire laisse le label déconnecté → extract_netlist() isole
    # chaque pin dans son propre Net-(REF-PinN) → netlist PCB fragmenté
    # (83 nets au lieu de 12, routage bloqué à 0%). snap=False : pin_position
    # est déjà précis, un re-snap décalerait le label hors de la pin.
    for conn in connections:
        for pin in conn.pins:
            sym = sym_instances.get(pin.ref)
            if sym is None:
                continue
            try:
                lx, ly = sym.pin_position(str(pin.pin))
            except Exception as exc:
                logger.warning(
                    "kicad-tools pin_position %s.%s introuvable: %s",
                    pin.ref, pin.pin, exc,
                )
                continue
            try:
                sch.add_label(
                    conn.name, lx, ly, snap=False, validate_connection=False,
                )
            except Exception as exc:
                logger.warning("kicad-tools add_label %s @%s: %s", conn.name, pin.ref, exc)

    content = sch.to_sexp()
    return content if content else None


def generate_schematic(
    components: list[SchemaComponent],
    connections: list[SchemaNet],
    nets: list[str],
    board_w: float = 50.0,
    board_h: float = 50.0,
    project_id: str = "",
) -> str:
    """
    Primary    : circuit_synth pip (20s timeout)
    Fallback 1 : kicad-tools Schematic class
    Fallback 2 : empty string → TypeScript S-expr (schematic-engine.ts)
    Returns .kicad_sch content, or "" when all Python paths fail.
    """
    # Primary: circuit_synth pip
    if _circuit_synth_available():
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    fut = pool.submit(
                        _generate_with_cs_lib,
                        components, connections, nets, board_w, board_h, project_id,
                        Path(tmp),
                    )
                    try:
                        sch_content = fut.result(timeout=20)
                    except concurrent.futures.TimeoutError:
                        fut.cancel()
                        raise RuntimeError("circuit_synth timed out after 20s")
                if sch_content:
                    logger.info("generate_schematic: circuit_synth succeeded")
                    return sch_content
        except Exception as exc:
            logger.warning("generate_schematic: circuit_synth failed (%s) — trying kicad-tools", exc)

    # Fallback 1: kicad-tools Schematic class
    try:
        sch_content = _generate_with_kicad_tools(components, connections)
        if sch_content:
            logger.info("generate_schematic: kicad-tools succeeded")
            return sch_content
    except Exception as exc:
        logger.warning("generate_schematic: kicad-tools failed (%s) — TypeScript fallback needed", exc)

    # Fallback 2: return "" → router returns success=False → TypeScript S-expr takes over
    logger.warning("generate_schematic: all Python paths failed")
    return ""


def execute_cs_code(
    code: str,
    project_id: str,
    board_w: float,
    board_h: float,
) -> tuple[str, str]:
    """
    Execute circuit_synth Python code in a subprocess.
    Returns (kicad_sch_content, kicad_pcb_content).
    """
    import subprocess
    import shutil
    import json as _json

    proj_dir = tempfile.mkdtemp(prefix=f"cs_{project_id or 'exec'}_")
    logger.info("=== CIRCUIT_SYNTH SCRIPT ===\n%s\n=== END SCRIPT ===", code)
    try:
        wrapper = f"""import sys, os
sys.path.insert(0, '/app/circuit_synth/src')
_PROJECT_PATH = {repr(proj_dir)}

{code}
"""
        script = Path(proj_dir) / "generate.py"
        script.write_text(wrapper, encoding="utf-8")

        env = {
            **os.environ,
            "PYTHONPATH": "/app/circuit_synth/src:/usr/lib/python3/dist-packages",
            "PYTHONUTF8": "1",
        }
        result = subprocess.run(
            ["python3", str(script)],
            capture_output=True, text=True, timeout=30, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"circuit_synth code execution failed:\n{result.stderr[:3000]}")

        sch_files = list(Path(proj_dir).rglob("*.kicad_sch"))
        if not sch_files:
            raise RuntimeError("No .kicad_sch file generated by the code")
        sch_content = sch_files[0].read_text(encoding="utf-8")

        comps: list[SchemaComponent] = []
        json_files = list(Path(proj_dir).rglob("*.json"))
        if json_files:
            try:
                comps, _, _ = _parse_circuit_synth_json(
                    _json.loads(json_files[0].read_text(encoding="utf-8"))
                )
            except Exception as e:
                logger.warning("Failed to parse circuit_synth JSON: %s", e)

        conns: list[SchemaNet] = []
        net_content: Optional[str] = None
        net_files = list(Path(proj_dir).rglob("*.net"))
        if net_files:
            net_content = net_files[0].read_text(encoding="utf-8")
            net_comps, _, conns = _parse_net_file(net_content)
            if not comps:
                comps = net_comps

        # Lazy import to avoid circular dependency with tools.pcb
        from tools.pcb import generate_pcb
        pcb_content = generate_pcb(
            comps, conns, board_w, board_h,
            kicad_sch_content=sch_content,
            kicad_net_content=net_content,
        )
        return sch_content, pcb_content

    finally:
        shutil.rmtree(proj_dir, ignore_errors=True)


def validate_symbols(
    components: list[SchemaComponent],
) -> tuple[list[dict], list[SchemaComponent], bool]:
    """
    Validate KiCad symbol ids against local .kicad_sym libraries.
    Returns (results, corrected_components, has_corrections).
    """
    results: list[dict] = []
    corrected_components: list[SchemaComponent] = []
    has_corrections = False

    for comp in components:
        original = _map_symbol(comp)
        validated = _safe_symbol(original)
        corrected = validated != original
        if corrected:
            has_corrections = True
        results.append({
            "ref": comp.ref,
            "original_symbol": original,
            "validated_symbol": validated,
            "corrected": corrected,
        })
        corrected_components.append(comp.model_copy(update={"symbol": validated}))

    return results, corrected_components, has_corrections


# Pre-load symbol cache at import time (non-blocking)
import threading as _threading
_threading.Thread(target=_load_symbol_cache, daemon=True).start()
