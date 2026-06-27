/**
 * Circuit-Synth engine — generates native .kicad_sch + .kicad_pcb files.
 *
 * Always works without any external service:
 *   - Inline TypeScript S-expression generators produce valid KiCad 7 files
 *   - If KICAD_SERVICE_URL is set, the Python service is tried first for pcbnew quality
 *
 * TSCircuit is NEVER used — this is the sole engine.
 */

import type { SchemaJson, SchemaComponent, SchemaNet } from '@cirqix/types';

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
  'TO-220': {
    width: 10.4, height: 4.6,
    pads: [{ dx: -2.54, dy: 0 }, { dx: 0, dy: 0 }, { dx: 2.54, dy: 0 }],
  },
  'LM7805': {
    width: 10.4, height: 4.6,
    pads: [{ dx: -2.54, dy: 0 }, { dx: 0, dy: 0 }, { dx: 2.54, dy: 0 }],
  },
  '1X03': {
    width: 2.54, height: 7.62,
    pads: [{ dx: 0, dy: -2.54 }, { dx: 0, dy: 0 }, { dx: 0, dy: 2.54 }],
  },
  'CONN': {
    width: 2.54, height: 5.08,
    pads: [{ dx: 0, dy: -1.27 }, { dx: 0, dy: 1.27 }],
  },
  'DIODE': { width: 3.5, height: 1.5, pads: [{ dx: -1.5, dy: 0 }, { dx: 1.5, dy: 0 }] },
  'LED': { width: 2.0, height: 1.2, pads: [{ dx: -0.9, dy: 0 }, { dx: 0.9, dy: 0 }] },
};

function getFootprintDims(footprint: string): PadDimensions {
  const f = footprint.toUpperCase();

  // Dynamic Header parsing (e.g. 1x04, 2x05)
  const headerMatch = f.match(/(\d+)X(\d+)/);
  if (headerMatch) {
    const rows = parseInt(headerMatch[1]!, 10);
    const cols = parseInt(headerMatch[2]!, 10);
    const pads = [];
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        pads.push({ dx: (c - (cols - 1) / 2) * 2.54, dy: (r - (rows - 1) / 2) * 2.54 });
      }
    }
    return { width: cols * 2.54, height: rows * 2.54, pads };
  }

  // Dynamic DIP parsing (e.g. DIP-14)
  const dipMatch = f.match(/DIP[_-]?(\d+)/);
  if (dipMatch) {
    const pins = parseInt(dipMatch[1]!, 10);
    const half = Math.floor(pins / 2);
    const pads = [];
    for (let i = 0; i < pins; i++) {
      pads.push({
        dx: i < half ? -3.81 : 3.81,
        dy: (i < half ? i : (pins - 1) - i) * 2.54 - (half - 1) * 1.27
      });
    }
    return { width: 8.0, height: half * 2.54 + 1.0, pads };
  }

  // Dynamic SOIC/SOP parsing
  const soicMatch = f.match(/SOIC[_-]?(\d+)/) || f.match(/SOP[_-]?(\d+)/);
  if (soicMatch) {
    const pins = parseInt(soicMatch[1]!, 10);
    const half = Math.floor(pins / 2);
    const pads = [];
    for (let i = 0; i < pins; i++) {
      pads.push({
        dx: i < half ? -2.6 : 2.6,
        dy: (i < half ? i : (pins - 1) - i) * 1.27 - (half - 1) * 0.635
      });
    }
    return { width: 6.0, height: half * 1.27 + 1.0, pads };
  }

  const key = Object.keys(FOOTPRINT_DIMS).find(k => f.includes(k.toUpperCase()));
  return FOOTPRINT_DIMS[key ?? '0402'] ?? FOOTPRINT_DIMS['0402']!;
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

function footprintToLibId(ref: string, footprint: string, value?: string): string {
  const fp = footprint.toUpperCase();
  const r  = ref.toUpperCase();
  const v  = value ? value.toUpperCase() : '';

  if (v === 'NE555' || v.includes('555') || fp.includes('555')) return 'Timer:NE555P';
  if (v.includes('7805') || v === 'LM7805' || fp.includes('7805') || fp === 'LM7805' || fp.includes('TO-220')) return 'Device:VReg_3Pin';

  if (fp.includes('LED')   || r.startsWith('LED'))             return 'Device:LED';
  if (fp.includes('SOT-23'))                                   return 'Device:Q_NPN_BCE';
  if (fp.includes('DIP')   || fp.includes('SOIC') || fp.includes('TSSOP')) return 'Device:IC';
  if (fp.includes('CONN')  || fp.includes('2PIN') || r.startsWith('J') || fp.includes('1X03')) return 'Connector_Generic:Conn_01x02';
  if (r.startsWith('C')    || fp.includes('CAP') || fp.includes('10UF') || fp.includes('UF') || v.includes('UF')) return 'Device:C';
  if (r.startsWith('Q')    || r.startsWith('D') || fp.includes('DIODE') || fp.includes('1N4148')) return 'Device:Q_NPN_BCE';
  return 'Device:R';
}

