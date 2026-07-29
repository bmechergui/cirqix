'use client';

import Link from 'next/link';
import { Coins } from 'lucide-react';
import { useAppStore } from '@/shared/store/app-store';

export function CreditsBadge() {
  const credits = useAppStore((s) => s.credits);

  if (!credits) {
    return (
      <div className="flex items-center gap-1.5 text-xs font-mono font-medium text-muted-foreground">
        <Coins size={13} />
        <span>—</span>
      </div>
    );
  }

  // Paid plans (null daily_limit) → always primary; free plan → color by percentage
  const color =
    credits.daily_limit === null || credits.daily_limit === 0
      ? 'text-primary'
      : credits.balance / credits.daily_limit > 0.5
        ? 'text-primary'
        : credits.balance / credits.daily_limit > 0.2
          ? 'text-amber-400'
          : 'text-red-400';

  const isLow = color === 'text-red-400' || color === 'text-amber-400';

  return (
    <div className="flex items-center gap-2">
      <div className={`flex items-center gap-1.5 text-xs font-mono font-medium ${color}`}>
        <Coins size={13} />
        <span>{credits.balance}</span>
        <span className="text-muted-foreground font-normal">cr · {credits.plan}</span>
      </div>
      {isLow && (
        <Link
          href="/dashboard/billing"
          className="text-xs text-primary hover:underline font-medium"
        >
          Recharge →
        </Link>
      )}
    </div>
  );
}
