import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { runCircuitSynthEngine, isCircuitSynthAvailable } from './circuit-synth-engine';
import type { SchemaJson } from './circuit-synth-engine';

const SCHEMA: SchemaJson = {
  components: [
    { ref: 'R1', value: '10k', footprint: '0402' },
    { ref: 'C1', value: '100nF', footprint: '0402' },
    { ref: 'U1', value: 'NE555', footprint: 'DIP-8' },
  ],
  nets: ['GND', 'VCC', 'NET1'],
  connections: [
    { name: 'GND', pins: [{ ref: 'R1', pin: 2 }, { ref: 'C1', pin: 2 }] },
    { name: 'VCC', pins: [{ ref: 'U1', pin: 1 }, { ref: 'C1', pin: 1 }] },
    { name: 'NET1', pins: [{ ref: 'R1', pin: 1 }, { ref: 'U1', pin: 2 }] },
  ],
};

// ============================================================
// isCircuitSynthAvailable — always true (inline TS fallback)
// ============================================================

describe('isCircuitSynthAvailable', () => {
  afterEach(() => {
    delete process.env.KICAD_SERVICE_URL;
  });

  it('returns true regardless of KICAD_SERVICE_URL', () => {
    delete process.env.KICAD_SERVICE_URL;
    expect(isCircuitSynthAvailable()).toBe(true);
  });

  it('returns true when KICAD_SERVICE_URL is set', () => {
    process.env.KICAD_SERVICE_URL = 'http://localhost:8000';
    expect(isCircuitSynthAvailable()).toBe(true);
  });
});

// ============================================================
// runCircuitSynthEngine — inline generation (no external service)
// ============================================================

describe('runCircuitSynthEngine — inline mode', () => {
  afterEach(() => {
    delete process.env.KICAD_SERVICE_URL;
    vi.restoreAllMocks();
  });

  it('generates kicad_sch_content without any external service', async () => {
    const result = await runCircuitSynthEngine(SCHEMA);
    expect(result.kicad_sch_content).toContain('kicad_sch');
    expect(result.kicad_sch_content).toContain('R1');
    expect(result.kicad_sch_content).toContain('NE555');
  });

  it('generates kicad_pcb_content without any external service', async () => {
    const result = await runCircuitSynthEngine(SCHEMA);
    expect(result.kicad_pcb_content).toContain('kicad_pcb');
    expect(result.kicad_pcb_content).toContain('Edge.Cuts');
  });

  it('result is never null — always falls back to inline generation', async () => {
    const result = await runCircuitSynthEngine(SCHEMA);
    expect(result.kicad_sch_content).toBeTruthy();
    expect(result.kicad_pcb_content).toBeTruthy();
  });

  it('respects custom board dimensions', async () => {
    const result = await runCircuitSynthEngine(SCHEMA, 60, 40);
    // Board outline must contain the custom dimensions
    expect(result.kicad_pcb_content).toContain('60');
    expect(result.kicad_pcb_content).toContain('40');
  });

  it('includes all component refs in schematic', async () => {
    const result = await runCircuitSynthEngine(SCHEMA);
    for (const comp of SCHEMA.components) {
      expect(result.kicad_sch_content).toContain(comp.ref);
    }
  });
});

// ============================================================
// runCircuitSynthEngine — with external service (mocked fetch)
// ============================================================

describe('runCircuitSynthEngine — external service mode', () => {
  beforeEach(() => {
    process.env.KICAD_SERVICE_URL = 'http://localhost:8000';
  });

  afterEach(() => {
    delete process.env.KICAD_SERVICE_URL;
    vi.restoreAllMocks();
  });

  it('calls /schematic/generate with correct payload when service URL is set', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        kicad_sch_content: '(kicad_sch)',
        kicad_pcb_content: '(kicad_pcb)',
      }),
    });
    vi.stubGlobal('fetch', mockFetch);

    await runCircuitSynthEngine(SCHEMA, 60, 40, 'proj-123');

    expect(mockFetch).toHaveBeenCalledOnce();
    const [url, opts] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://localhost:8000/schematic/generate');
    expect(opts.method).toBe('POST');

    const body = JSON.parse(opts.body as string) as Record<string, unknown>;
    expect(body.components).toHaveLength(3);
    expect(body.board_width_mm).toBe(60);
    expect(body.board_height_mm).toBe(40);
    expect(body.project_id).toBe('proj-123');
    expect(Array.isArray(body.connections)).toBe(true);
  });

  it('returns service content when service succeeds', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        kicad_sch_content: '(kicad_sch (version 20230121))',
        kicad_pcb_content: '(kicad_pcb (version 20221018))',
      }),
    }));

    const result = await runCircuitSynthEngine(SCHEMA);
    expect(result.kicad_sch_content).toBe('(kicad_sch (version 20230121))');
    expect(result.kicad_pcb_content).toBe('(kicad_pcb (version 20221018))');
  });

  it('falls back to inline generation when service returns nulls', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, kicad_sch_content: null, kicad_pcb_content: null }),
    }));

    const result = await runCircuitSynthEngine(SCHEMA);
    // Inline fallback — non-null
    expect(result.kicad_sch_content).toBeTruthy();
    expect(result.kicad_pcb_content).toBeTruthy();
  });

  it('falls back to inline generation on non-2xx status', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }));

    const result = await runCircuitSynthEngine(SCHEMA);
    expect(result.kicad_sch_content).toContain('kicad_sch');
  });

  it('falls back to inline generation when service reports failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: false, error: 'No components in schema' }),
    }));

    const result = await runCircuitSynthEngine(SCHEMA);
    expect(result.kicad_sch_content).toContain('kicad_sch');
  });

  it('falls back to inline generation when fetch throws', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network error')));

    const result = await runCircuitSynthEngine(SCHEMA);
    expect(result.kicad_sch_content).toContain('kicad_sch');
  });
});
