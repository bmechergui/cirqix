'use client';

import dynamic from 'next/dynamic';
import { useState, useEffect } from 'react';
import { Layers, Box, Download, ZoomIn, ZoomOut, Maximize2, Eye, EyeOff, Cpu, Ruler, Activity } from 'lucide-react';
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

type ViewMode = '2d' | '3d';

interface ViewerPanelProps {
  projectId?: string;
}

export function ViewerPanel({ projectId }: ViewerPanelProps) {
  const [mode, setMode] = useState<ViewMode>('2d');
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
        <div className="flex items-center gap-1 bg-[#141414] rounded-lg p-1">
          <button
            type="button"
            onClick={() => setMode('2d')}
            className={`flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-medium transition-colors ${
              mode === '2d'
                ? 'bg-primary/20 text-primary'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            <Layers size={12} />
            2D
          </button>
          <button
            type="button"
            onClick={() => setMode('3d')}
            className={`flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-medium transition-colors ${
              mode === '3d'
                ? 'bg-primary/20 text-primary'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            <Box size={12} />
            3D
          </button>
        </div>

        <div className="flex items-center gap-1">
          <Button
            variant="ghost" size="icon" className="h-7 w-7" aria-label="Zoom in"
            disabled={!zoomControls}
            onClick={() => zoomControls?.zoomIn()}
          >
            <ZoomIn size={13} />
          </Button>
          <Button
            variant="ghost" size="icon" className="h-7 w-7" aria-label="Zoom out"
            disabled={!zoomControls}
            onClick={() => zoomControls?.zoomOut()}
          >
            <ZoomOut size={13} />
          </Button>
          <Button
            variant="ghost" size="icon" className="h-7 w-7" aria-label="Reset zoom"
            disabled={!zoomControls}
            onClick={() => zoomControls?.resetZoom()}
          >
            <Maximize2 size={13} />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1.5 text-xs"
            disabled={!pcbState || !projectId}
            onClick={() => {
              if (projectId) window.location.assign(`/api/projects/${projectId}/export`);
            }}
          >
            <Download size={12} />
            Gerbers
          </Button>
        </div>
      </div>

      {/* Viewer area */}
      <div className="flex-1 relative overflow-hidden">
        {mode === '2d' ? (
          <>
            <PixiCanvas
              pcbState={pcbState}
              layerVisibility={layerVisibility}
              onReady={setZoomControls}
            />
            {!(pcbState?.circuit_json?.length) && (
              <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#0d0d0d]/90 pointer-events-none">
                <PCBMetadataPanel pcbState={pcbState} agentStep={agentStep} />
              </div>
            )}
          </>
        ) : (
          <PCBViewer3DPlaceholder />
        )}
      </div>

      {/* Layer legend + toggles (2D only) */}
      {mode === '2d' && (
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

function PCBMetadataPanel({
  pcbState,
  agentStep,
}: {
  pcbState: PCBState | null;
  agentStep: AgentStep;
}) {
  const placement = pcbState?.placement as { placements?: unknown[] } | undefined;
  const componentCount = placement?.placements?.length ?? 0;
  const boardW = pcbState?.board_width_mm;
  const boardH = pcbState?.board_height_mm;
  const status = pcbState?.status ?? 'INITIAL';
  const iteration = pcbState?.iteration ?? 0;

  return (
    <div className="pointer-events-none flex flex-col items-center gap-4">
      <div className="w-12 h-12 rounded-xl bg-[#141414] border border-border flex items-center justify-center">
        <Layers size={24} className="text-primary/40" />
      </div>

      <div className="bg-[#111111] border border-border rounded-lg p-4 w-56">
        <p className="text-[10px] text-[#52525B] font-mono uppercase tracking-wider mb-3">
          PCB Metadata
        </p>
        <div className="grid grid-cols-2 gap-x-4 gap-y-2">
          <div className="flex items-center gap-1.5">
            <Ruler size={10} className="text-[#52525B] shrink-0" />
            <span className="text-[10px] text-[#71717A]">Board</span>
          </div>
          <span className="text-[10px] text-[#A1A1AA] font-mono text-right">
            {boardW && boardH ? `${boardW}×${boardH}mm` : '--'}
          </span>

          <div className="flex items-center gap-1.5">
            <Cpu size={10} className="text-[#52525B] shrink-0" />
            <span className="text-[10px] text-[#71717A]">Components</span>
          </div>
          <span className="text-[10px] text-[#A1A1AA] font-mono text-right">
            {componentCount > 0 ? componentCount : '--'}
          </span>

          <div className="flex items-center gap-1.5">
            <Activity size={10} className="text-[#52525B] shrink-0" />
            <span className="text-[10px] text-[#71717A]">Status</span>
          </div>
          <span className="text-[10px] text-[#A1A1AA] font-mono text-right truncate">
            {status}
          </span>

          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-[#52525B]">#</span>
            <span className="text-[10px] text-[#71717A]">Iteration</span>
          </div>
          <span className="text-[10px] text-[#A1A1AA] font-mono text-right">
            {iteration}
          </span>
        </div>
      </div>

      {agentStep && (
        <div className="flex items-center gap-2 bg-[#111111] border border-border rounded-full px-3 py-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse shrink-0" />
          <span className="text-[10px] text-[#A1A1AA] font-mono">
            {STEP_LABELS[agentStep]}
          </span>
        </div>
      )}

      {!agentStep && status === 'INITIAL' && (
        <p className="text-[11px] text-[#52525B] text-center max-w-[180px]">
          Describe your circuit in the chat to start designing
        </p>
      )}
    </div>
  );
}

function PCBViewer3DPlaceholder() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-3 text-center p-8">
      <div className="w-16 h-16 rounded-xl bg-[#141414] border border-border flex items-center justify-center">
        <Box size={32} className="text-primary/50" />
      </div>
      <p className="text-xs text-muted-foreground max-w-xs">
        3D viewer available on{' '}
        <span className="text-amber-400 font-medium">Maker</span> plan and above.
        Generate your PCB first to preview it in 3D.
      </p>
      <p className="text-[10px] text-[#52525B] max-w-[220px] mt-1">
        The 3D view renders a realistic preview of your assembled PCB — components,
        solder mask, silkscreen, and copper layers — ready for visual inspection
        before ordering.
      </p>
    </div>
  );
}
