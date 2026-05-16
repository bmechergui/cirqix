import { describe, it, expect, vi, beforeEach } from 'vitest';
import { PCB_TOOLS, executeToolStub } from './tools';
import {
  runRealPlacement,
  PlacementServiceUnavailableError,
} from './engines/placement-service';
import {
  runRealErc,
  ErcServiceUnavailableError,
} from './engines/erc-service';

// Mock Anthropic SDK at module level for generateDesignWithHaiku tests
const mockCreate = vi.fn();
vi.mock('@anthropic-ai/sdk', () => ({
  default: vi.fn().mockImplementation(() => ({
    messages: { create: mockCreate },
  })),
}));

// Mock placement-service so we can control success/failure per test.
// The real PlacementServiceUnavailableError is re-exported so `instanceof` works.
vi.mock('./engines/placement-service', async () => {
  const actual =
    await vi.importActual<typeof import('./engines/placement-service')>(
      './engines/placement-service',
    );
  return {
    ...actual,
    runRealPlacement: vi.fn(),
  };
});

vi.mock('./engines/erc-service', async () => {
  const actual = await vi.importActual<typeof import('./engines/erc-service')>(
    './engines/erc-service',
  );
  return {
    ...actual,
    runRealErc: vi.fn(),
  };
});

beforeEach(() => {
  mockCreate.mockReset();
  process.env['ANTHROPIC_API_KEY'] = 'test-key';
});

describe('PCB_TOOLS — call_agent_spec', () => {
  it('exposes a call_agent_spec tool definition', () => {
    const designTool = PCB_TOOLS.find((t) => t.name === 'call_agent_spec');
    expect(designTool).toBeDefined();
    expect(designTool?.description).toMatch(/design|type|circuit/i);
  });

  it('declares user_description as required input', () => {
    const designTool = PCB_TOOLS.find((t) => t.name === 'call_agent_spec');
    const schema = designTool?.input_schema as {
      type: string;
      properties: Record<string, unknown>;
      required: string[];
    };
    expect(schema.type).toBe('object');
    expect(schema.required).toContain('user_description');
    expect(schema.properties).toHaveProperty('user_description');
  });

  it('appears BEFORE call_agent_schema in PCB_TOOLS list', () => {
    const designIdx = PCB_TOOLS.findIndex((t) => t.name === 'call_agent_spec');
    const schemaIdx = PCB_TOOLS.findIndex((t) => t.name === 'call_agent_schema');
    expect(designIdx).toBeGreaterThanOrEqual(0);
    expect(schemaIdx).toBeGreaterThanOrEqual(0);
    expect(designIdx).toBeLessThan(schemaIdx);
  });
});

describe('executeToolStub — call_agent_spec', () => {
  it('returns success with a fallback design when API key absent', async () => {
    delete process.env['ANTHROPIC_API_KEY'];

    const result = await executeToolStub(
      'call_agent_spec',
      { user_description: 'régulateur 5V LM7805 avec condensateurs' },
      'proj-test'
    );

    expect(result['status']).toBe('success');
    expect(result['design']).toBeDefined();
    const design = result['design'] as Record<string, unknown>;
    expect(typeof design['type']).toBe('string');
    expect(Array.isArray(design['blocks'])).toBe(true);
    expect([2, 4, 8]).toContain(design['layers']);
    expect(design['rules']).toBeDefined();
  });

  it('parses Haiku design JSON when LLM responds correctly', async () => {
    mockCreate.mockResolvedValueOnce({
      content: [
        {
          type: 'text',
          text: JSON.stringify({
            type: 'power_supply',
            blocks: ['Power', 'Decoupling'],
            layers: 2,
            rules: {
              trace_width_mm: 0.3,
              clearance_mm: 0.2,
              via_drill_mm: 0.3,
              min_text_mm: 1.0,
            },
            constraints: {
              output_voltage: 5,
              max_current_A: 1.5,
              max_board_mm: [50, 50],
            },
          }),
        },
      ],
    });

    const result = await executeToolStub(
      'call_agent_spec',
      { user_description: 'régulateur 5V LM7805' },
      'proj-test'
    );

    expect(result['status']).toBe('success');
    const design = result['design'] as Record<string, unknown>;
    expect(design['type']).toBe('power_supply');
    expect(design['layers']).toBe(2);
    expect((design['blocks'] as string[]).length).toBeGreaterThan(0);
  });

  it('returns a usable fallback design when Haiku output is invalid JSON', async () => {
    mockCreate.mockResolvedValueOnce({
      content: [{ type: 'text', text: 'this is not JSON at all' }],
    });

    const result = await executeToolStub(
      'call_agent_spec',
      { user_description: 'circuit simple' },
      'proj-test'
    );

    // Must NOT crash — returns a fallback design
    expect(result['status']).toBe('success');
    const design = result['design'] as Record<string, unknown>;
    expect(design['type']).toBeDefined();
    expect([2, 4, 8]).toContain(design['layers']);
  });

  it('does NOT change PCBStatus (design = context, not a deliverable)', async () => {
    delete process.env['ANTHROPIC_API_KEY'];

    const result = await executeToolStub(
      'call_agent_spec',
      { user_description: 'simple LED' },
      'proj-test'
    );

    // No pcb_status field, or pcb_status === 'INITIAL'
    const status = result['pcb_status'];
    if (status !== undefined) {
      expect(status).toBe('INITIAL');
    }
  });

  it('includes a human-readable note in the result', async () => {
    delete process.env['ANTHROPIC_API_KEY'];

    const result = await executeToolStub(
      'call_agent_spec',
      { user_description: 'régulateur 5V' },
      'proj-test'
    );

    expect(typeof result['note']).toBe('string');
    expect((result['note'] as string).length).toBeGreaterThan(0);
  });
});

