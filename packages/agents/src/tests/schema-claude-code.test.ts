import { describe, it, expect, vi } from 'vitest';

/**
 * Claude Code écrit le schéma à la place de Haiku (D-2026-09-13-a) — même
 * contrat (`SCHEMA_SYSTEM_PROMPT`, `parseSchemaText`), une seule entrée
 * (stdin), aucune fabrication en cas de panne.
 */
vi.hoisted(() => {
  process.env['LOG_LEVEL'] = 'silent';
});

import {
  generateSchemaWithClaudeCode,
  texteDeLEnveloppe,
} from '../tools/handlers/schema-claude-code';
import { SCHEMA_SYSTEM_PROMPT, parseSchemaText } from '../tools/handlers/schema-prompt';
import { schemaProvider } from '../tools/handlers/schema-provider';

const SCHEMA = {
  components: [
    { ref: 'R1', value: '330R', footprint: 'Resistor_SMD:R_0603_1608Metric', symbol: 'Device:R' },
    { ref: 'D1', value: 'LED', footprint: 'LED_SMD:LED_0603_1608Metric', symbol: 'Device:LED' },
  ],
  nets: ['VCC', 'GND', 'LED_A'],
  connections: [{ name: 'LED_A', pins: [{ ref: 'R1', pin: 2 }, { ref: 'D1', pin: 2 }, { ref: 'X9', pin: 1 }] }],
};
const enveloppe = (result: unknown, extra: Record<string, unknown> = {}) =>
  JSON.stringify({ type: 'result', subtype: 'success', is_error: false, result, ...extra });

describe('le fournisseur de schéma', () => {
  it('est Haiku par défaut et sur toute valeur inconnue (échec fermé)', () => {
    expect(schemaProvider({})).toBe('haiku');
    expect(schemaProvider({ CIRQIX_SCHEMA_PROVIDER: 'claude_code' })).toBe('haiku');
    expect(schemaProvider({ CIRQIX_SCHEMA_PROVIDER: 'oui' })).toBe('haiku');
  });
  it('est Claude Code sur la valeur exacte', () => {
    expect(schemaProvider({ CIRQIX_SCHEMA_PROVIDER: 'claude-code' })).toBe('claude-code');
    expect(schemaProvider({ CIRQIX_SCHEMA_PROVIDER: ' Claude-Code ' })).toBe('claude-code');
  });
});

describe('le contrat partagé', () => {
  it('le prompt système est unique et exige du JSON nu', () => {
    expect(SCHEMA_SYSTEM_PROMPT).toContain('Return ONLY valid JSON');
  });
  it('parseSchemaText retire les clôtures markdown et les broches impossibles', () => {
    const s = parseSchemaText('```json\n' + JSON.stringify(SCHEMA) + '\n```');
    expect(s).not.toBeNull();
    // X9 n existe pas : sa broche est retirée, la connexion survit.
    expect(s!.connections![0]!.pins.map((p) => p.ref)).toEqual(['R1', 'D1']);
  });
  it('parseSchemaText rend null sur un schéma sans composant ou illisible', () => {
    expect(parseSchemaText('{"components":[],"nets":["GND"]}')).toBeNull();
    expect(parseSchemaText('pas du json')).toBeNull();
  });
});

describe('generateSchemaWithClaudeCode', () => {
  it('passe le contrat par STDIN, jamais en argument, et rend le schéma', async () => {
    const executer = vi.fn().mockResolvedValue({ stdout: enveloppe(JSON.stringify(SCHEMA)), code: 0 });
    const s = await generateSchemaWithClaudeCode('une LED et sa résistance', { executer, bin: 'claude' });
    expect(s?.components).toHaveLength(2);
    const [bin, args, stdin] = executer.mock.calls[0]!;
    expect(bin).toBe('claude');
    expect(args).toEqual(['-p', '--output-format', 'json']);
    expect(args.join(' ')).not.toContain('LED');
    expect(stdin).toContain(SCHEMA_SYSTEM_PROMPT);
    expect(stdin).toContain('Circuit: une LED et sa résistance');
  });
  it('transmet le modèle demandé', async () => {
    const executer = vi.fn().mockResolvedValue({ stdout: enveloppe(JSON.stringify(SCHEMA)), code: 0 });
    await generateSchemaWithClaudeCode('x', { executer, model: 'sonnet' });
    expect(executer.mock.calls[0]![1]).toEqual(['-p', '--output-format', 'json', '--model', 'sonnet']);
  });
  it('rend null — jamais un schéma fabriqué — sur une enveloppe en erreur, un texte illisible ou une panne', async () => {
    const erreur = vi.fn().mockResolvedValue({ stdout: enveloppe('x', { is_error: true }), code: 1 });
    expect(await generateSchemaWithClaudeCode('x', { executer: erreur })).toBeNull();
    const illisible = vi.fn().mockResolvedValue({ stdout: enveloppe('je ne sais pas'), code: 0 });
    expect(await generateSchemaWithClaudeCode('x', { executer: illisible })).toBeNull();
    const panne = vi.fn().mockRejectedValue(new Error('ENOENT'));
    expect(await generateSchemaWithClaudeCode('x', { executer: panne })).toBeNull();
  });
  it('accepte aussi une sortie nue (sans enveloppe)', () => {
    expect(texteDeLEnveloppe(JSON.stringify(SCHEMA))).toBe(JSON.stringify(SCHEMA));
    expect(texteDeLEnveloppe(enveloppe('abc'))).toBe('abc');
    expect(texteDeLEnveloppe('')).toBeNull();
  });
});
