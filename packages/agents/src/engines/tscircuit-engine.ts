import {
  convertSoupToGerberCommands,
  stringifyGerberCommandLayers,
} from 'circuit-json-to-gerber';
import type { SchemaComponent, SchemaPin, SchemaNet, SchemaJson } from '@layrix/types';

// Re-export so existing consumers of @layrix/agents keep working
export type { SchemaComponent, SchemaPin, SchemaNet, SchemaJson };

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

// --- Smart layout --------------------------------------------------------
// Groups components by function: ICs → center, passives → cluster near ICs,
// connectors → left edge, LEDs → top-right, others → bottom row.

type PlacedComp = { ref: string; x: number; y: number };

function autoLayout(
  components: SchemaComponent[],
  boardW: number,
  boardH: number
): PlacedComp[] {
  const margin = 6;
  const usableW = boardW - margin * 2;

  const ics        = components.filter(c => /^U\d*/i.test(c.ref));
  const connectors = components.filter(c => /^J\d*/i.test(c.ref));
  const leds       = components.filter(c => /^LED/i.test(c.ref));
  const passives   = components.filter(c => /^[RCL]\d*/i.test(c.ref));
  const transistors = components.filter(c => /^[QD]\d*/i.test(c.ref));
  const rest       = components.filter(
    c => !ics.includes(c) && !connectors.includes(c) && !leds.includes(c)
      && !passives.includes(c) && !transistors.includes(c)
  );

  const result: PlacedComp[] = [];

  // ── ICs: center horizontal band ──────────────────────────────────────
  const icCenterY = boardH * 0.48;
  const icStep    = ics.length > 1 ? usableW / (ics.length + 1) : usableW / 2;
  ics.forEach((ic, i) => {
    result.push({
      ref: ic.ref,
      x: margin + icStep * (i + 1),
      y: icCenterY,
    });
  });

  // ── Passives: two rows above / below IC band ──────────────────────────
  // Row A: y = icCenterY - gap   Row B: y = icCenterY + gap
  // Distribute evenly across usable width in batches of columns
  const passiveGap = 10;
  const passiveCols = Math.max(4, Math.ceil(passives.length / 2));
  const passiveStep = usableW / (passiveCols + 1);
  passives.forEach((p, i) => {
    const col     = i % passiveCols;
    const rowAbove = Math.floor(i / passiveCols) % 2 === 0;
    result.push({
      ref: p.ref,
      x: margin + passiveStep * (col + 1),
      y: icCenterY + (rowAbove ? -passiveGap : passiveGap),
    });
  });

  // ── Connectors: left edge, stacked vertically ────────────────────────
  connectors.forEach((conn, i) => {
    result.push({
      ref: conn.ref,
      x: margin + 4,
      y: margin + 10 + i * 14,
    });
  });

  // ── LEDs: top-right corner ───────────────────────────────────────────
  leds.forEach((led, i) => {
    result.push({
      ref: led.ref,
      x: boardW - margin - 8 - i * 10,
      y: margin + 6,
    });
  });

  // ── Transistors / diodes: bottom band ───────────────────────────────
  const tranStep = transistors.length > 0 ? usableW / (transistors.length + 1) : 0;
  transistors.forEach((t, i) => {
    result.push({
      ref: t.ref,
      x: margin + tranStep * (i + 1),
      y: boardH - margin - 8,
    });
  });

  // ── Anything else: bottom-right ──────────────────────────────────────
  const restStep = rest.length > 0 ? usableW / (rest.length + 1) : 0;
  rest.forEach((c, i) => {
    result.push({
      ref: c.ref,
      x: margin + restStep * (i + 1),
      y: boardH - margin - 18,
    });
  });

  return result;
}

// --- Nearest-neighbour trace routing -------------------------------------
// For each net, collect all pads that logically belong to it by matching
// component reference patterns (power pins, known signal names).
// Falls back to minimum-spanning-tree by Euclidean distance so traces
// are short and don't cross the whole board.

