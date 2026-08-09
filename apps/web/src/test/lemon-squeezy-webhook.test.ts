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
  processedEvents: Set<string>;
  balance: number;
  plan: string;
}

// Stub de contrat route → RPC : il reproduit les résultats documentés de
// credit_webhook_event pour tester le comportement HTTP. Il ne constitue pas
// une preuve du rollback PostgreSQL réel, qui exige un test SQL d’intégration.
function makeClient(opts: {
  rpcError?: { message: string };
  state?: MockState;
} = {}) {
  const state = opts.state ?? {
    rpcCalls: [],
    processedEvents: new Set<string>(),
    balance: 0,
    plan: 'free',
  };
  const client = {
    rpc: async (fn: string, args: Record<string, unknown>) => {
      state.rpcCalls.push({ fn, args });
      if (fn !== 'credit_webhook_event') {
        throw new Error(`unexpected RPC ${fn}`);
      }
      if (opts.rpcError) {
        return { data: null, error: opts.rpcError };
      }
      const eventKey = String(args.p_event_key);
      if (state.processedEvents.has(eventKey)) {
        return { data: false, error: null };
      }
      state.processedEvents.add(eventKey);
      state.balance += Number(args.p_amount);
      if (typeof args.p_plan === 'string') {
        state.plan = args.p_plan;
      }
      return { data: true, error: null };
    },
    from: (table: string) => {
      throw new Error(`unexpected table access ${table}`);
    },
  };
  return { client, state };
}

