import type { SchemaComponent, SchemaNet } from '@cirqix/types';

export type Role = 'INPUT' | 'IC' | 'PASSIVE' | 'OUTPUT';

export interface SchematicNode {
  ref: string;
  value: string;
  footprint: string;
  symbol?: string | undefined;
  role: Role;
  col: number; // 0..maxCol
  row: number;
  /** Pins that participate in named nets (subset of all component pins). */
  pinRows: Array<{ pin: string; net: string }>;
}

export interface SchematicWire {
  fromRef: string;
  fromPin: string;
  toRef: string;
  toPin: string;
  net: string;
}

export interface SchematicLayout {
  nodes: SchematicNode[];
  wires: SchematicWire[];
}

export const POWER_NET = /^(VCC|VDD|VIN|VBUS|VBAT|VOUT|3V3|5V|12V|PWR)/i;
export const GND_NET = /^GND$/i;
const INPUT_HINT = /^(VIN|IN|INPUT|J1|USB)/i;
const OUTPUT_HINT = /^(VOUT|OUT|OUTPUT|J2)/i;

function refPrefix(ref: string): string {
  return ref.replace(/\d+$/, '').toUpperCase();
}

function classifyRole(comp: SchemaComponent, nets: SchemaNet[]): Role {
  const prefix = refPrefix(comp.ref);
  // Heuristic: connectors with INPUT hints → INPUT
  if (prefix === 'J' || prefix === 'CONN' || prefix === 'P') {
    const matchInput = nets.some(
      (n) =>
        INPUT_HINT.test(n.name) &&
        n.pins.some((p) => p.ref === comp.ref)
    );
    if (matchInput) return 'INPUT';
    const matchOutput = nets.some(
      (n) =>
        OUTPUT_HINT.test(n.name) &&
        n.pins.some((p) => p.ref === comp.ref)
    );
    if (matchOutput) return 'OUTPUT';
    return 'INPUT';
  }
  if (prefix === 'U' || prefix === 'IC') return 'IC';
  return 'PASSIVE';
}

export function buildSchematicLayout(
  components: SchemaComponent[],
  connections: SchemaNet[],
): SchematicLayout {
  if (components.length === 0) {
    return { nodes: [], wires: [] };
  }

  // 1. Classify
  const roles: Map<string, Role> = new Map();
  components.forEach((c) => roles.set(c.ref, classifyRole(c, connections)));

  // 2. Decide each passive's column (input-side vs output-side)
  //    based on whether it touches an input-hint net or output-hint net.
  function passiveColumn(ref: string): number {
    const conns = connections.filter((c) => c.pins.some((p) => p.ref === ref));
    const touchesInput = conns.some((c) => INPUT_HINT.test(c.name) || /^(VCC|VIN|5V|VBUS)/i.test(c.name));
    const touchesOutput = conns.some((c) => OUTPUT_HINT.test(c.name) || /^(VOUT|3V3)/i.test(c.name));
    if (touchesInput && !touchesOutput) return 1;
    if (touchesOutput && !touchesInput) return 3;
    return 2; // middle / generic
  }

  // 3. Column assignment: 0=input, 1=input-passives, 2=IC, 3=output-passives, 4=output
  const COL = { INPUT: 0, IN_P: 1, IC: 2, OUT_P: 3, OUTPUT: 4 } as const;
  const buckets: Record<number, SchemaComponent[]> = { 0: [], 1: [], 2: [], 3: [], 4: [] };
  components.forEach((c) => {
    const role = roles.get(c.ref)!;
    if (role === 'INPUT') buckets[COL.INPUT]!.push(c);
    else if (role === 'OUTPUT') buckets[COL.OUTPUT]!.push(c);
    else if (role === 'IC') buckets[COL.IC]!.push(c);
    else {
      const col = passiveColumn(c.ref);
      buckets[col === 1 ? COL.IN_P : col === 3 ? COL.OUT_P : COL.IC]!.push(c);
    }
  });

  // 4. Build nodes with row assignments per column
  const nodes: SchematicNode[] = [];
  for (let col = 0; col <= 4; col++) {
    const bucket = buckets[col] ?? [];
    bucket.forEach((c, row) => {
      const pinRows = connections
        .filter((cn) => cn.pins.some((p) => p.ref === c.ref))
        .flatMap((cn) =>
          cn.pins.filter((p) => p.ref === c.ref).map((p) => ({ pin: String(p.pin), net: cn.name }))
        );
      nodes.push({
        ref: c.ref,
        value: c.value,
        footprint: c.footprint,
        symbol: c.symbol,
        role: roles.get(c.ref)!,
        col,
        row,
        pinRows,
      });
    });
  }

  // 5. Wires: for each net, connect consecutive pins in the order components appear
  const wires: SchematicWire[] = [];
  connections.forEach((cn) => {
    if (POWER_NET.test(cn.name) || GND_NET.test(cn.name)) return; // Prevent spaghetti by hiding global Power/GND nets

    const pins = cn.pins.filter((p) => nodes.some((n) => n.ref === p.ref));
    for (let i = 1; i < pins.length; i++) {
      const a = pins[i - 1]!;
      const b = pins[i]!;
      wires.push({
        fromRef: a.ref,
        fromPin: String(a.pin),
        toRef: b.ref,
        toPin: String(b.pin),
        net: cn.name,
      });
    }
  });

  return { nodes, wires };
}

export function netColor(name: string): string {
  // Hash to a pleasant color
  const palette = [
    '#00C2FF', '#22C55E', '#A855F7', '#F472B6', 
    '#FACC15', '#38BDF8', '#F87171', '#10B981',
    '#FB923C', '#818CF8'
  ];
  let h = 0;
  for (let i = 0; i < name.length; i++) {
    h = Math.imul(31, h) + name.charCodeAt(i) | 0;
  }
  // Mix in more entropy to avoid collisions
  h ^= h >>> 16;
  h = Math.imul(h, 0x85ebca6b);
  return palette[Math.abs(h) % palette.length]!;
}
