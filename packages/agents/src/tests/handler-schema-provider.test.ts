import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

/**
 * `call_agent_schema` choisit son fournisseur par `CIRQIX_SCHEMA_PROVIDER`
 * (D-2026-09-13-a) : `claude-code` fait écrire le schéma par Claude Code, tout
 * le reste du handler est INCHANGÉ. Sans schéma rendu, aucun repli fabriqué.
 */
vi.hoisted(() => {
  process.env['LOG_LEVEL'] = 'silent';
});
const haikuMock = vi.hoisted(() => ({ generateSchemaWithHaiku: vi.fn() }));
vi.mock('../tools/handlers/schema-haiku', () => haikuMock);
const claudeMock = vi.hoisted(() => ({ generateSchemaWithClaudeCode: vi.fn() }));
vi.mock('../tools/handlers/schema-claude-code', () => claudeMock);
const engineMock = vi.hoisted(() => ({ runCircuitSynthEngine: vi.fn(), runPCBEngine: vi.fn() }));
vi.mock('../engines/engine-router', () => engineMock);

import { handleSchema } from '../tools/handlers/schema';
import { pcbStateCache } from '../tools/shared';

const SCHEMA = {
  components: [{ ref: 'R1', value: '1k', footprint: 'Resistor_SMD:R_0603_1608Metric', symbol: 'Device:R' }],
  nets: ['GND'],
  connections: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  pcbStateCache.clear();
  engineMock.runCircuitSynthEngine.mockResolvedValue({ kicad_sch_content: '(kicad_sch)' });
});
afterEach(() => {
  delete process.env['CIRQIX_SCHEMA_PROVIDER'];
});

describe('call_agent_schema — fournisseur', () => {
  it('sans réglage, Haiku écrit le schéma et Claude Code n est jamais appelé', async () => {
    haikuMock.generateSchemaWithHaiku.mockResolvedValue(SCHEMA);
    const r = await handleSchema({ user_description: 'une résistance' }, 'p1');
    expect(r['status']).toBe('success');
    expect(r['engine']).toBe('circuit-synth-json');
    expect(claudeMock.generateSchemaWithClaudeCode).not.toHaveBeenCalled();
  });

  it('avec claude-code, Claude Code écrit le schéma, Haiku n est jamais appelé, la provenance le dit', async () => {
    process.env['CIRQIX_SCHEMA_PROVIDER'] = 'claude-code';
    claudeMock.generateSchemaWithClaudeCode.mockResolvedValue(SCHEMA);
    const r = await handleSchema({ user_description: 'une résistance' }, 'p2');
    expect(r['status']).toBe('success');
    expect(r['engine']).toBe('claude-code');
    expect(claudeMock.generateSchemaWithClaudeCode).toHaveBeenCalledWith('une résistance');
    expect(haikuMock.generateSchemaWithHaiku).not.toHaveBeenCalled();
    expect(pcbStateCache.get('p2')?.schema.components).toHaveLength(1);
  });

  it('un schéma fourni (schema_json) l emporte sur tout fournisseur', async () => {
    process.env['CIRQIX_SCHEMA_PROVIDER'] = 'claude-code';
    const r = await handleSchema({ schema_json: SCHEMA, user_description: 'x' }, 'p3');
    expect(r['engine']).toBe('driver-json');
    expect(claudeMock.generateSchemaWithClaudeCode).not.toHaveBeenCalled();
  });

  it('si Claude Code ne rend rien, le run échoue et nomme le fournisseur — rien n est fabriqué', async () => {
    process.env['CIRQIX_SCHEMA_PROVIDER'] = 'claude-code';
    claudeMock.generateSchemaWithClaudeCode.mockResolvedValue(null);
    const r = await handleSchema({ user_description: 'x' }, 'p4');
    expect(r['status']).toBe('error');
    expect(String(r['error'])).toContain('claude-code');
    expect(engineMock.runCircuitSynthEngine).not.toHaveBeenCalled();
  });
});
