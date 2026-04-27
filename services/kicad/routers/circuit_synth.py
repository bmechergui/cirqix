"""
Circuit-Synth router — converts JSON schema to native .kicad_sch + .kicad_pcb files.
Primary path: circuit_synth Python library (requires KICAD_SYMBOL_DIR).
Fallback path: hand-written KiCad 7 S-expression generator.
"""

import concurrent.futures
import math
import os
import re
import sys
import tempfile
import logging
from pathlib import Path
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Ensure UTF-8 encoding for circuit_synth on Windows
os.environ.setdefault("PYTHONUTF8", "1")

router = APIRouter(prefix="/circuit-synth", tags=["circuit-synth"])

# ============================================================
# Pydantic models
# ============================================================

class SchemaPin(BaseModel):
    ref: str
    pin: int  # 1-indexed


class SchemaNet(BaseModel):
    name: str
    pins: list[SchemaPin]


class SchemaComponent(BaseModel):
    ref: str
    value: str
    footprint: str
    symbol: Optional[str] = None   # KiCad symbol id (e.g. "Device:R") — optional
    lcsc: Optional[str] = None


class CircuitSynthRequest(BaseModel):
    components: list[SchemaComponent]
    nets: list[str]
    connections: list[SchemaNet] = Field(default_factory=list)
    board_width_mm: float = Field(default=50.0, ge=10.0, le=200.0)
    board_height_mm: float = Field(default=50.0, ge=10.0, le=200.0)
    project_id: str = ""


class CircuitSynthResponse(BaseModel):
    success: bool
    kicad_sch_content: Optional[str] = None
    kicad_pcb_content: Optional[str] = None
    error: Optional[str] = None


# ============================================================
# Symbol mapping (JSON → KiCad symbol id)
# ============================================================

# Maps (value substring, footprint substring) → symbol id
# Checked in order — first match wins.
_SYMBOL_RULES: list[tuple[tuple[str, str], str]] = [
    # --- Timers ---
    (("NE555", ""), "Timer:NE555P"),
    (("LM555", ""), "Timer:NE555P"),
    (("NA555", ""), "Timer:NE555P"),
    (("SA555", ""), "Timer:NE555P"),
    (("TLC555", ""), "Timer:NE555P"),
    (("ICM7555", ""), "Timer:NE555P"),
    # --- Voltage regulators ---
    (("LM7805", ""), "Regulator_Linear:L7805"),
    (("L7805", ""), "Regulator_Linear:L7805"),
    (("LM7812", ""), "Regulator_Linear:L7812"),
    (("LM317", ""), "Regulator_Linear:LM317_TO-220"),
    (("LM1117", "3.3"), "Regulator_Linear:LM1117T-3.3"),
    (("LM1117", "5"), "Regulator_Linear:LM1117T-5.0"),
    (("LM1117", ""), "Regulator_Linear:LM1117T-3.3"),
    # --- Op-amps ---
    (("LM358", ""), "Amplifier_Operational:LM358"),
    (("LM741", ""), "Amplifier_Operational:LM741"),
    # --- Diodes ---
    (("1N4148", ""), "Diode:1N4148"),
    (("1N4001", ""), "Diode:1N4001"),
    (("1N4007", ""), "Diode:1N4007"),
    # --- Transistors ---
    (("BC547", ""), "Transistor_BJT:BC547"),
    (("BC557", ""), "Transistor_BJT:BC557"),
    (("2N3904", ""), "Transistor_BJT:2N3904"),
    (("2N3906", ""), "Transistor_BJT:2N3906"),
    (("BC337", ""), "Transistor_BJT:BC337"),
    # --- Connectors ---
    (("", "CONN_01X01"), "Connector_Generic:Conn_01x01"),
    (("", "CONN_01X02"), "Connector_Generic:Conn_01x02"),
    (("", "CONN_01X03"), "Connector_Generic:Conn_01x03"),
    (("", "CONN_01X04"), "Connector_Generic:Conn_01x04"),
    (("", "PINHEADER_1X02"), "Connector_Generic:Conn_01x02"),
    (("", "PINHEADER_1X03"), "Connector_Generic:Conn_01x03"),
    (("", "PINHEADER_1X04"), "Connector_Generic:Conn_01x04"),
    (("", "PINHEADER_2X"), "Connector_Generic:Conn_02x02"),
    # --- LEDs ---
    (("LED", ""), "Device:LED"),
    (("", "LED_THT"), "Device:LED"),
    (("", "LED_SMD"), "Device:LED"),
    # --- Diodes ---
    (("1N4148", ""), "Device:D"),
    (("1N4001", ""), "Device:D"),
    (("", "DIODE"), "Device:D"),
    # --- Transistors (BJT) ---
    (("BC547", ""), "Device:Q_NPN_BCE"),
    (("BC557", ""), "Device:Q_PNP_BCE"),
    (("2N3904", ""), "Device:Q_NPN_BCE"),
    (("2N3906", ""), "Device:Q_PNP_BCE"),
    (("", "SOT-23-3"), "Device:Q_NPN_BCE"),
    (("", "SOT-23_3"), "Device:Q_NPN_BCE"),
    # --- Polarized caps (check before regular caps) ---
    (("", "C_POLARIZED"), "Device:C_Polarized"),
    (("", "CP_"), "Device:C_Polarized"),
    (("", "CPOL"), "Device:C_Polarized"),
    # --- Capacitors ---
    (("", "C_0402"), "Device:C"),
    (("", "C_0603"), "Device:C"),
    (("", "C_0805"), "Device:C"),
    (("", "C_1206"), "Device:C"),
    (("", "CAP_"), "Device:C"),
    # --- Resistors ---
    (("", "R_0402"), "Device:R"),
    (("", "R_0603"), "Device:R"),
    (("", "R_0805"), "Device:R"),
    (("", "R_1206"), "Device:R"),
    (("", "R_AXIAL"), "Device:R"),
]


