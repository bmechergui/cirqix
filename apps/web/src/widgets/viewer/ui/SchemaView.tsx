'use client';

import { useState } from 'react';
import { FileText, Hash, Network, ListTree, Cable } from 'lucide-react';
import type { PCBState } from '@layrix/types';
import { StageHeader } from './StageHeader';
import { KiCanvasViewer } from './KiCanvasViewer';
import { SchematicGraph } from './SchematicGraph';
import { ViewModeSwitch, type ViewMode } from './ViewModeSwitch';
import { cn } from '@/shared/lib/utils';

type SpecTab = 'diagram' | 'components' | 'nets';

const NET_PALETTE = [
  '#00C2FF', '#D4820A', '#22C55E', '#A855F7', '#F472B6', '#FACC15', '#38BDF8', '#F87171',
];

function netColor(name: string): string {
  if (/^GND$/i.test(name)) return '#71717A';
  if (/^(VCC|VDD|VIN|VBUS|VBAT|3V3|5V|12V)/i.test(name)) return '#D4820A';
  const idx = Math.abs(hashCode(name)) % NET_PALETTE.length;
  return NET_PALETTE[idx]!;
}

function hashCode(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return h;
}

interface TabButtonProps {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  count?: number;
}

function TabButton({ active, onClick, icon, label, count }: TabButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium transition-colors',
        active
          ? 'bg-primary/15 text-primary border border-primary/30'
          : 'text-muted-foreground hover:text-foreground hover:bg-[#141414] border border-transparent'
      )}
    >
      {icon}
      <span>{label}</span>
      {typeof count === 'number' && (
        <span
          className={cn(
            'text-[10px] font-mono px-1.5 py-0.5 rounded',
            active ? 'bg-primary/15 text-primary' : 'bg-[#1a1a1a] text-muted-foreground/70'
          )}
        >
          {count}
        </span>
      )}
    </button>
  );
}

export function SchemaView({ state }: { state: PCBState }) {
  const components = state.components ?? [];
  const connections = state.connections ?? [];
  const nets = state.nets ?? [];
  const nativeUrl = state.kicad_sch_url;
  const [mode, setMode] = useState<ViewMode>(nativeUrl ? 'native' : 'spec');
  const [tab, setTab] = useState<SpecTab>('diagram');
  const effectiveMode: ViewMode = nativeUrl ? mode : 'spec';

  return (
    <div className="flex flex-col h-full bg-[#0d0d0d]">
      <StageHeader
        icon={<FileText size={12} />}
        title="Schematic"
        meta={`${components.length} components · ${nets.length} nets`}
        actions={
          <ViewModeSwitch
            mode={effectiveMode}
            onChange={setMode}
            nativeDisabled={!nativeUrl}
          />
        }
      />

      {effectiveMode === 'native' && nativeUrl ? (
        <KiCanvasViewer src={nativeUrl} controls="basic" />
      ) : (
        <>
          {/* Sub-tabs: one view at a time, no vertical scroll through stacked sections */}
          <div className="flex items-center gap-1 px-4 py-2 border-b border-border bg-[#0a0a0a] shrink-0">
            <TabButton
              active={tab === 'diagram'}
              onClick={() => setTab('diagram')}
              icon={<Network size={12} />}
              label="Diagram"
            />
            <TabButton
              active={tab === 'components'}
              onClick={() => setTab('components')}
              icon={<ListTree size={12} />}
              label="Components"
              count={components.length}
            />
            <TabButton
              active={tab === 'nets'}
              onClick={() => setTab('nets')}
              icon={<Cable size={12} />}
              label="Nets"
              count={nets.length}
            />
          </div>

          <div className="flex-1 min-h-0 overflow-hidden">
            {tab === 'diagram' && (
              <div className="h-full overflow-auto p-4 md:p-6 bg-[#0a0a0a]">
                <SchematicGraph components={components} connections={connections} />
              </div>
            )}

            {tab === 'components' && (
              <div className="h-full overflow-auto p-4 md:p-6">
                <div className="max-w-5xl mx-auto rounded-xl border border-border bg-[#111111] overflow-hidden">
                  <header className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-[#0d0d0d]">
                    <span className="text-xs font-semibold text-foreground">Bill of materials</span>
                    <span className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider">
                      {components.length} parts
                    </span>
                  </header>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead className="bg-[#0a0a0a] sticky top-0">
                        <tr className="text-left text-[10px] uppercase tracking-wider text-muted-foreground">
                          <th className="px-4 py-2 font-medium">Ref</th>
                          <th className="px-4 py-2 font-medium">Value</th>
                          <th className="px-4 py-2 font-medium">Footprint</th>
                          <th className="px-4 py-2 font-medium hidden md:table-cell">Symbol</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border">
                        {components.map((c) => (
                          <tr key={c.ref} className="hover:bg-[#161616] transition-colors">
                            <td className="px-4 py-2 font-mono text-primary font-semibold">{c.ref}</td>
                            <td className="px-4 py-2 text-foreground">{c.value}</td>
                            <td className="px-4 py-2 text-muted-foreground font-mono">{c.footprint}</td>
                            <td className="px-4 py-2 text-muted-foreground font-mono text-[11px] hidden md:table-cell">
                              {c.symbol ?? '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}

            {tab === 'nets' && (
              <div className="h-full overflow-auto p-4 md:p-6">
                <div className="max-w-3xl mx-auto rounded-xl border border-border bg-[#111111] overflow-hidden">
                  <header className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-[#0d0d0d]">
                    <span className="text-xs font-semibold text-foreground">Nets</span>
                    <span className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider">
                      {nets.length}
                    </span>
                  </header>
                  <ul className="divide-y divide-border">
                    {nets.map((name) => {
                      const conn = connections.find((cn) => cn.name === name);
                      const pinCount = conn?.pins.length ?? 0;
                      const color = netColor(name);
                      return (
                        <li key={name} className="px-4 py-3 hover:bg-[#161616] transition-colors">
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2 min-w-0">
                              <span
                                className="w-2.5 h-2.5 rounded-full shrink-0"
                                style={{ backgroundColor: color }}
                              />
                              <span className="font-mono text-sm text-foreground truncate">{name}</span>
                            </div>
                            <span className="flex items-center gap-1 text-[10px] text-muted-foreground font-mono">
                              <Hash size={9} />
                              {pinCount} pins
                            </span>
                          </div>
                          {conn && conn.pins.length > 0 && (
                            <p className="text-[11px] font-mono text-muted-foreground mt-1.5 pl-4.5 pl-[18px] break-all">
                              {conn.pins.map((p) => `${p.ref}.${p.pin}`).join(' · ')}
                            </p>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
