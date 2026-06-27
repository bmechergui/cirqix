---
name: cirqix-credits
description: This skill should be used when the user asks to "gérer les crédits", "déduire des crédits", "vérifier le solde", "implémenter le système de crédits", "créer la table credits Supabase", "ajouter un top-up", "configurer les plans Free/Pro/Pro Max" or mentions credits, balance, plans, or middleware de crédits.
version: 0.1.0
---

# Cirqix — Système de Crédits

## Tarifs par action

```typescript
// packages/agents/src/credits/costs.ts
export const CREDIT_COSTS = {
  chat:        0.5,
  schema:      2,
  placement:   2,
  routing:     3,
  drc:         1,
  export:      1,
  footprint:   3,   // plan Pro+ uniquement
  view_3d:     1,   // plan Pro+ uniquement
  simulation:  3,   // plan Pro Max+ uniquement
} as const;

export type CreditAction = keyof typeof CREDIT_COSTS;
```

## Plans

```typescript
export const PLANS = {
  free:       { daily_credits: 5,    monthly_credits: null, price_eur: 0,    layers_max: 2    },
  pro:        { daily_credits: null, monthly_credits: 100,  price_eur: 25,   layers_max: 4    },
  pro_max:    { daily_credits: null, monthly_credits: 300,  price_eur: 50,   layers_max: 8    },
  enterprise: { daily_credits: null, monthly_credits: null, price_eur: null, layers_max: null }, // illimité
} as const;

// Actions réservées selon le plan
export const PLAN_RESTRICTIONS = {
  footprint: ["pro", "pro_max", "enterprise"],
  view_3d:   ["pro", "pro_max", "enterprise"],
  simulation:["pro_max", "enterprise"],
};
```

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

## Core credit functions

```typescript
// packages/agents/src/credits/index.ts
import { supabase } from "../lib/supabase";
import { CREDIT_COSTS, PLAN_RESTRICTIONS, CreditAction } from "./costs";

export async function checkCredits(userId: string, action: CreditAction): Promise<void> {
  const { data, error } = await supabase
    .from("credits")
    .select("balance, plan, daily_used, daily_reset_at")
    .eq("user_id", userId)
    .single();

  if (error || !data) throw new Error("Compte crédits introuvable");

  const cost = CREDIT_COSTS[action];

  // Vérifier restriction de plan
  const restriction = PLAN_RESTRICTIONS[action as keyof typeof PLAN_RESTRICTIONS];
  if (restriction && !restriction.includes(data.plan)) {
    throw new CreditError(
      `Action "${action}" requiert le plan ${restriction[0]} ou supérieur`,
      "PLAN_REQUIRED"
    );
  }

  // Reset compteur daily si nouveau jour
  if (data.daily_reset_at !== new Date().toISOString().slice(0, 10)) {
    await supabase.from("credits").update({
      daily_used: 0,
      daily_reset_at: new Date().toISOString().slice(0, 10)
    }).eq("user_id", userId);
    data.daily_used = 0;
  }

  // Vérifier solde plan Free (limite quotidienne)
  if (data.plan === "free") {
    if (data.daily_used + cost > 5) {
      throw new CreditError("Limite quotidienne atteinte (5 crédits/jour). Passez à Pro.", "DAILY_LIMIT");
    }
  }

  // Vérifier solde général
  if (data.balance < cost) {
    throw new CreditError(`Solde insuffisant (${data.balance} crédits, besoin de ${cost})`, "INSUFFICIENT");
  }
}

export async function deductCredits(
  userId: string,
  action: CreditAction,
  projectId?: string
): Promise<number> {
  const cost = CREDIT_COSTS[action];

  const { data, error } = await supabase.rpc("deduct_credits", {
    p_user_id: userId,
    p_cost: cost,
    p_action: action,
    p_project_id: projectId ?? null,
  });

  if (error) throw new Error(`Déduction crédits échouée: ${error.message}`);
  return data; // balance restante
}

export async function getBalance(userId: string): Promise<{ balance: number; plan: string }> {
  const { data } = await supabase
    .from("credits")
    .select("balance, plan")
    .eq("user_id", userId)
    .single();
  return data ?? { balance: 0, plan: "free" };
}
```

## Fonction RPC Supabase (atomique)

