'use client';

import { Activity, AlertTriangle, CheckCircle2, Info, ShieldAlert } from 'lucide-react';
import type { ERCViolation, PCBState } from '@cirqix/types';
import { StageHeader } from './StageHeader';

// ─── Helpers ─────────────────────────────────────────────────────────────────

const SEV = {
  error: {
    icon: <AlertTriangle size={12} />,
    label: 'ERROR',
    row: 'border-l-2 border-red-500/50 bg-[#1a0f0f]/30 hover:bg-[#221212]/40',
    badge: 'bg-red-500/10 text-red-400 border-red-500/20',
    text: '#ef4444',
  },
  warning: {
    icon: <Info size={12} />,
    label: 'WARN',
    row: 'border-l-2 border-amber-500/40 bg-[#1a140b]/30 hover:bg-[#221a0e]/40',
    badge: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
    text: '#f59e0b',
  },
} as const;

function GroupHeader({ label, count, color }: { label: string; count: number; color: string }) {
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 bg-white/[0.01] border-b border-[#141414]">
      <span className="text-[10px] font-mono font-bold tracking-widest uppercase" style={{ color }}>
        {label}
      </span>
      <span
        className="text-[9px] font-mono px-1.5 py-0.5 rounded leading-none font-semibold"
        style={{ background: `${color}18`, color }}
      >
        {count}
      </span>
      <span className="flex-1 border-t border-dashed border-[#1e1e1e]/60" />
    </div>
  );
}

