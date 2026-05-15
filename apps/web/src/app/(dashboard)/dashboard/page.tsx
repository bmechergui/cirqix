'use client';

import { CircuitBoard } from 'lucide-react';

export default function DashboardPage() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center gap-4 px-4">
      <div className="w-16 h-16 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center">
        <CircuitBoard size={28} className="text-primary/60" />
      </div>
      <div>
        <h1 className="font-display font-bold text-2xl text-foreground mb-1">Layrix dashboard</h1>
        <p className="text-sm text-muted-foreground max-w-md">
          The project workspace is being rebuilt. New version landing soon.
        </p>
      </div>
    </div>
  );
}
