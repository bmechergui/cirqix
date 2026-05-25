/**
 * Pure-TypeScript placement planner — byte-for-byte port of
 * `services/kicad/tools/placement_layout.py`.
 *
 * Used as a fallback when the FastAPI placement microservice is unreachable.
 * Returns positions in the same shape as the Python planner so the agent
 * pipeline behaves identically across both code paths.
 */

export type Kind = 'IC' | 'RES' | 'CAP' | 'DIODE' | 'CONN' | 'MISC';

// Tunable constants — must match placement_layout.py
export const MARGIN_MM = 3.0;
export const IC_SPACING_MM = 15.0;
export const CLUSTER_RADIUS_BASE_MM = 8.0;
export const CLUSTER_RADIUS_STEP_MM = 1.5;
export const EDGE_OFFSET_MM = 2.0;

const REF_RE = /^([A-Za-z]+)/;

export function classifyKind(ref: string): Kind {
  const match = REF_RE.exec(ref);
  if (!match) return 'MISC';
  const prefix = match[1]!.toUpperCase();
  if (prefix.startsWith('LED')) return 'DIODE';
  if (prefix.startsWith('IC')) return 'IC';
  if (prefix.startsWith('TP')) return 'MISC';
  const head = prefix[0]!;
  if (head === 'U') return 'IC';
  if (head === 'R') return 'RES';
  if (head === 'C') return 'CAP';
  if (head === 'D') return 'DIODE';
  if (head === 'J' || head === 'P') return 'CONN';
  return 'MISC';
}

function clamp(value: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, value));
}

type Position = [x: number, y: number, rotation: number];
type Layout = Record<string, Position>;

function placeIcs(icRefs: readonly string[], boardW: number, boardH: number): Layout {
  const out: Layout = {};
  if (icRefs.length === 0) return out;
  const cy = boardH / 2;
  if (icRefs.length === 1) {
    out[icRefs[0]!] = [boardW / 2, cy, 0];
    return out;
  }
  const usableW = boardW - 2 * MARGIN_MM;
  const naturalStep = usableW / (icRefs.length + 1);
  const step = Math.min(naturalStep, IC_SPACING_MM);
  const total = step * (icRefs.length - 1);
  const x0 = (boardW - total) / 2;
  icRefs.forEach((ref, i) => {
    const x = clamp(x0 + i * step, MARGIN_MM, boardW - MARGIN_MM);
    out[ref] = [x, cy, 0];
  });
  return out;
}

function placeCluster(
  refs: readonly string[],
  icPositions: ReadonlyArray<readonly [number, number]>,
  boardW: number,
  boardH: number,
): Layout {
  const out: Layout = {};
  const n = refs.length;
  if (n === 0) return out;
  // Distribute refs across ICs by index (matches placement_layout.py)
  const buckets = new Map<number, string[]>();
  refs.forEach((ref, i) => {
    let idx = Math.floor((i * Math.max(1, icPositions.length)) / Math.max(1, n));
    idx = Math.min(idx, Math.max(0, icPositions.length - 1));
    const list = buckets.get(idx) ?? [];
    list.push(ref);
    buckets.set(idx, list);
  });
  for (const [icIdx, bucketRefs] of buckets) {
    const anchor: readonly [number, number] =
      icPositions.length > 0 ? icPositions[icIdx]! : [boardW / 2, boardH / 2];
    const radius = CLUSTER_RADIUS_BASE_MM + CLUSTER_RADIUS_STEP_MM * bucketRefs.length;
    bucketRefs.forEach((ref, i) => {
      // Start at 45° (diagonal) so passives spread nicely.
      // Starting at 90° or 0° creates 1D columns for n=2.
      const angle = Math.PI / 4 + (2 * Math.PI * i) / Math.max(1, bucketRefs.length);
      const x = clamp(anchor[0] + radius * Math.cos(angle), MARGIN_MM, boardW - MARGIN_MM);
      const y = clamp(anchor[1] + radius * Math.sin(angle), MARGIN_MM, boardH - MARGIN_MM);
      out[ref] = [x, y, 0];
    });
  }
  return out;
}

function placeConnectors(
  connRefs: readonly string[],
  boardW: number,
  boardH: number,
): Layout {
  const out: Layout = {};
  if (connRefs.length === 0) return out;
  const left = connRefs.filter((_, i) => i % 2 === 0);
  const right = connRefs.filter((_, i) => i % 2 === 1);
  const usableH = boardH - 2 * MARGIN_MM;
  const lanes: Array<[readonly string[], number]> = [
    [left, MARGIN_MM + EDGE_OFFSET_MM],
    [right, boardW - MARGIN_MM - EDGE_OFFSET_MM],
  ];
  for (const [refs, x] of lanes) {
    if (refs.length === 0) continue;
    const step = usableH / (refs.length + 1);
    refs.forEach((ref, i) => {
      const y = clamp(MARGIN_MM + step * (i + 1), MARGIN_MM, boardH - MARGIN_MM);
      out[ref] = [clamp(x, MARGIN_MM, boardW - MARGIN_MM), y, 0];
    });
  }
  return out;
}

