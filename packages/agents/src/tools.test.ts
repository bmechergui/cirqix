import { describe, it, expect, vi, beforeEach } from 'vitest';
import { PCB_TOOLS, executeToolStub } from './tools';

// Mock Anthropic SDK at module level for generateDesignWithHaiku tests
const mockCreate = vi.fn();
vi.mock('@anthropic-ai/sdk', () => ({
  default: vi.fn().mockImplementation(() => ({
    messages: { create: mockCreate },
  })),
}));

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
