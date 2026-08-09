import { createHash, createHmac, timingSafeEqual } from 'crypto';
import { NextRequest, NextResponse } from 'next/server';
import { createAdminClient } from '@/shared/lib/supabase-server';

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

type LsAttributes = Record<string, unknown>;

interface LsPayload {
  meta: { event_name: string };
  data: { id?: string | number; attributes: LsAttributes };
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
// Idempotence (PLAN.md §4.4 action 4 — migration 008)
//
// Lemon Squeezy retente un webhook tant qu'il n'a pas de 2xx : sans
// déduplication, un order_created rejoué créditerait deux fois le même pack.
// Le marker est inséré AVANT le crédit (conflit PK = doublon → 200 sans
// traitement) et supprimé si le crédit échoue, pour que le retry aboutisse.
// Toute autre erreur d'insert (table absente, DB down) fait échouer la
// requête (fail-closed) : traiter sans marker = double crédit au retry.
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

/**
 * 'duplicate' = événement déjà traité (conflit PK) ;
 * 'claimed' = marker posé, traiter ;
 * 'error' = insert impossible (table absente, DB down…) → la requête DOIT
 * échouer : traiter sans marker laisserait un retry créditer une seconde fois.
 */
async function claimEvent(
  supabase: AdminClient,
  eventKey: string,
  eventName: string,
): Promise<'duplicate' | 'claimed' | 'error'> {
  const { error } = await supabase.from('processed_webhook_events').insert({
    event_key: eventKey,
    event_name: eventName,
  });
  if (!error) return 'claimed';
  // 23505 = violation de clé primaire → l'événement a déjà été crédité.
  return error.code === '23505' ? 'duplicate' : 'error';
}

/** Libère le marker après un échec de crédit, pour laisser passer le retry. */
async function releaseEvent(supabase: AdminClient, eventKey: string): Promise<void> {
  await supabase.from('processed_webhook_events').delete().eq('event_key', eventKey);
}

export async function POST(req: NextRequest) {
  const rawBody = await req.text();
  const signature = req.headers.get('x-signature') ?? '';

  // Secret absent = configuration cassée : un HMAC à clé vide est forgeable
  // par n'importe qui. On échoue fort (500) plutôt que de vérifier avec ''.
  const secret = process.env.LEMON_SQUEEZY_WEBHOOK_SECRET;
  if (!secret) {
    console.error('[ls-webhook] LEMON_SQUEEZY_WEBHOOK_SECRET manquant');
    return NextResponse.json({ error: 'Webhook not configured' }, { status: 500 });
  }

  if (!verifySignature(rawBody, signature, secret)) {
    return NextResponse.json({ error: 'Invalid signature' }, { status: 401 });
  }

  let payload: LsPayload;
  try {
    payload = JSON.parse(rawBody) as LsPayload;
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const { meta, data } = payload;
  const eventName = meta.event_name;
  const attrs = data.attributes;

  const userId = (attrs.custom_data as { user_id?: string } | null)?.user_id;
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
    const claim = await claimEvent(supabase, eventKey, eventName);
    if (claim === 'error') {
      console.error('[ls-webhook] marker insert failed (table processed_webhook_events ?)');
      return NextResponse.json({ error: 'DB error' }, { status: 500 });
    }
    if (claim === 'duplicate') {
      return NextResponse.json({ received: true, duplicate: true });
    }
    const { error } = await supabase.rpc('add_credits', {
      p_user_id: userId,
      p_amount: credits,
      p_action: 'topup',
    });
    if (error) {
      console.error('[ls-webhook] add_credits failed:', error.message);
      // Ne pas marquer l'événement comme traité : LS retentera.
      await releaseEvent(supabase, eventKey);
      return NextResponse.json({ error: 'DB error' }, { status: 500 });
    }
    return NextResponse.json({ received: true });
  }

  if (eventName === 'subscription_created' || eventName === 'subscription_renewed') {
    const productId = String(attrs.product_id ?? '');
    const sub = subscriptionPlans()[productId];
    if (!sub) {
      return NextResponse.json({ received: true });
    }
    const claim = await claimEvent(supabase, eventKey, eventName);
    if (claim === 'error') {
      console.error('[ls-webhook] marker insert failed (table processed_webhook_events ?)');
      return NextResponse.json({ error: 'DB error' }, { status: 500 });
    }
    if (claim === 'duplicate') {
      return NextResponse.json({ received: true, duplicate: true });
    }
    const { error: planError, count } = await supabase
      .from('credits')
      .update(
        { plan: sub.plan, updated_at: new Date().toISOString() },
        { count: 'exact' },
      )
      .eq('user_id', userId);
    if (planError || count !== 1) {
      console.error(
        '[ls-webhook] credits plan update failed:',
        planError?.message ?? `expected 1 row, updated ${count ?? 0}`,
      );
      await releaseEvent(supabase, eventKey);
      return NextResponse.json({ error: 'DB error' }, { status: 500 });
    }
    const { error: creditError } = await supabase.rpc('add_credits', {
      p_user_id: userId,
      p_amount: sub.credits,
      p_action: eventName,
    });
    if (creditError) {
      console.error('[ls-webhook] add_credits failed:', creditError.message);
      await releaseEvent(supabase, eventKey);
      return NextResponse.json({ error: 'DB error' }, { status: 500 });
    }
    return NextResponse.json({ received: true });
  }

  // Other events: acknowledge without processing
  return NextResponse.json({ received: true });
}