# ============================================================
# Symbol validator — loads .kicad_sym files from KICAD_SYMBOL_DIR
# ============================================================

# Generic fallbacks when a symbol is not found in local .kicad_sym files
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
    """Parse all .kicad_sym files in KICAD_SYMBOL_DIR and build a set of 'lib:symbol' keys."""
    global _symbol_cache, _symbol_cache_loaded
    if _symbol_cache_loaded:
        return
    sym_dir = os.environ.get("KICAD_SYMBOL_DIR", "")
    if not sym_dir:
        _symbol_cache_loaded = True
        return
    sym_path = Path(sym_dir)
    if not sym_path.is_dir():
        logger.warning(f"KICAD_SYMBOL_DIR not found: {sym_dir}")
        _symbol_cache_loaded = True
        return
    pattern = re.compile(r'\(symbol\s+"([^"]+)"')
    for sym_file in sym_path.glob("*.kicad_sym"):
        lib = sym_file.stem
        try:
            text = sym_file.read_text(encoding="utf-8", errors="ignore")
            for m in pattern.finditer(text):
                name = m.group(1)
                # Skip sub-unit entries like "Device:R_0" — they contain '_' + digit at end
                if not re.search(r'_\d+$', name):
                    _symbol_cache.add(f"{lib}:{name}")
        except OSError as e:
            logger.warning(f"Could not read {sym_file}: {e}")
    logger.info(f"Symbol cache loaded: {len(_symbol_cache)} symbols from {sym_dir}")
    _symbol_cache_loaded = True


def _symbol_exists(symbol: str) -> bool:
    """Return True if the 'lib:name' symbol exists in the local KiCad symbol libraries."""
    _load_symbol_cache()
    if not _symbol_cache:
        return True  # cache empty (no KICAD_SYMBOL_DIR) — trust the symbol
    return symbol in _symbol_cache


def _safe_symbol(symbol: str) -> str:
    """
    Return the symbol as-is if it exists in the local libraries.
    Otherwise, fall back to the closest generic equivalent and log a warning.
    """
    if _symbol_exists(symbol):
        return symbol
    lib = symbol.split(":")[0] if ":" in symbol else ""
    fallback = _SYMBOL_FALLBACKS.get(lib, "Device:R")
    logger.warning(f"Symbol '{symbol}' not found in KiCad libraries — using '{fallback}' as fallback")
    return fallback


