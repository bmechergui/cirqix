'use client';

import dynamic from 'next/dynamic';
import { useState, useEffect } from 'react';
import { Layers, Box, Download, ZoomIn, ZoomOut, Eye, EyeOff } from 'lucide-react';
import { Button } from '@/shared/ui/button';
import { useAppStore } from '@/shared/store/app-store';
import { LAYER_COLORS, DEFAULT_LAYER_VISIBILITY, colorToHex } from '../lib/layers';

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

  const pcbState = useAppStore((s) =>
    projectId ? s.pcbStateByProject[projectId] ?? null : null
  );
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
          <Button variant="ghost" size="icon" className="h-7 w-7" aria-label="Zoom in" disabled>
            <ZoomIn size={13} />
          </Button>
          <Button variant="ghost" size="icon" className="h-7 w-7" aria-label="Zoom out" disabled>
            <ZoomOut size={13} />
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
          <PixiCanvas pcbState={pcbState} layerVisibility={layerVisibility} />
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
    </div>
  );
}
