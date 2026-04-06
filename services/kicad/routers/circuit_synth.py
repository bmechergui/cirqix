"""
Circuit-Synth router — converts JSON schema to native .kicad_sch + .kicad_pcb files.
Primary path: circuit_synth Python library (requires KICAD_SYMBOL_DIR).
Fallback path: hand-written KiCad 7 S-expression generator.
"""

import math
import os
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
    """Check if circuit_synth library and KICAD_SYMBOL_DIR are both available."""
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
            symbol = _map_symbol(comp)
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


def _generate_schematic_fallback(
    components: list[SchemaComponent],
    connections: list[SchemaNet],
) -> str:
    """Minimal but valid KiCad 7 schematic — no symbol bodies (fallback)."""
    lines: list[str] = []
    lines.append('(kicad_sch (version 20230121) (generator "layrix-circuit-synth")')
    lines.append('  (paper "A4")')
    lines.append('  (lib_symbols)')

    cols = max(1, math.ceil(math.sqrt(len(components))))
    for i, comp in enumerate(components):
        col = i % cols
        row = i // cols
        x = 50 + col * 25
        y = 50 + row * 25
        lib_id = _map_symbol(comp)
        ref_e = comp.ref.replace('"', '\\"')
        val_e = comp.value.replace('"', '\\"')
        fp_e = comp.footprint.replace('"', '\\"')
        lines.append(f'  (symbol (lib_id "{lib_id}") (at {x} {y} 0) (unit 1)')
        lines.append(f'    (property "Reference" "{ref_e}" (at {x} {y - 4} 0)')
        lines.append(f'      (effects (font (size 1.27 1.27))))')
        lines.append(f'    (property "Value" "{val_e}" (at {x} {y + 4} 0)')
        lines.append(f'      (effects (font (size 1.27 1.27))))')
        lines.append(f'    (property "Footprint" "{fp_e}" (at {x} {y + 8} 0)')
        lines.append(f'      (effects (font (size 1.27 1.27)) (hide yes)))')
        lines.append('  )')

    for net in connections:
        if not net.pins:
            continue
        name_e = net.name.replace('"', '\\"')
        comp_idx = next((j for j, c in enumerate(components) if c.ref == net.pins[0].ref), 0)
        col = comp_idx % cols
        row = comp_idx // cols
        lx = 50 + col * 25 + 8
        ly = 50 + row * 25
        lines.append(f'  (global_label "{name_e}" (shape input) (at {lx} {ly} 0)')
        lines.append('    (effects (font (size 1.27 1.27)))')
        lines.append('  )')

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


# ============================================================
# Route
# ============================================================

@router.post("/generate", response_model=CircuitSynthResponse)
def generate(req: CircuitSynthRequest) -> CircuitSynthResponse:
    """Convert JSON schema → native .kicad_sch + .kicad_pcb files."""
    if not req.components:
        return CircuitSynthResponse(success=False, error="No components in schema")

    sch_content: Optional[str] = None
    pcb_content: Optional[str] = None

    # Primary path: use circuit_synth library (requires KICAD_SYMBOL_DIR)
    if _circuit_synth_available():
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                sch_content, pcb_content = _generate_with_circuit_synth(
                    req, Path(tmp_dir)
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
