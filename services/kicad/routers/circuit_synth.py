"""
Circuit-Synth router — converts JSON schema to native .kicad_sch + .kicad_pcb files.
Accepts the schema JSON produced by Haiku and returns KiCad file contents as strings.
"""

import math
import os
import tempfile
import logging
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

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
# Layout helpers
# ============================================================

def _grid_position(idx: int, total: int, board_w: float, board_h: float) -> tuple[float, float]:
    """Distribute components in a grid, centered on the board."""
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

# ============================================================
# .kicad_sch generator (KiCad 7+ S-expression format)
# ============================================================

def _generate_schematic(
    components: list[SchemaComponent],
    connections: list[SchemaNet],
) -> str:
    """Generate a minimal but valid KiCad 7 schematic file."""
    lines: list[str] = []
    lines.append('(kicad_sch (version 20230121) (generator "layrix-circuit-synth")')
    lines.append('  (paper "A4")')
    lines.append('  (lib_symbols)')

    # Place components on a 10×10 grid (in schematic units — 1 unit = 1mm)
    cols = max(1, math.ceil(math.sqrt(len(components))))
    for i, comp in enumerate(components):
        col = i % cols
        row = i // cols
        x = 50 + col * 25
        y = 50 + row * 25
        lib_id = _footprint_to_lib_id(comp.footprint)
        ref_escaped = comp.ref.replace('"', '\\"')
        val_escaped = comp.value.replace('"', '\\"')
        fp_escaped = comp.footprint.replace('"', '\\"')
        lines.append(f'  (symbol (lib_id "{lib_id}") (at {x} {y} 0) (unit 1)')
        lines.append(f'    (property "Reference" "{ref_escaped}" (at {x} {y - 4} 0)')
        lines.append(f'      (effects (font (size 1.27 1.27))))')
        lines.append(f'    (property "Value" "{val_escaped}" (at {x} {y + 4} 0)')
        lines.append(f'      (effects (font (size 1.27 1.27))))')
        lines.append(f'    (property "Footprint" "{fp_escaped}" (at {x} {y + 8} 0)')
        lines.append(f'      (effects (font (size 1.27 1.27)) (hide yes)))')
        if comp.lcsc:
            lcsc_escaped = comp.lcsc.replace('"', '\\"')
            lines.append(f'    (property "LCSC" "{lcsc_escaped}" (at {x} {y + 12} 0)')
            lines.append(f'      (effects (font (size 1.27 1.27)) (hide yes)))')
        lines.append('  )')

    # Net labels
    for net in connections:
        if not net.pins:
            continue
        name_escaped = net.name.replace('"', '\\"')
        # Place label near first component
        comp_idx = next(
            (j for j, c in enumerate(components) if c.ref == net.pins[0].ref), 0
        )
        col = comp_idx % cols
        row = comp_idx // cols
        lx = 50 + col * 25 + 8
        ly = 50 + row * 25
        lines.append(f'  (global_label "{name_escaped}" (shape input) (at {lx} {ly} 0)')
        lines.append('    (effects (font (size 1.27 1.27)))')
        lines.append('  )')

    lines.append('  (sheet_instances (path "/" (page "1")))')
    lines.append(')')
    return "\n".join(lines)


def _footprint_to_lib_id(footprint: str) -> str:
    """Map a footprint string to a KiCad symbol lib_id."""
    fp_upper = footprint.upper()
    if any(x in fp_upper for x in ["0402", "0603", "0805", "1206"]):
        return "Device:R"
    if "LED" in fp_upper:
        return "Device:LED"
    if "CAP" in fp_upper or "C_" in fp_upper:
        return "Device:C"
    if "SOT-23" in fp_upper:
        return "Device:Q_NPN_BCE"
    if "DIP" in fp_upper or "SOIC" in fp_upper:
        return "Device:IC"
    return "Device:R"

# ============================================================
# .kicad_pcb generator (pcbnew API or fallback S-expression)
# ============================================================

