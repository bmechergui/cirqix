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
    // Marqueur d'idempotence et crédit dans la MÊME transaction (migration 013).
    // Auparavant le marqueur était posé d'abord : si le process mourait entre les
    // deux, le paiement était encaissé, le marqueur en place, le crédit jamais
    // pose — et le réessai de Lemon Squeezy classé « duplicate ».
    const { data: credited, error } = await supabase.rpc('credit_webhook_event', {
      p_event_key: eventKey,
      p_event_name: eventName,
      p_user_id: userId,
      p_amount: credits,
      p_action: 'topup',
    });
    if (error) {
      console.error('[ls-webhook] credit_webhook_event failed:', error.message);
      return NextResponse.json({ error: 'DB error' }, { status: 500 });
    }
    if (credited === false) {
      return NextResponse.json({ received: true, duplicate: true });
    }
    return NextResponse.json({ received: true });
  }

  if (eventName === 'subscription_created' || eventName === 'subscription_renewed') {
    const productId = String(attrs.product_id ?? '');
    const sub = subscriptionPlans()[productId];
    if (!sub) {
      return NextResponse.json({ received: true });
    }
    // Marqueur, plan et allocation dans la MÊME transaction (migration 013).
    // La RPC échoue si aucune ligne `credits` ne correspond à l'utilisateur —
    // un `update` silencieux sur zéro ligne faisait auparavant répondre
    // « received » sans que rien n'ait été credité, marqueur déjà pose.
    const { data: credited, error: creditError } = await supabase.rpc('credit_webhook_event', {
      p_event_key: eventKey,
      p_event_name: eventName,
      p_user_id: userId,
      p_amount: sub.credits,
      p_action: eventName,
      p_plan: sub.plan,
    });
    if (creditError) {
      console.error('[ls-webhook] credit_webhook_event failed:', creditError.message);
      return NextResponse.json({ error: 'DB error' }, { status: 500 });
    }
    if (credited === false) {
      return NextResponse.json({ received: true, duplicate: true });
    }
    return NextResponse.json({ received: true });
  }

  // Other events: acknowledge without processing
  return NextResponse.json({ received: true });
}
