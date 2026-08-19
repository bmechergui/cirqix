import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { INVOCATION_BUDGET_MS } from '@cirqix/agents';

/**
 * `maxDuration` (route) et `INVOCATION_BUDGET_MS` (packages/agents) décrivent la
 * MÊME limite : le plafond d'horloge murale que la plateforme applique à
 * l'invocation qui tient le flux SSE.
 *
 * Les laisser diverger recrée exactement le bug corrigé ici : `ROUTING_TIMEOUT_MS`
 * valait 330 s pour un `maxDuration` de 300 s, si bien que le garde-fou
 * `AbortSignal.timeout()` du routage ne pouvait JAMAIS se déclencher — la
 * plateforme tuait la fonction 30 s plus tôt, sans message d'erreur et sans que
 * le board routé ne revienne jamais.
 *
 * La valeur est lue dans la SOURCE de la route plutôt qu'importée : `route.ts`
 * tire tout Next.js et la chaîne Supabase derrière lui, ce qui ferait de cette
 * garde un test d'intégration fragile pour vérifier une seule constante.
 */
describe('budget d invocation — route et agents restent alignés', () => {
  const routeSource = readFileSync(
    join(__dirname, '..', 'app', 'api', 'agent', 'route.ts'),
    'utf-8',
  );

  it('la route déclare bien un maxDuration', () => {
    expect(routeSource).toMatch(/export const maxDuration\s*=\s*\d+/);
  });

  it('maxDuration vaut exactement INVOCATION_BUDGET_MS', () => {
    const match = routeSource.match(/export const maxDuration\s*=\s*(\d+)/);
    expect(match, 'maxDuration introuvable dans route.ts').not.toBeNull();

    const maxDurationSeconds = Number(match![1]);
    expect(maxDurationSeconds * 1000).toBe(INVOCATION_BUDGET_MS);
  });
});
