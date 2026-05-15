/**
 * Datasheet-style schematic layout — components grouped into labeled functional
 * blocks (POWER INPUT / REGULATOR / OUTPUT / SIGNAL), each with its own
 * bordered region and title bar. Power flows left → right, signal sits above.
 *
 * Block bbox is computed after components are placed inside; the canvas
 * renders the frame + uppercase label.
 */
import type { SchemaComponent, SchemaNet } from '@layrix/types';
import {
  capacitor, capacitorPolarized, resistor, diode, led, ic, connector,
  gndFlag, powerFlag, type SymbolDef, type ICPin,
} from './schema-symbols';

const POWER_NET_REGEX = /^(VCC|VDD|\+?[0-9.]+V|VIN|V_?BUS|V_?BAT|PWR_?\d*V?)$/i;
const GND_NET_REGEX = /^(GND|VSS|0V|AGND|DGND|PGND)$/i;
const OUT_NET_REGEX = /^(VOUT|V_?OUT|OUTPUT|OUT)$/i;

export interface PlacedSymbol {
  ref: string;
  value: string;
  symbol: SymbolDef;
  ox: number;
  oy: number;
  sourceRef: string | null;
  netLabel: string | null;
}

export interface ResolvedPin {
  ref: string;
  pinId: string;
  x: number;
  y: number;
}

export interface WireSegment {
  x1: number; y1: number; x2: number; y2: number;
}

export interface RoutedNet {
  name: string;
  segments: WireSegment[];
  junctions: Array<{ x: number; y: number }>;
  isPower: boolean;
  isGround: boolean;
  color: string;
}

export interface SchemaBlock {
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
  componentRefs: string[];
}

export interface LayoutResult {
  placed: PlacedSymbol[];
  pinIndex: Map<string, ResolvedPin>;
  nets: RoutedNet[];
  blocks: SchemaBlock[];
  width: number;
  height: number;
}

type CompType = 'ic' | 'cap' | 'pcap' | 'res' | 'led' | 'diode' | 'conn' | 'other';

function classify(c: SchemaComponent): CompType {
  const ref = c.ref.toUpperCase();
  const val = (c.value ?? '').toUpperCase();
  const fp = (c.footprint ?? '').toUpperCase();
  if (ref.startsWith('U') || ref.startsWith('IC')) return 'ic';
  if (ref.startsWith('LED') || val.includes('LED')) return 'led';
  if (ref.startsWith('D')) return 'diode';
  if (ref.startsWith('R')) return 'res';
  if (ref.startsWith('C')) {
    if (fp.includes('CP_') || (val.includes('UF') && parseFloat(val) >= 10)) return 'pcap';
    return 'cap';
  }
  if (ref.startsWith('J') || ref.startsWith('CONN') || ref.startsWith('P')) return 'conn';
  return 'other';
}

const IC_PIN_MAPS: Record<string, ICPin[]> = {
  'LM7805':    [{ name: 'VI', side: 'left' }, { name: 'GND', side: 'bottom' }, { name: 'VO', side: 'right' }],
  '7805':      [{ name: 'VI', side: 'left' }, { name: 'GND', side: 'bottom' }, { name: 'VO', side: 'right' }],
  'LM317':     [{ name: 'ADJ', side: 'bottom' }, { name: 'VO', side: 'right' }, { name: 'VI', side: 'left' }],
  'AMS1117':   [{ name: 'GND', side: 'bottom' }, { name: 'VO', side: 'right' }, { name: 'VI', side: 'left' }],
  'TPS7333':   [{ name: 'IN', side: 'left' }, { name: 'GND', side: 'bottom' }, { name: 'OUT', side: 'right' }, { name: 'EN', side: 'left' }],
  'NE555':     [
    { name: 'GND', side: 'bottom' }, { name: 'TRG', side: 'left' }, { name: 'OUT', side: 'right' },
    { name: 'RST', side: 'left' },   { name: 'CTL', side: 'right' }, { name: 'THR', side: 'left' },
    { name: 'DIS', side: 'right' },  { name: 'VCC', side: 'top' },
  ],
  'NE555P':    [
    { name: 'GND', side: 'bottom' }, { name: 'TRG', side: 'left' }, { name: 'OUT', side: 'right' },
    { name: 'RST', side: 'left' },   { name: 'CTL', side: 'right' }, { name: 'THR', side: 'left' },
    { name: 'DIS', side: 'right' },  { name: 'VCC', side: 'top' },
  ],
};

