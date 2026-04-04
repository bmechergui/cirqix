import {
  convertSoupToGerberCommands,
  stringifyGerberCommandLayers,
} from 'circuit-json-to-gerber';

// --- Types ---------------------------------------------------------------

export interface SchemaComponent {
  ref: string;
  value: string;
  lcsc?: string;
  footprint: string;
}

export interface SchemaJson {
  components: SchemaComponent[];
  nets: string[];
}

export interface TSCircuitResult {
  /** Circuit-json soup — ready for viewer + Gerber export */
  circuitJson: object[];
  /** Gerber layers: { 'F.Cu': '...gerber...', 'B.Cu': '...', ... } */
  gerbers: Record<string, string>;
  boardWidthMm: number;
  boardHeightMm: number;
  /** Viewer-friendly placement summary */
  placements: Array<{ ref: string; x_mm: number; y_mm: number; rotation: number; side: string }>;
}

// --- Footprint dimensions (mm) -------------------------------------------

interface PadDimensions {
  width: number;
  height: number;
  pads: Array<{ dx: number; dy: number; net?: string }>;
}

const FOOTPRINT_DIMS: Record<string, PadDimensions> = {
  '0402': { width: 1.0, height: 0.5, pads: [{ dx: -0.5, dy: 0 }, { dx: 0.5, dy: 0 }] },
  '0603': { width: 1.6, height: 0.8, pads: [{ dx: -0.8, dy: 0 }, { dx: 0.8, dy: 0 }] },
  '0805': { width: 2.0, height: 1.25, pads: [{ dx: -1.0, dy: 0 }, { dx: 1.0, dy: 0 }] },
  '1206': { width: 3.2, height: 1.6, pads: [{ dx: -1.6, dy: 0 }, { dx: 1.6, dy: 0 }] },
  'SOT-23': {
    width: 2.9, height: 1.6,
    pads: [{ dx: -1.4, dy: -0.9 }, { dx: -1.4, dy: 0.9 }, { dx: 1.4, dy: 0 }],
  },
  'SOT-23-5': {
    width: 3.0, height: 1.8,
    pads: [
      { dx: -1.4, dy: -0.95 }, { dx: -1.4, dy: 0 }, { dx: -1.4, dy: 0.95 },
      { dx: 1.4, dy: -0.95 }, { dx: 1.4, dy: 0.95 },
    ],
  },
  'TSSOP-8': {
    width: 4.4, height: 3.0,
    pads: Array.from({ length: 8 }, (_, i) => ({
      dx: i < 4 ? -2.0 : 2.0,
      dy: (i < 4 ? i : i - 4) * 0.65 - 0.975,
    })),
  },
  'DIP-8': {
    width: 8.0, height: 9.5,
    pads: Array.from({ length: 8 }, (_, i) => ({
      dx: i < 4 ? -3.8 : 3.8,
      dy: (i < 4 ? i : 7 - i) * 2.54 - 3.81,
    })),
  },
  'LED': { width: 2.0, height: 1.2, pads: [{ dx: -0.9, dy: 0 }, { dx: 0.9, dy: 0 }] },
};

const PAD_SIZE = { width: 0.8, height: 0.8 };

function getFootprintDims(footprint: string): PadDimensions {
  const key = Object.keys(FOOTPRINT_DIMS).find(
    (k) => footprint.toUpperCase().includes(k.toUpperCase())
  );
  return FOOTPRINT_DIMS[key ?? '0402'] ?? FOOTPRINT_DIMS['0402']!;
}

// --- Net helpers ---------------------------------------------------------

const POWER_NET_PREFIXES = ['GND', 'VSS', 'VCC', 'VDD', 'VIN', 'VOUT', 'VBAT', '3V3', '5V', '12V', '24V', 'PWR', 'POWER'];

function isPowerNet(netName: string): boolean {
  const u = netName.toUpperCase();
  return POWER_NET_PREFIXES.some((p) => u === p || u.startsWith(p));
}

function traceWidth(netName: string): number {
  return isPowerNet(netName) ? 0.3 : 0.15;
}

// --- Auto-layout ---------------------------------------------------------

function autoLayout(
  components: SchemaComponent[],
  boardW: number,
  boardH: number
): Array<{ ref: string; x: number; y: number }> {
  const cols = Math.max(1, Math.ceil(Math.sqrt(components.length)));
  const rows = Math.ceil(components.length / cols);
  const spacingX = boardW / (cols + 1);
  const spacingY = boardH / (rows + 1);

  return components.map((c, i) => ({
    ref: c.ref,
    x: spacingX * ((i % cols) + 1),
    y: spacingY * (Math.floor(i / cols) + 1),
  }));
}

// --- Engine --------------------------------------------------------------

