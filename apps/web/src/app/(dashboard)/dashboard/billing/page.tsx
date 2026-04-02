import { redirect } from 'next/navigation';
import { Zap, Sparkles, Crown, Check } from 'lucide-react';
import { createRouteHandlerClient } from '@/shared/lib/supabase-server';

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------

interface TopupPack {
  credits: number;
  price: string;
  popular?: boolean;
  checkoutEnvKey: string;
}

interface PlanRow {
  name: string;
  price: string;
  creditsLabel: string;
  features: string[];
  planKey: string;
  checkoutEnvKey?: string;
  popular?: boolean;
}

const TOPUP_PACKS: TopupPack[] = [
  { credits: 20,  price: '5 €',  checkoutEnvKey: 'NEXT_PUBLIC_LS_CHECKOUT_TOPUP_20'  },
  { credits: 100, price: '20 €', checkoutEnvKey: 'NEXT_PUBLIC_LS_CHECKOUT_TOPUP_100', popular: true },
  { credits: 300, price: '50 €', checkoutEnvKey: 'NEXT_PUBLIC_LS_CHECKOUT_TOPUP_300' },
];

const PLANS: PlanRow[] = [
  {
    name: 'Free',
    price: '0 €/mois',
    creditsLabel: '5 cr / jour',
    features: ['Chat PCB', 'Génération schéma', 'DRC basique'],
    planKey: 'free',
  },
  {
    name: 'Maker',
    price: '25 €/mois',
    creditsLabel: '100 cr / mois',
    features: ['Tout Free', 'Placement composants', 'Routage automatique', 'Footprint IA', 'Vue 3D'],
    planKey: 'maker',
    checkoutEnvKey: 'NEXT_PUBLIC_LS_CHECKOUT_MAKER',
    popular: true,
  },
  {
    name: 'Pro',
    price: '50 €/mois',
    creditsLabel: '300 cr / mois',
    features: ['Tout Maker', 'Simulation SPICE', 'Export prioritaire', 'Support dédié'],
    planKey: 'pro',
    checkoutEnvKey: 'NEXT_PUBLIC_LS_CHECKOUT_PRO',
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildCheckoutUrl(baseUrl: string | undefined, userId: string): string | null {
  if (!baseUrl) return null;
  return `${baseUrl}?checkout[custom][user_id]=${encodeURIComponent(userId)}`;
}

// ---------------------------------------------------------------------------
// Sub-components (all server, no interactivity needed)
// ---------------------------------------------------------------------------

function PlanBadge({ plan }: { plan: string }) {
  const styles: Record<string, string> = {
    free:       'bg-[#242424] text-muted-foreground',
    maker:      'bg-primary/15 text-primary',
    pro:        'bg-amber-500/15 text-amber-400',
    enterprise: 'bg-purple-500/15 text-purple-400',
  };
  return (
    <span className={`text-xs font-semibold uppercase tracking-wider px-2 py-0.5 rounded ${styles[plan] ?? styles.free}`}>
      {plan}
    </span>
  );
}

function BalanceBar({ balance, plan }: { balance: number; plan: string }) {
  const max = plan === 'free' ? 5 : plan === 'maker' ? 100 : plan === 'pro' ? 300 : 1000;
  const pct = Math.min((balance / max) * 100, 100);
  const color = pct > 50 ? 'bg-primary' : pct > 20 ? 'bg-amber-400' : 'bg-red-500';
  return (
    <div className="w-full h-1.5 bg-[#242424] rounded-full mt-2">
      <div className={`h-1.5 rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default async function BillingPage() {
  const supabase = await createRouteHandlerClient();

  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect('/login');

  const { data: credits } = await supabase
    .from('credits')
    .select('balance, plan')
    .eq('user_id', user.id)
    .single();

  const currentPlan = credits?.plan ?? 'free';
  const balance = Number(credits?.balance ?? 0);

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-10">

      {/* ── Current plan ── */}
      <section>
        <h2 className="text-lg font-semibold text-foreground mb-1">Current Plan</h2>
        <p className="text-sm text-muted-foreground mb-4">Your active subscription and credit balance.</p>
        <div className="rounded-xl border border-[#2E2E2E] bg-[#111111] p-5 flex items-center justify-between gap-4">
          <div className="flex-1">
            <div className="flex items-center gap-3 mb-1">
              <PlanBadge plan={currentPlan} />
              <span className="text-2xl font-bold font-mono text-foreground">{balance}</span>
              <span className="text-sm text-muted-foreground">credits remaining</span>
            </div>
            <BalanceBar balance={balance} plan={currentPlan} />
          </div>
        </div>
      </section>

      {/* ── Top-up packs ── */}
      <section>
        <h2 className="text-lg font-semibold text-foreground mb-1">Top-up Credits</h2>
        <p className="text-sm text-muted-foreground mb-4">One-time credit packs — no subscription required.</p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {TOPUP_PACKS.map((pack) => {
            const checkoutUrl = buildCheckoutUrl(
              process.env[pack.checkoutEnvKey],
              user.id
            );
            return (
              <div
                key={pack.credits}
                className={`relative rounded-xl border bg-[#111111] p-5 flex flex-col gap-3 ${
                  pack.popular ? 'border-primary/50' : 'border-[#2E2E2E]'
                }`}
              >
                {pack.popular && (
                  <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 text-[10px] font-bold uppercase tracking-widest bg-primary text-[#080808] px-2 py-0.5 rounded-full">
                    Popular
                  </span>
                )}
                <div className="flex items-center gap-2">
                  <Zap size={16} className="text-primary" />
                  <span className="text-lg font-bold font-mono text-foreground">{pack.credits} cr</span>
                </div>
                <p className="text-2xl font-bold text-foreground">{pack.price}</p>
                {checkoutUrl ? (
                  <a
                    href={checkoutUrl}
                    className="mt-auto block text-center text-sm font-medium bg-primary text-[#080808] hover:bg-primary/90 rounded-lg py-2 transition-colors"
                  >
                    Buy now
                  </a>
                ) : (
                  <span className="mt-auto block text-center text-sm font-medium text-muted-foreground bg-[#1A1A1A] rounded-lg py-2 cursor-not-allowed">
                    Coming soon
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* ── Plans ── */}
      <section>
        <h2 className="text-lg font-semibold text-foreground mb-1">Subscription Plans</h2>
        <p className="text-sm text-muted-foreground mb-4">Monthly credits included with your subscription.</p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {PLANS.map((plan) => {
            const isCurrent = plan.planKey === currentPlan;
            const checkoutUrl = plan.checkoutEnvKey
              ? buildCheckoutUrl(process.env[plan.checkoutEnvKey], user.id)
              : null;

            return (
              <div
                key={plan.planKey}
                className={`relative rounded-xl border bg-[#111111] p-5 flex flex-col gap-4 ${
                  plan.popular ? 'border-primary/50' : 'border-[#2E2E2E]'
                }`}
              >
                {plan.popular && (
                  <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 text-[10px] font-bold uppercase tracking-widest bg-primary text-[#080808] px-2 py-0.5 rounded-full">
                    Popular
                  </span>
                )}
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    {plan.planKey === 'free'  && <Sparkles size={15} className="text-muted-foreground" />}
                    {plan.planKey === 'maker' && <Zap       size={15} className="text-primary" />}
                    {plan.planKey === 'pro'   && <Crown     size={15} className="text-amber-400" />}
                    <span className="font-semibold text-foreground">{plan.name}</span>
                  </div>
                  <p className="text-xl font-bold text-foreground">{plan.price}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{plan.creditsLabel}</p>
                </div>
                <ul className="space-y-1.5 flex-1">
                  {plan.features.map((f) => (
                    <li key={f} className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Check size={13} className="text-primary shrink-0" />
                      {f}
                    </li>
                  ))}
                </ul>
                {isCurrent ? (
                  <span className="block text-center text-sm font-medium text-muted-foreground bg-[#1A1A1A] rounded-lg py-2">
                    Current plan
                  </span>
                ) : checkoutUrl ? (
                  <a
                    href={checkoutUrl}
                    className="block text-center text-sm font-medium bg-primary text-[#080808] hover:bg-primary/90 rounded-lg py-2 transition-colors"
                  >
                    Upgrade
                  </a>
                ) : (
                  <span className="block text-center text-sm font-medium text-muted-foreground bg-[#1A1A1A] rounded-lg py-2 cursor-not-allowed">
                    Coming soon
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </section>

    </div>
  );
}