function ViolationRow({ v }: { v: ERCViolation }) {
  const s = SEV[v.severity];
  return (
    <li className={`flex items-start gap-4 px-4 py-3.5 transition-colors border-b border-[#141414]/40 ${s.row}`}>
      <span style={{ color: s.text }} className="shrink-0 mt-0.5 animate-pulse">{s.icon}</span>
      <div className="flex-1 min-w-0 space-y-1.5">
        <p className="text-xs text-foreground/90 leading-relaxed font-sans">{v.message}</p>
        <div className="flex flex-wrap items-center gap-2">
          {v.type && (
            <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded border leading-none tracking-wider ${s.badge}`}>
              {v.type}
            </span>
          )}
          {(v.ref || v.pin) && (
            <span className="text-[10px] font-mono text-[#777] bg-[#141414]/30 px-1 py-0.5 rounded border border-[#222]/30">
              {v.ref}{v.pin ? `.${v.pin}` : ''}
            </span>
          )}
          {v.x_mm !== undefined && v.y_mm !== undefined && (
            <span className="text-[9px] font-mono text-[#555] bg-[#111] px-1 py-0.5 rounded border border-[#222]/20">
              LOC: ({v.x_mm.toFixed(2)}, {v.y_mm.toFixed(2)}) mm
            </span>
          )}
        </div>
      </div>
    </li>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────

export function ErcView({ state }: { state: PCBState }) {
  const violations = state.ercViolations ?? [];
  const skipped    = state.erc_skipped === true;
  const errors     = violations.filter((v) => v.severity === 'error');
  const warnings   = violations.filter((v) => v.severity === 'warning');

  const metaText = skipped
    ? 'skipped'
    : violations.length === 0
    ? 'clean'
    : `${errors.length} error${errors.length !== 1 ? 's' : ''} · ${warnings.length} warning${warnings.length !== 1 ? 's' : ''}`;

  return (
    <div className="flex flex-col h-full bg-[#08080c] relative overflow-hidden">
      {/* Grid Pattern */}
      <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.005)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.005)_1px,transparent_1px)] bg-[size:24px_24px] pointer-events-none" />

      <StageHeader
        icon={<Activity size={12} />}
        title="ERC — Electrical Rules Check"
        meta={
          <span className={violations.length > 0 ? 'text-warning font-semibold' : skipped ? 'text-muted-foreground' : 'text-green-400 font-semibold'}>
            {metaText.toUpperCase()}
          </span>
        }
        actions={
          violations.length > 0 ? (
            <div className="flex items-center gap-1.5">
              {errors.length > 0 && (
                <span className="flex items-center gap-1 text-[9px] font-mono px-2 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/20">
                  <AlertTriangle size={9} /> {errors.length}
                </span>
              )}
              {warnings.length > 0 && (
                <span className="flex items-center gap-1 text-[9px] font-mono px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">
                  <Info size={9} /> {warnings.length}
                </span>
              )}
            </div>
          ) : undefined
        }
      />

      <div className="flex-1 overflow-auto relative z-10">
        {/* Skipped */}
        {skipped && (
          <div className="m-6 rounded-xl border border-warning/15 bg-warning/[0.02] px-5 py-4 flex items-start gap-3 backdrop-blur-sm">
            <Info size={16} className="text-warning shrink-0 mt-0.5" />
            <div className="space-y-1">
              <p className="text-xs font-semibold text-warning">ERC skipped</p>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                kicad-cli is not available in this environment.
                Schematic electrical rules will be enforced in the production pipeline.
              </p>
            </div>
          </div>
        )}

        {/* Clean State with Animated Radar */}
        {!skipped && violations.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full min-h-[400px] gap-6 px-8 py-12">
            {/* SVG Scanner/Radar Animation */}
            <div className="relative w-28 h-28 flex items-center justify-center">
              {/* Outer pulsing ring */}
              <div className="absolute inset-0 rounded-full border border-green-500/20 animate-ping [animation-duration:3s]" />
              <div className="absolute inset-2 rounded-full border border-green-500/30 animate-pulse" />
              
              <svg className="w-full h-full text-green-500/40" viewBox="0 0 100 100">
                <circle cx="50" cy="50" r="48" fill="none" stroke="currentColor" strokeWidth="0.5" strokeDasharray="3 3" />
                <circle cx="50" cy="50" r="32" fill="none" stroke="currentColor" strokeWidth="0.5" />
                <circle cx="50" cy="50" r="16" fill="none" stroke="currentColor" strokeWidth="0.5" />
                <line x1="50" y1="2" x2="50" y2="98" stroke="currentColor" strokeWidth="0.25" />
                <line x1="2" y1="50" x2="98" y2="50" stroke="currentColor" strokeWidth="0.25" />
                
                {/* Scanning sweep */}
                <g className="origin-[50px_50px] animate-[spin_5s_linear_infinite]">
                  <path d="M50 50 L50 2 A48 48 0 0 1 98 50 Z" fill="url(#radar-sweep)" opacity="0.4" />
                  <circle cx="50" cy="8" r="1.5" fill="#22c55e" className="animate-ping" />
                </g>
                <defs>
                  <radialGradient id="radar-sweep" cx="50%" cy="50%" r="50%">
                    <stop offset="0%" stopColor="rgba(34, 197, 94, 0)" />
                    <stop offset="100%" stopColor="rgba(34, 197, 94, 0.4)" />
                  </radialGradient>
                </defs>
              </svg>
              
              <div className="absolute inset-0 flex items-center justify-center">
                <CheckCircle2 size={28} className="text-green-400 drop-shadow-[0_0_8px_rgba(74,222,128,0.5)]" />
              </div>
            </div>

            <div className="text-center max-w-sm space-y-2">
              <p className="text-sm font-semibold text-foreground tracking-wide uppercase font-mono">
                Schematic is ERC Clean
              </p>
              <p className="text-xs text-muted-foreground leading-relaxed px-4">
                No net conflicts or unconnected inputs detected. All terminals mapped correctly.
                You are ready to proceed with component placement.
              </p>
            </div>
          </div>
        )}

        {/* Violations list — errors first, then warnings */}
        {violations.length > 0 && (
          <div className="rounded-xl border border-white/5 bg-[#0c0d12]/75 backdrop-blur-md overflow-hidden m-6 shadow-2xl">
            {errors.length > 0 && (
              <>
                <GroupHeader label="Electrical Errors" count={errors.length} color="#ef4444" />
                <ul className="divide-y divide-[#1e1e24]/10">
                  {errors.map((v) => <ViolationRow key={v.id} v={v} />)}
                </ul>
              </>
            )}
            {warnings.length > 0 && (
              <>
                <GroupHeader label="Electrical Warnings" count={warnings.length} color="#f59e0b" />
                <ul className="divide-y divide-[#1e1e24]/10">
                  {warnings.map((v) => <ViolationRow key={v.id} v={v} />)}
                </ul>
              </>
            )}
          </div>
        )}

        {/* Action hint when violations */}
        {violations.length > 0 && (
          <div className="flex items-start gap-3 mx-6 mb-6 px-4 py-3 rounded-xl border border-white/5 bg-[#08080c]/50 backdrop-blur-sm">
            <ShieldAlert size={15} className="text-[#555] shrink-0 mt-0.5" />
            <p className="text-[11px] text-[#777] leading-relaxed">
              <strong className="text-foreground/70">Design Rule Notice:</strong> Fix ERC errors before proceeding to placement.
              Warnings may indicate acceptable design choices (e.g. unused pins with internal pull-ups or test-points).
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
