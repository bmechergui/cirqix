import { afterEach, describe, expect, it } from 'vitest';
import { paymentEventKey, verifySignature } from './route';

const originalSecret = process.env.LEMON_SQUEEZY_WEBHOOK_SECRET;

afterEach(() => {
  if (originalSecret === undefined) delete process.env.LEMON_SQUEEZY_WEBHOOK_SECRET;
  else process.env.LEMON_SQUEEZY_WEBHOOK_SECRET = originalSecret;
});

describe('Lemon Squeezy webhook signature', () => {
  it('fails closed when the webhook secret is missing', () => {
    delete process.env.LEMON_SQUEEZY_WEBHOOK_SECRET;

    expect(verifySignature('{"event":"order_created"}', '00')).toBe(false);
  });

  it('uses a resource-qualified idempotency key', () => {
    expect(paymentEventKey('order_created', 'orders', '42'))
      .not.toBe(paymentEventKey('subscription_payment_success', 'subscription-invoices', '42'));
  });
});