// ============================================================
// call_agent_placement — real pcbnew service + TS fallback
// ============================================================

const SIMPLE_SCHEMA_JSON = JSON.stringify({
  components: [
    { ref: 'U1', value: 'NE555P', footprint: 'DIP-8', symbol: 'Timer:NE555P' },
    { ref: 'R1', value: '4.7k', footprint: '0603', symbol: 'Device:R' },
    { ref: 'C1', value: '100nF', footprint: '0603', symbol: 'Device:C' },
    { ref: 'J1', value: 'PWR', footprint: 'Conn_2', symbol: 'Connector_Generic:Conn_01x02' },
  ],
  nets: ['GND', 'VCC'],
  connections: [
    { name: 'GND', pins: [{ ref: 'U1', pin: 'GND' }, { ref: 'C1', pin: 2 }, { ref: 'J1', pin: 2 }] },
    { name: 'VCC', pins: [{ ref: 'U1', pin: 'VCC' }, { ref: 'C1', pin: 1 }, { ref: 'J1', pin: 1 }] },
  ],
});

describe('executeToolStub — call_agent_placement', () => {
  beforeEach(() => {
    vi.mocked(runRealPlacement).mockReset();
  });

  it('uses the placement service when it succeeds', async () => {
    vi.mocked(runRealPlacement).mockResolvedValueOnce({
      kicadPcbContent: '(kicad_pcb placed-by-service)',
      positions: [
        { ref: 'U1', x_mm: 25, y_mm: 25 },
        { ref: 'R1', x_mm: 30, y_mm: 20 },
        { ref: 'C1', x_mm: 20, y_mm: 30 },
        { ref: 'J1', x_mm: 5, y_mm: 25 },
      ],
    });

    const result = await executeToolStub(
      'call_agent_placement',
      { schema_json: SIMPLE_SCHEMA_JSON, board_width_mm: 50, board_height_mm: 50 },
      'proj-pcbnew',
    );

    expect(result['status']).toBe('success');
    expect(result['pcb_status']).toBe('PLACEMENT_DONE');
    expect(result['engine']).toBe('pcbnew');
    expect(result['kicad_pcb_content']).toBe('(kicad_pcb placed-by-service)');
    expect(Array.isArray(result['placements'])).toBe(true);
    expect((result['placements'] as unknown[]).length).toBe(4);
    expect(runRealPlacement).toHaveBeenCalledOnce();
  });

  it('falls back to TS planner when service throws PlacementServiceUnavailableError', async () => {
    vi.mocked(runRealPlacement).mockRejectedValueOnce(
      new PlacementServiceUnavailableError('service down'),
    );

    const result = await executeToolStub(
      'call_agent_placement',
      { schema_json: SIMPLE_SCHEMA_JSON, board_width_mm: 50, board_height_mm: 50 },
      'proj-fallback',
    );

    expect(result['status']).toBe('success');
    expect(result['pcb_status']).toBe('PLACEMENT_DONE');
    expect(result['engine']).toBe('fallback-ts');
    // Fallback still ships a kicad_pcb_content (from Circuit-Synth at schema step
    // or a fresh regeneration here) so the viewer keeps a valid native preview
    expect(typeof result['kicad_pcb_content']).toBe('string');
    expect((result['kicad_pcb_content'] as string).length).toBeGreaterThan(0);
    const placements = result['placements'] as Array<Record<string, unknown>>;
    expect(placements).toHaveLength(4);
    // U1 (IC) must land near board center via the pure fallback planner
    const u1 = placements.find((p) => p['ref'] === 'U1')!;
    expect(Math.abs((u1['x_mm'] as number) - 25)).toBeLessThan(2);
    expect(Math.abs((u1['y_mm'] as number) - 25)).toBeLessThan(2);
  });

  it('falls back on any service error, not just PlacementServiceUnavailableError', async () => {
    vi.mocked(runRealPlacement).mockRejectedValueOnce(new Error('unexpected'));

    const result = await executeToolStub(
      'call_agent_placement',
      { schema_json: SIMPLE_SCHEMA_JSON, board_width_mm: 50, board_height_mm: 50 },
      'proj-any-err',
    );
    expect(result['status']).toBe('success');
    expect(result['engine']).toBe('fallback-ts');
  });

  it('respects custom board dimensions', async () => {
    vi.mocked(runRealPlacement).mockRejectedValueOnce(
      new PlacementServiceUnavailableError('down'),
    );

    const result = await executeToolStub(
      'call_agent_placement',
      { schema_json: SIMPLE_SCHEMA_JSON, board_width_mm: 80, board_height_mm: 60 },
      'proj-dims',
    );
    expect(result['board_width_mm']).toBe(80);
    expect(result['board_height_mm']).toBe(60);
    const u1 = (result['placements'] as Array<Record<string, unknown>>).find(
      (p) => p['ref'] === 'U1',
    )!;
    // Centroid for 80x60 board
    expect(Math.abs((u1['x_mm'] as number) - 40)).toBeLessThan(3);
    expect(Math.abs((u1['y_mm'] as number) - 30)).toBeLessThan(3);
  });

  it('handles empty schema gracefully', async () => {
    vi.mocked(runRealPlacement).mockRejectedValueOnce(
      new PlacementServiceUnavailableError('down'),
    );

    const result = await executeToolStub(
      'call_agent_placement',
      { schema_json: JSON.stringify({ components: [], nets: [] }) },
      'proj-empty',
    );
    expect(result['status']).toBe('success');
    expect(result['placements']).toEqual([]);
  });

  it('includes a human-readable note', async () => {
    vi.mocked(runRealPlacement).mockResolvedValueOnce({
      kicadPcbContent: '(kicad_pcb x)',
      positions: [{ ref: 'U1', x_mm: 25, y_mm: 25 }],
    });

    const result = await executeToolStub(
      'call_agent_placement',
      { schema_json: SIMPLE_SCHEMA_JSON },
      'proj-note',
    );
    expect(typeof result['note']).toBe('string');
    expect((result['note'] as string).length).toBeGreaterThan(0);
  });
});

