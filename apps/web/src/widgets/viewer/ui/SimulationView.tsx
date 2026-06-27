'use client';

import { Activity, Zap, AlertTriangle } from 'lucide-react';
import type { PCBState, SimulationVector } from '@cirqix/types';
import { StageHeader } from './StageHeader';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';

// ─── Colour palette for waveform traces ──────────────────────────────────────

const TRACE_COLORS = [
  '#6366f1', // indigo — primary
  '#f59e0b', // amber
  '#10b981', // emerald
  '#ef4444', // red
  '#8b5cf6', // violet
  '#06b6d4', // cyan
  '#f97316', // orange
];

// ─── Format helpers ───────────────────────────────────────────────────────────

function fmtTime(s: number): string {
  if (Math.abs(s) < 1e-9) return `${(s * 1e12).toFixed(1)} ps`;
  if (Math.abs(s) < 1e-6) return `${(s * 1e9).toFixed(1)} ns`;
  if (Math.abs(s) < 1e-3) return `${(s * 1e6).toFixed(1)} µs`;
  if (Math.abs(s) < 1)    return `${(s * 1e3).toFixed(2)} ms`;
  return `${s.toFixed(3)} s`;
}

function fmtFreq(hz: number): string {
  if (hz >= 1e6) return `${(hz / 1e6).toFixed(1)} MHz`;
  if (hz >= 1e3) return `${(hz / 1e3).toFixed(1)} kHz`;
  return `${hz.toFixed(0)} Hz`;
}

function fmtVal(v: number, unit: string): string {
  const abs = Math.abs(v);
  if (unit === 'A') {
    if (abs < 1e-3) return `${(v * 1e6).toFixed(2)} µA`;
    if (abs < 1)    return `${(v * 1e3).toFixed(2)} mA`;
    return `${v.toFixed(3)} A`;
  }
  return `${v.toFixed(4)} ${unit}`;
}

// ─── Waveform chart ───────────────────────────────────────────────────────────

function WaveformChart({ vectors, isAC }: { vectors: SimulationVector[]; isAC: boolean }) {
  const firstVec = vectors[0];
  if (!firstVec) return null;

  const xKey = isAC ? 'freq' : 'time';
  const xLabel = isAC ? 'Frequency' : 'Time';
  const firstUnit = firstVec.unit;

  // Build unified data array: [{ time|freq, v(vin): 5, v(vmid): 2.3, ... }]
  const N = firstVec.time.length;
  const data = Array.from({ length: N }, (_, i): Record<string, number> => {
    const row: Record<string, number> = { [xKey]: firstVec.time[i] ?? 0 };
    for (const vec of vectors) {
      row[vec.name] = vec.values[i] ?? 0;
    }
    return row;
  });

  const xFormatter = isAC ? fmtFreq : fmtTime;

  return (
    <div className="h-60 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
          <XAxis
            dataKey={xKey}
            tickFormatter={xFormatter}
            label={{ value: xLabel, position: 'insideBottomRight', offset: -8, fontSize: 10, fill: '#666' }}
            tick={{ fontSize: 9, fill: '#666' }}
            scale={isAC ? 'log' : 'linear'}
            type="number"
            domain={['auto', 'auto']}
          />
          <YAxis
            tick={{ fontSize: 9, fill: '#666' }}
            tickFormatter={(v: number) => fmtVal(v, firstUnit)}
            width={60}
          />
          <Tooltip
            contentStyle={{ background: '#0d0d0d', border: '1px solid #222', fontSize: 11 }}
            formatter={(value: unknown, name: unknown) => {
              const vec = vectors.find((v) => v.name === String(name));
              const numVal = typeof value === 'number' ? value : 0;
              return [fmtVal(numVal, vec?.unit ?? ''), String(name)];
            }}
            labelFormatter={(label: unknown) => xFormatter(typeof label === 'number' ? label : 0)}
          />
          <Legend wrapperStyle={{ fontSize: 10, color: '#888' }} />
          {vectors.map((vec, i) => (
            <Line
              key={vec.name}
              type="monotone"
              dataKey={vec.name}
              stroke={TRACE_COLORS[i % TRACE_COLORS.length] ?? '#6366f1'}
              dot={false}
              strokeWidth={1.5}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─── Group vectors by unit ────────────────────────────────────────────────────

function groupByUnit(vectors: SimulationVector[]): Map<string, SimulationVector[]> {
  const map = new Map<string, SimulationVector[]>();
  for (const v of vectors) {
    const key = v.unit || 'misc';
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(v);
  }
  return map;
}

// ─── Empty state ──────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 text-center py-16">
      <div className="w-12 h-12 rounded-full bg-[#0d0d0d] border border-[#1a1a1a] flex items-center justify-center">
        <Activity size={20} className="text-muted-foreground/40" />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground/60">No simulation data</p>
        <p className="text-xs text-muted-foreground/50 max-w-xs">
          Ask the AI to run a simulation — e.g. &ldquo;Simulate the transient response&rdquo;
        </p>
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

interface SimulationViewProps {
  state: PCBState;
}

export function SimulationView({ state }: SimulationViewProps) {
  const sim = state.simulationData;

  if (!sim || sim.vectors.length === 0) {
    return (
      <div className="flex flex-col h-full bg-[#060606]">
        <StageHeader
          title="Simulation"
          meta="ngspice SPICE analysis"
          icon={<Activity size={14} />}
        />
        <EmptyState />
      </div>
    );
  }

  const isAC = sim.sim_type === 'ac';
  const groups = groupByUnit(sim.vectors);
  const excluded = sim.excluded_components ?? [];

  return (
    <div className="flex flex-col h-full bg-[#060606] overflow-y-auto">
      <StageHeader
        title="Simulation"
        meta={`${sim.sim_type.toUpperCase()} · ${sim.vectors.length} trace${sim.vectors.length !== 1 ? 's' : ''}`}
        icon={<Activity size={14} />}
        actions={
          <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-[#6366f1]/10 text-[#6366f1] border border-[#6366f1]/25 text-[10px] font-medium">
            <Zap size={8} />
            ngspice
          </span>
        }
      />

      {excluded.length > 0 && (
        <div className="mx-4 mt-3 flex items-start gap-2 rounded-md border border-amber-500/20 bg-amber-500/5 px-3 py-2">
          <AlertTriangle size={12} className="text-amber-400 mt-0.5 shrink-0" />
          <div className="min-w-0">
            <p className="text-[10px] font-medium text-amber-400">Analog subsystem only</p>
            <p className="text-[9px] text-amber-400/70 mt-0.5 font-mono">
              Excluded (no SPICE model): {excluded.join(', ')}
            </p>
          </div>
        </div>
      )}

      <div className="flex flex-col gap-6 p-4">
        {Array.from(groups.entries()).map(([unit, vecs]) => (
          <div key={unit} className="rounded-lg border border-[#141414] overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-2 bg-[#0a0a0a] border-b border-[#141414]">
              <span className="text-[9px] font-mono font-bold tracking-widest uppercase text-[#6366f1]/70">
                {unit === 'V' ? 'Voltage' : unit === 'A' ? 'Current' : 'Misc'} [{unit}]
              </span>
              <span className="ml-auto text-[9px] text-muted-foreground/40 font-mono">
                {vecs.map((v) => v.name).join('  ·  ')}
              </span>
            </div>
            <div className="p-3 bg-[#060606]">
              <WaveformChart vectors={vecs} isAC={isAC} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
