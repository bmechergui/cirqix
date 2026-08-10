import { beforeEach, describe, expect, it } from 'vitest';

import {
  signCheckoutUserId,
  verifyCheckoutUserId,
} from '@/shared/lib/checkout-signature';

const SECRET = 'secret-de-test-suffisamment-long-pour-hmac';

beforeEach(() => {
  process.env.LEMON_SQUEEZY_WEBHOOK_SECRET = SECRET;
});

describe('signature du checkout', () => {
  it('accepte un user_id accompagné de sa propre signature', () => {
    const sig = signCheckoutUserId('user-1');

    expect(verifyCheckoutUserId('user-1', sig)).toBe(true);
  });

  // Le cœur du correctif. Le HMAC du webhook prouve que le message vient de
  // Lemon Squeezy ; il ne prouve rien sur le compte à créditer, puisque
  // `custom_data.user_id` voyage dans une URL que l'acheteur peut modifier.
  it('refuse la signature d’un AUTRE compte — substitution de user_id', () => {
    const sigDeVictime = signCheckoutUserId('user-victime');

    expect(verifyCheckoutUserId('user-attaquant', sigDeVictime)).toBe(false);
  });

  it('refuse une signature forgée', () => {
    expect(verifyCheckoutUserId('user-1', 'deadbeef'.repeat(8))).toBe(false);
  });

  it('refuse une signature absente', () => {
    expect(verifyCheckoutUserId('user-1', undefined)).toBe(false);
    expect(verifyCheckoutUserId('user-1', '')).toBe(false);
  });

  // Une signature de longueur inattendue fait lever `timingSafeEqual` :
  // l'exception doit être absorbée en `false`, jamais remonter à l'appelant.
  it('refuse une signature de longueur invalide sans lever', () => {
    expect(() => verifyCheckoutUserId('user-1', 'ab')).not.toThrow();
    expect(verifyCheckoutUserId('user-1', 'ab')).toBe(false);
  });

  it('refuse tout si le secret n’est pas configuré — fail-closed', () => {
    delete process.env.LEMON_SQUEEZY_WEBHOOK_SECRET;

    expect(() => signCheckoutUserId('user-1')).toThrow();
    expect(verifyCheckoutUserId('user-1', 'peu-importe')).toBe(false);
  });

  it('produit une signature stable pour un même user_id', () => {
    expect(signCheckoutUserId('user-1')).toBe(signCheckoutUserId('user-1'));
  });

  it('produit des signatures distinctes pour des comptes distincts', () => {
    expect(signCheckoutUserId('user-1')).not.toBe(signCheckoutUserId('user-2'));
  });
});