function placeMisc(miscRefs: readonly string[], boardW: number, boardH: number): Layout {
  const out: Layout = {};
  if (miscRefs.length === 0) return out;
  const y = boardH - MARGIN_MM - EDGE_OFFSET_MM;
  const usableW = boardW - 2 * MARGIN_MM;
  const step = usableW / (miscRefs.length + 1);
  miscRefs.forEach((ref, i) => {
    const x = clamp(MARGIN_MM + step * (i + 1), MARGIN_MM, boardW - MARGIN_MM);
    out[ref] = [x, clamp(y, MARGIN_MM, boardH - MARGIN_MM), 0];
  });
  return out;
}

export function computeLayout(
  refs: readonly string[],
  boardWidthMm: number,
  boardHeightMm: number,
): Layout {
  if (refs.length === 0) return {};
  const buckets: Record<Kind, string[]> = {
    IC: [],
    RES: [],
    CAP: [],
    DIODE: [],
    CONN: [],
    MISC: [],
  };
  for (const ref of refs) {
    buckets[classifyKind(ref)].push(ref);
  }

  const out: Layout = {};
  Object.assign(out, placeIcs(buckets.IC, boardWidthMm, boardHeightMm));
  const icPositions: Array<readonly [number, number]> = buckets.IC.map(
    (r) => [out[r]![0], out[r]![1]] as const,
  );
  const passives = [...buckets.RES, ...buckets.CAP, ...buckets.DIODE];
  Object.assign(out, placeCluster(passives, icPositions, boardWidthMm, boardHeightMm));
  Object.assign(out, placeConnectors(buckets.CONN, boardWidthMm, boardHeightMm));
  Object.assign(out, placeMisc(buckets.MISC, boardWidthMm, boardHeightMm));

  const refsPl = Object.keys(out);
  if (refsPl.length > 0) {
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const ref of refsPl) {
      const [x, y] = out[ref]!;
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }

    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    const targetX = boardWidthMm / 2;
    const targetY = boardHeightMm / 2;
    const dx = targetX - centerX;
    const dy = targetY - centerY;

    for (const ref of refsPl) {
      const [x, y, rot] = out[ref]!;
      const newX = clamp(x + dx, MARGIN_MM, boardWidthMm - MARGIN_MM);
      const newY = clamp(y + dy, MARGIN_MM, boardHeightMm - MARGIN_MM);
      out[ref] = [newX, newY, rot];
    }
  }

  return out;
}

/**
 * Apply a layout (ref → [x, y, rotation]) to a .kicad_pcb S-expression string.
 *
 * Finds each footprint by its Reference property and rewrites the (at X Y)
 * in the footprint header line. Used by the TS fallback when pcbnew is
 * unavailable — ensures the cached PCB has real positions so the routing
 * agent works on a properly-placed board.
 */
export function applyLayoutToPcb(kicadPcbContent: string, layout: Layout): string {
  const lines = kicadPcbContent.split('\n');
  const out: string[] = [];
  let pendingPlacement: { ref: string; x: number; y: number } | null = null;

  for (let i = 0; i < lines.length; i++) {
    let line = lines[i]!;

    if (/^  \(footprint /.test(line)) {
      // Peek forward to find Reference
      let ref: string | undefined;
      for (let j = 1; j <= 15 && i + j < lines.length; j++) {
        const peek = lines[i + j]!;
        const m = peek.match(/^\s+\((?:property "Reference"|fp_text reference)\s+"([^"]+)"/);
        if (m) { ref = m[1]; break; }
        if (/^\s+\(pad /.test(peek)) break;
      }
      
      if (ref !== undefined && layout[ref] !== undefined) {
        const [nx, ny] = layout[ref]!;
        pendingPlacement = { ref, x: nx, y: ny };
      } else {
        pendingPlacement = null;
      }
    }

    if (pendingPlacement) {
      // Look for the first (at ...) before any property or pad
      if (/\(at\s+[\d.+-]+\s+[\d.+-]+(?:\s+[\d.+-]+)?\)/.test(line)) {
        line = line.replace(
          /\(at\s+[\d.+-]+\s+[\d.+-]+(?:\s+[\d.+-]+)?\)/,
          `(at ${pendingPlacement.x.toFixed(3)} ${pendingPlacement.y.toFixed(3)})`
        );
        pendingPlacement = null; // applied
      } else if (/^\s+\((?:property|pad|fp_)/.test(line) && !line.includes('(fp_text reference')) {
        // If we hit a property, pad, or fp_ shape (that is NOT the reference we are looking for), 
        // we missed the (at ...). But since `(at ...)` comes right after `(footprint ...)`,
        // it shouldn't happen.
        pendingPlacement = null; // stop looking
      }
    }

    out.push(line);
  }
  return out.join('\n');
}

/**
 * Convenience helper for the agent tool: turn the {ref: [x,y,rot]} layout
 * into the placement objects already consumed by PCBEngineResult.
 */
export function layoutToPlacements(
  layout: Layout,
): Array<{ ref: string; x_mm: number; y_mm: number; rotation: number; side: string }> {
  return Object.entries(layout).map(([ref, [x, y, rot]]) => ({
    ref,
    x_mm: +x.toFixed(3),
    y_mm: +y.toFixed(3),
    rotation: rot,
    side: 'front',
  }));
}
