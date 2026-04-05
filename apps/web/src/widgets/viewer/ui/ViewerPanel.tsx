'use client';

import dynamic from 'next/dynamic';
import React, { useState, useEffect } from 'react';
import { Layers, Box, Download, ZoomIn, ZoomOut, Maximize2, Eye, EyeOff, FileText, Cpu, Route } from 'lucide-react';
import { Button } from '@/shared/ui/button';
import { useAppStore } from '@/shared/store/app-store';
import { LAYER_COLORS, DEFAULT_LAYER_VISIBILITY, colorToHex } from '../lib/layers';
import type { ZoomControls } from '../lib/renderer';
import type { PCBState, SchemaComponent, SchemaNet } from '@layrix/types';

// PixiJS ne fonctionne pas côté serveur → dynamic import obligatoire
const PixiCanvas = dynamic(() => import('./PixiCanvas').then((m) => m.PixiCanvas), {
  ssr: false,
  loading: () => <PCBPlaceholder />,
});

type ViewMode = 'routing' | '3d' | 'schematic' | 'components';

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
              { id: 'schematic',  icon: <FileText size={12} />, label: 'Schematic' },
              { id: 'routing',    icon: <Route size={12} />,    label: 'Routing' },
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
          <>
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
          </>
        ) : mode === 'schematic' ? (
          <SchemaNetlistView pcbState={pcbState} />
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

const FOOTPRINT_PAD_COUNT: Record<string, number> = {
  '0402': 2, '0603': 2, '0805': 2, '1206': 2, 'LED': 2,
  'SOT-23': 3, 'SOT-23-5': 5, 'TSSOP-8': 8, 'DIP-8': 8,
};

function getPadCount(footprint: string): number {
  const key = Object.keys(FOOTPRINT_PAD_COUNT).find(
    (k) => footprint.toUpperCase().includes(k.toUpperCase())
  );
  return FOOTPRINT_PAD_COUNT[key ?? '0402'] ?? 2;
}

const NET_PALETTE = [
  '#D4820A', '#4488FF', '#22C55E', '#F59E0B', '#A855F7',
  '#EC4899', '#06B6D4', '#F97316', '#84CC16', '#EF4444',
];

function SchemaNetlistView({ pcbState }: { pcbState: PCBState | null }) {
  const components: SchemaComponent[] = pcbState?.components ?? [];
  const connections: SchemaNet[] = pcbState?.connections ?? [];
  const nets: string[] = pcbState?.nets ?? [];

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

  // --- SVG layout constants ---
  const BOX_W = 90;
  const BOX_H = 48;
  const GAP_X = 50;
  const GAP_Y = 70;
  const COLS = Math.min(5, components.length);
  const ROWS = Math.ceil(components.length / COLS);
  const PAD_Y = BOX_H + 8; // pins drawn below the box

  const svgW = COLS * (BOX_W + GAP_X) + GAP_X;
  const svgH = ROWS * (BOX_H + GAP_Y) + GAP_Y + 20;

  const compPos = components.map((_, i) => ({
    x: (i % COLS) * (BOX_W + GAP_X) + GAP_X,
    y: Math.floor(i / COLS) * (BOX_H + GAP_Y) + GAP_Y,
  }));

  const compIdxByRef = new Map(components.map((c, i) => [c.ref, i]));

  // Pin position: evenly spaced across bottom edge of box
  function pinPos(ref: string, pin: number): { x: number; y: number } | null {
    const idx = compIdxByRef.get(ref);
    if (idx === undefined) return null;
    const pos = compPos[idx]!;
    const total = getPadCount(components[idx]!.footprint);
    return {
      x: pos.x + ((pin) / (total + 1)) * BOX_W,
      y: pos.y + PAD_Y,
    };
  }

  return (
    <div className="h-full overflow-auto bg-[#090909] p-4">
      {/* SVG schematic diagram */}
      <svg
        width={svgW}
        height={svgH}
        viewBox={`0 0 ${svgW} ${svgH}`}
        className="block"
        style={{ minWidth: svgW }}
      >
        {/* Ratsnest lines */}
        {connections.map((conn, netIdx) => {
          const color = NET_PALETTE[netIdx % NET_PALETTE.length]!;
          const pts = conn.pins.map((p) => pinPos(p.ref, p.pin)).filter(Boolean) as Array<{ x: number; y: number }>;
          if (pts.length < 2) return null;
          return (
            <g key={conn.name}>
              {pts.slice(1).map((pt, i) => (
                <line
                  key={i}
                  x1={pts[i]!.x} y1={pts[i]!.y}
                  x2={pt.x} y2={pt.y}
                  stroke={color} strokeWidth={1.5}
                  strokeDasharray="5 3" opacity={0.7}
                />
              ))}
              {/* Net label near first pin */}
              {pts[0] && (
                <text
                  x={pts[0].x + 3} y={pts[0].y + 11}
                  fill={color} fontSize={7} fontFamily="monospace" opacity={0.9}
                >
                  {conn.name}
                </text>
              )}
            </g>
          );
        })}

        {/* Component boxes */}
        {components.map((comp, i) => {
          const pos = compPos[i]!;
          const padCount = getPadCount(comp.footprint);
          return (
            <g key={comp.ref}>
              {/* Box */}
              <rect
                x={pos.x} y={pos.y} width={BOX_W} height={BOX_H}
                fill="#0F0F0F" stroke="#2E2E2E" strokeWidth={1} rx={4}
              />
              {/* Ref */}
              <text
                x={pos.x + BOX_W / 2} y={pos.y + 16}
                fill="#D4820A" fontSize={10} fontFamily="monospace"
                textAnchor="middle" fontWeight="600"
              >
                {comp.ref}
              </text>
              {/* Value */}
              <text
                x={pos.x + BOX_W / 2} y={pos.y + 29}
                fill="#A1A1AA" fontSize={8} fontFamily="monospace" textAnchor="middle"
              >
                {comp.value.length > 12 ? comp.value.slice(0, 12) + '…' : comp.value}
              </text>
              {/* Footprint */}
              <text
                x={pos.x + BOX_W / 2} y={pos.y + 40}
                fill="#3D3D3D" fontSize={7} fontFamily="monospace" textAnchor="middle"
              >
                {comp.footprint}
              </text>
              {/* Pin dots */}
              {Array.from({ length: padCount }, (_, k) => {
                const p = pinPos(comp.ref, k + 1)!;
                return (
                  <circle key={k} cx={p.x} cy={p.y} r={2.5}
                    fill="#1A1A1A" stroke="#3D3D3D" strokeWidth={1}
                  />
                );
              })}
            </g>
          );
        })}
      </svg>

      {/* Fallback: net chips when no connections data */}
      {connections.length === 0 && nets.length > 0 && (
        <div className="mt-4">
          <p className="text-[9px] text-[#3D3D3D] font-mono uppercase tracking-wider mb-2">
            Nets — {nets.length}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {nets.map((net, i) => (
              <span
                key={net}
                className="px-2 py-0.5 rounded border text-[9px] font-mono"
                style={{
                  color: NET_PALETTE[i % NET_PALETTE.length],
                  borderColor: `${NET_PALETTE[i % NET_PALETTE.length]}40`,
                  backgroundColor: `${NET_PALETTE[i % NET_PALETTE.length]}10`,
                }}
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
  const components: SchemaComponent[] = pcbState?.components ?? [];

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