def _generate_pcb_pcbnew(
    components: list[SchemaComponent],
    connections: list[SchemaNet],
    board_w: float,
    board_h: float,
    output_path: str,
) -> bool:
    """Generate PCB using pcbnew Python API. Returns True if successful."""
    try:
        import pcbnew  # type: ignore[import]
        board = pcbnew.BOARD()

        # Board outline (Edge.Cuts)
        edge_layer = pcbnew.Edge_Cuts
        pts = [
            (0, 0), (board_w, 0), (board_w, board_h), (0, board_h)
        ]
        for i in range(4):
            seg = pcbnew.PCB_SHAPE(board)
            seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
            seg.SetLayer(edge_layer)
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % 4]
            seg.SetStart(pcbnew.FromMM(x1), pcbnew.FromMM(y1))
            seg.SetEnd(pcbnew.FromMM(x2), pcbnew.FromMM(y2))
            board.Add(seg)

        # Add footprints
        fp_map: dict[str, pcbnew.FOOTPRINT] = {}
        for idx, comp in enumerate(components):
            fp = pcbnew.FOOTPRINT(board)
            fp.SetReference(comp.ref)
            fp.SetValue(comp.value)
            x, y = _grid_position(idx, len(components), board_w, board_h)
            fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
            board.Add(fp)
            fp_map[comp.ref] = fp

        # Add copper traces from connections (simple straight lines)
        for conn in connections:
            pts_list = []
            for pin_ref in conn.pins:
                if pin_ref.ref in fp_map:
                    fp = fp_map[pin_ref.ref]
                    pts_list.append(fp.GetPosition())
            for i in range(len(pts_list) - 1):
                track = pcbnew.PCB_TRACK(board)
                track.SetStart(pts_list[i])
                track.SetEnd(pts_list[i + 1])
                track.SetWidth(pcbnew.FromMM(0.2))
                track.SetLayer(pcbnew.F_Cu)
                board.Add(track)

        board.Save(output_path)
        return True
    except Exception as e:
        logger.warning(f"pcbnew generation failed: {e}")
        return False


def _generate_pcb_sexpr(
    components: list[SchemaComponent],
    connections: list[SchemaNet],
    board_w: float,
    board_h: float,
) -> str:
    """Generate .kicad_pcb S-expression without pcbnew (fallback)."""
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

    # Net list
    lines.append('  (net 0 "")')
    for i, net_name in enumerate(([c.name for c in connections] or []), start=1):
        escaped = net_name.replace('"', '\\"')
        lines.append(f'  (net {i} "{escaped}")')

    # Board outline
    bw, bh = board_w, board_h
    outline = [(0, 0, bw, 0), (bw, 0, bw, bh), (bw, bh, 0, bh), (0, bh, 0, 0)]
    for x1, y1, x2, y2 in outline:
        lines.append(
            f'  (gr_line (start {x1} {y1}) (end {x2} {y2}) (layer "Edge.Cuts") (width 0.05))'
        )

    # Footprints (minimal — pads only)
    comp_positions: dict[str, tuple[float, float]] = {}
    for idx, comp in enumerate(components):
        x, y = _grid_position(idx, len(components), board_w, board_h)
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

    # Traces from connections
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
    # Default passives (0402, 0603, 0805, 1206, LED, CAP…)
    return 2


# ============================================================
# Route
# ============================================================

@router.post("/generate", response_model=CircuitSynthResponse)
def generate(req: CircuitSynthRequest) -> CircuitSynthResponse:
    """Convert JSON schema → native .kicad_sch + .kicad_pcb files."""
    if not req.components:
        return CircuitSynthResponse(success=False, error="No components in schema")

    try:
        # Generate schematic
        sch_content = _generate_schematic(req.components, req.connections)

        # Generate PCB — try pcbnew first, fallback to S-expression
        with tempfile.NamedTemporaryFile(suffix=".kicad_pcb", delete=False) as tmp:
            tmp_path = tmp.name

        pcb_content: Optional[str] = None
        try:
            ok = _generate_pcb_pcbnew(
                req.components, req.connections,
                req.board_width_mm, req.board_height_mm, tmp_path
            )
            if ok and os.path.exists(tmp_path):
                with open(tmp_path) as f:
                    pcb_content = f.read()
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

        if not pcb_content:
            pcb_content = _generate_pcb_sexpr(
                req.components, req.connections,
                req.board_width_mm, req.board_height_mm
            )

        return CircuitSynthResponse(
            success=True,
            kicad_sch_content=sch_content,
            kicad_pcb_content=pcb_content,
        )

    except Exception as e:
        logger.exception("circuit-synth generation error")
        return CircuitSynthResponse(success=False, error=str(e))