# ============================================================
# Footprint expansion: simplified key → full KiCad footprint path
# ============================================================

# Generic SMD size → resistor/capacitor footprint (symbol determines which)
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

def _expand_footprint(comp: SchemaComponent) -> str:
    """Convert simplified footprint key to full KiCad footprint path."""
    fp = comp.footprint.strip()
    symbol = (comp.symbol or "").lower()
    fp_up = fp.upper()

    # Already a full path (contains ':')
    if ":" in fp:
        return fp

    # Capacitor symbols → use capacitor footprints for SMD sizes
    if any(x in symbol for x in ["device:c", "capacitor"]):
        if fp_up in _SMD_CAPACITOR:
            return _SMD_CAPACITOR[fp_up]
        if "polarized" in symbol:
            return "Capacitor_THT:C_Radial_D8.0mm_H11.5mm_P3.50mm"

    # Resistor / LED / diode → SMD resistor footprints for SMD sizes
    if fp_up in _SMD_RESISTOR:
        return _SMD_RESISTOR[fp_up]

    # LED THT
    if fp_up == "LED":
        return "LED_THT:LED_D5.0mm"

    # Connectors
    fp_conn_map = {
        "CONN_2": "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
        "CONN_3": "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
        "CONN_4": "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
    }
    if fp_up in fp_conn_map:
        return fp_conn_map[fp_up]

    # TO-220 (LM7805 etc.)
    if fp_up == "TO-220":
        return "Package_TO_SOT_THT:TO-220-3_Vertical"

    # SOT-223 (LM1117 etc.)
    if fp_up == "SOT-223":
        return "Package_TO_SOT_SMD:SOT-223-3_TabPin2"

    # SOT-23 (transistors, small ICs)
    if fp_up in ("SOT-23", "SOT-23-3"):
        return "Package_TO_SOT_SMD:SOT-23"

    # SOT-23-5
    if fp_up == "SOT-23-5":
        return "Package_TO_SOT_SMD:SOT-23-5"

    # DIP-8
    if fp_up == "DIP-8":
        return "Package_DIP:DIP-8_W7.62mm"

    # TSSOP-8
    if fp_up == "TSSOP-8":
        return "Package_SO:TSSOP-8_4.4x3mm_P0.65mm"

    # Fallback: keep original value
    return fp


def _map_symbol(comp: SchemaComponent) -> str:
    """Map a component to its KiCad symbol id."""
    if comp.symbol:
        return comp.symbol

    val = comp.value.upper()
    fp = comp.footprint.upper()

    for (val_kw, fp_kw), symbol in _SYMBOL_RULES:
        if val_kw and val_kw not in val:
            continue
        if fp_kw and fp_kw not in fp:
            continue
        if val_kw or fp_kw:  # at least one match condition must be non-empty
            return symbol

    # Generic fallback based on broad footprint patterns
    if any(x in fp for x in ["R_0", "R_1", "R_AXIAL"]):
        return "Device:R"
    if any(x in fp for x in ["C_0", "C_1", "C_POLARIZED"]):
        return "Device:C"
    if "LED" in fp or "LED" in val:
        return "Device:LED"
    if "CONN" in fp or "PINHEADER" in fp:
        return "Connector_Generic:Conn_01x02"

    return "Device:R"  # last resort


# ============================================================
# circuit_synth generation (primary path)
# ============================================================

def _circuit_synth_available() -> bool:
    """Return True if circuit_synth + KICAD_SYMBOL_DIR are usable.

    NOTE: circuit_synth 0.12.1 placement algorithm enters an infinite loop on
    Windows (bbox loop never converges).  Until a fixed version is released or
    the service runs in a Linux container, force the fallback on Windows.
    The fallback (compact stub+label schematic) renders correctly in KiCanvas.
    """
    if os.name == "nt":
        return False
    if not os.environ.get("KICAD_SYMBOL_DIR"):
        return False
    try:
        import circuit_synth  # noqa: F401
        return True
    except ImportError:
        return False


