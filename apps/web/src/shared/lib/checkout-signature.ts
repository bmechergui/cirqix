import { createHmac, timingSafeEqual } from 'crypto';

/**
 * Signature du `user_id` transporté dans l'URL de checkout Lemon Squeezy.
 *
 * Pourquoi cette signature existe : le lien de paiement porte
 * `checkout[custom][user_id]` en clair, dans une URL que l'acheteur voit et peut
 * modifier avant de payer. Le HMAC du webhook prouve que le message vient bien
 * de Lemon Squeezy — il ne prouve RIEN sur le compte à créditer, puisque Lemon
 * Squeezy renvoie fidèlement le `custom_data` qu'on lui a donné, modifié ou non.
 *
 * Sans cette signature, un acheteur peut substituer l'identifiant d'un autre
 * compte et y faire atterrir le crédit. Ce n'est pas un vol — il paie
 * réellement — mais ça rompt le lien paiement ↔ compte : transfert de crédits
 * entre comptes, et surtout paiement frauduleux attribué à un tiers innocent,
 * qui garde les crédits pendant que le porteur de carte fait un chargeback.
 *
 * Pas d'expiration volontairement : une signature divulguée ne permet que de
 * payer POUR ce compte, ce qui n'est pas une menace. Une expiration casserait en
 * revanche les liens de paiement mis de côté par un utilisateur légitime.
 *
 * Le secret réutilisé est `LEMON_SQUEEZY_WEBHOOK_SECRET` : il est déjà requis,
 * strictement serveur, et ne quitte jamais la machine. Un secret dédié serait
 * plus orthodoxe ; il ajouterait une variable d'environnement à déployer sans
 * renforcer le modèle de menace, les deux usages étant du même côté de la
 * frontière.
 */

function secret(): string {
  const value = process.env.LEMON_SQUEEZY_WEBHOOK_SECRET;
  if (!value) {
    throw new Error('LEMON_SQUEEZY_WEBHOOK_SECRET manquant — signature de checkout impossible');
  }
  return value;
}

/** Signe un `user_id` pour l'URL de checkout. Lève si le secret est absent. */
export function signCheckoutUserId(userId: string): string {
  return createHmac('sha256', secret()).update(userId).digest('hex');
}

/**
 * Vérifie qu'une signature correspond bien au `user_id` reçu.
 *
 * Fail-closed : renvoie `false` sur secret absent, signature absente, ou
 * signature de longueur inattendue — cas où `timingSafeEqual` lève.
 */
export function verifyCheckoutUserId(userId: string, signature: string | undefined): boolean {
  if (!signature) return false;
  try {
    const expected = createHmac('sha256', secret()).update(userId).digest('hex');
    return timingSafeEqual(Buffer.from(signature, 'hex'), Buffer.from(expected, 'hex'));
  } catch {
    return false;
  }
}
