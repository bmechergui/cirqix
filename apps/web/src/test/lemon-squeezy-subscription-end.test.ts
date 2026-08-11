import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createHmac } from 'node:crypto';

/**
 * Fin de vie d'un abonnement (PLAN.md §4.4).
 *
 * Le webhook traitait la souscription et le renouvellement, jamais la fin : un
 * abonné qui résiliait gardait `plan='pro'` indéfiniment. Aucun crédit n'était
 * perdu — ils viennent des renouvellements, qui cessent — mais le plan restera
 * la source des droits (2/4/8 couches) en Phase 5, et il mentait.
 *
 * La distinction qui structure ces tests : `subscription_cancelled` signifie
 * « ne pas renouveler », l'accès reste payé jusqu'à la fin de période ;
 * `subscription_expired` signifie « c'est fini ». Seul le second déclasse.
 */

const WEBHOOK_SECRET = 'secret-de-test';

const rpcMock = vi.hoisted(() => vi.fn());
vi.mock('@/shared/lib/supabase-server', () => ({
  createAdminClient: () => ({ rpc: rpcMock }),
}));

import { POST } from '@/app/api/webhooks/lemon-squeezy/route';
import { signCheckoutUserId } from '@/shared/lib/checkout-signature';

const USER_ID = '11111111-1111-4111-8111-111111111111';

function makeRequest(eventName: string, overrides: Record<string, unknown> = {}) {
  const body = JSON.stringify({
    meta: { event_name: eventName },
    data: {
      id: 'sub-42',
      attributes: {
        product_id: 'prod-pro',
        custom_data: {
          user_id: USER_ID,
          user_sig: signCheckoutUserId(USER_ID),
        },
        ...overrides,
      },
    },
  });
  const signature = createHmac('sha256', WEBHOOK_SECRET).update(body).digest('hex');
  return new Request('http://localhost:3333/api/webhooks/lemon-squeezy', {
    method: 'POST',
    headers: { 'x-signature': signature, 'content-type': 'application/json' },
    body,
  }) as never;
}

beforeEach(() => {
  vi.clearAllMocks();
  process.env.LEMON_SQUEEZY_WEBHOOK_SECRET = WEBHOOK_SECRET;
  rpcMock.mockResolvedValue({ data: true, error: null });
});

describe('webhook Lemon Squeezy — fin d\'abonnement', () => {
  it('ramène le plan à free quand l\'abonnement expire', async () => {
    const res = await POST(makeRequest('subscription_expired'));

    expect(res.status).toBe(200);
    expect(rpcMock).toHaveBeenCalledWith(
      'expire_subscription_plan',
      expect.objectContaining({ p_user_id: USER_ID, p_event_name: 'subscription_expired' }),
    );
  });

  it('ne déclasse PAS une résiliation dont la période court encore', async () => {
    // `subscription_cancelled` = « ne pas renouveler ». L'accès est payé
    // jusqu'à `ends_at` ; déclasser ici retirerait un droit acquis.
    // Lemon Squeezy enverra `subscription_expired` le moment venu.
    const dansUnMois = new Date(Date.now() + 30 * 86_400_000).toISOString();
    const res = await POST(makeRequest('subscription_cancelled', { ends_at: dansUnMois }));

    expect(res.status).toBe(200);
    expect(rpcMock).not.toHaveBeenCalled();
  });

  it('déclasse une résiliation immédiate, sans attendre un expired hypothétique', async () => {
    // Filet contre une hypothèse invérifiable depuis le code : on ne sait pas
    // avec certitude qu'une résiliation IMMÉDIATE (« cancel now » côté Lemon
    // Squeezy) est suivie d'un `subscription_expired` distinct. Si elle ne
    // l'est pas, l'abonnement serait terminé et le compte resterait « Pro » —
    // exactement le défaut corrigé ici, par un autre chemin.
    //
    // `ends_at` déjà passé signifie que l'accès est fini : on déclasse, sans
    // rien retirer de payé.
    const hier = new Date(Date.now() - 86_400_000).toISOString();
    const res = await POST(makeRequest('subscription_cancelled', { ends_at: hier }));

    expect(res.status).toBe(200);
    expect(rpcMock).toHaveBeenCalledWith(
      'expire_subscription_plan',
      expect.objectContaining({ p_user_id: USER_ID }),
    );
  });

  it("traite une résiliation sans date de fin comme immédiate", async () => {
    // Pas de `ends_at` : rien ne prouve qu'il reste de l'accès payé, et aucun
    // événement ultérieur n'est garanti. Le choix prudent côté facturation est
    // de déclasser — un utilisateur lésé le signale, un accès gratuit
    // indéfini ne se signale jamais.
    const res = await POST(makeRequest('subscription_cancelled'));

    expect(res.status).toBe(200);
    expect(rpcMock).toHaveBeenCalled();
  });

  it('exige la signature de checkout — sinon on déclasse le compte d\'autrui', async () => {
    // Le HMAC prouve que le message vient de Lemon Squeezy, pas que `user_id`
    // désigne le payeur : ce champ voyage dans une URL que l'acheteur édite.
    // Sans cette garde, il suffirait de mettre l'identifiant d'un tiers dans
    // son propre checkout, puis de résilier, pour le déclasser.
    const res = await POST(
      makeRequest('subscription_expired', {
        custom_data: { user_id: USER_ID, user_sig: 'deadbeef' },
      }),
    );

    expect(res.status).toBe(400);
    expect(rpcMock).not.toHaveBeenCalled();
  });

  it('transmet une clé d\'idempotence', async () => {
    // Lemon Squeezy retente jusqu'au 2xx. Le déclassement est idempotent par
    // nature, mais le marqueur garde la trace auditable de l'événement.
    await POST(makeRequest('subscription_expired'));

    const call = rpcMock.mock.calls[0];
    expect(call).toBeDefined();
    const args = call?.[1] as Record<string, unknown>;
    expect(args.p_event_key).toBe('subscription_expired:sub-42');
  });

  it('répond 422, pas 500, sur un refus définitif', async () => {
    // Un 500 ferait boucler le webhook indéfiniment sur une erreur qui ne se
    // résoudra jamais — même règle que le crédit.
    rpcMock.mockResolvedValue({ data: null, error: { code: '22023', message: 'unknown_user' } });

    const res = await POST(makeRequest('subscription_expired'));

    expect(res.status).toBe(422);
  });

  it('répond 500 sur une panne transitoire, pour que Lemon Squeezy retente', async () => {
    rpcMock.mockResolvedValue({ data: null, error: { code: '08006', message: 'connection lost' } });

    const res = await POST(makeRequest('subscription_expired'));

    expect(res.status).toBe(500);
  });
});
