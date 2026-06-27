'use client';

import { ShieldCheck, ShieldAlert, AlertTriangle, Info } from 'lucide-react';
import type { DRCViolation, PCBState } from '@cirqix/types';
import { StageHeader } from './StageHeader';
import { PcbView } from './PcbView';

// ─── Helpers ─────────────────────────────────────────────────────────────────

const SEV = {
  error: {
    icon: <AlertTriangle size={11} />,
    rowBorder: 'border-l-2 border-destructive/50',
    rowBg: 'bg-[#180808] hover:bg-[#1e0a0a]',
    badgeCls: 'bg-destructive/15 text-destructive border border-destructive/25',
    color: '#ef4444',
  },
  warning: {
    icon: <Info size={11} />,
    rowBorder: 'border-l-2 border-warning/40',
    rowBg: 'bg-[#141008] hover:bg-[#181208]',
    badgeCls: 'bg-warning/15 text-warning border border-warning/25',
    color: '#f59e0b',
  },
} as const;

function GroupHeader({ label, count, color }: { label: string; count: number; color: string }) {
  return (
    <div className="flex items-center gap-3 px-4 py-2 bg-[#080808] border-b border-[#111]">
      <span className="text-[9px] font-mono font-bold tracking-widest uppercase" style={{ color }}>
        {label}
      </span>
      <span
        className="text-[9px] font-mono px-1.5 py-0.5 rounded leading-none"
        style={{ background: `${color}18`, color }}
      >
        {count}
      </span>
      <span className="flex-1 border-t border-dashed border-[#1e1e1e]" />
    </div>
  );
}

function DrcRow({ v }: { v: DRCViolation }) {
  const s = SEV[v.severity];
  return (
    <li className={`flex items-start gap-3 px-4 py-2.5 transition-colors ${s.rowBorder} ${s.rowBg}`}>
      <span style={{ color: s.color }} className="shrink-0 mt-0.5">{s.icon}</span>
      <div className="flex-1 min-w-0">
        <p className="text-[11px] text-foreground/85 leading-snug">{v.message}</p>
        <div className="flex flex-wrap items-center gap-2 mt-1">
          {/* Coordinates badge */}
          <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded leading-none ${s.badgeCls}`}>
            ({v.x_mm.toFixed(2)}, {v.y_mm.toFixed(2)}) mm
          </span>
          {/* Layer badge */}
          {v.layer && (
            <span className="text-[9px] font-mono px-1.5 py-0.5 rounded leading-none bg-[#1a1a1a] text-[#555] border border-[#2a2a2a]">
              {v.layer}
            </span>
          )}
        </div>
      </div>
    </li>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────

export function DrcView({ state }: { state: PCBState }) {
  const violations = state.drcViolations ?? [];
  const errors     = violations.filter((v) => v.severity === 'error');
  const warnings   = violations.filter((v) => v.severity === 'warning');
  const isClean    = violations.length === 0;

  const metaText = isClean
    ? '0 violations'
    : `${errors.length} error${errors.length !== 1 ? 's' : ''} · ${warnings.length} warning${warnings.length !== 1 ? 's' : ''}`;

  return (
    <div className="flex flex-col h-full bg-[#080808] overflow-hidden">
      <StageHeader
        icon={<ShieldCheck size={12} />}
        title="DRC — Design Rules Check"
        meta={
          <span className={isClean ? 'text-[#22C55E]' : 'text-warning'}>
            {metaText}
          </span>
        }
        actions={
          !isClean ? (
            <div className="flex items-center gap-1">
              {errors.length > 0 && (
                <span className="flex items-center gap-1 text-[9px] font-mono px-2 py-1 rounded bg-destructive/10 text-destructive border border-destructive/20">
                  <AlertTriangle size={9} /> {errors.length}
                </span>
              )}
              {warnings.length > 0 && (
                <span className="flex items-center gap-1 text-[9px] font-mono px-2 py-1 rounded bg-warning/10 text-warning border border-warning/20">
                  <Info size={9} /> {warnings.length}
                </span>
              )}
            </div>
          ) : undefined
        }
      />

      {/* Status banner */}
      {isClean ? (
        <div className="flex items-center gap-2.5 px-4 py-2.5 border-b border-[#22C55E]/15 bg-[#22C55E]/05 shrink-0">
          <ShieldCheck size={14} className="text-[#22C55E]" />
          <span className="text-xs font-medium text-[#22C55E]">
            DRC clean — board is ready for Gerber export and manufacturing.
          </span>
        </div>
      ) : (
        <div className="flex items-center gap-2.5 px-4 py-2.5 border-b border-warning/15 bg-warning/5 shrink-0">
          <ShieldAlert size={14} className="text-warning" />
          <span className="text-xs font-medium text-warning">
            {violations.length} violation{violations.length !== 1 ? 's' : ''} — fix before ordering Gerbers.
          </span>
        </div>
      )}

      {/* Violation list (collapsible height, scrollable) */}
      {violations.length > 0 && (
        <div className="max-h-56 overflow-auto border-b border-[#141414] shrink-0">
          <div className="rounded-none bg-[#0d0d0d]">
            {errors.length > 0 && (
              <>
                <GroupHeader label="Errors" count={errors.length} color="#ef4444" />
                <ul className="divide-y divide-[#0f0f0f]">
                  {errors.map((v, i) => <DrcRow key={`e-${i}-${v.id}`} v={v} />)}
                </ul>
              </>
            )}
            {warnings.length > 0 && (
              <>
                <GroupHeader label="Warnings" count={warnings.length} color="#f59e0b" />
                <ul className="divide-y divide-[#0f0f0f]">
                  {warnings.map((v, i) => <DrcRow key={`w-${i}-${v.id}`} v={v} />)}
                </ul>
              </>
            )}
          </div>
        </div>
      )}

      {/* PCB layout view takes remaining space */}
      <div className="flex-1 min-h-0">
        <PcbView state={state} title="PCB with routing" showRouting />
      </div>
    </div>
  );
}
