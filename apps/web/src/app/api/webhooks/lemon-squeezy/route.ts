import { createHmac, timingSafeEqual } from 'crypto';
import { NextRequest, NextResponse } from 'next/server';
import { createAdminClient } from '@/shared/lib/supabase-server';

// Map Lemon Squeezy variant ID → credits amount (one-time top-up packs)
function configuredMap<T>(entries: Array<[string | undefined, T]>): Record<string, T> {
  return Object.fromEntries(
    entries
      .filter(([id]) => Boolean(id?.trim()))
      .map(([id, value]) => [id!.trim(), value]),
  );
}

const TOPUP_PACKS = configuredMap<number>([
  [process.env.LS_VARIANT_TOPUP_20, 20],
  [process.env.LS_VARIANT_TOPUP_100, 100],
  [process.env.LS_VARIANT_TOPUP_300, 300],
]);

// Map Lemon Squeezy product ID → plan + monthly credits
const SUBSCRIPTION_PLANS = configuredMap<{ credits: number; plan: string }>([
  [process.env.LS_PRODUCT_PRO, { credits: 100, plan: 'pro' }],
  [process.env.LS_PRODUCT_PRO_MAX, { credits: 300, plan: 'pro_max' }],
]);

type LsAttributes = Record<string, unknown>;

interface LsPayload {
  meta: { event_name: string; custom_data?: { user_id?: string } };
  data: { type?: string; id?: string; attributes: LsAttributes };
}

export function paymentEventKey(eventName: string, resourceType: string, resourceId: string): string {
  return `lemon_squeezy:${eventName}:${resourceType}:${resourceId}`;
}

export function verifySignature(rawBody: string, signature: string): boolean {
  const secret = process.env.LEMON_SQUEEZY_WEBHOOK_SECRET?.trim();
  if (!secret || !/^[a-f0-9]{64}$/i.test(signature)) return false;
  const expected = createHmac('sha256', secret).update(rawBody).digest('hex');
  try {
    const received = Buffer.from(signature, 'hex');
    const computed = Buffer.from(expected, 'hex');
    return received.length === computed.length && timingSafeEqual(received, computed);
  } catch {
    return false;
  }
}

export async function POST(req: NextRequest) {
  const rawBody = await req.text();
  const signature = req.headers.get('x-signature') ?? '';

  if (!verifySignature(rawBody, signature)) {
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
  const eventId = typeof data.id === 'string' ? data.id.trim() : '';
  const resourceType = typeof data.type === 'string' ? data.type.trim() : '';

  if (!eventId || !resourceType) {
    return NextResponse.json({ error: 'Missing event resource identity' }, { status: 400 });
  }
  const eventKey = paymentEventKey(eventName, resourceType, eventId);
  const userId = meta.custom_data?.user_id;

  const supabase = createAdminClient();

  if (eventName === 'order_created') {
    const variantId = String(
      (attrs.first_order_item as { variant_id?: unknown } | null)?.variant_id ?? ''
    );
    const credits = TOPUP_PACKS[variantId];
    if (credits) {
      if (!userId) {
        return NextResponse.json({ error: 'Missing user_id in meta.custom_data' }, { status: 400 });
      }
      const { data: applied, error } = await supabase.rpc('process_payment_event', {
        p_event_id: eventKey,
        p_event_name: 'topup',
        p_user_id: userId,
        p_amount: credits,
        p_plan: null,
        p_replace_balance: false,
      });
      if (error) {
        console.error('[ls-webhook] payment processing failed:', error.message);
        return NextResponse.json({ error: 'DB error' }, { status: 500 });
      }
      return NextResponse.json({ received: true, duplicate: applied === false });
    }
    return NextResponse.json({ received: true });
  }

  if (eventName === 'subscription_created') {
    const productId = String(attrs.product_id ?? '');
    const sub = SUBSCRIPTION_PLANS[productId];
    if (sub) {
      if (!userId) {
        return NextResponse.json({ error: 'Missing user_id in meta.custom_data' }, { status: 400 });
      }
      const { error } = await supabase.rpc('register_lemon_subscription', {
        p_subscription_id: eventId,
        p_user_id: userId,
        p_product_id: productId,
        p_plan: sub.plan,
        p_credits: sub.credits,
      });
      if (error) {
        console.error('[ls-webhook] subscription registration failed:', error.message);
        return NextResponse.json({ error: 'DB error' }, { status: 500 });
      }
    }
    return NextResponse.json({ received: true });
  }

  if (eventName === 'subscription_payment_success') {
    const subscriptionId = String(attrs.subscription_id ?? '');
    if (!subscriptionId) {
      return NextResponse.json({ error: 'Missing subscription_id' }, { status: 400 });
    }
    const { data: subscription, error: subscriptionError } = await supabase
      .from('lemon_subscriptions')
      .select('user_id, plan, credits')
      .eq('subscription_id', subscriptionId)
      .single();
    if (subscriptionError || !subscription) {
      console.error('[ls-webhook] subscription mapping unavailable:', subscriptionError?.message);
      return NextResponse.json({ error: 'Subscription mapping unavailable' }, { status: 500 });
    }
    const { data: applied, error } = await supabase.rpc('process_payment_event', {
      p_event_id: eventKey,
      p_event_name: 'subscription_credit_reset',
      p_user_id: subscription.user_id,
      p_amount: subscription.credits,
      p_plan: subscription.plan,
      p_replace_balance: true,
    });
    if (error) {
      console.error('[ls-webhook] payment processing failed:', error.message);
      return NextResponse.json({ error: 'DB error' }, { status: 500 });
    }
    return NextResponse.json({ received: true, duplicate: applied === false });
  }

  // Other events: acknowledge without processing
  return NextResponse.json({ received: true });
}
