import { describe, it, expect } from 'vitest';
import { runErcFallback } from './erc-fallback';

describe('erc-fallback', () => {
  it('returns clean skipped result with no violations', () => {
    const result = runErcFallback();
    expect(result.ercClean).toBe(true);
    expect(result.violations).toEqual([]);
    expect(result.skipped).toBe(true);
    expect(result.fixedCount).toBe(0);
  });

  it('includes a human-readable warning', () => {
    expect(typeof runErcFallback().warning).toBe('string');
    expect(runErcFallback().warning!.length).toBeGreaterThan(0);
  });

  it('is pure — returns equivalent results on every call', () => {
    expect(runErcFallback()).toEqual(runErcFallback());
  });

  it('engine label identifies the fallback path', () => {
    expect(runErcFallback().engine).toBe('fallback-skip');
  });
});
