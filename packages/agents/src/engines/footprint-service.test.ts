import { describe, it, expect } from 'vitest';
import { findFootprint } from './footprint-service';

// These tests exercise only the KiCad library lookup (Step 1) — no network,
// no Anthropic API key required. The cascade is deterministic for known parts.

describe('findFootprint — KiCad library lookup (Step 1)', () => {
  it('resolves 0402 resistor', async () => {
    const r = await findFootprint('R1', '0402');
    expect(r.source).toBe('kicad_official');
    expect(r.footprint_name).toBe('Resistor_SMD:R_0402_1005Metric');
  });

  it('resolves 0603 capacitor', async () => {
    const r = await findFootprint('C1', '0603');
    expect(r.source).toBe('kicad_official');
    expect(r.footprint_name).toBe('Capacitor_SMD:C_0603_1608Metric');
  });

  it('resolves SOT-23 by package hint', async () => {
    const r = await findFootprint('2N7002', 'SOT-23');
    expect(r.source).toBe('kicad_official');
    expect(r.footprint_name).toContain('SOT-23');
  });

  it('resolves NE555 by part number', async () => {
    const r = await findFootprint('NE555P');
    expect(r.source).toBe('kicad_official');
    expect(r.footprint_name).toContain('DIP-8');
  });

  it('resolves LM7805 by part number', async () => {
    const r = await findFootprint('LM7805');
    expect(r.source).toBe('kicad_official');
    expect(r.footprint_name).toContain('TO-220');
  });

  it('resolves SOIC-8 by package hint', async () => {
    const r = await findFootprint('SN74HC00N', 'SOIC-8');
    expect(r.source).toBe('kicad_official');
    expect(r.footprint_name).toContain('SOIC-8');
  });

  it('resolves ESP32-WROOM by part number', async () => {
    const r = await findFootprint('ESP32-WROOM-32');
    expect(r.source).toBe('kicad_official');
    expect(r.footprint_name).toContain('ESP32');
  });

  it('falls back to generic for unknown part (no API keys)', async () => {
    // In CI there are no API keys, so steps 2-4 are skipped → generic fallback
    const r = await findFootprint('UNKNOWN_PART_XYZ_99999');
    expect(r.footprint_name).toBeTruthy();
    expect(typeof r.footprint_name).toBe('string');
  });

  it('uses package hint for fallback generic', async () => {
    const r = await findFootprint('UNKNOWN_XYZ', '0805');
    // Package hint "0805" should resolve via library even without specific part
    expect(r.footprint_name).toBeTruthy();
  });
});