// ============================================================
// Inline KiCad 7 lib_symbols — pin positions match schPinOffset()
// ============================================================

const INLINE_LIB_SYMBOLS = `
  (symbol "Device:R"
    (pin_numbers hide) (pin_names (offset 0)) (in_bom yes) (on_board yes)
    (property "Reference" "R" (at 0 -2.5 0) (effects (font (size 1.27 1.27))))
    (property "Value" "R" (at 0 2.5 0) (effects (font (size 1.27 1.27))))
    (symbol "Device:R_0_1"
      (rectangle (start -2.032 -0.762) (end 2.032 0.762)
        (stroke (width 0.254) (type default)) (fill (type none))))
    (symbol "Device:R_1_1"
      (pin passive line (at -3.81 0 0) (length 1.778)
        (name "~" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 3.81 0 180) (length 1.778)
        (name "~" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))))
  (symbol "Device:C"
    (pin_numbers hide) (pin_names (offset 0)) (in_bom yes) (on_board yes)
    (property "Reference" "C" (at 0 -2.5 0) (effects (font (size 1.27 1.27))))
    (property "Value" "C" (at 0 2.5 0) (effects (font (size 1.27 1.27))))
    (symbol "Device:C_0_1"
      (polyline (pts (xy -2.032 0.381) (xy 2.032 0.381))
        (stroke (width 0.508) (type default)) (fill (type none)))
      (polyline (pts (xy -2.032 -0.381) (xy 2.032 -0.381))
        (stroke (width 0.508) (type default)) (fill (type none))))
    (symbol "Device:C_1_1"
      (pin passive line (at -3.81 0 0) (length 1.778)
        (name "+" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 3.81 0 180) (length 1.778)
        (name "-" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))))
  (symbol "Device:LED"
    (pin_numbers hide) (pin_names (offset 0)) (in_bom yes) (on_board yes)
    (property "Reference" "D" (at 0 -2.5 0) (effects (font (size 1.27 1.27))))
    (property "Value" "LED" (at 0 2.5 0) (effects (font (size 1.27 1.27))))
    (symbol "Device:LED_0_1"
      (polyline (pts (xy -1.778 -1.778) (xy -1.778 1.778) (xy 1.778 0) (xy -1.778 -1.778))
        (stroke (width 0.254) (type default)) (fill (type none)))
      (polyline (pts (xy 1.778 -1.778) (xy 1.778 1.778))
        (stroke (width 0.254) (type default)) (fill (type none))))
    (symbol "Device:LED_1_1"
      (pin passive line (at -3.81 0 0) (length 2.032)
        (name "A" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 3.81 0 180) (length 2.032)
        (name "K" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))))
  (symbol "Connector_Generic:Conn_01x02"
    (pin_numbers hide) (pin_names (offset 1.016)) (in_bom yes) (on_board yes)
    (property "Reference" "J" (at 0 -2.5 0) (effects (font (size 1.27 1.27))))
    (property "Value" "Conn_01x02" (at 0 2.5 0) (effects (font (size 1.27 1.27))))
    (symbol "Connector_Generic:Conn_01x02_0_1"
      (rectangle (start -1.524 -0.762) (end 1.524 0.762)
        (stroke (width 0.254) (type default)) (fill (type none))))
    (symbol "Connector_Generic:Conn_01x02_1_1"
      (pin passive line (at -3.81 0 0) (length 2.286)
        (name "Pin_1" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 3.81 0 180) (length 2.286)
        (name "Pin_2" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))))
  (symbol "Device:Q_NPN_BCE"
    (pin_numbers hide) (pin_names (offset 0)) (in_bom yes) (on_board yes)
    (property "Reference" "Q" (at 0 -4 0) (effects (font (size 1.27 1.27))))
    (property "Value" "Q" (at 0 4 0) (effects (font (size 1.27 1.27))))
    (symbol "Device:Q_NPN_BCE_0_1"
      (polyline (pts (xy -1.27 1.27) (xy -1.27 -1.27))
        (stroke (width 0.508) (type default)) (fill (type none)))
      (polyline (pts (xy -1.27 0.635) (xy 1.27 2.54))
        (stroke (width 0.254) (type default)) (fill (type none)))
      (polyline (pts (xy -1.27 -0.635) (xy 1.27 -2.54))
        (stroke (width 0.254) (type default)) (fill (type none))))
    (symbol "Device:Q_NPN_BCE_1_1"
      (pin input line (at -5.08 2.54 0) (length 3.81)
        (name "B" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at -5.08 -2.54 0) (length 3.81)
        (name "E" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 5.08 0 180) (length 3.81)
        (name "C" (effects (font (size 1.27 1.27)))) (number "3" (effects (font (size 1.27 1.27)))))))
  (symbol "Device:IC"
    (pin_numbers hide) (pin_names (offset 0.254)) (in_bom yes) (on_board yes)
    (property "Reference" "U" (at 0 -6 0) (effects (font (size 1.27 1.27))))
    (property "Value" "IC" (at 0 6 0) (effects (font (size 1.27 1.27))))
    (symbol "Device:IC_0_1"
      (rectangle (start -4 -4.5) (end 4 4.5)
        (stroke (width 0.254) (type default)) (fill (type none))))
    (symbol "Device:IC_1_1"
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
  (symbol "Device:VReg_3Pin"
    (pin_numbers hide) (pin_names (offset 0)) (in_bom yes) (on_board yes)
    (property "Reference" "U" (at 0 -4 0) (effects (font (size 1.27 1.27))))
    (property "Value" "VReg" (at 0 4 0) (effects (font (size 1.27 1.27))))
    (symbol "Device:VReg_3Pin_0_1"
      (rectangle (start -4 -4) (end 4 4)
        (stroke (width 0.254) (type default)) (fill (type none))))
    (symbol "Device:VReg_3Pin_1_1"
      (pin input line (at -6.35 0 0) (length 2.35)
        (name "VI" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
      (pin power_in line (at 0 -6.35 90) (length 2.35)
        (name "GND" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))
      (pin power_out line (at 6.35 0 180) (length 2.35)
        (name "VO" (effects (font (size 1.27 1.27)))) (number "3" (effects (font (size 1.27 1.27)))))))
  (symbol "Timer:NE555P"
    (pin_numbers hide) (pin_names (offset 0.254)) (in_bom yes) (on_board yes)
    (property "Reference" "U" (at 0 -6 0) (effects (font (size 1.27 1.27))))
    (property "Value" "NE555P" (at 0 6 0) (effects (font (size 1.27 1.27))))
    (symbol "Timer:NE555P_0_1"
      (rectangle (start -5 -5) (end 5 5)
        (stroke (width 0.254) (type default)) (fill (type none))))
    (symbol "Timer:NE555P_1_1"
      (pin input line (at -7.54 -2.54 0) (length 2.54)
        (name "GND" (effects (font (size 1.016 1.016)))) (number "1" (effects (font (size 1.016 1.016)))))
      (pin input line (at -7.54 0 0) (length 2.54)
        (name "TRIG" (effects (font (size 1.016 1.016)))) (number "2" (effects (font (size 1.016 1.016)))))
      (pin output line (at 7.54 2.54 180) (length 2.54)
        (name "OUT" (effects (font (size 1.016 1.016)))) (number "3" (effects (font (size 1.016 1.016)))))
      (pin input line (at -7.54 2.54 0) (length 2.54)
        (name "RESET" (effects (font (size 1.016 1.016)))) (number "4" (effects (font (size 1.016 1.016)))))
      (pin input line (at 7.54 0 180) (length 2.54)
        (name "CTRL" (effects (font (size 1.016 1.016)))) (number "5" (effects (font (size 1.016 1.016)))))
      (pin input line (at 7.54 -2.54 180) (length 2.54)
        (name "THR" (effects (font (size 1.016 1.016)))) (number "6" (effects (font (size 1.016 1.016)))))
      (pin input line (at 7.54 -5.08 180) (length 2.54)
        (name "DIS" (effects (font (size 1.016 1.016)))) (number "7" (effects (font (size 1.016 1.016)))))
      (pin power_in line (at 0 7.54 270) (length 2.54)
        (name "VCC" (effects (font (size 1.016 1.016)))) (number "8" (effects (font (size 1.016 1.016)))))))
  (symbol "power:GND"
    (pin_names (offset 0)) (in_bom no) (on_board no)
    (property "Reference" "#PWR" (at 0 -4 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Value" "GND" (at 0 -4 0) (effects (font (size 1.27 1.27))))
    (symbol "power:GND_0_1"
      (polyline (pts (xy 0 0) (xy 0 -1.27)) (stroke (width 0) (type default)) (fill (type none)))
      (polyline (pts (xy -1.27 -1.27) (xy 1.27 -1.27)) (stroke (width 0) (type default)) (fill (type none)))
      (polyline (pts (xy -0.762 -1.778) (xy 0.762 -1.778)) (stroke (width 0) (type default)) (fill (type none)))
      (polyline (pts (xy -0.254 -2.286) (xy 0.254 -2.286)) (stroke (width 0) (type default)) (fill (type none))))
    (symbol "power:GND_1_1"
      (pin power_in line (at 0 0 270) (length 0)
        (name "GND" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))))
  (symbol "power:VCC"
    (pin_names (offset 0)) (in_bom no) (on_board no)
    (property "Reference" "#PWR" (at 0 2.5 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Value" "VCC" (at 0 2.5 0) (effects (font (size 1.27 1.27))))
    (symbol "power:VCC_0_1"
      (polyline (pts (xy 0 0) (xy 0 1.27)) (stroke (width 0) (type default)) (fill (type none)))
      (polyline (pts (xy -1.27 1.27) (xy 1.27 1.27)) (stroke (width 0) (type default)) (fill (type none))))
    (symbol "power:VCC_1_1"
      (pin power_in line (at 0 0 90) (length 0)
        (name "VCC" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))))`;

