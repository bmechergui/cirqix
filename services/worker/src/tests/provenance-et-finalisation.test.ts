import { describe, it, expect, vi } from 'vitest';

/**
 * Deux défauts du worker, trouvés le 2026-09-07 par le PREMIER run réel de la
 * chaîne du driver. Ni l'un ni l'autre n'était visible en test.
 *
 * ## 1. La provenance était une constante
 *
 * `createWorkerStore` écrivait `agent_mode: 'orchestrator'` en dur dans
 * `projects`, aux deux endroits qui y touchent. C'était exact tant que le worker
 * ne savait faire QUE l'orchestrateur ; depuis qu'il exécute aussi la chaîne du
 * driver, c'est devenu un mensonge exécutoire — `POST /api/jlcpcb/order`
 * autorise la commande sur `agent_mode = 'orchestrator'`, donc un board dont le
 * schéma a été écrit à la main devenait COMMANDABLE.
 *
 * Mesuré sur le premier run : `projet : PCB_LIVRÉ · provenance orchestrator`.
 *
 * ## 2. Les arguments de la RPC ne correspondaient pas à la fonction
 *
 * `finalize_pipeline_success` est déclarée `(uuid, uuid, integer, jsonb, text)`
 * depuis la migration 018 — `p_iteration_count`, et PAS de `p_status`. L'appel
 * envoyait `p_pcb_state, p_status` : Postgres ne trouvait aucune surcharge, et
 * TOUT run arrivé jusqu'à `done` échouait à la finalisation — sans débit.
 *
 * ⚠️ Invisible aux tests parce qu'ils remplacent le client Supabase par un faux
 * qui accepte n'importe quel objet d'arguments. **Un faux plus pauvre que le
 * vrai ne peut pas révéler un contrat rompu.** Cette garde compare donc les
 * NOMS des paramètres à ceux que la migration déclare.
 */

vi.hoisted(() => {
  process.env['LOG_LEVEL'] = 'silent';
});

import { createWorkerStore } from '../adapters.js';

/** Les paramètres exacts déclarés par la migration 018. */
const PARAMETRES_DE_LA_MIGRATION = [
  'p_user_id', 'p_project_id', 'p_iteration_count', 'p_pcb_state', 'p_agent_mode',
];

function faussSupabase() {
  const appels: { fn: string; args: Record<string, unknown> }[] = [];
  const majs: Record<string, unknown>[] = [];
  return {
    appels,
    majs,
    client: {
      rpc: (fn: string, args: Record<string, unknown>) => {
        appels.push({ fn, args });
        return Promise.resolve({ data: true, error: null });
      },
      from: () => ({
        update: (valeurs: Record<string, unknown>) => {
          majs.push(valeurs);
          return { eq: () => Promise.resolve({ error: null }) };
        },
      }),
      storage: { from: () => ({}) },
    } as never,
  };
}

const ETAT = { projectId: 'p', status: 'PCB_LIVRÉ', iteration: 3 } as never;

describe('provenance du board', () => {
  it('écrit la provenance DU RUN, pas une constante', async () => {
    const f = faussSupabase();
    const store = createWorkerStore(f.client, 'u1', 'p1', 'driver');

    await store.persistProgress('ROUTING_DONE' as never, ETAT);

    expect(f.majs[0]?.['agent_mode']).toBe('driver');
    // La régression exacte qu'on interdit : un board du driver estampillé
    // `orchestrator` passerait le gate JLCPCB.
    expect(f.majs[0]?.['agent_mode']).not.toBe('orchestrator');
  });

  it('transmet la même provenance à la finalisation', async () => {
    const f = faussSupabase();
    const store = createWorkerStore(f.client, 'u1', 'p1', 'driver');

    await store.finalizeSuccess('PCB_LIVRÉ' as never, ETAT);

    expect(f.appels[0]?.args['p_agent_mode']).toBe('driver');
  });

  it('laisse passer `orchestrator` quand c est bien lui', async () => {
    const f = faussSupabase();
    const store = createWorkerStore(f.client, 'u1', 'p1', 'orchestrator');
    await store.persistProgress('DRC_CLEAN' as never, ETAT);
    expect(f.majs[0]?.['agent_mode']).toBe('orchestrator');
  });
});

describe('appel de finalize_pipeline_success', () => {
  it('emploie EXACTEMENT les paramètres déclarés par la migration 018', async () => {
    const f = faussSupabase();
    const store = createWorkerStore(f.client, 'u1', 'p1', 'orchestrator');

    await store.finalizeSuccess('PCB_LIVRÉ' as never, ETAT);

    expect(f.appels[0]?.fn).toBe('finalize_pipeline_success');
    expect(Object.keys(f.appels[0]?.args ?? {}).sort())
      .toEqual([...PARAMETRES_DE_LA_MIGRATION].sort());
  });

  it('n envoie PAS `p_status` — le paramètre qui n a jamais existé', async () => {
    const f = faussSupabase();
    const store = createWorkerStore(f.client, 'u1', 'p1', 'orchestrator');
    await store.finalizeSuccess('PCB_LIVRÉ' as never, ETAT);
    expect(f.appels[0]?.args).not.toHaveProperty('p_status');
  });

  it('envoie l itération, que la garde `stale_iteration` exige', async () => {
    const f = faussSupabase();
    const store = createWorkerStore(f.client, 'u1', 'p1', 'orchestrator');
    await store.finalizeSuccess('PCB_LIVRÉ' as never, ETAT);
    expect(f.appels[0]?.args['p_iteration_count']).toBe(3);
  });

  it('publie le statut DANS l état, puisque la fonction le lit là', async () => {
    // `finalize_pipeline_success` fait `v_final_status := p_pcb_state ->> 'status'`.
    const f = faussSupabase();
    const store = createWorkerStore(f.client, 'u1', 'p1', 'orchestrator');
    await store.finalizeSuccess('DRC_CLEAN' as never, ETAT);
    const etat = f.appels[0]?.args['p_pcb_state'] as Record<string, unknown>;
    expect(etat['status']).toBe('DRC_CLEAN');
  });
});