```sql
-- Déduction atomique pour éviter les race conditions
create or replace function deduct_credits(
  p_user_id uuid,
  p_cost numeric,
  p_action text,
  p_project_id uuid default null
) returns numeric
language plpgsql security definer as $$
declare
  v_balance numeric;
  v_plan text;
begin
  -- Lock row pour éviter double déduction
  select balance, plan into v_balance, v_plan
  from credits where user_id = p_user_id for update;

  if v_balance < p_cost then
    raise exception 'INSUFFICIENT_CREDITS';
  end if;

  -- Déduire
  update credits
  set balance = balance - p_cost,
      daily_used = daily_used + p_cost,
      updated_at = now()
  where user_id = p_user_id;

  -- Enregistrer transaction
  insert into credit_transactions (user_id, project_id, action, amount, balance_after)
  values (p_user_id, p_project_id, p_action, -p_cost, v_balance - p_cost);

  return v_balance - p_cost;
end;
$$;
```

## Middleware API Next.js

```typescript
// apps/api/src/middleware/credits.ts
import { checkCredits, deductCredits } from "@cirqix/agents/credits";
import type { CreditAction } from "@cirqix/agents/credits/costs";

export function withCredits(action: CreditAction) {
  return async function creditMiddleware(req: Request, userId: string, projectId?: string) {
    // Vérifier avant d'exécuter
    await checkCredits(userId, action);
    return async (result: unknown) => {
      // Déduire après succès seulement
      const remaining = await deductCredits(userId, action, projectId);
      return { result, credits_remaining: remaining };
    };
  };
}

// Usage dans un endpoint
export async function POST(req: Request) {
  const user = await getUser(req);
  const commit = await withCredits("schema")(req, user.id);

  const schema = await runSchemaAgent(await req.json());

  const { credits_remaining } = await commit(schema);
  return Response.json({ schema, credits_remaining });
}
```

## Recharge Lemon Squeezy (webhook)

```typescript
// apps/api/app/api/webhooks/lemon-squeezy/route.ts
const CREDIT_PACKS = {
  "prod_topup_20":  { credits: 20,  price: 5  },
  "prod_topup_100": { credits: 100, price: 20 },
  "prod_topup_300": { credits: 300, price: 50 },
};

const PLAN_CREDITS = {
  "prod_pro":     100,
  "prod_pro_max": 300,
};

export async function POST(req: Request) {
  const payload = await req.json();
  const { event_name, data } = payload;

  const userId = data.attributes.custom_data?.user_id;
  if (!userId) return new Response("Missing user_id", { status: 400 });

  if (event_name === "order_created") {
    // Top-up ponctuel
    const productId = data.attributes.first_order_item.product_id;
    const pack = CREDIT_PACKS[productId];
    if (pack) {
      await supabase.rpc("add_credits", { p_user_id: userId, p_amount: pack.credits, p_action: "topup" });
    }
  }

  if (event_name === "subscription_created" || event_name === "subscription_renewed") {
    // Recharge mensuelle
    const productId = data.attributes.product_id;
    const monthlyCredits = PLAN_CREDITS[productId];
    const plan = productId === "prod_pro" ? "pro" : "pro_max";
    if (monthlyCredits) {
      await supabase.from("credits").update({ balance: monthlyCredits, plan }).eq("user_id", userId);
    }
  }

  return new Response("ok");
}
```

## UI — Affichage crédits (sidebar)

```tsx
// packages/ui/src/dashboard/CreditsBadge.tsx
export function CreditsBadge({ balance, plan, dailyLimit }: CreditsProps) {
  const pct = plan === "free" ? (balance / 5) * 100 : (balance / (plan === "pro" ? 100 : 300)) * 100;
  const isLow = pct < 20;

  return (
    <div className="p-4 border-t border-[#2E2E2E]">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-[#71717A] uppercase tracking-wide">Crédits</span>
        <span className={`text-sm font-semibold ${isLow ? "text-amber-500" : "text-white"}`}>
          {balance}
        </span>
      </div>
      <div className="w-full h-1 bg-[#242424] rounded-full">
        <div
          className={`h-1 rounded-full transition-all ${isLow ? "bg-amber-500" : "bg-[#00C2FF]"}`}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
      {isLow && (
        <a href="/dashboard/billing" className="mt-2 block text-xs text-[#00C2FF] hover:underline">
          Recharger →
        </a>
      )}
    </div>
  );
}
```

## Classe d'erreur

```typescript
export class CreditError extends Error {
  constructor(message: string, public code: "INSUFFICIENT" | "DAILY_LIMIT" | "PLAN_REQUIRED") {
    super(message);
    this.name = "CreditError";
  }
}
```