// ============================================================
// Schematic pin offset estimation (KiCad schematic units = mm)
// Two-pin passives: pins at ±3.81mm on X axis
// Multi-pin ICs: pins at ±5.08mm on X, spaced 2.54mm on Y
// ============================================================

function schPinOffset(libId: string, pinIndex: number): { dx: number; dy: number } {
  if (libId === 'Device:R' || libId === 'Device:C' || libId === 'Device:LED' || libId === 'Connector_Generic:Conn_01x02') {
    return { dx: pinIndex === 0 ? -3.81 : 3.81, dy: 0 };
  }
  if (libId === 'Device:Q_NPN_BCE') {
    const offsets = [{ dx: -5.08, dy: 2.54 }, { dx: -5.08, dy: -2.54 }, { dx: 5.08, dy: 0 }];
    return offsets[pinIndex] ?? { dx: 0, dy: 0 };
  }
  if (libId === 'Device:VReg_3Pin') {
    const offsets = [{ dx: -6.35, dy: 0 }, { dx: 0, dy: -6.35 }, { dx: 6.35, dy: 0 }];
    return offsets[pinIndex] ?? { dx: 0, dy: 0 };
  }
  if (libId === 'Timer:NE555P') {
    const offsets = [
      { dx: -7.54, dy: -2.54 },
      { dx: -7.54, dy: 0 },
      { dx: 7.54, dy: 2.54 },
      { dx: -7.54, dy: 2.54 },
      { dx: 7.54, dy: 0 },
      { dx: 7.54, dy: -2.54 },
      { dx: 7.54, dy: -5.08 },
      { dx: 0, dy: 7.54 }
    ];
    return offsets[pinIndex] ?? { dx: 0, dy: 0 };
  }
  
  // Generic IC fallback
  const pads = 8;
  const half = Math.floor(pads / 2);
  if (pinIndex < half) {
    return { dx: -5.08, dy: (pinIndex - (half - 1) / 2) * 2.54 };
  }
  const ri = pinIndex - half;
  return { dx: 5.08, dy: ((half - 1 - ri) - (half - 1) / 2) * 2.54 };
}

