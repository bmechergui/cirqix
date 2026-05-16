'use client';

import { Activity, AlertTriangle, CheckCircle2, Info } from 'lucide-react';
import type { PCBState } from '@layrix/types';
import { StageHeader } from './StageHeader';

interface ErcViewProps {
  state: PCBState;
}

export function ErcView({ state }: ErcViewProps) {
  const violations = state.ercViolations ?? [];
  const skipped = state.erc_skipped === true;
  const errorCount = violations.filter((v) => v.severity === 'error').length;
  const warningCount = violations.filter((v) => v.severity === 'warning').length;

  return (
    <div className="flex flex-col h-full bg-[#0d0d0d]">
      <StageHeader
        icon={<Activity size={12} />}
        title="Electrical Rules Check"
        meta={
          skipped
            ? 'skipped'
            : violations.length === 0
            ? 'clean'
            : `${errorCount} errors · ${warningCount} warnings`
        }
      />

      <div className="flex-1 overflow-auto p-4 md:p-6">
        <div className="max-w-3xl mx-auto space-y-3">
          {skipped && (
            <div className="rounded-lg border border-warning/30 bg-warning/10 px-4 py-3 flex items-start gap-3">
              <Info size={14} className="text-warning shrink-0 mt-0.5" />
              <div className="text-xs text-foreground/90 leading-relaxed">
                <div className="font-semibold">ERC skipped</div>
                <div className="text-muted-foreground">
                  kicad-cli is not available in this environment. Schema rules will be re-checked in production.
                </div>
              </div>
            </div>
          )}

          {!skipped && violations.length === 0 && (
            <div className="rounded-lg border border-success/30 bg-success/10 px-4 py-3 flex items-start gap-3">
              <CheckCircle2 size={14} className="text-success shrink-0 mt-0.5" />
              <div className="text-xs text-foreground/90">
                <div className="font-semibold">Schematic is electrically valid</div>
                <div className="text-muted-foreground">
                  No errors, no warnings. All pins are connected, no power rail conflicts.
                </div>
              </div>
            </div>
          )}

          {violations.length > 0 && (
            <div className="rounded-xl border border-border bg-[#111111] overflow-hidden">
              <header className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-[#0d0d0d]">
                <span className="text-xs font-semibold text-foreground">Violations</span>
                <span className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider">
                  {violations.length} total
                </span>
              </header>
              <ul className="divide-y divide-border">
                {violations.map((v) => (
                  <li key={v.id} className="px-4 py-3 flex items-start gap-3 hover:bg-[#161616] transition-colors">
                    {v.severity === 'error' ? (
                      <AlertTriangle size={14} className="text-destructive shrink-0 mt-0.5" />
                    ) : (
                      <Info size={14} className="text-warning shrink-0 mt-0.5" />
                    )}
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-foreground">{v.message}</p>
                      {(v.ref || v.pin) && (
                        <p className="text-[10px] font-mono text-muted-foreground mt-1">
                          {v.ref ? `${v.ref}` : ''}
                          {v.pin ? `.${v.pin}` : ''}
                          {v.type ? ` · ${v.type}` : ''}
                        </p>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
