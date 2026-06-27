import { Check, X } from 'lucide-react';
import { COMPARISON_FEATURES, COMPARISON_TOOLS } from '@/shared/lib/marketing-content';

export function Comparison() {
  return (
    <section className="py-24 px-6 border-t border-border">
      <div className="max-w-4xl mx-auto">
        <div className="text-center mb-12">
          <h2 className="text-2xl sm:text-3xl md:text-4xl font-bold tracking-tight mb-4">How Cirqix compares</h2>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left py-4 pr-8 text-muted-foreground font-medium text-sm w-1/3 min-w-0">Feature</th>
                {COMPARISON_TOOLS.map((t) => (
                  <th key={t.name} className={`text-center py-4 px-4 text-sm font-semibold min-w-[90px] ${t.name === 'Cirqix' ? 'text-primary' : 'text-foreground'}`}>
                    {t.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {COMPARISON_FEATURES.map((feature, i) => (
                <tr key={feature} className="border-b border-border/50 hover:bg-[#111111] transition-colors">
                  <td className="py-3 pr-8 text-sm text-muted-foreground">{feature}</td>
                  {COMPARISON_TOOLS.map((t) => (
                    <td key={t.name} className="py-3 px-4 text-center">
                      {t.values[i] ? (
                        <Check size={16} className="text-[#22C55E] mx-auto" />
                      ) : (
                        <X size={16} className="text-muted-foreground/40 mx-auto" />
                      )}
                    </td>
                  ))}
                </tr>
              ))}
              <tr className="border-t border-border">
                <td className="py-4 text-sm font-medium text-foreground">Price</td>
                {COMPARISON_TOOLS.map((t) => (
                  <td key={t.name} className={`py-4 px-4 text-center text-sm font-semibold ${t.name === 'Cirqix' ? 'text-primary' : 'text-muted-foreground'}`}>
                    {t.price}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