function newState(balance = 0): MockState {
  return {
    rpcCalls: [],
    processedEvents: new Set<string>(),
    balance,
    plan: 'free',
  };
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

  it('refuse aussi un HMAC incorrect de longueur SHA-256 valide', async () => {
    const body = topupPayload();
    const wrongSignature = createHmac('sha256', 'wrong-secret').update(body).digest('hex');
    const { response, state } = await post(body, {}, wrongSignature);

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
  });

  it('acquitte un variant de top-up inconnu sans créditer', async () => {
    const body = JSON.stringify({
      meta: { event_name: 'order_created' },
      data: {
        id: 'ord-unknown',
        attributes: {
          custom_data: { user_id: 'u1' },
          first_order_item: { variant_id: 'var-unknown' },
        },
      },
    });
    const { response, json, state } = await post(body);

    expect(response.status).toBe(200);
    expect(json.received).toBe(true);
    expect(state.rpcCalls).toHaveLength(0);
  });

  it('acquitte un produit d’abonnement inconnu sans créditer', async () => {
    const body = JSON.stringify({
      meta: { event_name: 'subscription_renewed' },
      data: {
        id: 'sub-unknown',
        attributes: {
          custom_data: { user_id: 'u1' },
          product_id: 'prod-unknown',
        },
      },
    });
    const { response, json, state } = await post(body);

    expect(response.status).toBe(200);
    expect(json.received).toBe(true);
    expect(state.rpcCalls).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Fail-closed — secret manquant ou transaction RPC impossible → 500
// ---------------------------------------------------------------------------

describe('fail-closed', () => {
  it('refuse (500) si LEMON_SQUEEZY_WEBHOOK_SECRET est absent — HMAC à clé vide forgeable', async () => {
    delete process.env.LEMON_SQUEEZY_WEBHOOK_SECRET;
    const { response, state } = await post(topupPayload());

    expect(response.status).toBe(500);
    expect(state.rpcCalls).toHaveLength(0);
  });

  it.each([
    ['order_created', topupPayload('ord-rpc-error'), 20],
    ['subscription_renewed', subscriptionPayload('subscription_renewed'), 100],
  ])('une erreur RPC sur %s renvoie 500 sans prétendre avoir reçu l’événement', async (_name, body, amount) => {
    const state = newState(40);

    // L’ancien test vérifiait releaseEvent(). La RPC transactionnelle remplace
    // cette mécanique. Ce test vérifie le contrat applicatif et le retry ; le
    // rollback PostgreSQL lui-même relève d’un test SQL d’intégration.
    const { response, json } = await post(body, {
      rpcError: { message: 'transaction failed' },
      state,
    });

    expect(response.status).toBe(500);
    expect(json.received).toBeUndefined();
    expect(json.duplicate).toBeUndefined();
    expect(state.processedEvents.size).toBe(0);
    expect(state.balance).toBe(40);
    expect(state.rpcCalls).toHaveLength(1);

    const retry = await post(body, { state });
    expect(retry.response.status).toBe(200);
    expect(retry.json.duplicate).toBeUndefined();
    expect(state.processedEvents.size).toBe(1);
    expect(state.balance).toBe(40 + Number(amount));
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
      {
        fn: 'credit_webhook_event',
        args: {
          p_event_key: 'order_created:ord-1',
          p_event_name: 'order_created',
          p_user_id: 'u1',
          p_amount: 20,
          p_action: 'topup',
        },
      },
    ]);
    expect(state.balance).toBe(20);
  });

  it('subscription_renewed conserve les recharges et ajoute l’allocation mensuelle', async () => {
    const state = newState(140);
    const { response } = await post(
      subscriptionPayload('subscription_renewed'),
      { state },
    );

    expect(response.status).toBe(200);
    expect(state.balance).toBe(240);
    expect(state.plan).toBe('pro');
    expect(state.rpcCalls[0]?.args).toMatchObject({
      p_amount: 100,
      p_action: 'subscription_renewed',
      p_plan: 'pro',
    });
  });

  it.each(['subscription_created', 'subscription_renewed'])(
    '%s transmet le plan et l’allocation dans la même RPC',
    async (eventName) => {
      const { response, state } = await post(subscriptionPayload(eventName));

      expect(response.status).toBe(200);
      expect(state.rpcCalls).toEqual([
        {
          fn: 'credit_webhook_event',
          args: {
            p_event_key: expect.stringMatching(`^${eventName}:sub-1`),
            p_event_name: eventName,
            p_user_id: 'u1',
            p_amount: 100,
            p_action: eventName,
            p_plan: 'pro',
          },
        },
      ]);
      expect(state.plan).toBe('pro');
      expect(state.balance).toBe(100);
    },
  );
});

// ---------------------------------------------------------------------------
// Idempotence — un retry ne doit jamais créditer deux fois
// ---------------------------------------------------------------------------

describe('idempotence', () => {
  it('un order_created rejoué (même order id) ne crédite pas deux fois', async () => {
    const state = newState();
    const first = await post(topupPayload('ord-42'), { state });
    expect(first.response.status).toBe(200);
    expect(state.balance).toBe(20);

    const second = await post(topupPayload('ord-42'), { state });

    expect(second.response.status).toBe(200);
    expect(second.json.duplicate).toBe(true);
    expect(state.rpcCalls).toHaveLength(2);
    expect(state.balance).toBe(20);
    expect(state.processedEvents.size).toBe(1);
  });

  it('la clé d’idempotence transmise porte l’id de commande', async () => {
    const { state } = await post(topupPayload('ord-42'));

    expect(state.rpcCalls[0]?.args.p_event_key).toBe('order_created:ord-42');
  });

  it('un subscription_renewed rejoué à l’identique est dédupliqué', async () => {
    const state = newState(40);
    await post(
      subscriptionPayload('subscription_renewed', '2026-08-27'),
      { state },
    );
    expect(state.balance).toBe(140);

    const second = await post(
      subscriptionPayload('subscription_renewed', '2026-08-27'),
      { state },
    );

    expect(second.response.status).toBe(200);
    expect(second.json.duplicate).toBe(true);
    expect(state.balance).toBe(140);
    expect(state.processedEvents.size).toBe(1);
  });

  it('deux renouvellements DISTINCTS (corps différent) créditent tous les deux', async () => {
    const state = newState();
    await post(
      subscriptionPayload('subscription_renewed', '2026-08-27'),
      { state },
    );
    await post(
      subscriptionPayload('subscription_renewed', '2026-09-27'),
      { state },
    );

    const firstKey = state.rpcCalls[0]?.args.p_event_key;
    const secondKey = state.rpcCalls[1]?.args.p_event_key;
    expect(firstKey).not.toBe(secondKey);
    expect(state.processedEvents.size).toBe(2);
    expect(state.balance).toBe(200);
  });
});