function dist(a: { x: number; y: number }, b: { x: number; y: number }): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/** Prim's MST: returns edges [from, to] connecting all pads with minimum total length */
function mstEdges(
  pads: Array<{ x: number; y: number }>
): Array<[{ x: number; y: number }, { x: number; y: number }]> {
  if (pads.length < 2) return [];
  const inTree = new Set<number>([0]);
  const edges: Array<[{ x: number; y: number }, { x: number; y: number }]> = [];

  while (inTree.size < pads.length) {
    let bestDist = Infinity;
    let bestFrom = -1;
    let bestTo   = -1;

    for (const fi of inTree) {
      for (let ti = 0; ti < pads.length; ti++) {
        if (inTree.has(ti)) continue;
        const d = dist(pads[fi]!, pads[ti]!);
        if (d < bestDist) { bestDist = d; bestFrom = fi; bestTo = ti; }
      }
    }

    if (bestFrom === -1) break;
    inTree.add(bestTo);
    edges.push([pads[bestFrom]!, pads[bestTo]!]);
  }

  return edges;
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
    const pos  = positions[idx]!;
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

  // --- MST trace routing — one tree per net, shortest total wire length ---
  if (schemaJson.nets.length > 0) {
    const netPadMap = new Map<string, Array<{ x: number; y: number }>>();
    for (const net of schemaJson.nets) netPadMap.set(net, []);

    if (schemaJson.connections && schemaJson.connections.length > 0) {
      // Use actual netlist connectivity: map each net to its physical pad positions
      const compPosMap = new Map<string, { x: number; y: number }>();
      const compDimsMap = new Map<string, PadDimensions>();
      schemaJson.components.forEach((comp, idx) => {
        compPosMap.set(comp.ref, positions[idx]!);
        compDimsMap.set(comp.ref, getFootprintDims(comp.footprint));
      });

      for (const conn of schemaJson.connections) {
        if (!netPadMap.has(conn.name)) netPadMap.set(conn.name, []);
        for (const { ref, pin } of conn.pins) {
          const pos = compPosMap.get(ref);
          const dims = compDimsMap.get(ref);
          if (pos && dims) {
            const pad = dims.pads[pin - 1];
            if (pad) {
              netPadMap.get(conn.name)!.push({ x: pos.x + pad.dx, y: pos.y + pad.dy });
            }
          }
        }
      }
    } else {
      // Fallback: round-robin distribution when no connectivity data is available
      const allPads: Array<{ x: number; y: number }> = [];
      schemaJson.components.forEach((comp, idx) => {
        const pos = positions[idx]!;
        const dims = getFootprintDims(comp.footprint);
        for (const pad of dims.pads) {
          allPads.push({ x: pos.x + pad.dx, y: pos.y + pad.dy });
        }
      });
      allPads.forEach((pad, i) => {
        const net = schemaJson.nets[i % schemaJson.nets.length]!;
        netPadMap.get(net)!.push(pad);
      });
    }

    let traceIdx = 0;
    for (const [net, pads] of netPadMap) {
      if (pads.length < 2) continue;
      const width = traceWidth(net);
      const edges = mstEdges(pads);

      for (const [from, to] of edges) {
        // Route as L-shaped (horizontal first, then vertical)
        soup.push({
          type: 'pcb_trace',
          pcb_trace_id: `trace-${traceIdx++}`,
          route: [
            { x: from.x, y: from.y },
            { x: to.x,   y: from.y },
            { x: to.x,   y: to.y   },
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
    gerbers = {};
  }

  return { circuitJson: soup, gerbers, boardWidthMm, boardHeightMm, placements };
}

/** Returns true when a schema is simple enough for TSCircuit */
export function isSimpleCircuit(schema: SchemaJson): boolean {
  return schema.components.length <= 20 && schema.nets.length <= 30;
}