// ============================================================
// call_agent_erc — Electrical Rules Check
// ============================================================

describe('PCB_TOOLS — call_agent_erc', () => {
  it('exposes a call_agent_erc tool definition', () => {
    const ercTool = PCB_TOOLS.find((t) => t.name === 'call_agent_erc');
    expect(ercTool).toBeDefined();
    expect(ercTool?.description).toMatch(/electrical rules|erc/i);
  });

  it('positioned AFTER call_agent_schema and BEFORE call_agent_placement', () => {
    const schemaIdx = PCB_TOOLS.findIndex((t) => t.name === 'call_agent_schema');
    const ercIdx = PCB_TOOLS.findIndex((t) => t.name === 'call_agent_erc');
    const placementIdx = PCB_TOOLS.findIndex((t) => t.name === 'call_agent_placement');
    expect(ercIdx).toBeGreaterThan(schemaIdx);
    expect(ercIdx).toBeLessThan(placementIdx);
  });
});

describe('executeToolStub — call_agent_erc', () => {
  beforeEach(() => {
    vi.mocked(runRealErc).mockReset();
  });

  it('skips when no schema is cached', async () => {
    const result = await executeToolStub('call_agent_erc', { auto_fix: true }, 'proj-no-cache');
    expect(result['status']).toBe('success');
    expect(result['pcb_status']).toBe('ERC_CLEAN');
    expect(result['erc_skipped']).toBe(true);
    expect(result['engine']).toBe('fallback-skip');
    expect(runRealErc).not.toHaveBeenCalled();
  });

  it('returns clean result when service reports no violations', async () => {
    // Prime cache via call_agent_schema (mocked Haiku absent → fallback path)
    delete process.env['ANTHROPIC_API_KEY'];
    await executeToolStub(
      'call_agent_schema',
      { user_description: 'LED indicator', complexity: 'simple' },
      'proj-erc-clean',
    );

    vi.mocked(runRealErc).mockResolvedValueOnce({
      ercClean: true,
      violations: [],
      fixedCount: 0,
      skipped: false,
    });

    const result = await executeToolStub('call_agent_erc', { auto_fix: true }, 'proj-erc-clean');
    expect(result['pcb_status']).toBe('ERC_CLEAN');
    expect(result['engine']).toBe('kicad-cli');
    expect(result['ercViolations']).toEqual([]);
    expect(result['erc_skipped']).toBe(false);
  });

  it('propagates skipped state when kicad-cli unavailable', async () => {
    delete process.env['ANTHROPIC_API_KEY'];
    await executeToolStub(
      'call_agent_schema',
      { user_description: 'LED indicator', complexity: 'simple' },
      'proj-erc-skip',
    );

    vi.mocked(runRealErc).mockResolvedValueOnce({
      ercClean: true,
      violations: [],
      fixedCount: 0,
      skipped: true,
      warning: 'kicad-cli not available',
    });

    const result = await executeToolStub('call_agent_erc', { auto_fix: true }, 'proj-erc-skip');
    expect(result['engine']).toBe('kicad-cli-skipped');
    expect(result['erc_skipped']).toBe(true);
    expect(result['warning']).toContain('kicad-cli');
  });

  it('falls back when service throws ErcServiceUnavailableError', async () => {
    delete process.env['ANTHROPIC_API_KEY'];
    await executeToolStub(
      'call_agent_schema',
      { user_description: 'LED indicator', complexity: 'simple' },
      'proj-erc-fallback',
    );

    vi.mocked(runRealErc).mockRejectedValueOnce(
      new ErcServiceUnavailableError('service down'),
    );

    const result = await executeToolStub(
      'call_agent_erc',
      { auto_fix: true },
      'proj-erc-fallback',
    );
    expect(result['engine']).toBe('fallback-skip');
    expect(result['erc_skipped']).toBe(true);
  });

  it('falls back on any unexpected error', async () => {
    delete process.env['ANTHROPIC_API_KEY'];
    await executeToolStub(
      'call_agent_schema',
      { user_description: 'LED indicator', complexity: 'simple' },
      'proj-erc-error',
    );

    vi.mocked(runRealErc).mockRejectedValueOnce(new Error('unexpected'));

    const result = await executeToolStub(
      'call_agent_erc',
      { auto_fix: true },
      'proj-erc-error',
    );
    expect(result['status']).toBe('success');
    expect(result['engine']).toBe('fallback-skip');
  });

  it('returns updated kicad_sch_content when auto-fix applied', async () => {
    delete process.env['ANTHROPIC_API_KEY'];
    await executeToolStub(
      'call_agent_schema',
      { user_description: 'LED indicator', complexity: 'simple' },
      'proj-erc-fix',
    );

    const fixedSch = '(kicad_sch with no_connect added)';
    vi.mocked(runRealErc).mockResolvedValueOnce({
      ercClean: true,
      violations: [],
      fixedCount: 1,
      skipped: false,
      kicadSchContent: fixedSch,
    });

    const result = await executeToolStub('call_agent_erc', { auto_fix: true }, 'proj-erc-fix');
    expect(result['kicad_sch_content']).toBe(fixedSch);
    expect(result['fixed_count']).toBe(1);
  });
});
