import { createHash, createHmac, timingSafeEqual } from 'crypto';
import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { logger } from '@cirqix/logger';
import { createAdminClient } from '@/shared/lib/supabase-server';
import { verifyCheckoutUserId } from '@/shared/lib/checkout-signature';

const log = logger.child({ module: 'ls-webhook' });

// Config lue à chaque requête (et non au chargement du module) pour rester
// testable et refléter les variables d'environnement réelles au moment de
// l'appel.

/** Map Lemon Squeezy variant ID → credits amount (one-time top-up packs) */
function topupPacks(): Record<string, number> {
  return {
    [process.env.LS_VARIANT_TOPUP_20  ?? 'unset']: 20,
    [process.env.LS_VARIANT_TOPUP_100 ?? 'unset']: 100,
    [process.env.LS_VARIANT_TOPUP_300 ?? 'unset']: 300,
  };
}

/** Map Lemon Squeezy product ID → plan + monthly credits */
function subscriptionPlans(): Record<string, { credits: number; plan: string }> {
  return {
    [process.env.LS_PRODUCT_PRO     ?? 'unset']: { credits: 100, plan: 'pro'     },
    [process.env.LS_PRODUCT_PRO_MAX ?? 'unset']: { credits: 300, plan: 'pro_max' },
  };
}

const lsPayloadSchema = z.object({
  meta: z.object({ event_name: z.string().min(1) }),
  data: z.object({
    id: z.union([z.string(), z.number()]).optional(),
    attributes: z.object({
      product_id: z.unknown().optional(),
      first_order_item: z.unknown().optional(),
      custom_data: z
        .object({ user_id: z.string().optional(), user_sig: z.string().optional() })
        .nullable()
        .optional(),
    }).passthrough(),
  }),
});

