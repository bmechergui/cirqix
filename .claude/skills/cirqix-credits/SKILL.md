---
name: cirqix-credits
description: This skill should be used when the user asks to "gérer les crédits", "déduire des crédits", "vérifier le solde", "implémenter le système de crédits", "créer la table credits Supabase", "ajouter un top-up", "configurer les plans Free/Pro/Pro Max" or mentions credits, balance, plans, or middleware de crédits.
version: 0.1.0
---

# Cirqix — Système de Crédits

## Tarifs et droits

Source unique : `packages/types/src/index.ts`. `CREDIT_COSTS` a les clés chat, spec, schema, erc, placement, routing, drc, export, footprint, view3d et simulation ; `PLAN_ENTITLEMENTS` porte `maxLayers`, `canSimulate` et `canView3D`. Lire ces objets plutôt que les recopier. `maxLayers` et `canSimulate` sont appliqués côté serveur, dans les handlers ; `canView3D` côté client seulement.

## Table Supabase

```sql
-- Solde crédits par utilisateur
create table credits (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users not null unique,
  balance numeric(10,1) default 0,
  plan text default 'free' check (plan in ('free','pro','pro_max','enterprise')),
  daily_used numeric(10,1) default 0,
  daily_reset_at date default current_date,
  updated_at timestamptz default now()
);

-- Historique transactions
create table credit_transactions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users not null,
  project_id uuid references projects,
  action text not null,
  amount numeric(10,1) not null,  -- négatif = déduction, positif = recharge
  balance_after numeric(10,1) not null,
  created_at timestamptz default now()
);

-- RLS
alter table credits enable row level security;
alter table credit_transactions enable row level security;

create policy "own credits" on credits for all using (auth.uid() = user_id);
create policy "own transactions" on credit_transactions for all using (auth.uid() = user_id);
```

## Flux de facturation

`apps/web/src/app/api/agent/lib/credits.ts` : réserver avant le run (`reservePipelineCredits` → RPC `reserve_pipeline_credits`), libérer sur échec (`release_pipeline_reservation`), débiter après un succès prouvé (`finalize_pipeline_success`). Un run `driver` ou simulé n'est pas facturé. Tout mouvement de solde passe par une RPC atomique, jamais par un `update` client.

## RPC crédits

Le SQL fait foi dans `packages/db/supabase/migrations/` : 009 (appel réservé au propriétaire ou à `service_role`), 010 (durcissement), 015 (réservations). Ne pas recopier de SQL ici : une copie figée a déjà conservé une faille corrigée.

## Webhook Lemon Squeezy

`apps/web/src/app/api/webhooks/lemon-squeezy/route.ts` fait foi. Vérifier d'abord la signature HMAC `x-signature`. N'accepter le `user_id` que s'il est signé (`apps/web/src/shared/lib/checkout-signature.ts`) : sans cela, n'importe qui créditerait le compte d'autrui. Créditer par la RPC atomique et idempotente `credit_webhook_event`. Événements traités : `order_created`, `subscription_created`, `subscription_renewed`, `subscription_cancelled`, `subscription_expired`.

## UI

Badge de crédits : `apps/web/src/features/dashboard/ui/CreditsBadge.tsx` (couleurs issues de `docs/design/design-system.md`).

## Classe d'erreur

```typescript
export class CreditError extends Error {
  constructor(message: string, public code: "INSUFFICIENT" | "DAILY_LIMIT" | "PLAN_REQUIRED") {
    super(message);
    this.name = "CreditError";
  }
}
```
