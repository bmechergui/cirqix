import { describe, it, expect, beforeEach, vi } from 'vitest';
import { createHmac } from 'crypto';

/**
 * POST /api/webhooks/lemon-squeezy — chemin de paiement.
 *
 * PLAN.md §4.4 action 4 : « Idempotence : vérifier transaction_id avant
 * insert ». Lemon Squeezy retente les webhooks tant qu'il n'a pas de 2xx :
 * sans déduplication, un `order_created` rejoué crédite deux fois le même
 * pack. La clé d'idempotence est `event_name:data.id` (`:sha256(body)[:16]`
 * en plus pour subscription_renewed, dont data.id est constant d'un
 * renouvellement à l'autre).
 */

const supabaseMock = vi.hoisted(() => ({ createAdminClient: vi.fn() }));
vi.mock('@/shared/lib/supabase-server', () => supabaseMock);

import { POST } from '@/app/api/webhooks/lemon-squeezy/route';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SECRET = 'test-secret';

function sign(rawBody: string): string {
  return createHmac('sha256', SECRET).update(rawBody).digest('hex');
}

function makeRequest(rawBody: string, signature: string) {
  return {
    text: async () => rawBody,
    headers: { get: (name: string) => (name === 'x-signature' ? signature : null) },
  } as never;
}

interface MockState {
  rpcCalls: Array<{ fn: string; args: Record<string, unknown> }>;
  creditUpdates: Array<Record<string, unknown>>;
  markersInserted: string[];
  markersDeleted: string[];
  balance: number;
}

function makeClient(opts: {
  insertConflict?: boolean;
  insertError?: { code: string; message: string };
  rpcFails?: boolean;
  initialBalance?: number;
  creditsRowsAffected?: number;
  markers?: Set<string>;
} = {}) {
  const state: MockState = {
    rpcCalls: [],
    creditUpdates: [],
    markersInserted: [],
    markersDeleted: [],
    balance: opts.initialBalance ?? 0,
  };
  const client = {
    rpc: async (fn: string, args: Record<string, unknown>) => {
      state.rpcCalls.push({ fn, args });
      if (opts.rpcFails) {
        return { error: { message: 'db down' } };
      }
      if (fn === 'add_credits') {
        state.balance += Number(args.p_amount);
      }
      return { error: null };
    },
    from: (table: string) => {
      if (table === 'processed_webhook_events') {
        return {
          insert: (row: { event_key: string }) => {
            if (opts.insertConflict || opts.markers?.has(row.event_key)) {
              return { error: { code: '23505', message: 'duplicate key' } };
            }
            if (opts.insertError) {
              return { error: opts.insertError };
            }
            opts.markers?.add(row.event_key);
            state.markersInserted.push(row.event_key);
            return { error: null };
          },
          delete: () => ({
            eq: async (_col: string, key: string) => {
              opts.markers?.delete(key);
              state.markersDeleted.push(key);
              return { error: null };
            },
          }),
        };
      }
      if (table === 'credits') {
        return {
          update: (payload: Record<string, unknown>) => {
            state.creditUpdates.push(payload);
            return {
              eq: async () => ({
                error: null,
                count: opts.creditsRowsAffected ?? 1,
              }),
            };
          },
        };
      }
      throw new Error(`unexpected table ${table}`);
    },
  };
  return { client, state };
}

function topupPayload(orderId = 'ord-1') {
  return JSON.stringify({
    meta: { event_name: 'order_created' },
    data: {
      id: orderId,
      attributes: {
        custom_data: { user_id: 'u1' },
        first_order_item: { variant_id: 'var-20' },
      },
    },
  });
}

function subscriptionPayload(eventName: string, renewsAt = '2026-08-27') {
  return JSON.stringify({
    meta: { event_name: eventName },
    data: {
      id: 'sub-1',
      attributes: {
        custom_data: { user_id: 'u1' },
        product_id: 'prod-pro',
        renews_at: renewsAt,
      },
    },
  });
}

