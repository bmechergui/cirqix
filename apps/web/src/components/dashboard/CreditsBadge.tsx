'use client';

import { Coins } from 'lucide-react';
import { useAppStore } from '@/store/app-store';

export function CreditsBadge() {
  const credits = useAppStore((s) => s.credits);

  // Paid plans (null daily_limit) → always primary; free plan → color by percentage
  const color =
    credits.daily_limit === null || credits.daily_limit === 0
      ? 'text-primary'
      : credits.balance / credits.daily_limit > 0.5
        ? 'text-primary'
        : credits.balance / credits.daily_limit > 0.2
          ? 'text-amber-400'
          : 'text-red-400';

  return (
    <div className={`flex items-center gap-1.5 text-xs font-mono font-medium ${color}`}>
      <Coins size={13} />
      <span>{credits.balance}</span>
      <span className="text-muted-foreground font-normal">cr · {credits.plan}</span>
    </div>
  );
}