function resolvePinIndex(pinVal: number | string | undefined, libId?: string): number {
  if (typeof pinVal === 'number') return pinVal - 1;
  if (!pinVal) return 0;
  
  const s = String(pinVal).toUpperCase();
  const parsed = parseInt(s, 10);
  if (!isNaN(parsed)) return parsed - 1;

  if (libId === 'Device:VReg_3Pin') {
    if (s === 'VI' || s === 'IN') return 0;
    if (s === 'GND') return 1;
    if (s === 'VO' || s === 'OUT') return 2;
  }
  if (libId === 'Timer:NE555P') {
    const map: Record<string, number> = { 'GND': 0, 'TRIG': 1, 'OUT': 2, 'RESET': 3, 'CTRL': 4, 'THR': 5, 'DIS': 6, 'VCC': 7 };
    if (map[s] !== undefined) return map[s]!;
  }
  if (libId === 'Device:Q_NPN_BCE') {
    if (s === 'B' || s === 'BASE') return 0;
    if (s === 'E' || s === 'EMITTER') return 1;
    if (s === 'C' || s === 'COLLECTOR') return 2;
    if (s === 'A' || s === 'ANODE') return 0;
    if (s === 'K' || s === 'CATHODE') return 2;
  }
  if (libId === 'Device:LED') {
    if (s === 'A' || s === 'ANODE' || s === '+') return 0;
    if (s === 'K' || s === 'CATHODE' || s === '-') return 1;
  }
  return 0; // Fallback to 1st pin
}

