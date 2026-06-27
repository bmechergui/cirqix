/**
 * TypeScript ERC — validates schema JSON without kicad-cli.
 *
 * Used when the FastAPI ERC service is unreachable. Checks the four most
 * common electrical errors that would cause a PCB to fail:
 *   1. Duplicate component references
 *   2. Nets with fewer than 2 connections (floating net)
 *   3. Missing GND net
 *   4. Unconnected components (no net assigned)
 *
 * Returns real violations (not a silent skip) so the pipeline can surface
 * issues to the user before proceeding to placement.
 */

import type { ERCViolation } from '@cirqix/types';
import type { SchemaJson } from './engine-router';

export interface ErcFallbackResult {
  ercClean: boolean;
  violations: ERCViolation[];
  fixedCount: number;
  skipped: boolean;
  warning: string | undefined;
  engine: 'ts-erc' | 'fallback-skip';
}

function makeId(): string {
  return Math.random().toString(36).slice(2, 10);
}

export function runErcFallback(schema?: SchemaJson): ErcFallbackResult {
  // No schema in cache — silent skip (pipeline hasn't run schema step yet)
  if (!schema || !schema.components?.length) {
    return {
      ercClean: true,
      violations: [],
      fixedCount: 0,
      skipped: true,
      warning: 'kicad-cli unavailable — ERC will be re-checked in production',
      engine: 'fallback-skip',
    };
  }

  const violations: ERCViolation[] = [];
  const connections = schema.connections ?? [];

  // ── 1. Duplicate references ──────────────────────────────────────────────
  const seen = new Set<string>();
  for (const comp of schema.components) {
    if (seen.has(comp.ref)) {
      violations.push({
        id: makeId(),
        severity: 'error',
        message: `Duplicate reference: ${comp.ref}`,
        type: 'duplicate_ref',
        ref: comp.ref,
      });
    }
    seen.add(comp.ref);
  }

  // ── 2. Floating nets (< 2 pins) ──────────────────────────────────────────
  for (const conn of connections) {
    if (conn.pins.length < 2) {
      violations.push({
        id: makeId(),
        severity: 'error',
        message: `Net "${conn.name}" has only ${conn.pins.length} connection — floating net`,
        type: 'pin_not_connected',
      });
    }
  }

  // ── 3. Missing GND ───────────────────────────────────────────────────────
  const hasGnd = connections.some((c) => /^GND$/i.test(c.name) || /^VSS$/i.test(c.name));
  if (!hasGnd) {
    violations.push({
      id: makeId(),
      severity: 'error',
      message: 'No GND net — circuit has no ground reference',
      type: 'missing_gnd',
    });
  }

  // ── 4. Unconnected components ─────────────────────────────────────────────
  const connectedRefs = new Set(connections.flatMap((c) => c.pins.map((p) => p.ref)));
  for (const comp of schema.components) {
    if (!connectedRefs.has(comp.ref)) {
      violations.push({
        id: makeId(),
        severity: 'warning',
        message: `Component ${comp.ref} (${comp.value}) has no connections`,
        type: 'pin_not_connected',
        ref: comp.ref,
      });
    }
  }

  const errorCount = violations.filter((v) => v.severity === 'error').length;
  const ercClean = errorCount === 0;

  return {
    ercClean,
    violations,
    fixedCount: 0,
    skipped: false,
    warning: ercClean
      ? undefined
      : `TypeScript ERC: ${errorCount} error(s), ${violations.length - errorCount} warning(s) — kicad-cli unavailable for full check`,
    engine: 'ts-erc',
  };
}
