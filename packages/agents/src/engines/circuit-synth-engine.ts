/**
 * Circuit-Synth engine — generates native .kicad_sch + .kicad_pcb files.
 *
 * Always works without any external service:
 *   - Inline TypeScript S-expression generators produce valid KiCad 7 files
 *   - If KICAD_SERVICE_URL is set, the Python service is tried first for pcbnew quality
 *
 * TSCircuit is NEVER used — this is the sole engine.
 */

import type { SchemaJson, SchemaComponent, SchemaNet } from '@layrix/types';

export type { SchemaJson };

export interface CircuitSynthResult {
  kicad_sch_content: string;
  kicad_pcb_content: string;
}

// ============================================================
// Footprint dimensions (mm) — pad count + relative pad positions
// ============================================================

interface PadDimensions {
  width: number;
  height: number;
  pads: Array<{ dx: number; dy: number }>;
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

function getFootprintDims(footprint: string): PadDimensions {
  const key = Object.keys(FOOTPRINT_DIMS).find(
    (k) => footprint.toUpperCase().includes(k.toUpperCase())
  );
  return FOOTPRINT_DIMS[key ?? '0402'] ?? FOOTPRINT_DIMS['0402']!;
}

function padCount(footprint: string): number {
  return getFootprintDims(footprint).pads.length;
}

// ============================================================
// Net helpers — power vs signal trace widths
// ============================================================

const POWER_NET_PREFIXES = ['GND', 'VSS', 'VCC', 'VDD', 'VIN', 'VOUT', 'VBAT', '3V3', '5V', '12V', '24V', 'PWR'];

function isPowerNet(netName: string): boolean {
  const u = netName.toUpperCase();
  return POWER_NET_PREFIXES.some((p) => u === p || u.startsWith(p));
}

function traceWidth(netName: string): number {
  return isPowerNet(netName) ? 0.3 : 0.15;
}

// ============================================================
// Smart layout — ICs center, passives cluster, connectors left
// ============================================================

interface PlacedComp { ref: string; x: number; y: number }

function autoLayout(
  components: SchemaComponent[],
  boardW: number,
  boardH: number
): PlacedComp[] {
  const margin = 6;
  const usableW = boardW - margin * 2;

  const ics         = components.filter(c => /^U\d*/i.test(c.ref));
  const connectors  = components.filter(c => /^J\d*/i.test(c.ref));
  const leds        = components.filter(c => /^LED/i.test(c.ref));
  const passives    = components.filter(c => /^[RCL]\d*/i.test(c.ref));
  const transistors = components.filter(c => /^[QD]\d*/i.test(c.ref));
  const rest        = components.filter(
    c => !ics.includes(c) && !connectors.includes(c) && !leds.includes(c)
      && !passives.includes(c) && !transistors.includes(c)
  );

  const result: PlacedComp[] = [];

  // ICs: center horizontal band
  const icCenterY = boardH * 0.48;
  const icStep = ics.length > 1 ? usableW / (ics.length + 1) : usableW / 2;
  ics.forEach((ic, i) => {
    result.push({ ref: ic.ref, x: margin + icStep * (i + 1), y: icCenterY });
  });

  // Passives: two rows above / below IC band
  const passiveGap  = 10;
  const passiveCols = Math.max(4, Math.ceil(passives.length / 2));
  const passiveStep = usableW / (passiveCols + 1);
  passives.forEach((p, i) => {
    const col      = i % passiveCols;
    const rowAbove = Math.floor(i / passiveCols) % 2 === 0;
    result.push({
      ref: p.ref,
      x: margin + passiveStep * (col + 1),
      y: icCenterY + (rowAbove ? -passiveGap : passiveGap),
    });
  });

  // Connectors: left edge, stacked vertically
  connectors.forEach((conn, i) => {
    result.push({ ref: conn.ref, x: margin + 4, y: margin + 10 + i * 14 });
  });

  // LEDs: top-right corner
  leds.forEach((led, i) => {
    result.push({ ref: led.ref, x: boardW - margin - 8 - i * 10, y: margin + 6 });
  });

  // Transistors/diodes: bottom band
  const tranStep = transistors.length > 0 ? usableW / (transistors.length + 1) : 0;
  transistors.forEach((t, i) => {
    result.push({ ref: t.ref, x: margin + tranStep * (i + 1), y: boardH - margin - 8 });
  });

  // Anything else: bottom-right area
  const restStep = rest.length > 0 ? usableW / (rest.length + 1) : 0;
  rest.forEach((c, i) => {
    result.push({ ref: c.ref, x: margin + restStep * (i + 1), y: boardH - margin - 18 });
  });

  return result;
}

// ============================================================
// MST routing — Prim's algorithm, minimum total trace length
// ============================================================

function dist(a: { x: number; y: number }, b: { x: number; y: number }): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

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

function footprintToLibId(footprint: string): string {
  const fp = footprint.toUpperCase();
  if (fp.includes('LED')) return 'Device:LED';
  if (fp.includes('CAP') || fp.includes('C_')) return 'Device:C';
  if (fp.includes('SOT-23')) return 'Device:Q_NPN_BCE';
  if (fp.includes('DIP') || fp.includes('SOIC')) return 'Device:IC';
  if (fp.includes('CONN') || fp.includes('2PIN') || fp.includes('2BROCHE')) return 'Connector_Generic:Conn_01x02';
  return 'Device:R';
}

// ============================================================
// .kicad_sch generator (KiCad 7 S-expression format)
// ============================================================

function generateSchematic(
  components: SchemaComponent[],
  connections: SchemaNet[]
): string {
  const lines: string[] = [];
  lines.push('(kicad_sch (version 20230121) (generator "layrix-circuit-synth")');
  lines.push('  (paper "A4")');
  lines.push('  (lib_symbols)');

  const cols = Math.max(1, Math.ceil(Math.sqrt(components.length)));

  components.forEach((comp, i) => {
    const col = i % cols;
    const row = Math.floor(i / cols);
    const x = 50 + col * 30;
    const y = 50 + row * 30;
    const libId = footprintToLibId(comp.footprint);
    const ref = comp.ref.replace(/"/g, '\\"');
    const val = comp.value.replace(/"/g, '\\"');
    const fp  = comp.footprint.replace(/"/g, '\\"');

    lines.push(`  (symbol (lib_id "${libId}") (at ${x} ${y} 0) (unit 1)`);
    lines.push(`    (property "Reference" "${ref}" (at ${x} ${y - 5} 0) (effects (font (size 1.27 1.27))))`);
    lines.push(`    (property "Value" "${val}" (at ${x} ${y + 5} 0) (effects (font (size 1.27 1.27))))`);
    lines.push(`    (property "Footprint" "${fp}" (at ${x} ${y + 9} 0) (effects (font (size 1.27 1.27)) (hide yes)))`);
    if (comp.lcsc) {
      lines.push(`    (property "LCSC" "${comp.lcsc.replace(/"/g, '\\"')}" (at ${x} ${y + 13} 0) (effects (font (size 1.27 1.27)) (hide yes)))`);
    }
    lines.push('  )');
  });

  // Global net labels
  const compIdx = new Map(components.map((c, i) => [c.ref, i]));
  connections.forEach((conn) => {
    if (!conn.pins.length) return;
    const idx = compIdx.get(conn.pins[0]!.ref) ?? 0;
    const col = idx % cols;
    const row = Math.floor(idx / cols);
    const lx  = 50 + col * 30 + 10;
    const ly  = 50 + row * 30;
    const name = conn.name.replace(/"/g, '\\"');
    lines.push(`  (global_label "${name}" (shape input) (at ${lx} ${ly} 0)`);
    lines.push('    (effects (font (size 1.27 1.27)))');
    lines.push('  )');
  });

  lines.push('  (sheet_instances (path "/" (page "1")))');
  lines.push(')');
  return lines.join('\n');
}

// ============================================================
// .kicad_pcb generator (KiCad 7 S-expression format)
// ============================================================

function generatePCB(
  components: SchemaComponent[],
  connections: SchemaNet[],
  boardW: number,
  boardH: number
): string {
  const lines: string[] = [];
  lines.push('(kicad_pcb (version 20221018) (generator "layrix-circuit-synth")');
  lines.push('  (general (thickness 1.6))');
  lines.push('  (paper "A4")');
  lines.push('  (layers');
  const layerDefs = [
    '(0 "F.Cu" signal)',
    '(31 "B.Cu" signal)',
    '(36 "B.SilkS" user "B.Silkscreen")',
    '(37 "F.SilkS" user "F.Silkscreen")',
    '(38 "B.Mask" user)',
    '(39 "F.Mask" user)',
    '(44 "Edge.Cuts" user)',
  ];
  layerDefs.forEach((l) => lines.push(`    ${l}`));
  lines.push('  )');
  lines.push('  (setup (pad_to_mask_clearance 0.05))');

  // Net declarations
  lines.push('  (net 0 "")');
  connections.forEach((conn, i) => {
    lines.push(`  (net ${i + 1} "${conn.name.replace(/"/g, '\\"')}")`);
  });
  const netIdx = new Map(connections.map((c, i) => [c.name, i + 1]));

  // Board outline
  const outline: [number, number, number, number][] = [
    [0, 0, boardW, 0],
    [boardW, 0, boardW, boardH],
    [boardW, boardH, 0, boardH],
    [0, boardH, 0, 0],
  ];
  outline.forEach(([x1, y1, x2, y2]) => {
    lines.push(
      `  (gr_line (start ${x1} ${y1}) (end ${x2} ${y2}) (layer "Edge.Cuts") (width 0.05))`
    );
  });

  // Footprints — smart placement
  const placed = autoLayout(components, boardW, boardH);
  const compPositions = new Map<string, { x: number; y: number }>();
  const compDims      = new Map<string, PadDimensions>();

  components.forEach((comp, i) => {
    const pos  = placed[i] ?? { x: boardW / 2, y: boardH / 2 };
    const dims = getFootprintDims(comp.footprint);
    compPositions.set(comp.ref, { x: +pos.x.toFixed(3), y: +pos.y.toFixed(3) });
    compDims.set(comp.ref, dims);

    const pads = dims.pads.length;
    const ref  = comp.ref.replace(/"/g, '\\"');
    const val  = comp.value.replace(/"/g, '\\"');
    const fp   = comp.footprint.replace(/"/g, '\\"');

    lines.push(`  (footprint "${fp}" (layer "F.Cu") (at ${pos.x.toFixed(3)} ${pos.y.toFixed(3)})`);
    lines.push(`    (property "Reference" "${ref}" (at 0 -2 0) (layer "F.SilkS"))`);
    lines.push(`    (property "Value" "${val}" (at 0 2 0) (layer "F.Fab"))`);

    for (let p = 0; p < pads; p++) {
      const pad = dims.pads[p]!;
      lines.push(
        `    (pad "${p + 1}" smd rect (at ${pad.dx.toFixed(3)} ${pad.dy.toFixed(3)}) (size 0.6 0.6) (layers "F.Cu" "F.Paste" "F.Mask"))`
      );
    }
    lines.push('  )');
  });

  // Traces — MST routing per net with correct pad absolute positions + power trace widths
  connections.forEach((conn) => {
    const ni = netIdx.get(conn.name) ?? 0;
    const width = traceWidth(conn.name);
    const pads: Array<{ x: number; y: number }> = [];

    conn.pins.forEach((pin) => {
      const pos  = compPositions.get(pin.ref);
      const dims = compDims.get(pin.ref);
      if (!pos || !dims) return;
      const pad = dims.pads[pin.pin - 1];
      if (pad) {
        pads.push({ x: +(pos.x + pad.dx).toFixed(3), y: +(pos.y + pad.dy).toFixed(3) });
      }
    });

    // Fallback: round-robin when no connectivity
    if (pads.length === 0) return;

    const edges = mstEdges(pads);
    for (const [a, b] of edges) {
      lines.push(
        `  (segment (start ${a.x} ${a.y}) (end ${b.x} ${b.y}) (width ${width}) (layer "F.Cu") (net ${ni}))`
      );
    }
  });

  // Ground plane (B.Cu filled zone)
  lines.push(`  (zone (net 0) (net_name "") (layer "B.Cu") (hatch edge 0.508)`);
  lines.push(`    (connect_pads (clearance 0.5))`);
  lines.push(`    (min_thickness 0.25)`);
  lines.push(`    (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))`);
  lines.push(`    (polygon (pts`);
  lines.push(`      (xy 0.5 0.5) (xy ${boardW - 0.5} 0.5) (xy ${boardW - 0.5} ${boardH - 0.5}) (xy 0.5 ${boardH - 0.5})`);
  lines.push(`    ))`);
  lines.push('  )');

  lines.push(')');
  return lines.join('\n');
}

// ============================================================
// Public API
// ============================================================

/** Circuit-Synth is always available — inline generation requires no external service. */
export function isCircuitSynthAvailable(): boolean {
  return true;
}

/**
 * Generate native .kicad_sch + .kicad_pcb from a JSON schema.
 *
 * 1. If KICAD_SERVICE_URL is set → try the Python service (pcbnew quality)
 * 2. Always falls back to inline TypeScript S-expression generation
 */
export async function runCircuitSynthEngine(
  schema: SchemaJson,
  boardWidthMm = 50,
  boardHeightMm = 50,
  projectId = ''
): Promise<CircuitSynthResult> {
  const serviceUrl = process.env.KICAD_SERVICE_URL;

  // Try external service first (optional — better quality with pcbnew)
  if (serviceUrl) {
    try {
      const res = await fetch(`${serviceUrl}/circuit-synth/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          components: schema.components,
          nets: schema.nets,
          connections: schema.connections ?? [],
          board_width_mm: boardWidthMm,
          board_height_mm: boardHeightMm,
          project_id: projectId,
        }),
        signal: AbortSignal.timeout(30_000),
      });

      if (res.ok) {
        const data = await res.json() as {
          success: boolean;
          kicad_sch_content?: string | null;
          kicad_pcb_content?: string | null;
          error?: string;
        };
        if (data.success && data.kicad_sch_content && data.kicad_pcb_content) {
          return {
            kicad_sch_content: data.kicad_sch_content,
            kicad_pcb_content: data.kicad_pcb_content,
          };
        }
      }
    } catch {
      // Service unavailable — fall through to inline generation
    }
  }

  // Inline TypeScript S-expression generation (always works)
  return {
    kicad_sch_content: generateSchematic(
      schema.components,
      schema.connections ?? []
    ),
    kicad_pcb_content: generatePCB(
      schema.components,
      schema.connections ?? [],
      boardWidthMm,
      boardHeightMm
    ),
  };
}
