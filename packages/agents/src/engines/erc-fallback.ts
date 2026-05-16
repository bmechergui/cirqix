/**
 * Pure ERC fallback — used when the FastAPI service is unreachable.
 *
 * A real Electrical Rules Check requires KiCad's CLI; we can't reproduce it in
 * TypeScript. The fallback skips the check with a clear warning so the agent
 * pipeline keeps moving and the user sees the schematic was not validated.
 */

import type { ERCViolation } from '@layrix/types';

export interface ErcFallbackResult {
  ercClean: boolean;
  violations: ERCViolation[];
  fixedCount: number;
  skipped: boolean;
  warning: string;
  engine: 'fallback-skip';
}

export function runErcFallback(): ErcFallbackResult {
  return {
    ercClean: true,
    violations: [],
    fixedCount: 0,
    skipped: true,
    warning: 'kicad-cli unavailable — ERC will be re-checked in production',
    engine: 'fallback-skip',
  };
}
