'use client';

import { useMemo, useState } from 'react';
import { FileText, Network, ListTree, Cable, Cpu, Zap, Plug } from 'lucide-react';
import type { PCBState, SchemaComponent } from '@cirqix/types';
import { StageHeader } from './StageHeader';
import { KiCanvasViewer } from './KiCanvasViewer';
import { SchematicGraph } from './SchematicGraph';
import { ViewModeSwitch, type ViewMode } from './ViewModeSwitch';
import { cn } from '@/shared/lib/utils';
import { netColor } from '../lib/schematic-layout';

// ─── Types ───────────────────────────────────────────────────────────────────

type SpecTab = 'diagram' | 'components' | 'nets';
type ComponentGroup = 'ic' | 'passive' | 'connector' | 'other';

// ─── Helpers ─────────────────────────────────────────────────────────────────

function classifyRef(ref: string): ComponentGroup {
  const p = ref.replace(/\d+$/, '').toUpperCase();
  if (p === 'U' || p === 'IC') return 'ic';
  if (['J', 'P', 'CONN', 'SB', 'SW', 'BTN', 'X'].includes(p)) return 'connector';
  if (['R', 'C', 'L', 'D', 'Q', 'T', 'LED', 'FB', 'Y'].includes(p)) return 'passive';
  return 'other';
}

function sortByRef(a: SchemaComponent, b: SchemaComponent): number {
  const parse = (r: string) => {
    const m = r.match(/^([A-Za-z]+)(\d+)$/);
    return m ? ([m[1]!, parseInt(m[2]!)] as [string, number]) : ([r, 0] as [string, number]);
  };
  const [pa, na] = parse(a.ref);
  const [pb, nb] = parse(b.ref);
  return pa < pb ? -1 : pa > pb ? 1 : na - nb;
}

function isPowerNet(name: string) {
  return /^(VCC|VDD|VIN|VBUS|VBAT|3V3|5V|12V|PWR)/i.test(name);
}
function isGndNet(name: string) {
  return /^GND$/i.test(name);
}

// ─── Sub-components ──────────────────────────────────────────────────────────

interface TabBtnProps {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  count?: number;
}

function TabBtn({ active, onClick, icon, label, count }: TabBtnProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-150',
        active
          ? 'bg-primary/10 text-primary border border-primary/20'
          : 'text-[#555] hover:text-[#888] hover:bg-[#141414] border border-transparent',
      )}
    >
      {icon}
      {label}
      {typeof count === 'number' && (
        <span
          className={cn(
            'text-[9px] font-mono px-1.5 py-0.5 rounded leading-none',
            active ? 'bg-primary/15 text-primary' : 'bg-[#1a1a1a] text-[#3d3d3d]',
          )}
        >
          {count}
        </span>
      )}
    </button>
  );
}

// Group header for the BOM
const GROUP_META: Record<ComponentGroup, { label: string; icon: React.ReactNode; color: string }> = {
  ic: {
    label: 'Integrated circuits',
    icon: <Cpu size={10} />,
    color: '#5baeff',
  },
  passive: {
    label: 'Passives',
    icon: <Zap size={10} />,
    color: '#D4820A',
  },
  connector: {
    label: 'Connectors',
    icon: <Plug size={10} />,
    color: '#22C55E',
  },
  other: {
    label: 'Other',
    icon: <ListTree size={10} />,
    color: '#6b6b6b',
  },
};

// ─── BOM Tab ─────────────────────────────────────────────────────────────────

