import { Check } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { PRICING_PLANS, CREDIT_COSTS } from '@/lib/marketing-content';

export function Pricing() {
  return (
    <section id="pricing" className="py-24 px-6 border-t border-border scroll-mt-14">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-16">
          <h2 className="text-4xl font-bold tracking-tight mb-4">Simple, transparent pricing</h2>
          <p className="text-muted-foreground text-lg">Pay only for what you use. No hidden fees.</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-12 pt-12">
          {PRICING_PLANS.map((plan) => (
            <Card key={plan.name} className={`relative flex flex-col overflow-visible ${plan.popular ? 'border-primary glow-cyan-sm' : ''}`}>
              {plan.popular && (
                <div className="absolute -top-8 left-1/2 -translate-x-1/2 z-10">
                  <Badge className="px-4 py-1 whitespace-nowrap text-xs font-semibold shadow-lg shadow-primary/20">Most Popular</Badge>
                </div>
              )}
              <CardHeader className={`pb-4 ${plan.popular ? 'pt-8' : ''}`}>
                <CardTitle className="text-base font-medium text-muted-foreground">{plan.name}</CardTitle>
                <div className="flex items-baseline gap-1 mt-2">
                  <span className="text-3xl font-bold text-foreground">{plan.price}</span>
                  <span className="text-muted-foreground text-sm">{plan.period}</span>
                </div>
                <p className="text-xs text-primary font-medium">{plan.credits}</p>
                <p className="text-xs text-muted-foreground">{plan.layers}</p>
              </CardHeader>
              <CardContent className="flex flex-col flex-1">
                <ul className="space-y-2 flex-1 mb-6">
                  {plan.features.map((f) => (
                    <li key={f} className="flex items-start gap-2 text-sm text-muted-foreground">
                      <Check size={14} className="text-primary mt-0.5 shrink-0" />
                      {f}
                    </li>
                  ))}
                </ul>
                <Button variant={plan.ctaVariant} className="w-full" size="sm">{plan.cta}</Button>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Credits breakdown */}
        <div className="max-w-2xl mx-auto bg-[#111111] border border-border rounded-xl p-6">
          <h3 className="text-sm font-semibold text-foreground mb-4">Credits per action</h3>
          <div className="grid grid-cols-3 gap-2">
            {CREDIT_COSTS.map(([action, cost]) => (
              <div key={action} className="flex items-center justify-between gap-1 bg-[#1a1a1a] rounded-md px-3 py-2">
                <span className="text-xs text-muted-foreground truncate">{action}</span>
                <span className="text-xs font-mono text-primary shrink-0">{cost}cr</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
