'use client';

import dynamic from 'next/dynamic';
import React, { useState, useEffect } from 'react';
import { Layers, Box, Download, ZoomIn, ZoomOut, Maximize2, Eye, EyeOff, FileText, Cpu, Route } from 'lucide-react';
import { Button } from '@/shared/ui/button';
import { useAppStore } from '@/shared/store/app-store';
import { LAYER_COLORS, DEFAULT_LAYER_VISIBILITY, colorToHex } from '../lib/layers';
import type { ZoomControls } from '../lib/renderer';
import type { PCBState } from '@layrix/types';

// PixiJS ne fonctionne pas côté serveur → dynamic import obligatoire
const PixiCanvas = dynamic(() => import('./PixiCanvas').then((m) => m.PixiCanvas), {
  ssr: false,
  loading: () => <PCBPlaceholder />,
});

type ViewMode = 'routing' | '3d' | 'schematic' | 'components';

interface SchemaComponent {
  ref: string;
  value: string;
  footprint: string;
  lcsc?: string;
}

interface ViewerPanelProps {
  projectId?: string;
}

export function ViewerPanel({ projectId }: ViewerPanelProps) {
  const [mode, setMode] = useState<ViewMode>('routing');
  const [layerVisibility, setLayerVisibility] =
    useState<Record<string, boolean>>(DEFAULT_LAYER_VISIBILITY);
  const [zoomControls, setZoomControls] = useState<ZoomControls | null>(null);

  const pcbState = useAppStore((s) =>
    projectId ? s.pcbStateByProject[projectId] ?? null : null
  );
  const agentStep = useAppStore((s) => s.agentStep);
  const setPcbState = useAppStore((s) => s.setPcbState);

  // Load persisted PCB state from DB on mount
  useEffect(() => {
    if (!projectId) return;
    void (async () => {
      try {
        const res = await fetch(`/api/projects/${projectId}/pcb-state`);
        if (!res.ok) return;
        const json = await res.json() as { success: boolean; data: Record<string, unknown> | null };
        if (json.success && json.data) {
          setPcbState(projectId, json.data);
        }
      } catch {
        // Non-blocking — viewer still works without persisted state
      }
    })();
  }, [projectId, setPcbState]);

  const toggleLayer = (layer: string) => {
    setLayerVisibility((prev) => ({ ...prev, [layer]: !prev[layer] }));
  };

  return (
    <div className="flex flex-col h-full bg-[#0d0d0d]">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border shrink-0">
        {/* Tab switcher */}
        <div className="flex items-center gap-0.5 bg-[#141414] rounded-lg p-1">
          {(
            [
              { id: 'routing',    icon: <Route size={12} />,    label: 'Routing' },
              { id: 'schematic',  icon: <FileText size={12} />, label: 'Schematic' },
              { id: '3d',         icon: <Box size={12} />,      label: '3D' },
              { id: 'components', icon: <Cpu size={12} />,      label: 'Components' },
            ] as { id: ViewMode; icon: React.ReactNode; label: string }[]
          ).map(({ id, icon, label }) => (
            <button
              key={id}
              type="button"
              onClick={() => setMode(id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                mode === id
                  ? 'bg-primary/20 text-primary'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {icon}
              {label}
            </button>
          ))}
        </div>

        {/* Zoom + Gerber controls */}
        <div className="flex items-center gap-1">
          <div className="flex items-center gap-0.5 bg-[#141414] rounded-lg px-1 py-0.5">
            <Button
              variant="ghost" size="icon" className="h-8 w-8" aria-label="Zoom in"
              disabled={mode !== 'routing' || !zoomControls}
              onClick={() => zoomControls?.zoomIn()}
              title="Zoom in"
            >
              <ZoomIn size={14} />
            </Button>
            <Button
              variant="ghost" size="icon" className="h-8 w-8" aria-label="Zoom out"
              disabled={mode !== 'routing' || !zoomControls}
              onClick={() => zoomControls?.zoomOut()}
              title="Zoom out"
            >
              <ZoomOut size={14} />
            </Button>
            <Button
              variant="ghost" size="icon" className="h-8 w-8" aria-label="Reset zoom"
              disabled={mode !== 'routing' || !zoomControls}
              onClick={() => zoomControls?.resetZoom()}
              title="Fit to screen"
            >
              <Maximize2 size={14} />
            </Button>
          </div>
          <Button
            variant="default"
            size="sm"
            className="h-8 gap-1.5 text-xs bg-primary/90 hover:bg-primary text-black font-semibold"
            disabled={!pcbState || !projectId}
            onClick={() => {
              if (projectId) window.location.assign(`/api/projects/${projectId}/export`);
            }}
          >
            <Download size={13} />
            Gerbers
          </Button>
        </div>
      </div>

      {/* Viewer area */}
      <div className="flex-1 relative overflow-hidden">
        {mode === 'routing' ? (
          /* Split view: Schematic left | Routing right */
          <div className="flex h-full">
            {/* Left — Schematic panel */}
            <div className="w-[280px] shrink-0 border-r border-border overflow-hidden flex flex-col">
              <div className="px-3 py-1.5 border-b border-border shrink-0">
                <span className="text-[9px] text-[#3D3D3D] font-mono uppercase tracking-wider">Schematic</span>
              </div>
              <div className="flex-1 overflow-hidden">
                <SchemaNetlistView pcbState={pcbState} netsVisible />
              </div>
            </div>
            {/* Right — Routing canvas */}
            <div className="flex-1 relative overflow-hidden">
              <PixiCanvas
                pcbState={pcbState}
                layerVisibility={layerVisibility}
                onReady={setZoomControls}
              />
              {pcbState?.circuit_json?.length ? (
                <PCBInfoBadge pcbState={pcbState} />
              ) : (
                <div className="absolute inset-0 z-10">
                  <PCBEmptyState agentStep={agentStep} />
                </div>
              )}
            </div>
          </div>
        ) : mode === 'schematic' ? (
          <SchemaNetlistView pcbState={pcbState} netsVisible />
        ) : mode === 'components' ? (
          <ComponentsBOMView pcbState={pcbState} />
        ) : (
          <PCBViewer3DPlaceholder />
        )}
      </div>

      {/* Layer legend + toggles (Routing only) */}
      {mode === 'routing' && (
        <div className="flex flex-wrap gap-x-3 gap-y-1.5 px-4 py-2 border-t border-border shrink-0">
          {Object.entries(LAYER_COLORS).map(([layer, color]) => {
            const visible = layerVisibility[layer] ?? true;
            return (
              <button
                key={layer}
                type="button"
                onClick={() => toggleLayer(layer)}
                className={`flex items-center gap-1.5 transition-opacity ${
                  visible ? 'opacity-100' : 'opacity-40'
                }`}
                title={visible ? `Hide ${layer}` : `Show ${layer}`}
              >
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: colorToHex(color) }}
                />
                <span className="text-[10px] text-muted-foreground font-mono">{layer}</span>
                {visible ? (
                  <Eye size={9} className="text-muted-foreground" />
                ) : (
                  <EyeOff size={9} className="text-muted-foreground" />
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function PCBPlaceholder() {
  return (
    <div className="w-full h-full flex items-center justify-center">
      <div className="text-xs text-muted-foreground font-mono animate-pulse">
        Loading PCB viewer…
      </div>
    </div>
  );
}

type AgentStep = 'SCHEMA' | 'PLACEMENT' | 'ROUTING' | 'DRC' | 'EXPORT' | null;

const STEP_LABELS: Record<NonNullable<AgentStep>, string> = {
  SCHEMA:    'Generating schematic…',
  PLACEMENT: 'Placing components…',
  ROUTING:   'Auto-routing traces…',
  DRC:       'Running DRC check…',
  EXPORT:    'Exporting Gerbers…',
};

const EXAMPLE_CIRCUITS = [
  '3.3 V LDO regulator — TPS7333, bypass caps',
  'ESP32-C3 minimal — USB-C, reset, decoupling',
  'LED PWM driver — N-MOSFET, 100 mA, 10 kHz',
];

/** Full-area overlay shown when no circuit_json is available */
function PCBEmptyState({ agentStep }: { agentStep: AgentStep }) {
  return (
    <div className="w-full h-full flex items-center justify-center relative overflow-hidden bg-[#0a0a0a]">
      {/* Dot-grid background — PCB workspace feel */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage: 'radial-gradient(circle, #1c1c1c 1px, transparent 1px)',
          backgroundSize: '20px 20px',
        }}
      />

      <div className="relative z-10 flex flex-col items-center gap-6 text-center px-8 max-w-sm">
        {agentStep ? (
          /* Agent running */
          <div className="flex flex-col items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-[#141414] border border-border flex items-center justify-center">
              <Layers size={22} className="text-primary/60" />
            </div>
            <div className="flex items-center gap-2 bg-[#111111] border border-border rounded-full px-4 py-2">
              <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse shrink-0" />
              <span className="text-xs text-[#A1A1AA] font-mono">{STEP_LABELS[agentStep]}</span>
            </div>
            <p className="text-[10px] text-[#3D3D3D] font-mono">PCB renders here when placement is done</p>
          </div>
        ) : (
          /* INITIAL: welcoming canvas */
          <>
            <div className="w-14 h-14 rounded-xl bg-[#141414] border border-[#1E1E1E] flex items-center justify-center">
              <Layers size={26} className="text-primary/25" />
            </div>

            <div className="space-y-1">
              <p className="text-sm text-[#52525B]">PCB canvas</p>
              <p className="text-[11px] text-[#2E2E2E] leading-relaxed">
                Describe your circuit in the chat.<br />
                Schematic → placement → routing → Gerbers.
              </p>
            </div>

            <div className="w-full space-y-1.5">
              <p className="text-[9px] text-[#2A2A2A] font-mono uppercase tracking-wider text-left">
                Example circuits
              </p>
              {EXAMPLE_CIRCUITS.map((ex) => (
                <div
                  key={ex}
                  className="px-3 py-2 rounded-md border border-[#181818] bg-[#0D0D0D] text-left"
                >
                  <p className="text-[10px] text-[#383838] font-mono">{ex}</p>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** Small info badge overlaid on the PCB canvas when circuit is rendered */
function PCBInfoBadge({ pcbState }: { pcbState: PCBState }) {
  const placement = pcbState.placement as { placements?: unknown[] } | undefined;
  const componentCount = placement?.placements?.length ?? (pcbState.circuit_json?.length ? '?' : 0);
  const boardW = pcbState.board_width_mm;
  const boardH = pcbState.board_height_mm;
  const status = pcbState.status;

  const statusColor =
    status === 'DRC_CLEAN' || status === 'PCB_LIVRÉ'
      ? 'text-green-500'
      : status === 'ROUTING_DONE' || status === 'PLACEMENT_DONE'
        ? 'text-primary/70'
        : 'text-[#52525B]';

  return (
    <div className="absolute bottom-3 right-3 z-10 pointer-events-none">
      <div className="flex items-center gap-3 bg-[#0D0D0D]/85 backdrop-blur-sm border border-[#1E1E1E] rounded-md px-3 py-1.5">
        {boardW && boardH && (
          <span className="text-[9px] text-[#3D3D3D] font-mono">{boardW}×{boardH}mm</span>
        )}
        {componentCount ? (
          <span className="text-[9px] text-[#3D3D3D] font-mono">{componentCount} comp.</span>
        ) : null}
        <span className={`text-[9px] font-mono ${statusColor}`}>{status}</span>
      </div>
    </div>
  );
}

function PCBViewer3DPlaceholder() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 text-center p-8">
      <div className="w-16 h-16 rounded-xl bg-[#141414] border border-border flex items-center justify-center">
        <Box size={32} className="text-primary/30" />
      </div>
      <div className="space-y-1.5 max-w-[240px]">
        <p className="text-xs text-[#A1A1AA] font-medium">3D preview</p>
        <p className="text-[11px] text-[#52525B] leading-relaxed">
          Renders automatically after PCB completion — FR4 substrate, copper layers,
          solder mask, silkscreen, and component bodies.
        </p>
      </div>
      <p className="text-[9px] text-[#3D3D3D] font-mono">Maker plan · visual inspection before ordering</p>
    </div>
  );
}

const POWER_PREFIXES = ['GND', 'VSS', 'VCC', 'VDD', 'VIN', 'VOUT', '3V3', '5V', '12V'];
function netClass(net: string): string {
  const u = net.toUpperCase();
  if (POWER_PREFIXES.some((p) => u === p || u.startsWith('GND') || u.startsWith('VSS'))) {
    return 'border-[#1A2A1A] text-[#52A052] bg-[#0D160D]';
  }
  if (POWER_PREFIXES.some((p) => u.startsWith(p))) {
    return 'border-[#2A1E0D] text-[#A07030] bg-[#160F05]';
  }
  return 'border-[#1E1E1E] text-[#3D3D3D] bg-[#0D0D0D]';
}

function SchemaNetlistView({ pcbState, netsVisible = false }: { pcbState: PCBState | null; netsVisible?: boolean }) {
  const raw = pcbState as Record<string, unknown> | null;
  const components = Array.isArray(raw?.['components']) ? (raw['components'] as SchemaComponent[]) : [];
  const nets = Array.isArray(raw?.['nets']) ? (raw['nets'] as string[]) : [];

  if (!components.length) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2">
        <FileText size={20} className="text-[#2E2E2E]" />
        <p className="text-[10px] text-[#2E2E2E] font-mono">
          Schematic available after agent generates the netlist
        </p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto p-4 space-y-5 bg-[#090909]">
      {/* Component table */}
      <div>
        <p className="text-[9px] text-[#3D3D3D] font-mono uppercase tracking-wider mb-2">
          Components — {components.length}
        </p>
        <div className="space-y-px">
          <div className="grid grid-cols-[3rem_1fr_5rem_4rem] gap-2 px-2 py-1 text-[9px] text-[#2E2E2E] font-mono uppercase tracking-wider">
            <span>Ref</span><span>Value</span><span>Footprint</span><span>LCSC</span>
          </div>
          {components.map((c) => (
            <div
              key={c.ref}
              className="grid grid-cols-[3rem_1fr_5rem_4rem] gap-2 px-2 py-1.5 rounded bg-[#0F0F0F] border border-[#181818] text-[10px] font-mono"
            >
              <span className="text-primary/60 shrink-0">{c.ref}</span>
              <span className="text-[#A1A1AA] truncate">{c.value}</span>
              <span className="text-[#52525B] truncate">{c.footprint}</span>
              <span className="text-[#3D3D3D]">{c.lcsc ?? '—'}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Net chips — only in Schematic mode */}
      {netsVisible && nets.length > 0 && (
        <div>
          <p className="text-[9px] text-[#3D3D3D] font-mono uppercase tracking-wider mb-2">
            Nets — {nets.length}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {nets.map((net) => (
              <span
                key={net}
                className={`px-2 py-0.5 rounded border text-[9px] font-mono ${netClass(net)}`}
              >
                {net}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** Components tab — BOM only (no nets) */
function ComponentsBOMView({ pcbState }: { pcbState: PCBState | null }) {
  const raw = pcbState as Record<string, unknown> | null;
  const components = Array.isArray(raw?.['components']) ? (raw['components'] as SchemaComponent[]) : [];

  if (!components.length) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2">
        <Cpu size={20} className="text-[#2E2E2E]" />
        <p className="text-[10px] text-[#2E2E2E] font-mono">
          BOM available after agent generates the schematic
        </p>
      </div>
    );
  }

  // Group by value+footprint for BOM summary
  const grouped = components.reduce<Record<string, { refs: string[]; value: string; footprint: string; lcsc: string | undefined }>>(
    (acc, c) => {
      const key = `${c.value}||${c.footprint}`;
      if (!acc[key]) acc[key] = { refs: [], value: c.value, footprint: c.footprint, lcsc: c.lcsc };
      acc[key].refs.push(c.ref);
      return acc;
    },
    {}
  );
  const bomRows = Object.values(grouped).sort((a, b) => (a.refs[0] ?? '').localeCompare(b.refs[0] ?? ''));

  return (
    <div className="h-full overflow-auto p-4 bg-[#090909]">
      <div className="flex items-center justify-between mb-3">
        <p className="text-[9px] text-[#3D3D3D] font-mono uppercase tracking-wider">
          Bill of Materials — {components.length} refs · {bomRows.length} unique
        </p>
      </div>
      <div className="space-y-px">
        <div className="grid grid-cols-[2rem_2fr_2fr_3rem_3rem] gap-2 px-2 py-1 text-[9px] text-[#2E2E2E] font-mono uppercase tracking-wider border-b border-[#1A1A1A]">
          <span>Qty</span><span>Value</span><span>Footprint</span><span>LCSC</span><span>Refs</span>
        </div>
        {bomRows.map((row) => (
          <div
            key={`${row.value}-${row.footprint}`}
            className="grid grid-cols-[2rem_2fr_2fr_3rem_3rem] gap-2 px-2 py-2 rounded bg-[#0F0F0F] border border-[#181818] text-[10px] font-mono hover:border-[#252525] transition-colors"
          >
            <span className="text-primary/70 font-bold">{row.refs.length}</span>
            <span className="text-[#A1A1AA] truncate">{row.value}</span>
            <span className="text-[#52525B] truncate">{row.footprint}</span>
            <span className="text-[#3D3D3D]">{row.lcsc ?? '—'}</span>
            <span className="text-[#3D3D3D] truncate">{row.refs.join(', ')}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