def _generate_with_circuit_synth(
    req: "CircuitSynthRequest",
    output_dir: Path,
) -> tuple[Optional[str], Optional[str]]:
    """
    Use the circuit_synth Python library to generate .kicad_sch.
    Returns (sch_content, pcb_content) — pcb_content may be None.
    Raises on failure so the caller can fall back.
    """
    from circuit_synth import circuit as cs_circuit, Component as CSComponent, Net as CSNet

    project_name = req.project_id or "layrix_pcb"
    output_dir.mkdir(parents=True, exist_ok=True)

    @cs_circuit(name=project_name)
    def _build() -> None:
        # Create nets
        nets: dict[str, CSNet] = {name: CSNet(name) for name in req.nets}

        # Create components — pass full ref (e.g. "R1") so circuit_synth uses it as-is
        comps: dict[str, CSComponent] = {}
        for comp in req.components:
            symbol = _safe_symbol(_map_symbol(comp))
            # Use prefix only (strip trailing digits) — circuit_synth auto-numbers
            ref_prefix = comp.ref.rstrip("0123456789") or comp.ref
            c = CSComponent(
                symbol=symbol,
                ref=ref_prefix,
                value=comp.value,
                footprint=_expand_footprint(comp),
            )
            comps[comp.ref] = c

        # Connect pins
        for conn in req.connections:
            net = nets.get(conn.name)
            if net is None:
                continue
            for pin in conn.pins:
                comp_obj = comps.get(pin.ref)
                if comp_obj is None:
                    continue
                try:
                    comp_obj[pin.pin] += net
                except Exception as e:
                    logger.warning(f"Pin connection skipped {pin.ref}[{pin.pin}] to {conn.name}: {e}")

    circ = _build()
    project_path = str(output_dir / project_name)
    circ.generate_kicad_project(project_path, force_regenerate=True, generate_pcb=False)

    # Find generated files
    sch_files = list(output_dir.rglob("*.kicad_sch"))
    sch_content = sch_files[0].read_text(encoding="utf-8") if sch_files else None
    return sch_content, None


# ============================================================
# Fallback: hand-written S-expression generators
# ============================================================

def _grid_position(idx: int, total: int, board_w: float, board_h: float) -> tuple[float, float]:
    cols = max(1, math.ceil(math.sqrt(total)))
    rows = math.ceil(total / cols)
    margin = 5.0
    usable_w = board_w - 2 * margin
    usable_h = board_h - 2 * margin
    col = idx % cols
    row = idx // cols
    x = margin + (col + 0.5) * (usable_w / cols)
    y = margin + (row + 0.5) * (usable_h / rows)
    return round(x, 3), round(y, 3)


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


def _simple_lib_id(comp: SchemaComponent) -> str:
    """Map a component to one of the inline lib_symbols (fallback rendering)."""
    ref = comp.ref.upper()
    val = comp.value.upper()
    # 555 timer ICs — named pins GND/TRIG/OUT/RST/CTRL/THR/DIS/VCC
    if any(x in val for x in ["NE555", "LM555", "NA555", "SA555", "TLC555",
                               "ICM7555", "TS555"]):
        return "Timer:NE555P"
    # 3-pin voltage regulators — TO-220 / SOT-223 style
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


def _uuid4() -> str:
    import uuid
    return str(uuid.uuid4())


# Pin tip positions (dx, dy) relative to symbol origin — must match _INLINE_LIB_SYMBOLS
_IC_PIN_OFFSETS: dict[int, tuple[float, float]] = {
    1: (-5.08, -3.81),
    2: (-5.08, -1.27),
    3: (-5.08,  1.27),
    4: (-5.08,  3.81),
    5: ( 5.08,  3.81),
    6: ( 5.08,  1.27),
    7: ( 5.08, -1.27),
    8: ( 5.08, -3.81),
}

# Device:VReg_3Pin — IN(left) / GND(bottom) / OUT(right)
_VREG_PIN_OFFSETS: dict[int, tuple[float, float]] = {
    1: (-5.08, 0.0),   # IN  — left
    2: ( 0.0,  3.81),  # GND — bottom
    3: ( 5.08, 0.0),   # OUT — right
}


# --- Title block helpers ----------------------------------------------------