function BomTab({ components }: { components: SchemaComponent[] }) {
  const groups = useMemo(() => {
    const map: Record<ComponentGroup, SchemaComponent[]> = {
      ic: [], passive: [], connector: [], other: [],
    };
    for (const c of components) map[classifyRef(c.ref)].push(c);
    for (const g of Object.keys(map) as ComponentGroup[]) {
      map[g].sort(sortByRef);
    }
    return map;
  }, [components]);

  const order: ComponentGroup[] = ['ic', 'passive', 'connector', 'other'];

  if (components.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-xs text-[#3d3d3d] font-mono">
        No components
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto p-4 space-y-4">
      {order.map((group) => {
        const items = groups[group];
        if (items.length === 0) return null;
        const meta = GROUP_META[group];
        return (
          <div key={group} className="rounded-xl border border-[#1a1a1a] bg-[#0d0d0d] overflow-hidden">
            {/* Group header */}
            <div className="flex items-center justify-between px-4 py-2 border-b border-[#1a1a1a] bg-[#0a0a0a]">
              <div className="flex items-center gap-1.5" style={{ color: meta.color }}>
                {meta.icon}
                <span className="text-[10px] font-semibold tracking-wide uppercase">{meta.label}</span>
              </div>
              <span
                className="text-[9px] font-mono px-1.5 py-0.5 rounded leading-none"
                style={{ background: `${meta.color}18`, color: meta.color }}
              >
                {items.length}
              </span>
            </div>

            {/* Table */}
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[9px] uppercase tracking-widest text-[#555] border-b border-[#1e1e1e]">
                  <th className="px-4 py-2 font-medium w-16">Ref</th>
                  <th className="px-4 py-2 font-medium">Value</th>
                  <th className="px-4 py-2 font-medium hidden sm:table-cell">Footprint</th>
                  <th className="px-4 py-2 font-medium hidden md:table-cell">Symbol</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1a1a1a]">
                {items.map((c) => (
                  <tr key={c.ref} className="hover:bg-[#141414] transition-colors group">
                    <td className="px-4 py-2">
                      <span
                        className="font-mono font-bold text-[11px]"
                        style={{ color: meta.color }}
                      >
                        {c.ref}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-foreground/90 font-medium">{c.value}</td>
                    <td className="px-4 py-2 text-[#777] font-mono text-[10px] hidden sm:table-cell truncate max-w-[140px]">
                      {c.footprint}
                    </td>
                    <td className="px-4 py-2 text-[#666] font-mono text-[10px] hidden md:table-cell">
                      {c.symbol ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}

// ─── Nets Tab ─────────────────────────────────────────────────────────────────

function NetsTab({ nets, connections }: { nets: string[]; connections: NonNullable<PCBState['connections']> }) {
  const sorted = useMemo(() => {
    const gnd = nets.filter(isGndNet);
    const pwr = nets.filter((n) => !isGndNet(n) && isPowerNet(n));
    const sig = nets.filter((n) => !isGndNet(n) && !isPowerNet(n)).sort((a, b) => a.localeCompare(b));
    return [...gnd, ...pwr, ...sig];
  }, [nets]);

  const maxPins = useMemo(() => {
    return connections.reduce((m, c) => Math.max(m, c.pins.length), 1);
  }, [connections]);

  if (nets.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-xs text-[#555] font-mono">
        No nets
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto">
      <table className="w-full text-xs">
        <thead className="sticky top-0 z-10">
          <tr className="text-left text-[9px] uppercase tracking-widest text-[#555] bg-[#0a0a0a] border-b border-[#1e1e1e]">
            <th className="px-4 py-2.5 font-medium w-8">#</th>
            <th className="px-4 py-2.5 font-medium">Net</th>
            <th className="px-4 py-2.5 font-medium w-32 hidden sm:table-cell">Connections</th>
            <th className="px-4 py-2.5 font-medium hidden md:table-cell">Pins</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[#1a1a1a]">
          {sorted.map((name, idx) => {
            const conn = connections.find((c) => c.name === name);
            const pinCount = conn?.pins.length ?? 0;
            const color = netColor(name);
            const isPwr = isPowerNet(name);
            const isGnd = isGndNet(name);
            const pct = Math.round((pinCount / maxPins) * 100);

            return (
              <tr key={name} className="hover:bg-[#141414] transition-colors">
                <td className="px-4 py-2.5">
                  <span className="text-[9px] font-mono text-[#555]">{idx + 1}</span>
                </td>
                <td className="px-4 py-2.5">
                  <div className="flex items-center gap-2">
                    <span
                      className="w-2 h-2 rounded-full shrink-0"
                      style={{ background: color, boxShadow: `0 0 4px ${color}55` }}
                    />
                    <span
                      className="font-mono font-semibold text-[11px]"
                      style={{ color: isGnd ? '#888' : isPwr ? '#D4820A' : color }}
                    >
                      {name}
                    </span>
                    {(isPwr || isGnd) && (
                      <span
                        className="text-[8px] font-mono px-1 py-px rounded leading-none"
                        style={{
                          background: isGnd ? '#222' : '#1a1000',
                          color: isGnd ? '#888' : '#D4820A',
                          border: `1px solid ${isGnd ? '#3a3a3a' : '#D4820A40'}`,
                        }}
                      >
                        {isGnd ? 'GND' : 'PWR'}
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-2.5 hidden sm:table-cell">
                  <div className="flex items-center gap-2">
                    <div className="w-20 h-1.5 rounded-full bg-[#1e1e1e] overflow-hidden">
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${pct}%`, background: color, opacity: 0.8 }}
                      />
                    </div>
                    <span className="text-[10px] font-mono text-[#666]">{pinCount}</span>
                  </div>
                </td>
                <td className="px-4 py-2.5 hidden md:table-cell">
                  <span className="text-[10px] font-mono text-[#555] break-all leading-relaxed">
                    {conn?.pins.map((p) => `${p.ref}.${p.pin}`).join(' · ') ?? '—'}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function SchemaView({ state }: { state: PCBState }) {
  const components  = useMemo(() => state.components  ?? [], [state.components]);
  const connections = useMemo(() => state.connections ?? [], [state.connections]);
  const nets        = useMemo(() => state.nets        ?? [], [state.nets]);
  const nativeUrl = state.kicad_sch_url;

  const [mode, setMode] = useState<ViewMode>(nativeUrl ? 'native' : 'spec');
  const [tab, setTab] = useState<SpecTab>('diagram');
  const effectiveMode: ViewMode = nativeUrl ? mode : 'spec';

  const icCount = useMemo(() => components.filter((c) => classifyRef(c.ref) === 'ic').length, [components]);
  const passiveCount = useMemo(() => components.filter((c) => classifyRef(c.ref) === 'passive').length, [components]);
  const connCount = useMemo(() => components.filter((c) => classifyRef(c.ref) === 'connector').length, [components]);

  const metaLine = [
    icCount ? `${icCount} IC` : '',
    passiveCount ? `${passiveCount} passive${passiveCount > 1 ? 's' : ''}` : '',
    connCount ? `${connCount} connector${connCount > 1 ? 's' : ''}` : '',
    `${nets.length} net${nets.length !== 1 ? 's' : ''}`,
  ].filter(Boolean).join(' · ');

  return (
    <div className="flex flex-col h-full bg-[#080808] overflow-hidden">
      <StageHeader
        icon={<FileText size={12} />}
        title="Schematic"
        meta={metaLine}
        actions={
          <ViewModeSwitch
            mode={effectiveMode}
            onChange={setMode}
            nativeDisabled={!nativeUrl}
          />
        }
      />

      {effectiveMode === 'native' && nativeUrl ? (
        <KiCanvasViewer
          src={nativeUrl}
          zoom="objects"
        />
      ) : (
        <>
          {/* Sub-tabs */}
          <div className="flex items-center gap-1 px-3 py-2 border-b border-[#141414] bg-[#080808] shrink-0">
            <TabBtn
              active={tab === 'diagram'}
              onClick={() => setTab('diagram')}
              icon={<Network size={10} />}
              label="Diagram"
            />
            <TabBtn
              active={tab === 'components'}
              onClick={() => setTab('components')}
              icon={<ListTree size={10} />}
              label="Components"
              count={components.length}
            />
            <TabBtn
              active={tab === 'nets'}
              onClick={() => setTab('nets')}
              icon={<Cable size={10} />}
              label="Nets"
              count={nets.length}
            />
          </div>

          <div className="flex-1 min-h-0 overflow-hidden">
            {tab === 'diagram' && (
              <div className="h-full overflow-hidden p-3 bg-[#080808]">
                <SchematicGraph components={components} connections={connections} />
              </div>
            )}
            {tab === 'components' && <BomTab components={components} />}
            {tab === 'nets' && <NetsTab nets={nets} connections={connections} />}
          </div>
        </>
      )}
    </div>
  );
}