async function post(
  rawBody: string,
  clientOpts: Parameters<typeof makeClient>[0] = {},
  signature?: string,
) {
  const { client, state } = makeClient(clientOpts);
  supabaseMock.createAdminClient.mockReturnValue(client);
  const response = await POST(makeRequest(rawBody, signature ?? sign(rawBody)));
  return { response, json: await response.json(), state };
}

beforeEach(() => {
  supabaseMock.createAdminClient.mockReset();
  process.env.LEMON_SQUEEZY_WEBHOOK_SECRET = SECRET;
  process.env.LS_VARIANT_TOPUP_20 = 'var-20';
  process.env.LS_VARIANT_TOPUP_100 = 'var-100';
  process.env.LS_VARIANT_TOPUP_300 = 'var-300';
  process.env.LS_PRODUCT_PRO = 'prod-pro';
  process.env.LS_PRODUCT_PRO_MAX = 'prod-promax';
});

// ---------------------------------------------------------------------------
// Gardes existantes (signature, parsing, custom_data)
// ---------------------------------------------------------------------------

describe('gardes existantes', () => {
  it('refuse une signature invalide sans toucher la base', async () => {
    const { response, state } = await post(topupPayload(), {}, 'deadbeef');

    expect(response.status).toBe(401);
    expect(state.rpcCalls).toHaveLength(0);
  });

  it('refuse un JSON invalide', async () => {
    const { response } = await post('not-json{{{');

    expect(response.status).toBe(400);
  });

  it('refuse un payload sans user_id', async () => {
    const body = JSON.stringify({
      meta: { event_name: 'order_created' },
      data: { id: 'ord-1', attributes: { first_order_item: { variant_id: 'var-20' } } },
    });
    const { response } = await post(body);

    expect(response.status).toBe(400);
  });

  it('acquitte les événements non traités sans écrire', async () => {
    const body = JSON.stringify({
      meta: { event_name: 'subscription_payment_failed' },
      data: { id: 'sub-1', attributes: { custom_data: { user_id: 'u1' } } },
    });
    const { response, state } = await post(body);

    expect(response.status).toBe(200);
    expect(state.rpcCalls).toHaveLength(0);
    expect(state.creditUpdates).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Fail-closed — secret manquant ou marker impossible → 500, aucun crédit
// ---------------------------------------------------------------------------

describe('fail-closed', () => {
  it('refuse (500) si LEMON_SQUEEZY_WEBHOOK_SECRET est absent — HMAC à clé vide forgeable', async () => {
    delete process.env.LEMON_SQUEEZY_WEBHOOK_SECRET;
    const { response, state } = await post(topupPayload());

    expect(response.status).toBe(500);
    expect(state.rpcCalls).toHaveLength(0);
    expect(state.creditUpdates).toHaveLength(0);
    expect(state.markersInserted).toHaveLength(0);
  });

  it('échoue (500) sans créditer si l’insert du marker échoue (code ≠ 23505)', async () => {
    // Ex. table processed_webhook_events absente (migration 008 non appliquée)
    // : traiter sans marker laisserait un retry LS créditer une seconde fois.
    const { response, json, state } = await post(topupPayload('ord-77'), {
      insertError: { code: '42P01', message: 'relation "processed_webhook_events" does not exist' },
    });

    expect(response.status).toBe(500);
    expect(json.duplicate).toBeUndefined();
    expect(state.rpcCalls).toHaveLength(0);
    expect(state.markersInserted).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Crédits nominaux
// ---------------------------------------------------------------------------

describe('crédit nominal', () => {
  it('order_created top-up crédite le pack correspondant', async () => {
    const { response, state } = await post(topupPayload());

    expect(response.status).toBe(200);
    expect(state.rpcCalls).toEqual([
      { fn: 'add_credits', args: { p_user_id: 'u1', p_amount: 20, p_action: 'topup' } },
    ]);
  });

  it('subscription_renewed conserve les recharges et ajoute l’allocation mensuelle', async () => {
    const { response, state } = await post(
      subscriptionPayload('subscription_renewed'),
      { initialBalance: 140 },
    );

    expect(response.status).toBe(200);
    expect(state.balance).toBe(240);
    expect(state.rpcCalls).toEqual([
      {
        fn: 'add_credits',
        args: {
          p_user_id: 'u1',
          p_amount: 100,
          p_action: 'subscription_renewed',
        },
      },
    ]);
    expect(state.creditUpdates[0]).not.toHaveProperty('balance');
  });

  it.each(['subscription_created', 'subscription_renewed'])(
    '%s met à jour le plan',
    async (eventName) => {
      const { response, state } = await post(subscriptionPayload(eventName));

      expect(response.status).toBe(200);
      expect(state.creditUpdates).toHaveLength(1);
      expect(state.creditUpdates[0]).toMatchObject({ plan: 'pro' });
      expect(state.rpcCalls).toEqual([
        {
          fn: 'add_credits',
          args: {
            p_user_id: 'u1',
            p_amount: 100,
            p_action: eventName,
          },
        },
      ]);
    },
  );

  it('échoue et libère le marker si la ligne credits est absente', async () => {
    const { response, state } = await post(
      subscriptionPayload('subscription_renewed'),
      { creditsRowsAffected: 0 },
    );

    expect(response.status).toBe(500);
    expect(state.rpcCalls).toHaveLength(0);
    expect(state.markersDeleted).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// Idempotence — un retry ne doit jamais créditer deux fois
// ---------------------------------------------------------------------------

describe('idempotence', () => {
  it('un order_created rejoué (même order id) ne crédite pas deux fois', async () => {
    const markers = new Set<string>();
    const first = await post(topupPayload('ord-42'), { markers });
    expect(first.state.rpcCalls).toHaveLength(1);

    // Même événement renvoyé par LS : la table contient déjà la clé → conflit PK
    const second = await post(topupPayload('ord-42'), { markers });

    expect(second.response.status).toBe(200);
    expect(second.state.rpcCalls).toHaveLength(0);
    expect(second.json.duplicate).toBe(true);
  });

  it('la clé marker insérée porte l’id de commande', async () => {
    const { state } = await post(topupPayload('ord-42'));

    expect(state.markersInserted).toEqual(['order_created:ord-42']);
  });

  it('un subscription_renewed rejoué à l’identique est dédupliqué', async () => {
    const markers = new Set<string>();
    const first = await post(
      subscriptionPayload('subscription_renewed', '2026-08-27'),
      { initialBalance: 40, markers },
    );
    expect(first.state.rpcCalls).toHaveLength(1);
    expect(first.state.balance).toBe(140);

    const second = await post(
      subscriptionPayload('subscription_renewed', '2026-08-27'),
      { initialBalance: first.state.balance, markers },
    );

    expect(second.response.status).toBe(200);
    expect(second.state.rpcCalls).toHaveLength(0);
    expect(second.state.balance).toBe(140);
  });

  it('deux renouvellements DISTINCTS (corps différent) créditent tous les deux', async () => {
    const markers = new Set<string>();
    const aug = await post(
      subscriptionPayload('subscription_renewed', '2026-08-27'),
      { markers },
    );
    const sep = await post(
      subscriptionPayload('subscription_renewed', '2026-09-27'),
      { markers },
    );

    expect(aug.state.rpcCalls).toHaveLength(1);
    expect(sep.state.rpcCalls).toHaveLength(1);
    expect(aug.state.markersInserted[0]).not.toBe(sep.state.markersInserted[0]);
  });

  it('libère le marker si add_credits échoue pour un abonnement', async () => {
    const markers = new Set<string>();
    const { response, state } = await post(
      subscriptionPayload('subscription_renewed'),
      { rpcFails: true, markers },
    );

    expect(response.status).toBe(500);
    expect(state.markersDeleted).toHaveLength(1);
    expect(markers.size).toBe(0);
  });

  it('si le crédit échoue, le marker est libéré pour que le retry LS aboutisse', async () => {
    const { response, state } = await post(topupPayload('ord-99'), { rpcFails: true });

    expect(response.status).toBe(500);
    expect(state.markersInserted).toEqual(['order_created:ord-99']);
    expect(state.markersDeleted).toEqual(['order_created:ord-99']);
  });
});