def _today_iso() -> str:
    """Return today's date in ISO format (YYYY-MM-DD), used in the title block."""
    from datetime import date
    return date.today().isoformat()


def _derive_title(components: list[SchemaComponent]) -> str:
    """Derive a project title from the most prominent component value.

    Heuristic: the first IC (ref starting with "U") wins; otherwise the first
    component's value. Title is truncated/escaped for KiCad's S-expression syntax.
    """
    if not components:
        return "Layrix Project"
    primary = next(
        (c for c in components if c.ref.upper().startswith("U")),
        components[0],
    )
    raw = (primary.value or "Layrix Project").strip()
    # Strip quotes that would break the S-expression
    raw = raw.replace('"', "")
    if len(raw) > 60:
        raw = raw[:57] + "..."
    return f"Layrix — {raw}"


# --- Power-net handling for "pro" rendering ---------------------------------

# Nets considered power rails — these are rendered with standard KiCad power
# symbols (`power:GND` triangle, `power:VCC` arrow) instead of plain text labels.
# Aligned with KiCad / EE convention: any +Vxxx is a positive supply rail.
_GND_NETS: frozenset[str] = frozenset({"GND", "VSS", "AGND", "DGND", "PGND", "GROUND"})
_VCC_NETS: frozenset[str] = frozenset({"VCC", "VDD", "VBUS", "VBAT"})


def _is_power_net(name: str) -> bool:
    """Return True if `name` should be rendered with a KiCad power symbol."""
    if not name:
        return False
    upper = name.upper().strip()
    if upper in _GND_NETS or upper in _VCC_NETS:
        return True
    # Positive rails like "+5V", "+3V3", "+3.3V", "+12V"
    if upper.startswith("+") and len(upper) >= 2:
        return True
    return False


def _power_lib_id(name: str) -> str:
    """Return the KiCad power lib_id for a given net name."""
    upper = name.upper().strip()
    return "power:GND" if upper in _GND_NETS else "power:VCC"


def _pin_offset(lib_id: str, pin_num: int) -> tuple[float, float]:
    # DIP-8 style ICs: Device:IC and Timer:NE555P share same pin geometry
    if lib_id in ("Device:IC", "Timer:NE555P"):
        return _IC_PIN_OFFSETS.get(pin_num, (0.0, 0.0))
    if lib_id == "Device:VReg_3Pin":
        return _VREG_PIN_OFFSETS.get(pin_num, (0.0, 0.0))
    # 2-pin horizontal symbols (R, C, LED, Conn): pin 1 left / pin 2 right
    if pin_num == 1:
        return (-3.81, 0.0)
    return (3.81, 0.0)