export async function runTSCircuitEngine(
  schemaJson: SchemaJson,
  boardWidthMm = 50,
  boardHeightMm = 50
): Promise<TSCircuitResult> {
  const soup: object[] = [];
  const placements: TSCircuitResult['placements'] = [];

  // Board outline
  soup.push({
    type: 'pcb_board',
    pcb_board_id: 'board-1',
    center: { x: boardWidthMm / 2, y: boardHeightMm / 2 },
    width: boardWidthMm,
    height: boardHeightMm,
    num_layers: 2,
    thickness: 1.6,
  });

  const positions = autoLayout(schemaJson.components, boardWidthMm, boardHeightMm);

  schemaJson.components.forEach((comp, idx) => {
    const pos = positions[idx]!;
    const dims = getFootprintDims(comp.footprint);
    const pcbCompId = `pc-${comp.ref}`;

    // PCB component
    soup.push({
      type: 'pcb_component',
      pcb_component_id: pcbCompId,
      source_component_id: `sc-${comp.ref}`,
      center: { x: pos.x, y: pos.y },
      layer: 'top',
      rotation: 0,
      width: dims.width,
      height: dims.height,
    });

    // SMT pads
    dims.pads.forEach((pad, padIdx) => {
      soup.push({
        type: 'pcb_smtpad',
        pcb_smtpad_id: `pad-${comp.ref}-${padIdx}`,
        pcb_component_id: pcbCompId,
        shape: 'rect',
        x: pos.x + pad.dx,
        y: pos.y + pad.dy,
        width: PAD_SIZE.width,
        height: PAD_SIZE.height,
        layer: 'top',
        port_hints: [`${padIdx + 1}`],
      });
    });

    // Silkscreen outline
    const hw = dims.width / 2;
    const hh = dims.height / 2;
    soup.push({
      type: 'pcb_silkscreen_path',
      pcb_silkscreen_path_id: `silk-${comp.ref}`,
      pcb_component_id: pcbCompId,
      layer: 'top',
      route: [
        { x: pos.x - hw, y: pos.y - hh },
        { x: pos.x + hw, y: pos.y - hh },
        { x: pos.x + hw, y: pos.y + hh },
        { x: pos.x - hw, y: pos.y + hh },
        { x: pos.x - hw, y: pos.y - hh },
      ],
      stroke_width: 0.1,
    });

    // Silkscreen ref label
    soup.push({
      type: 'pcb_silkscreen_text',
      pcb_silkscreen_text_id: `ref-${comp.ref}`,
      pcb_component_id: pcbCompId,
      layer: 'top',
      text: comp.ref,
      anchor_position: { x: pos.x, y: pos.y - dims.height / 2 - 0.5 },
      font_size: 0.6,
      font_thickness: 0.1,
      anchor_alignment: 'center',
    });

    placements.push({
      ref: comp.ref,
      x_mm: pos.x,
      y_mm: pos.y,
      rotation: 0,
      side: 'front',
    });
  });

  // --- Route generation — L-shaped traces connecting pads of the same net ----
  if (schemaJson.nets.length > 0) {
    // Assign pads to nets (round-robin by global pad index)
    const netPadMap = new Map<string, Array<{ x: number; y: number }>>();
    for (const net of schemaJson.nets) netPadMap.set(net, []);

    let globalPadIdx = 0;
    schemaJson.components.forEach((comp, idx) => {
      const pos = positions[idx]!;
      const dims = getFootprintDims(comp.footprint);
      for (const pad of dims.pads) {
        const net = schemaJson.nets[globalPadIdx % schemaJson.nets.length]!;
        netPadMap.get(net)!.push({ x: pos.x + pad.dx, y: pos.y + pad.dy });
        globalPadIdx++;
      }
    });

    let traceIdx = 0;
    for (const [net, pads] of netPadMap) {
      if (pads.length < 2) continue;
      // Sort by x then y for deterministic routing
      const sorted = [...pads].sort((a, b) => a.x - b.x || a.y - b.y);
      const width = traceWidth(net);
      for (let i = 0; i < sorted.length - 1; i++) {
        const from = sorted[i]!;
        const to   = sorted[i + 1]!;
        soup.push({
          type: 'pcb_trace',
          pcb_trace_id: `trace-${traceIdx++}`,
          route: [
            { x: from.x, y: from.y },
            { x: to.x,   y: from.y }, // horizontal segment
            { x: to.x,   y: to.y   }, // vertical segment
          ],
          stroke_width: width,
          layer: 'top',
        });
      }
    }
  }

  // Ground copper pour on B.Cu — 1 mm inset from board edge
  const gndNet = schemaJson.nets.find((n) => isPowerNet(n) && n.toUpperCase().startsWith('GND'))
    ?? schemaJson.nets.find((n) => isPowerNet(n));
  if (gndNet) {
    const inset = 1;
    soup.push({
      type: 'pcb_copper_fill',
      pcb_copper_fill_id: 'gnd-pour',
      layer: 'bottom',
      net: gndNet,
      x: inset,
      y: inset,
      width: boardWidthMm - inset * 2,
      height: boardHeightMm - inset * 2,
    });
  }

  // Generate Gerbers
  let gerbers: Record<string, string> = {};
  try {
    const gerberCommands = convertSoupToGerberCommands(soup as Parameters<typeof convertSoupToGerberCommands>[0]);
    gerbers = stringifyGerberCommandLayers(gerberCommands) as Record<string, string>;
  } catch {
    // Gerber generation is best-effort — circuit-json is still useful for the viewer
    gerbers = {};
  }

  return { circuitJson: soup, gerbers, boardWidthMm, boardHeightMm, placements };
}

/** Returns true when a schema is simple enough for TSCircuit */
export function isSimpleCircuit(schema: SchemaJson): boolean {
  return schema.components.length <= 20 && schema.nets.length <= 30;
}