// ============================================================
// .kicad_sch generator (KiCad 7 S-expression format)
// ============================================================

function uuidv4(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

// ─── Topology-aware schematic layout ────────────────────────────────────────
//
// Groups components by functional category so the schematic reads left→right:
//   Connectors | Power/Reg ICs | Core ICs (MCU/FPGA) | Passives | Diodes/LEDs
//
// Within each group components are stacked in columns of max 3, with 60mm
// horizontal spacing and 50mm vertical spacing — large enough that net labels
// are legible in KiCanvas without zooming in.

function schematicLayout(
  components: SchemaComponent[],
): Array<{ ref: string; x: number; y: number }> {
  const COL_STEP = 60;
  const ROW_STEP = 50;
  const MARGIN   = 25;
  const MAX_ROWS = 3;

  type Group = 'conn' | 'power' | 'core' | 'passive' | 'diode';

  const classify = (c: SchemaComponent): Group => {
    const r = c.ref.toUpperCase();
    if (/^J\d*/.test(r) || /^P\d*/.test(r))         return 'conn';
    if (/^U\d*/.test(r) || /^IC\d*/.test(r)) {
      const v = c.value.toUpperCase();
      if (/LDO|REG|AMS|LM78|LM33|7805|3V3|5V|VREF/.test(v)) return 'power';
      return 'core';
    }
    if (/^[RCL]\d*/.test(r) || /^FB\d*/.test(r))    return 'passive';
    if (/^[DQ]\d*/.test(r) || /^LED\d*/.test(r))    return 'diode';
    return 'passive';
  };

  const groups: Record<Group, SchemaComponent[]> = {
    conn: [], power: [], core: [], passive: [], diode: [],
  };
  for (const c of components) groups[classify(c)].push(c);

  const order: Group[] = ['conn', 'power', 'core', 'passive', 'diode'];
  const result: Array<{ ref: string; x: number; y: number }> = [];
  let colOffset = 0;

  for (const gName of order) {
    const group = groups[gName];
    if (group.length === 0) continue;

    const cols = Math.ceil(group.length / MAX_ROWS);
    group.forEach((c, idx) => {
      const col = Math.floor(idx / MAX_ROWS);
      const row = idx % MAX_ROWS;
      result.push({
        ref: c.ref,
        x: MARGIN + (colOffset + col) * COL_STEP,
        y: MARGIN + row * ROW_STEP,
      });
    });
    colOffset += cols + 1; // +1 = gap between groups
  }

  return result;
}

function generateSchematic(
  components: SchemaComponent[],
  connections: SchemaNet[]
): string {
  const lines: string[] = [];

  // Topology-aware placement
  const layout = schematicLayout(components);
  const compPos = components.map((c) => {
    const pos = layout.find((p) => p.ref === c.ref);
    return pos ?? { x: 25, y: 25 };
  });
  const compIdx = new Map(components.map((c, i) => [c.ref, i]));

  // Paper = bounding box of placed components + margins so KiCanvas fills view
  const MARGIN = 25;
  const xs = compPos.map((p) => p.x);
  const ys = compPos.map((p) => p.y);
  const paperW = Math.max(100, Math.max(...xs) + MARGIN * 2);
  const paperH = Math.max(80,  Math.max(...ys) + MARGIN * 2 + 20);

  lines.push(`(kicad_sch (version 20230121) (generator "cirqix-circuit-synth") (uuid "${uuidv4()}")`);
  lines.push(`  (paper "User" ${paperW} ${paperH})`);
  lines.push(`  (lib_symbols${INLINE_LIB_SYMBOLS}\n  )`);

  // Component symbols
  components.forEach((comp, i) => {
    const { x, y } = compPos[i]!;
    const libId = footprintToLibId(comp.ref, comp.footprint, comp.value);
    const ref   = comp.ref.replace(/"/g, '\\"');
    const val   = comp.value.replace(/"/g, '\\"');
    const fp    = comp.footprint.replace(/"/g, '\\"');

    lines.push(`  (symbol (lib_id "${libId}") (at ${x} ${y} 0) (unit 1) (in_bom yes) (on_board yes)`);
    lines.push(`    (uuid "${uuidv4()}")`);
    lines.push(`    (property "Reference" "${ref}" (at ${x} ${y - 5} 0) (effects (font (size 1.524 1.524) bold)))`);
    lines.push(`    (property "Value" "${val}" (at ${x} ${y + 5} 0) (effects (font (size 1.524 1.524))))`);
    lines.push(`    (property "Footprint" "${fp}" (at ${x} ${y + 9} 0) (effects (font (size 1.27 1.27)) (hide yes)))`);
    if (comp.lcsc) {
      lines.push(`    (property "LCSC" "${comp.lcsc.replace(/"/g, '\\"')}" (at ${x} ${y + 13} 0) (effects (font (size 1.27 1.27)) (hide yes)))`);
    }
    lines.push('  )');
  });

  // Power symbols for GND / VCC nets
  const powerSymbolsEmitted = new Set<string>();
  let pwrIdx = 1;
  connections.forEach((conn) => {
    if (!isPowerNet(conn.name)) return;
    conn.pins.forEach((pin) => {
      const idx = compIdx.get(pin.ref);
      if (idx === undefined) return;
      const { x, y } = compPos[idx]!;
      const targetComp = components[idx]!;
      const targetLibId = footprintToLibId(targetComp.ref, targetComp.footprint, targetComp.value);
      const off = schPinOffset(targetLibId, resolvePinIndex(pin.pin, targetLibId));
      const px  = +(x + off.dx).toFixed(2);
      const py  = +(y + off.dy).toFixed(2);
      const netUpper = conn.name.toUpperCase();
      const libId    = netUpper.startsWith('GND') || netUpper.startsWith('VSS')
        ? 'power:GND' : 'power:VCC';
      const symKey = `${libId}@${px},${py}`;
      if (powerSymbolsEmitted.has(symKey)) return;
      powerSymbolsEmitted.add(symKey);
      const ref = `#PWR${String(pwrIdx++).padStart(2, '0')}`;
      lines.push(`  (symbol (lib_id "${libId}") (at ${px} ${py} 0) (unit 1) (in_bom no) (on_board no)`);
      lines.push(`    (uuid "${uuidv4()}")`);
      lines.push(`    (property "Reference" "${ref}" (at ${px} ${py - 3} 0) (effects (font (size 1.27 1.27)) (hide yes)))`);
      lines.push(`    (property "Value" "${conn.name.replace(/"/g, '\\"')}" (at ${px} ${py + 3} 0) (effects (font (size 1.27 1.27))))`);
      lines.push('  )');
    });
  });

  // Net labels + wire stubs — one label per pin endpoint per net.
  // Stubs are 5.08mm (2×KiCad grid step) so labels are visually separate from
  // the symbol body and legible at normal KiCanvas zoom levels.
  const STUB_LEN = 5.08;
  const LABEL_FONT = '1.524 1.524'; // slightly larger than default 1.27 for readability
  let wireIdx = 0;
  connections.forEach((conn) => {
    if (!conn.pins.length) return;
    const name = conn.name.replace(/"/g, '\\"');
    conn.pins.forEach((pin) => {
      const idx = compIdx.get(pin.ref);
      if (idx === undefined) return;
      const { x, y } = compPos[idx]!;
      const targetComp = components[idx]!;
      const targetLibId = footprintToLibId(targetComp.ref, targetComp.footprint, targetComp.value);
      const off = schPinOffset(targetLibId, resolvePinIndex(pin.pin, targetLibId));
      const px  = +(x + off.dx).toFixed(2);
      const py  = +(y + off.dy).toFixed(2);
      // Stub direction follows pin orientation: left pins get right-facing label, vice versa
      const goesRight = off.dx >= 0;
      const stubEndX  = +(px + (goesRight ? STUB_LEN : -STUB_LEN)).toFixed(2);
      const stubEndY  = py;
      const angle     = goesRight ? 0 : 180;
      const justify   = goesRight ? 'left' : 'right';
      // Cap total wires to avoid huge files (>500 connections = pathological case)
      if (++wireIdx <= 500) {
        lines.push(`  (wire (pts (xy ${px} ${py}) (xy ${stubEndX} ${stubEndY})) (stroke (width 0) (type default)))`);
      }
      lines.push(`  (label "${name}" (at ${stubEndX} ${stubEndY} ${angle})`);
      lines.push(`    (effects (font (size ${LABEL_FONT})) (justify ${justify}))`);
      lines.push('  )');
    });
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
  lines.push('(kicad_pcb (version 20221018) (generator "cirqix-circuit-synth")');
  lines.push('  (general (thickness 1.6))');
  // Custom paper = board dimensions → KiCanvas auto-fits to the board, not a huge A4 page
  lines.push(`  (paper "User" ${boardW + 10} ${boardH + 10})`);
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

  components.forEach((comp) => {
    const pos  = placed.find(p => p.ref === comp.ref) ?? { x: boardW / 2, y: boardH / 2 };
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
      const targetComp = components.find(c => c.ref === pin.ref);
      const targetLibId = targetComp ? footprintToLibId(pin.ref, targetComp.footprint, targetComp.value) : undefined;
      if (!dims || !pos) return;
      const pad = dims.pads[resolvePinIndex(pin.pin, targetLibId)];
      if (pad) {
        pads.push({ x: +(pos.x + pad.dx).toFixed(3), y: +(pos.y + pad.dy).toFixed(3) });
      }
    });

    // Fallback: round-robin when no connectivity
    if (pads.length === 0) return;

    const edges = mstEdges(pads);
    for (const [a, b] of edges) {
      // Orthogonal (L-shaped) routing: horizontal segment then vertical segment
      const mid = { x: b.x, y: a.y };
      if (Math.abs(a.x - b.x) > 0.001) {
        lines.push(
          `  (segment (start ${a.x} ${a.y}) (end ${mid.x} ${mid.y}) (width ${width}) (layer "F.Cu") (net ${ni}))`
        );
      }
      if (Math.abs(a.y - b.y) > 0.001) {
        lines.push(
          `  (segment (start ${mid.x} ${mid.y}) (end ${b.x} ${b.y}) (width ${width}) (layer "F.Cu") (net ${ni}))`
        );
      }
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
 * Validate and auto-correct KiCad symbols against local .kicad_sym libraries.
 * Calls POST /schematic/validate-symbols if KICAD_SERVICE_URL is set.
 * Returns the schema unchanged if the service is unavailable.
 */
export async function validateAndCorrectSchema(schema: SchemaJson): Promise<SchemaJson> {
  const serviceUrl = process.env.KICAD_SERVICE_URL;
  if (!serviceUrl) return schema;

  try {
    const res = await fetch(`${serviceUrl}/schematic/validate-symbols`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ components: schema.components }),
      signal: AbortSignal.timeout(5_000),
    });
    if (!res.ok) return schema;

    const data = await res.json() as {
      corrected_components: SchemaComponent[];
      has_corrections: boolean;
      results: Array<{ ref: string; original_symbol: string; validated_symbol: string; corrected: boolean }>;
    };

    if (data.has_corrections) {
      const corrections = data.results.filter((r) => r.corrected);
      console.warn(
        `[circuit-synth] Symbol corrections: ${corrections.map((r) => `${r.ref}: ${r.original_symbol} → ${r.validated_symbol}`).join(', ')}`
      );
      return { ...schema, components: data.corrected_components };
    }

    return schema;
  } catch {
    // FastAPI unavailable — passthrough, _safe_symbol() handles it server-side
    return schema;
  }
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
      const res = await fetch(`${serviceUrl}/schematic/generate`, {
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
        signal: AbortSignal.timeout(60_000),
      });

      if (res.ok) {
        const data = await res.json() as {
          success: boolean;
          kicad_sch_content?: string | null;
          error?: string;
        };
        if (data.success && data.kicad_sch_content) {
          return {
            kicad_sch_content: data.kicad_sch_content,
            kicad_pcb_content: '',
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
