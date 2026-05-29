import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

/**
 * Stub the Anthropic SDK so NO real (paid) network call is ever possible from
 * this suite — regardless of env vars or test execution order. The client is a
 * module-level singleton in tools.ts, so a prior test could otherwise leave a
 * real client cached. `messages.create` always rejects, which forces both Haiku
 * schema paths (JSON + circuit_synth code) to return null — the exact
 * "both AI paths down" condition under test.
 */
vi.mock('@anthropic-ai/sdk', () => ({
  default: class {
    messages = {
      create: vi.fn().mockRejectedValue(new Error('mocked SDK — no network in tests')),
    };
  },
}));

import { executeToolStub } from '../tools';

/**
 * Regression test — root cause of the recurring "n'importe quoi le schéma" bug.
 *
 * When BOTH AI schema-generation paths are unavailable:
 *   - Path A (circuit_synth Python via Docker) → skipped when KICAD_SERVICE_URL is absent
 *   - Path B (Haiku JSON)                      → null when the Anthropic call fails
 *
 * call_agent_schema MUST surface a real, diagnostic error instead of fabricating
 * a hardcoded schema unrelated to the user's request (e.g. an ATmega328P for a
 * temperature sensor, or a generic LED board for a voltage divider). A
 * plausible-looking but wrong board wastes the user's credits on a pointless
 * re-iteration.
 */
describe('call_agent_schema — never fabricate a hardcoded schema', () => {
  const saved: Record<string, string | undefined> = {};
  const MANAGED = ['ANTHROPIC_API_KEY', 'KICAD_SERVICE_URL'] as const;

  beforeEach(() => {
    for (const k of MANAGED) saved[k] = process.env[k];
    // A key IS set so the client path is exercised — but the mocked SDK rejects,
    // proving that even with a key present, an API failure yields an error and
    // never a fabricated schema. Docker stays unset so Path A is skipped (no fetch).
    process.env['ANTHROPIC_API_KEY'] = 'sk-test-fake-key';
    delete process.env['KICAD_SERVICE_URL'];
  });

  afterEach(() => {
    for (const k of MANAGED) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  });

  it('returns an error (not a hardcoded ATmega328P) for a "medium" circuit when both AI paths are down', async () => {
    const result = await executeToolStub(
      'call_agent_schema',
      { user_description: 'capteur de température I2C avec affichage OLED', complexity: 'medium' },
      'test-medium'
    );

    expect(result['status']).toBe('error');
    expect(typeof result['error']).toBe('string');
    // The fabricated fallback used to inject an ATmega328P — it must never leak.
    expect(JSON.stringify(result)).not.toContain('ATmega');
    expect(result['components']).toBeUndefined();
  });

  it('returns an error (not a generic LED board) for a "simple" circuit when both AI paths are down', async () => {
    const result = await executeToolStub(
      'call_agent_schema',
      { user_description: 'pont diviseur de tension 12V vers 3.3V', complexity: 'simple' },
      'test-simple'
    );

    expect(result['status']).toBe('error');
    expect(result['components']).toBeUndefined();
  });

  it('returns an error when complexity is omitted (defaults must not fabricate either)', async () => {
    const result = await executeToolStub(
      'call_agent_schema',
      { user_description: 'amplificateur audio classe D' },
      'test-default'
    );

    expect(result['status']).toBe('error');
    expect(result['components']).toBeUndefined();
  });

  it('still returns an error for "complex" circuits (regression — already fixed in a prior session)', async () => {
    const result = await executeToolStub(
      'call_agent_schema',
      { user_description: 'ESP32 IoT board with sensors and power management', complexity: 'complex' },
      'test-complex'
    );

    expect(result['status']).toBe('error');
    expect(result['components']).toBeUndefined();
  });
});
