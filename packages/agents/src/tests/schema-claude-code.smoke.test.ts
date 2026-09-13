import { describe, it, expect } from 'vitest';

/**
 * Appel RÉEL de `claude -p` — opt-in, coûte un appel d'abonnement :
 *   CIRQIX_SMOKE_CLAUDE=1 npx vitest run src/tests/schema-claude-code.smoke.test.ts
 * Sans le drapeau, le test est ignoré. C'est la seule preuve que le pont tient
 * hors des faux : un exécuteur mocké ne voit ni le `.cmd` Windows, ni
 * l'enveloppe JSON réelle, ni le délai.
 */
const actif = process.env['CIRQIX_SMOKE_CLAUDE'] === '1';

describe.skipIf(!actif)('claude -p écrit un schéma réel', () => {
  it('rend un schéma lisible pour un diviseur de tension', async () => {
    const { generateSchemaWithClaudeCode } = await import('../tools/handlers/schema-claude-code');
    const t0 = Date.now();
    const s = await generateSchemaWithClaudeCode(
      'Un diviseur de tension 10k/10k sur 5 V avec un condensateur de 100 nF en sortie et un connecteur 3 broches (VIN, VOUT, GND).',
      { timeoutMs: 4 * 60_000 },
    );
    // eslint-disable-next-line no-console
    console.log('smoke claude-code :', Math.round((Date.now() - t0) / 1000), 's,', s?.components.length, 'composants,', s?.nets.length, 'nets,', s?.connections?.length, 'connexions');
    expect(s).not.toBeNull();
    expect(s!.components.length).toBeGreaterThanOrEqual(3);
    expect(s!.nets.length).toBeGreaterThanOrEqual(3);
  }, 5 * 60_000);
});