function safeJsonParse(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/**
 * Codes PostgreSQL que nos RPC lèvent pour un refus DÉFINITIF : montant
 * invalide, utilisateur sans ligne `credits`, événement mal formé
 * (`USING ERRCODE = '22023'` dans les migrations 010, 012 et 013).
 *
 * Les distinguer compte : Lemon Squeezy retente indéfiniment un 5xx. Répondre
 * 500 sur une erreur qui ne se résoudra jamais fait boucler le webhook sans fin,
 * sans que personne ne soit alerté.
 */
const PERMANENT_PG_CODES = new Set(['22023', '42501']);

function isPermanentRpcError(error: { code?: string } | null): boolean {
  return Boolean(error?.code && PERMANENT_PG_CODES.has(error.code));
}

/**
 * Marqueur d'idempotence, plan et crédit dans la MÊME transaction
 * (`credit_webhook_event`, migration 013). Auparavant le marqueur était posé
 * d'abord : si le process mourait entre les deux, le paiement était encaissé, le
 * marqueur en place, le crédit jamais posé — et le réessai classé « duplicate ».
 *
 * Les deux familles d'événements partageaient ce même squelette ; les factoriser
 * évite qu'un futur changement ne soit appliqué qu'à l'une des deux.
 */
async function creditOnce(
  supabase: AdminClient,
  userSig: string | undefined,
  args: Record<string, unknown> & { p_user_id: string },
): Promise<NextResponse> {
  return applyOnce(supabase, userSig, 'credit_webhook_event', args);
}

/**
 * Le squelette commun à tout événement qui MUTE le compte : vérifier que
 * l'identifiant est bien celui du payeur, appeler une RPC transactionnelle et
 * idempotente, puis traduire son erreur en code HTTP que Lemon Squeezy sait
 * interpréter.
 *
 * Extrait de `creditOnce` quand la fin d'abonnement est arrivée (§4.4) : elle
 * partage ces trois besoins mais ne crédite rien, et dupliquer le squelette
 * aurait garanti qu'un futur correctif ne soit appliqué qu'à l'une des deux
 * familles — la raison même pour laquelle crédit et abonnement avaient déjà été
 * factorisés.
 */
async function applyOnce(
  supabase: AdminClient,
  userSig: string | undefined,
  rpcName: string,
  args: Record<string, unknown> & { p_user_id: string },
): Promise<NextResponse> {
  // Le HMAC de la requête prouve que le message vient de Lemon Squeezy, PAS que
  // `p_user_id` est le compte qui a payé : ce champ voyage dans une URL de
  // checkout que l'acheteur peut modifier. Sans cette vérification, substituer
  // l'identifiant d'un autre compte y fait atterrir le crédit.
  //
  // Le contrôle est ici, et non à l'entrée de la route : un événement qu'on
  // n'exploite pas — `subscription_payment_failed`, un variant inconnu — ne
  // crédite rien et n'a donc pas à être refusé. Le rejeter ferait retenter Lemon
  // Squeezy sur des événements parfaitement légitimes.
  if (!verifyCheckoutUserId(args.p_user_id, userSig)) {
    log.error(
      { userId: args.p_user_id, eventName: args['p_event_name'] },
      'signature de checkout invalide — credit refuse',
    );
    return NextResponse.json({ error: 'Invalid checkout signature' }, { status: 400 });
  }

  const { data: applied, error } = await supabase.rpc(rpcName, args);

  if (error) {
    if (isPermanentRpcError(error)) {
      // 4xx : Lemon Squeezy ne retentera pas. Un refus définitif — montant
      // invalide, utilisateur sans ligne `credits` — ne se résout jamais par un
      // réessai, et répondre 500 ferait boucler le webhook indéfiniment.
      log.error({ err: error, code: error.code, rpcName, args }, 'evenement refuse definitivement');
      return NextResponse.json({ error: 'Rejected', reason: error.code }, { status: 422 });
    }
    log.error({ err: error, code: error.code, rpcName }, 'RPC webhook a echoue — retry attendu');
    return NextResponse.json({ error: 'DB error' }, { status: 500 });
  }

  if (applied === false) {
    return NextResponse.json({ received: true, duplicate: true });
  }
  return NextResponse.json({ received: true });
}

/**
 * Reste-t-il de l'accès payé après une résiliation ?
 *
 * `true` seulement si `ends_at` est une date FUTURE et exploitable. Une valeur
 * absente, nulle ou illisible rend `false` : rien ne prouve alors qu'il reste
 * de l'accès, et aucun événement ultérieur n'est garanti. Entre déclasser à
 * tort — visible, signalé, réparable — et laisser un accès payant indéfiniment
 * gratuit — invisible, jamais signalé — le second est le pire des deux.
 */
function hasAccessRemaining(endsAt: unknown): boolean {
  if (typeof endsAt !== 'string' || endsAt.trim() === '') return false;
  const ts = Date.parse(endsAt);
  return Number.isFinite(ts) && ts > Date.now();
}

function verifySignature(rawBody: string, signature: string, secret: string): boolean {
  const expected = createHmac('sha256', secret).update(rawBody).digest('hex');
  try {
    return timingSafeEqual(Buffer.from(signature, 'hex'), Buffer.from(expected, 'hex'));
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Idempotence (PLAN.md §4.4 action 4 — migrations 008 puis 013)
//
// Lemon Squeezy retente un webhook tant qu'il n'a pas de 2xx : sans
// déduplication, un order_created rejoué créditerait deux fois le même pack.
// Le marqueur et le crédit sont posés dans la MÊME transaction, par la RPC
// `credit_webhook_event` (migration 013) : un conflit de clé renvoie `false`
// (doublon → 200 sans traitement), et toute erreur annule les deux écritures
// ensemble, si bien que le retry repart proprement. Le marqueur ne peut donc
// plus survivre à un crédit manquant.
// ---------------------------------------------------------------------------

/**
 * `event_name:data.id` suffit pour order_created / subscription_created (ids
 * uniques par achat / abonnement). subscription_renewed réutilise le MÊME
 * data.id à chaque échéance → on y ajoute un hash du corps : un retry
 * renvoie le même corps (même clé, dédupliqué), un vrai renouvellement non.
 */
function buildEventKey(eventName: string, dataId: string, rawBody: string): string {
  const base = `${eventName}:${dataId}`;
  if (eventName === 'subscription_renewed') {
    const bodyHash = createHash('sha256').update(rawBody).digest('hex').slice(0, 16);
    return `${base}:${bodyHash}`;
  }
  return base;
}

type AdminClient = ReturnType<typeof createAdminClient>;

// `claimEvent` / `releaseEvent` ont été SUPPRIMÉES : le marquage d'idempotence et
// le crédit se font désormais dans une seule transaction, via la RPC
// `credit_webhook_event` (migration 013).
//
// Le couple pose-marqueur-puis-crédite laissait une fenêtre : si le process
// mourait entre les deux — coupure serverless, redéploiement, redémarrage de pod —
// le marqueur survivait sans le crédit, et le réessai de Lemon Squeezy était
// classé « duplicate ». Le paiement était encaissé, les crédits perdus
// définitivement. `releaseEvent` ne couvrait que l'échec *retourné* par la RPC,
// jamais la mort du process — et ignorait par-dessus le marché l'erreur de son
// propre DELETE.

export async function POST(req: NextRequest) {
  const rawBody = await req.text();
  const signature = req.headers.get('x-signature') ?? '';

  // Secret absent = configuration cassée : un HMAC à clé vide est forgeable
  // par n'importe qui. On échoue fort (500) plutôt que de vérifier avec ''.
  const secret = process.env.LEMON_SQUEEZY_WEBHOOK_SECRET;
  if (!secret) {
    log.error('LEMON_SQUEEZY_WEBHOOK_SECRET manquant');
    return NextResponse.json({ error: 'Webhook not configured' }, { status: 500 });
  }

  if (!verifySignature(rawBody, signature, secret)) {
    return NextResponse.json({ error: 'Invalid signature' }, { status: 401 });
  }

  // `as LsPayload` était un cast, pas une validation : un corps `{}` — JSON
  // valide mais sans `meta` — faisait planter la déstructuration en TypeError
  // non interceptée, hors du try/catch. Zod aux frontières, comme l'impose
  // `.claude/rules/code.md`.
  const parsed = lsPayloadSchema.safeParse(safeJsonParse(rawBody));
  if (!parsed.success) {
    return NextResponse.json({ error: 'Invalid payload' }, { status: 400 });
  }

  const { meta, data } = parsed.data;
  const eventName = meta.event_name;
  const attrs = data.attributes;

  const custom = attrs.custom_data ?? null;
  const userId = custom?.user_id;
  if (!userId) {
    return NextResponse.json({ error: 'Missing user_id in custom_data' }, { status: 400 });
  }

  const supabase = createAdminClient();
  const eventKey = buildEventKey(eventName, String(data.id ?? ''), rawBody);

  if (eventName === 'order_created') {
    const variantId = String(
      (attrs.first_order_item as { variant_id?: unknown } | null)?.variant_id ?? ''
    );
    const credits = topupPacks()[variantId];
    if (!credits) {
      return NextResponse.json({ received: true });
    }
    return creditOnce(supabase, custom?.user_sig, {
      p_event_key: eventKey,
      p_event_name: eventName,
      p_user_id: userId,
      p_amount: credits,
      p_action: 'topup',
    });
  }

  if (eventName === 'subscription_created' || eventName === 'subscription_renewed') {
    const productId = String(attrs.product_id ?? '');
    const sub = subscriptionPlans()[productId];
    if (!sub) {
      return NextResponse.json({ received: true });
    }
    return creditOnce(supabase, custom?.user_sig, {
      p_event_key: eventKey,
      p_event_name: eventName,
      p_user_id: userId,
      p_amount: sub.credits,
      p_action: eventName,
      p_plan: sub.plan,
    });
  }

  // Fin d'abonnement — le plan redescend à `free` (migration 016).
  //
  // `subscription_expired` déclasse toujours : l'abonnement est terminé.
  //
  // `subscription_cancelled` dépend de `ends_at`. Il signifie normalement
  // « ne pas renouveler », l'accès restant payé jusqu'à cette date : déclasser
  // alors retirerait un droit acquis, et Lemon Squeezy émettra `expired` le
  // moment venu. Mais une résiliation IMMÉDIATE peut être terminale — nous
  // n'avons pas pu vérifier qu'un `expired` distinct suit dans ce cas, et si
  // ce n'est pas le cas le compte resterait « Pro » indéfiniment, soit
  // exactement le défaut que cette branche corrige. On tranche donc sur la
  // donnée plutôt que sur l'hypothèse : `ends_at` dans le futur → on attend ;
  // passé ou absent → l'accès est fini, on déclasse.
  //
  // La garde de signature est la même que pour le crédit, et pour une raison
  // symétrique : sans elle, il suffirait de placer l'identifiant d'un tiers
  // dans son propre checkout puis de résilier pour le faire déclasser.
  if (eventName === 'subscription_cancelled' && !hasAccessRemaining(attrs.ends_at)) {
    return applyOnce(supabase, custom?.user_sig, 'expire_subscription_plan', {
      p_event_key: eventKey,
      p_event_name: eventName,
      p_user_id: userId,
    });
  }

  if (eventName === 'subscription_expired') {
    return applyOnce(supabase, custom?.user_sig, 'expire_subscription_plan', {
      p_event_key: eventKey,
      p_event_name: eventName,
      p_user_id: userId,
    });
  }

  // Other events: acknowledge without processing
  return NextResponse.json({ received: true });
}
