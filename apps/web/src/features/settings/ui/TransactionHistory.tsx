'use client';

import { useEffect, useState } from 'react';
import { CREDIT_COSTS } from '@cirqix/types';

interface Transaction {
  id: string;
  action: string;
  amount: number;
  created_at: string;
  projects: { name: string } | null;
}

const ACTION_LABELS: Record<string, string> = {
  chat:       'Chat message',
  schema:     'Schema generation',
  placement:  'Component placement',
  routing:    'PCB routing',
  drc:        'DRC check',
  export:     'Gerber export',
  footprint:  'Footprint AI',
  view3d:     '3D preview',
  simulation: 'Simulation',
};

// Known costs for reference
const _COSTS = CREDIT_COSTS;

export function TransactionHistory() {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch('/api/settings/transactions');
        const json = await res.json() as { success: boolean; data?: Transaction[]; error?: string };
        if (!res.ok) {
          setError(json.error ?? 'Failed to load transactions.');
          return;
        }
        setTransactions(json.data ?? []);
      } catch {
        setError('Network error.');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return (
      <div className="space-y-2">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-12 rounded-lg bg-[#141414] animate-pulse" />
        ))}
      </div>
    );
  }

  if (error) {
    return <p className="text-sm text-red-400">{error}</p>;
  }

  if (transactions.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-4 text-center">
        No transactions yet.
      </p>
    );
  }

  return (
    <div className="divide-y divide-border rounded-xl border border-border overflow-hidden">
      {transactions.map((tx) => {
        const isDebit = tx.amount < 0;
        const label = ACTION_LABELS[tx.action] ?? tx.action;
        const date = new Date(tx.created_at).toLocaleDateString('en-GB', {
          day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
        });

        return (
          <div
            key={tx.id}
            className="flex items-center justify-between px-4 py-3 bg-[#0d0d0d] hover:bg-[#111111] transition-colors"
          >
            <div className="flex flex-col gap-0.5">
              <span className="text-sm text-foreground">{label}</span>
              <span className="text-[11px] text-muted-foreground font-mono">
                {tx.projects?.name ? (
                  <><span className="text-primary/60">{tx.projects.name}</span>{' · '}</>
                ) : null}
                {date}
              </span>
            </div>
            <span
              className={`text-sm font-medium font-mono tabular-nums ${
                isDebit ? 'text-red-400' : 'text-emerald-400'
              }`}
            >
              {isDebit ? '' : '+'}{tx.amount} cr
            </span>
          </div>
        );
      })}
    </div>
  );
}