function getICPins(comp: SchemaComponent, connections: SchemaNet[]): ICPin[] {
  const val = (comp.value ?? '').toUpperCase().replace(/[^\w]/g, '');
  for (const [key, pins] of Object.entries(IC_PIN_MAPS)) {
    if (val.includes(key)) return pins;
  }
  const conns = connections.filter(n => n.pins.some(p => p.ref === comp.ref));
  const pinNames = new Set<string>();
  for (const c of conns) {
    for (const p of c.pins) if (p.ref === comp.ref) pinNames.add(String(p.pin));
  }
  const arr = Array.from(pinNames).sort();
  const result: ICPin[] = [];
  const half = Math.ceil(arr.length / 2);
  arr.forEach((name, i) => result.push({ name, side: i < half ? 'left' : 'right' }));
  if (result.length === 0) return [{ name: '1', side: 'left' }, { name: '2', side: 'right' }];
  return result;
}

function symbolFor(c: SchemaComponent, type: CompType, connections: SchemaNet[]): SymbolDef {
  switch (type) {
    case 'cap':    return capacitor();
    case 'pcap':   return capacitorPolarized();
    case 'res':    return resistor();
    case 'diode':  return diode();
    case 'led':    return led();
    case 'ic':     return ic(getICPins(c, connections));
    case 'conn': {
      const conns = connections.filter(n => n.pins.some(p => p.ref === c.ref));
      const pinNums = new Set<number>();
      for (const cn of conns) {
        for (const p of cn.pins) {
          if (p.ref === c.ref) pinNums.add(typeof p.pin === 'number' ? p.pin : parseInt(String(p.pin), 10) || 1);
        }
      }
      return connector(Math.max(2, pinNums.size), c.value);
    }
    default:       return capacitor();
  }
}

// Stack components vertically within a block, returns total width/height of contents
function stackVertical(
  comps: SchemaComponent[],
  typeByRef: Map<string, CompType>,
  connections: SchemaNet[],
  startX: number,
  startY: number,
  placed: PlacedSymbol[],
  pinIndex: Map<string, ResolvedPin>,
  centerX: number,
): { width: number; height: number; bottom: number } {
  let y = startY;
  let maxW = 0;
  const ROW_GAP = 60;
  for (const c of comps) {
    const type = typeByRef.get(c.ref)!;
    const sym = symbolFor(c, type, connections);
    const ox = centerX - sym.width / 2;
    placed.push({ ref: c.ref, value: c.value, symbol: sym, ox, oy: y, sourceRef: c.ref, netLabel: null });
    for (const p of sym.pins) {
      pinIndex.set(`${c.ref}.${p.id}`, { ref: c.ref, pinId: p.id, x: ox + p.x, y: y + p.y });
    }
    maxW = Math.max(maxW, sym.width);
    y += sym.height + ROW_GAP;
  }
  return { width: maxW, height: y - startY - ROW_GAP, bottom: y - ROW_GAP };
}

