-- Phase 4.4 — idempotence des webhooks Lemon Squeezy (PLAN.md §4.4, action 4 :
-- « vérifier transaction_id avant insert »).
--
-- Lemon Squeezy retente un webhook tant qu'il ne reçoit pas de 2xx. Sans
-- déduplication, un `order_created` rejoué crédite deux fois le même pack.
-- Chaque événement traité est enregistré ici AVANT le crédit ; la clé
-- primaire fait office de verrou (conflit 23505 = doublon → 200 sans
-- traitement). Si le crédit échoue ensuite, la ligne est supprimée pour que
-- le retry aboutisse.
--
-- Clés : `event_name:data.id` pour order_created / subscription_created
-- (ids uniques par achat / abonnement) ; `event_name:data.id:hash(body)` pour
-- subscription_renewed, dont data.id est constant d'un renouvellement à
-- l'autre — un retry renvoie le même corps, un vrai renouvellement non.
--
-- Table technique : accès service_role uniquement (le webhook utilise
-- l'admin client, qui bypass RLS). Aucune policy anon/authenticated.
-- Idempotent : réapplicable sans effet de bord.

CREATE TABLE IF NOT EXISTS processed_webhook_events (
  event_key    text PRIMARY KEY,
  provider     text NOT NULL DEFAULT 'lemon_squeezy',
  event_name   text NOT NULL,
  processed_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE processed_webhook_events ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON processed_webhook_events FROM anon, authenticated;
