import type { SchemaComponent } from '@cirqix/types';

export interface PlacedComponent extends SchemaComponent {
  /** mm from top-left of board */
  x: number;
  y: number;
  /** mm width / height of footprint silkscreen */
  w: number;
  h: number;
  /** simplified footprint class */
  kind: 'IC' | 'CAP' | 'RES' | 'DIODE' | 'CONN' | 'LED' | 'MISC';
}

const FOOTPRINT_SIZE: Record<string, { w: number; h: number }> = {
  '0402':            { w: 1.4, h: 0.7 },
  '0603':            { w: 1.8, h: 0.9 },
  '0805':            { w: 2.4, h: 1.4 },
  '1206':            { w: 3.4, h: 1.7 },
  'SOT-23':          { w: 3.0, h: 1.4 },
  'SOT-223':         { w: 6.7, h: 3.7 },
  'TO-220':          { w: 10.5, h: 5.5 },
  'DIP-8':           { w: 10.0, h: 8.0 },
  'QFN-32':          { w: 7.0, h: 7.0 },
  'QFN-56':          { w: 8.0, h: 8.0 },
  'LGA-8':           { w: 3.0, h: 3.0 },
  'USB-C':           { w: 9.0, h: 7.5 },
  'LED-0805':        { w: 2.4, h: 1.4 },
  'PinHeader-2':     { w: 5.1, h: 2.5 },
};

function refToKind(ref: string): PlacedComponent['kind'] {
  const prefix = ref.replace(/\d+$/, '').toUpperCase();
  if (prefix === 'U' || prefix === 'IC') return 'IC';
  if (prefix === 'C') return 'CAP';
  if (prefix === 'R') return 'RES';
  if (prefix === 'D') return ref.includes('LED') ? 'LED' : 'DIODE';
  if (prefix === 'L') return 'MISC';
  if (prefix === 'J' || prefix === 'CONN' || prefix === 'P') return 'CONN';
  return 'MISC';
}

function sizeFor(footprint: string): { w: number; h: number } {
  if (FOOTPRINT_SIZE[footprint]) return FOOTPRINT_SIZE[footprint]!;
  if (footprint.startsWith('LED')) return { w: 2.4, h: 1.4 };
  if (footprint.includes('PinHeader')) return { w: 5.0, h: 2.5 };
  return { w: 4.0, h: 3.0 };
}

/**
 * Deterministic top-down placer. Connectors near edges, ICs centered,
 * passives gridded in remaining space. Pure layout — no DRC awareness.
 */
export function layoutBoard(
  components: SchemaComponent[],
  boardWidthMm: number,
  boardHeightMm: number,
): PlacedComponent[] {
  const margin = 3;
  const placed: PlacedComponent[] = [];

  const enriched = components.map((c) => {
    const kind = refToKind(c.ref);
    const size = sizeFor(c.footprint);
    return { ...c, kind, w: size.w, h: size.h };
  });

  const conns = enriched.filter((c) => c.kind === 'CONN');
  const ics = enriched.filter((c) => c.kind === 'IC');
  const passives = enriched.filter((c) => c.kind !== 'CONN' && c.kind !== 'IC');

  // Connectors → left & right edges
  conns.forEach((c, i) => {
    const onLeft = i % 2 === 0;
    const y = margin + (i / 2) * (c.h + 4);
    placed.push({
      ...c,
      x: onLeft ? margin : boardWidthMm - margin - c.w,
      y: Math.min(y, boardHeightMm - margin - c.h),
    });
  });

  // ICs → center, arranged horizontally
  const icRow = boardHeightMm / 2 - 4;
  let icCursor = boardWidthMm / 2 - (ics.reduce((sum, ic) => sum + ic.w + 3, 0)) / 2;
  ics.forEach((c) => {
    placed.push({ ...c, x: Math.max(margin, icCursor), y: icRow });
    icCursor += c.w + 3;
  });

  // Passives → grid above and below ICs
  const startX = margin + 8;
  const endX = boardWidthMm - margin - 8;
  const passiveAreaWidth = Math.max(10, endX - startX);
  const cols = Math.max(2, Math.floor(passiveAreaWidth / 4));
  passives.forEach((c, i) => {
    const row = Math.floor(i / cols);
    const col = i % cols;
    const rowAbove = row % 2 === 0;
    const baseY = rowAbove ? margin + 4 + Math.floor(row / 2) * 3.5 : boardHeightMm - margin - 4 - Math.floor(row / 2) * 3.5;
    const x = startX + col * (passiveAreaWidth / cols);
    placed.push({
      ...c,
      x: Math.min(x, boardWidthMm - margin - c.w),
      y: Math.max(margin, Math.min(baseY, boardHeightMm - margin - c.h)),
    });
  });

  return placed;
}