export function layoutSchema(
  components: SchemaComponent[],
  connections: SchemaNet[],
): LayoutResult {
  const placed: PlacedSymbol[] = [];
  const pinIndex = new Map<string, ResolvedPin>();
  const blocks: SchemaBlock[] = [];

  if (!components.length) {
    return { placed, pinIndex, nets: [], blocks, width: 800, height: 450 };
  }

  const typeByRef = new Map<string, CompType>();
  for (const c of components) typeByRef.set(c.ref, classify(c));

  // Build net membership per component
  const netsByRef = new Map<string, Set<string>>();
  for (const c of components) netsByRef.set(c.ref, new Set());
  for (const net of connections) {
    for (const p of net.pins) netsByRef.get(p.ref)?.add(net.name);
  }

  // Main IC = the IC connected to the most distinct nets
  const ics = components.filter(c => typeByRef.get(c.ref) === 'ic');
  const mainIC = ics.length
    ? ics.reduce((best, c) =>
        (netsByRef.get(c.ref)?.size ?? 0) > (netsByRef.get(best.ref)?.size ?? 0) ? c : best
      , ics[0]!)
    : null;

  const mainNets = mainIC ? Array.from(netsByRef.get(mainIC.ref) ?? []) : [];
  const inputNet = mainNets.find(n => /^(VIN|VI|IN|VBUS|VBAT|VCC|VDD|PWR)/i.test(n))
                ?? mainNets.find(n => POWER_NET_REGEX.test(n) && !OUT_NET_REGEX.test(n));
  const outputNet = mainNets.find(n => OUT_NET_REGEX.test(n));

  // Bucket components
  const bSource: SchemaComponent[] = [];
  const bInputCaps: SchemaComponent[] = [];
  const bCore: SchemaComponent[] = mainIC ? [mainIC] : [];
  const bOutputCaps: SchemaComponent[] = [];
  const bSink: SchemaComponent[] = [];
  const bSignal: SchemaComponent[] = [];

  for (const c of components) {
    if (c === mainIC) continue;
    const t = typeByRef.get(c.ref)!;
    const nets = netsByRef.get(c.ref) ?? new Set();

    if (t === 'conn') {
      if (inputNet && nets.has(inputNet)) bSource.push(c);
      else if (outputNet && nets.has(outputNet)) bSink.push(c);
      else if (bSource.length === 0) bSource.push(c);
      else bSink.push(c);
      continue;
    }

    if (t === 'ic') {
      bSignal.push(c);
      continue;
    }

    if (t === 'res' || t === 'diode' || t === 'led') {
      // Resistors/diodes generally signal-path unless on power+gnd only
      const onlyPower = Array.from(nets).every(n => POWER_NET_REGEX.test(n) || GND_NET_REGEX.test(n) || OUT_NET_REGEX.test(n));
      if (onlyPower && (inputNet && nets.has(inputNet))) bInputCaps.push(c);
      else if (onlyPower && (outputNet && nets.has(outputNet))) bOutputCaps.push(c);
      else bSignal.push(c);
      continue;
    }

    // Caps
    const onInput  = inputNet  ? nets.has(inputNet)  : false;
    const onOutput = outputNet ? nets.has(outputNet) : false;
    if (onInput && !onOutput) bInputCaps.push(c);
    else if (onOutput && !onInput) bOutputCaps.push(c);
    else if (mainIC) bSignal.push(c);
    else bInputCaps.push(c);
  }

  // Geometry
  const BLOCK_PAD_X = 26;
  const BLOCK_PAD_Y_TOP = 40;     // room for label
  const BLOCK_PAD_Y_BOT = 32;     // room for GND flags at bottom
  const BLOCK_GAP = 32;
  const FIRST_X = 30;
  const FIRST_Y = 100;
  const SIGNAL_HEIGHT_DEFAULT = 180;
  const POWER_ROW_Y = FIRST_Y + SIGNAL_HEIGHT_DEFAULT + 40;

  // Build power row blocks
  type ColumnPlan = { label: string; comps: SchemaComponent[]; minColW: number };
  const columns: ColumnPlan[] = [];
  if (bSource.length)     columns.push({ label: 'POWER INPUT',     comps: bSource,    minColW: 130 });
  if (bInputCaps.length)  columns.push({ label: 'INPUT FILTER',    comps: bInputCaps, minColW: 110 });
  if (bCore.length)       columns.push({ label: 'CORE',            comps: bCore,      minColW: 150 });
  if (bOutputCaps.length) columns.push({ label: 'OUTPUT FILTER',   comps: bOutputCaps,minColW: 110 });
  if (bSink.length)       columns.push({ label: 'OUTPUT',          comps: bSink,      minColW: 130 });

  // Override CORE label when no regulator detected
  if (mainIC) {
    const val = (mainIC.value ?? '').toUpperCase();
    const isReg = /78\d{2}|LM3\d{2}|AMS1117|TPS|LDO|MIC\d+|XC6\d+/.test(val);
    const coreIdx = columns.findIndex(c => c.label === 'CORE');
    if (coreIdx >= 0) columns[coreIdx]!.label = isReg ? 'REGULATOR' : (val || 'CORE');
  }

  let xCursor = FIRST_X;

  for (const col of columns) {
    const blockX = xCursor;
    const blockInnerStartY = POWER_ROW_Y + BLOCK_PAD_Y_TOP;
    // First pass: measure widest symbol
    let measuredMax = 0;
    for (const c of col.comps) {
      const t = typeByRef.get(c.ref)!;
      const sym = symbolFor(c, t, connections);
      measuredMax = Math.max(measuredMax, sym.width);
    }
    const colW = Math.max(col.minColW, measuredMax + BLOCK_PAD_X * 2);
    const centerX = blockX + colW / 2;

    const result = stackVertical(col.comps, typeByRef, connections, blockInnerStartY, blockInnerStartY, placed, pinIndex, centerX);
    const blockH = BLOCK_PAD_Y_TOP + result.height + BLOCK_PAD_Y_BOT;

    blocks.push({
      label: col.label,
      x: blockX,
      y: POWER_ROW_Y,
      width: colW,
      height: blockH,
      componentRefs: col.comps.map(c => c.ref),
    });

    xCursor += colW + BLOCK_GAP;
  }

  // Signal block — spans top, full width over power row
  if (bSignal.length) {
    const blockX = FIRST_X;
    const blockY = FIRST_Y;
    const blockInnerStartY = blockY + BLOCK_PAD_Y_TOP;
    // Stack horizontally inside the signal block
    let sigCursor = blockX + BLOCK_PAD_X;
    let maxBottom = blockInnerStartY;
    for (const c of bSignal) {
      const t = typeByRef.get(c.ref)!;
      const sym = symbolFor(c, t, connections);
      const ox = sigCursor;
      const oy = blockInnerStartY;
      placed.push({ ref: c.ref, value: c.value, symbol: sym, ox, oy, sourceRef: c.ref, netLabel: null });
      for (const p of sym.pins) {
        pinIndex.set(`${c.ref}.${p.id}`, { ref: c.ref, pinId: p.id, x: ox + p.x, y: oy + p.y });
      }
      sigCursor += sym.width + 36;
      maxBottom = Math.max(maxBottom, oy + sym.height);
    }
    const signalEndX = xCursor - BLOCK_GAP;
    blocks.unshift({
      label: 'SIGNAL',
      x: blockX,
      y: blockY,
      width: signalEndX - blockX,
      height: maxBottom - blockY + BLOCK_PAD_Y_BOT,
      componentRefs: bSignal.map(c => c.ref),
    });
  }

  // Resolve pin coords helper
  const resolvePin = (ref: string, pin: number | string): ResolvedPin | null => {
    const direct = pinIndex.get(`${ref}.${pin}`);
    if (direct) return direct;
    const compPlaced = placed.find(p => p.ref === ref);
    if (!compPlaced) return null;
    const num = typeof pin === 'number' ? pin : parseInt(String(pin), 10);
    if (!Number.isFinite(num)) return null;
    const pinDef = compPlaced.symbol.pins[num - 1];
    if (!pinDef) return null;
    return { ref, pinId: pinDef.id, x: compPlaced.ox + pinDef.x, y: compPlaced.oy + pinDef.y };
  };

  // Power flags
  let pwrCounter = 0;
  for (const net of connections) {
    const isGnd = GND_NET_REGEX.test(net.name);
    const isPwr = POWER_NET_REGEX.test(net.name) || OUT_NET_REGEX.test(net.name);
    if (!isGnd && !isPwr) continue;
    for (const p of net.pins) {
      const pin = resolvePin(p.ref, p.pin);
      if (!pin) continue;
      const flagRef = `__pwr:${net.name}:${pwrCounter++}`;
      if (isGnd) {
        const sym = gndFlag();
        const ox = pin.x - sym.width / 2;
        const oy = pin.y + 6;
        placed.push({ ref: flagRef, value: '', symbol: sym, ox, oy, sourceRef: null, netLabel: net.name });
        pinIndex.set(`${flagRef}.gnd`, { ref: flagRef, pinId: 'gnd', x: pin.x, y: pin.y + 6 });
      } else {
        const sym = powerFlag(net.name);
        const ox = pin.x - sym.width / 2;
        const oy = pin.y - sym.height - 6;
        placed.push({ ref: flagRef, value: '', symbol: sym, ox, oy, sourceRef: null, netLabel: net.name });
        pinIndex.set(`${flagRef}.pwr`, { ref: flagRef, pinId: 'pwr', x: pin.x, y: pin.y - 6 });
      }
    }
  }

  // Route wires
  const nets: RoutedNet[] = [];
  const NET_COLORS = [
    '#22D3EE', '#A78BFA', '#F472B6', '#FACC15', '#34D399',
    '#FB923C', '#60A5FA', '#F87171', '#84CC16', '#E879F9',
  ];

  for (let i = 0; i < connections.length; i++) {
    const net = connections[i]!;
    const isGnd = GND_NET_REGEX.test(net.name);
    const isPwr = POWER_NET_REGEX.test(net.name) || OUT_NET_REGEX.test(net.name);
    const color = isGnd ? '#8E8E92' : isPwr ? '#E07B39' : NET_COLORS[i % NET_COLORS.length]!;

    const pinCoords = net.pins
      .map(p => resolvePin(p.ref, p.pin))
      .filter((p): p is ResolvedPin => p !== null);
    if (pinCoords.length < 2) {
      nets.push({ name: net.name, segments: [], junctions: [], isPower: isPwr, isGround: isGnd, color });
      continue;
    }

    if (isGnd || isPwr) {
      const segs: WireSegment[] = [];
      for (const p of pinCoords) {
        if (isGnd) segs.push({ x1: p.x, y1: p.y, x2: p.x, y2: p.y + 6 });
        else       segs.push({ x1: p.x, y1: p.y, x2: p.x, y2: p.y - 6 });
      }
      nets.push({ name: net.name, segments: segs, junctions: [], isPower: isPwr, isGround: isGnd, color });
      continue;
    }

    const trunkY = Math.round(pinCoords.reduce((s, p) => s + p.y, 0) / pinCoords.length);
    const sorted = [...pinCoords].sort((a, b) => a.x - b.x);
    const minX = sorted[0]!.x;
    const maxX = sorted[sorted.length - 1]!.x;
    const segments: WireSegment[] = [{ x1: minX, y1: trunkY, x2: maxX, y2: trunkY }];
    const junctions: Array<{ x: number; y: number }> = [];
    for (const p of pinCoords) {
      if (p.y !== trunkY) {
        segments.push({ x1: p.x, y1: trunkY, x2: p.x, y2: p.y });
        if (pinCoords.length > 2 && p.x !== minX && p.x !== maxX) junctions.push({ x: p.x, y: trunkY });
      }
    }
    nets.push({ name: net.name, segments, junctions, isPower: false, isGround: false, color });
  }

  const maxX = Math.max(
    placed.reduce((m, p) => Math.max(m, p.ox + p.symbol.width), 0),
    blocks.reduce((m, b) => Math.max(m, b.x + b.width), 0),
  ) + 60;
  const maxY = Math.max(
    placed.reduce((m, p) => Math.max(m, p.oy + p.symbol.height), 0),
    blocks.reduce((m, b) => Math.max(m, b.y + b.height), 0),
  ) + 100;

  return {
    placed,
    pinIndex,
    nets,
    blocks,
    width: Math.max(800, maxX),
    height: Math.max(500, maxY),
  };
}