def _generate_schematic_fallback(
    components: list[SchemaComponent],
    connections: list[SchemaNet],
) -> str:
    """KiCad 7 fallback schematic: compact grid + net-label stubs.

    Each pin gets a short outward wire stub (2.54 mm) terminated by a net label.
    Net labels sharing the same name are electrically connected in KiCad/KiCanvas.
    No bus rails → compact paper, components clearly visible at zoom-to-fit.
    """
    n = len(components)
    cols = max(1, min(4, math.ceil(math.sqrt(n)))) if n else 1
    rows = max(1, math.ceil(n / cols)) if n else 1
    col_step = 55    # horizontal spacing between component origins (mm)
    row_step = 35    # vertical spacing — enough for 8-pin ICs with net labels
    stub_len = 2.54  # net-label stub length — one KiCad grid unit

    # ── Intelligent layout: KiCanvas title block has a FIXED height of ~43 mm
    # (verified empirically: for 93 mm paper, separator line at y≈50 mm).
    # Formula: paper_h = component_bottom_y + TITLE_PADDING + TITLE_BLOCK_HEIGHT
    # This guarantees a clean gap between the bottom component and the title block.
    TITLE_BLOCK_HEIGHT = 44   # mm — KiCad standard title block fixed height
    TITLE_PADDING      = 15   # mm — gap between last component label and title block (≥10 mm visual buffer)
    margin_top  = 25          # top margin: ≥20 mm from inner frame border (frame top at y≈5 mm) so reference labels don't crowd the border
    # margin_side accounts for BOTH component body (centered at origin_x)
    # AND the net-label text that extends to the left/right of the body.
    # Longest realistic net-label ("VCC_3V3", "LED_GREEN", "GND_R2") ≈ 18 mm
    # from body centre (half body width + stub 2.54 mm + text width).
    # Inner frame border is at x≈10 mm → need 38 mm so label text sits
    # ≥10 mm inside the frame (38 - 18 label_overhang = 20 mm body origin,
    # label text reaches x=20, clearance = 10 mm from frame at x=10).
    margin_side = 38
    comp_h_span = 18          # half-height of component body + value label below centre
    comp_w_span = 20          # half-width of component body + longest right-side net-label text

    # Bounding box of all component placements (bottom edge of last row)
    component_bottom_y = margin_top + (rows - 1) * row_step + comp_h_span
    component_right_x  = margin_side + (cols - 1) * col_step + comp_w_span

    paper_w = max(80, component_right_x + margin_side)
    paper_h = max(80, component_bottom_y + TITLE_PADDING + TITLE_BLOCK_HEIGHT)

    origin_x = margin_side
    origin_y = margin_top

    lines: list[str] = []
    lines.append(
        f'(kicad_sch (version 20230121) (generator "layrix-circuit-synth") (uuid "{_uuid4()}")'
    )
    lines.append(f'  (paper "User" {paper_w} {paper_h})')

    # Title block — fills the standard KiCad title block at bottom-right.
    # Project name is derived from the most prominent component's value.
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
        (origin_x + (i % cols) * col_step, origin_y + (i // cols) * row_step)
        for i in range(n)
    ]
    lib_ids: list[str] = [_simple_lib_id(c) for c in components]

    # --- Component instances ---
    for i, comp in enumerate(components):
        x, y = positions[i]
        lib_id = lib_ids[i]
        ref_e = comp.ref.replace('"', '\\"')
        val_e = comp.value.replace('"', '\\"')
        fp_e = comp.footprint.replace('"', '\\"')
        lines.append(
            f'  (symbol (lib_id "{lib_id}") (at {x} {y} 0) (unit 1) (in_bom yes) (on_board yes)'
        )
        lines.append(f'    (uuid "{_uuid4()}")')
        lines.append(
            f'    (property "Reference" "{ref_e}" (at {x} {y - 7} 0) '
            f'(effects (font (size 1.27 1.27)) (justify center)))'
        )
        lines.append(
            f'    (property "Value" "{val_e}" (at {x} {y + 7} 0) '
            f'(effects (font (size 1.27 1.27)) (justify center)))'
        )
        lines.append(
            f'    (property "Footprint" "{fp_e}" (at {x} {y + 10} 0) '
            f'(effects (font (size 1.27 1.27)) (hide yes)))'
        )
        lines.append('  )')

    # --- Net-label stubs: short wire + label OR power symbol at each pin ---
    # Power nets (GND, VCC, +5V, +3V3…) get standard KiCad power symbols
    # (triangle / arrow). Signal nets keep readable text labels.
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

            # Stub endpoint extends away from the component body
            if abs(dx) >= abs(dy):  # horizontal pin
                sign = -1 if dx < 0 else 1
                ex = round(px + sign * stub_len, 3)
                ey = py
                langle = 180 if dx < 0 else 0
            else:  # vertical pin (e.g. VReg_3Pin GND — always bottom)
                ex = px
                ey = round(py + stub_len, 3)
                langle = 90

            lines.append(
                f'  (wire (pts (xy {px} {py}) (xy {ex} {ey})) '
                f'(stroke (width 0.1524) (type default)) (uuid "{_uuid4()}"))'
            )
            if is_power:
                # Power symbol orientation: GND points down (rotation 0),
                # VCC points up (rotation 180). Choose orientation so the
                # symbol's pin connects to the stub endpoint.
                # GND triangle: pin at top, body extends downward → rotation 0
                # VCC arrow:    pin at bottom, body extends upward → rotation 0
                rot = 0
                lines.append(
                    f'  (symbol (lib_id "{power_id}") (at {ex} {ey} {rot}) '
                    f'(unit 1) (in_bom no) (on_board yes)'
                )
                lines.append(f'    (uuid "{_uuid4()}")')
                # Override the Value property to show the actual net name
                # (so "+5V", "+3V3", etc. display correctly even though they
                # all reuse the same `power:VCC` symbol shape).
                _value_y_offset = -3.81 if power_id == "power:GND" else 3.81
                lines.append(
                    f'    (property "Reference" "#PWR" (at {ex} {ey - 6.35} 0) '
                    f'(effects (font (size 1.27 1.27)) hide))'
                )
                lines.append(
                    f'    (property "Value" "{name_e}" (at {ex} {ey + _value_y_offset} 0) '
                    f'(effects (font (size 1.27 1.27))))'
                )
                lines.append('  )')
            else:
                lines.append(
                    f'  (label "{name_e}" (at {ex} {ey} {langle}) '
                    f'(effects (font (size 1.27 1.27))) '
                    f'(uuid "{_uuid4()}"))'
                )

    lines.append('  (sheet_instances (path "/" (page "1")))')
    lines.append(')')
    return "\n".join(lines)


def _pad_count(footprint: str) -> int:
    fp = footprint.upper()
    if "SOT-23-5" in fp:
        return 5
    if "SOT-23" in fp:
        return 3
    if "DIP-8" in fp or "TSSOP-8" in fp or "SOIC-8" in fp:
        return 8
    if "DIP-14" in fp:
        return 14
    if "DIP-16" in fp or "SOIC-16" in fp:
        return 16
    return 2


def _generate_pcb_sexpr(
    components: list[SchemaComponent],
    connections: list[SchemaNet],
    board_w: float,
    board_h: float,
) -> str:
    lines: list[str] = []
    lines.append('(kicad_pcb (version 20221018) (generator "layrix-circuit-synth")')
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

    lines.append('  (net 0 "")')
    for i, net_name in enumerate(([c.name for c in connections] or []), start=1):
        escaped = net_name.replace('"', '\\"')
        lines.append(f'  (net {i} "{escaped}")')

    bw, bh = board_w, board_h
    for x1, y1, x2, y2 in [(0, 0, bw, 0), (bw, 0, bw, bh), (bw, bh, 0, bh), (0, bh, 0, 0)]:
        lines.append(
            f'  (gr_line (start {x1} {y1}) (end {x2} {y2}) (layer "Edge.Cuts") (width 0.05))'
        )

    comp_positions: dict[str, tuple[float, float]] = {}
    cols = max(1, math.ceil(math.sqrt(len(components))))
    for idx, comp in enumerate(components):
        col = idx % cols
        row = idx // cols
        margin = 5.0
        x = margin + (col + 0.5) * ((board_w - 2 * margin) / cols)
        y = margin + (row + 0.5) * ((board_h - 2 * margin) / math.ceil(len(components) / cols))
        x, y = round(x, 3), round(y, 3)
        comp_positions[comp.ref] = (x, y)
        ref_e = comp.ref.replace('"', '\\"')
        val_e = comp.value.replace('"', '\\"')
        fp_e = comp.footprint.replace('"', '\\"')
        pad_count = _pad_count(comp.footprint)
        lines.append(f'  (footprint "{fp_e}" (layer "F.Cu") (at {x} {y})')
        lines.append(f'    (property "Reference" "{ref_e}" (at 0 -2 0) (layer "F.SilkS"))')
        lines.append(f'    (property "Value" "{val_e}" (at 0 2 0) (layer "F.Fab"))')
        spacing = 1.0
        start_x = -(pad_count - 1) * spacing / 2
        for p in range(pad_count):
            px = round(start_x + p * spacing, 3)
            lines.append(
                f'    (pad "{p + 1}" smd rect (at {px} 0) (size 0.6 0.6) (layers "F.Cu" "F.Paste" "F.Mask"))'
            )
        lines.append('  )')

    net_idx_map = {c.name: i + 1 for i, c in enumerate(connections)}
    for conn in connections:
        net_i = net_idx_map.get(conn.name, 0)
        pts: list[tuple[float, float]] = []
        for pin_ref in conn.pins:
            pos = comp_positions.get(pin_ref.ref)
            if pos:
                pad_c = _pad_count(
                    next((c.footprint for c in components if c.ref == pin_ref.ref), "0402")
                )
                spacing = 1.0
                start_x = -(pad_c - 1) * spacing / 2
                px = round(start_x + (pin_ref.pin - 1) * spacing, 3)
                pts.append((round(pos[0] + px, 3), round(pos[1], 3)))
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            lines.append(
                f'  (segment (start {x1} {y1}) (end {x2} {y2}) '
                f'(width 0.2) (layer "F.Cu") (net {net_i}))'
            )

    lines.append(')')
    return "\n".join(lines)


# Pre-load symbol cache at import time (non-blocking — runs once, ~100ms)
import threading as _threading
_threading.Thread(target=_load_symbol_cache, daemon=True).start()


# ============================================================
# Routes
# ============================================================

class SymbolValidationResult(BaseModel):
    ref: str
    original_symbol: str
    validated_symbol: str
    corrected: bool


class ValidateSymbolsRequest(BaseModel):
    components: list[SchemaComponent]


class ValidateSymbolsResponse(BaseModel):
    results: list[SymbolValidationResult]
    corrected_components: list[SchemaComponent]
    has_corrections: bool


@router.post("/validate-symbols", response_model=ValidateSymbolsResponse)
def validate_symbols(req: ValidateSymbolsRequest) -> ValidateSymbolsResponse:
    """
    Validate KiCad symbols for each component against local .kicad_sym libraries.
    Returns a corrected component list — symbols that don't exist are replaced with
    the closest generic fallback. Safe to call before /generate.
    """
    results: list[SymbolValidationResult] = []
    corrected_components: list[SchemaComponent] = []
    has_corrections = False

    for comp in req.components:
        original = _map_symbol(comp)
        validated = _safe_symbol(original)
        corrected = validated != original
        if corrected:
            has_corrections = True
        results.append(SymbolValidationResult(
            ref=comp.ref,
            original_symbol=original,
            validated_symbol=validated,
            corrected=corrected,
        ))
        # Apply the validated symbol back into the component
        corrected_components.append(comp.model_copy(update={"symbol": validated}))

    return ValidateSymbolsResponse(
        results=results,
        corrected_components=corrected_components,
        has_corrections=has_corrections,
    )


@router.post("/generate", response_model=CircuitSynthResponse)
def generate(req: CircuitSynthRequest) -> CircuitSynthResponse:
    """Convert JSON schema → native .kicad_sch + .kicad_pcb files."""
    if not req.components:
        return CircuitSynthResponse(success=False, error="No components in schema")

    sch_content: Optional[str] = None
    pcb_content: Optional[str] = None

    # Primary path: use circuit_synth library (requires KICAD_SYMBOL_DIR + UTF-8 mode)
    # Run in a thread with a hard 20s timeout — circuit_synth placement can hang.
    _CS_TIMEOUT = 20
    if _circuit_synth_available():
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _pool:
                    _fut = _pool.submit(_generate_with_circuit_synth, req, Path(tmp_dir))
                    try:
                        sch_content, pcb_content = _fut.result(timeout=_CS_TIMEOUT)
                    except concurrent.futures.TimeoutError:
                        _fut.cancel()
                        raise RuntimeError(
                            f"circuit_synth timed out after {_CS_TIMEOUT}s"
                        )
            if sch_content:
                logger.info("circuit_synth schematic generated successfully")
        except Exception as e:
            logger.warning(f"circuit_synth generation failed, using fallback: {e}")
            sch_content = None

    # Fallback: hand-written S-expression generator
    if not sch_content:
        logger.info("Using fallback S-expression schematic generator")
        sch_content = _generate_schematic_fallback(req.components, req.connections)

    # PCB: always use S-expression generator (circuit_synth PCB not yet enabled)
    if not pcb_content:
        pcb_content = _generate_pcb_sexpr(
            req.components, req.connections,
            req.board_width_mm, req.board_height_mm,
        )

    return CircuitSynthResponse(
        success=True,
        kicad_sch_content=sch_content,
        kicad_pcb_content=pcb_content,
    )
