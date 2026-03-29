'use client';

import { useState } from 'react';
import { Layers, Box, Download, ZoomIn, ZoomOut } from 'lucide-react';
import { Button } from '@/components/ui/button';

type ViewMode = '2d' | '3d';

const LAYER_COLORS: Record<string, string> = {
  'F.Cu': '#cc0000',
  'B.Cu': '#0000cc',
  'F.SilkS': '#ffffff',
  'B.SilkS': '#888888',
  'F.Mask': '#cc00cc',
  'Edge.Cuts': '#ffff00',
};

export function ViewerPanel() {
  const [mode, setMode] = useState<ViewMode>('2d');

  return (
    <div className="flex flex-col h-full bg-[#0d0d0d]">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border">
        <div className="flex items-center gap-1 bg-[#141414] rounded-lg p-1">
          <button
            type="button"
            onClick={() => setMode('2d')}
            className={`flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-medium transition-colors ${
              mode === '2d' ? 'bg-primary/20 text-primary' : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            <Layers size={12} />
            2D
          </button>
          <button
            type="button"
            onClick={() => setMode('3d')}
            className={`flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-medium transition-colors ${
              mode === '3d' ? 'bg-primary/20 text-primary' : 'text-muted-foreground hover:text-foreground'
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
          <Button variant="ghost" size="sm" className="h-7 gap-1.5 text-xs">
            <Download size={12} />
            Gerbers
          </Button>
        </div>
      </div>

      {/* Viewer area */}
      <div className="flex-1 relative overflow-hidden flex items-center justify-center">
        {mode === '2d' ? <PCBMockup2D /> : <PCBMockup3D />}
      </div>

      {/* Layer legend (2D only) */}
      {mode === '2d' && (
        <div className="flex flex-wrap gap-2 px-4 py-2 border-t border-border">
          {Object.entries(LAYER_COLORS).map(([layer, color]) => (
            <div key={layer} className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
              <span className="text-[10px] text-muted-foreground font-mono">{layer}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PCBMockup2D() {
  return (
    <svg viewBox="0 0 400 300" className="w-full max-w-lg opacity-80" xmlns="http://www.w3.org/2000/svg">
      {/* PCB board */}
      <rect x="20" y="20" width="360" height="260" rx="4" fill="#1a3300" stroke="#ffff00" strokeWidth="1.5" />
      {/* Traces F.Cu */}
      <path d="M60 80 L200 80 L200 150" stroke="#cc0000" strokeWidth="2" fill="none" />
      <path d="M200 150 L320 150 L320 220" stroke="#cc0000" strokeWidth="2" fill="none" />
      <path d="M60 220 L150 220 L150 150 L200 150" stroke="#cc0000" strokeWidth="2" fill="none" />
      {/* Traces B.Cu */}
      <path d="M100 100 L100 200 L260 200" stroke="#0000cc" strokeWidth="1.5" fill="none" />
      {/* Components */}
      <rect x="50" y="68" width="20" height="24" rx="2" fill="#2a2a2a" stroke="#888888" strokeWidth="1" />
      <rect x="189" y="139" width="22" height="22" rx="2" fill="#2a2a2a" stroke="#888888" strokeWidth="1" />
      <rect x="309" y="209" width="22" height="22" rx="2" fill="#2a2a2a" stroke="#888888" strokeWidth="1" />
      {/* IC chip */}
      <rect x="130" y="110" width="60" height="60" rx="3" fill="#111111" stroke="#aaaaaa" strokeWidth="1" />
      <text x="160" y="143" textAnchor="middle" fill="#666" fontSize="8" fontFamily="monospace">IC1</text>
      {/* Via holes */}
      {[[200, 150], [150, 200], [260, 200]].map(([cx, cy], i) => (
        <circle key={i} cx={cx} cy={cy} r="4" fill="#0d1a00" stroke="#888" strokeWidth="1" />
      ))}
      {/* Silkscreen labels */}
      <text x="52" y="64" fill="#ffffff" fontSize="7" fontFamily="monospace">R1</text>
      <text x="191" y="135" fill="#ffffff" fontSize="7" fontFamily="monospace">C1</text>
    </svg>
  );
}

function PCBMockup3D() {
  return (
    <div className="flex flex-col items-center gap-3 text-center p-8">
      <div className="w-16 h-16 rounded-xl bg-[#141414] border border-border flex items-center justify-center">
        <Box size={32} className="text-primary/50" />
      </div>
      <p className="text-xs text-muted-foreground max-w-xs">
        3D viewer available on <span className="text-amber-400 font-medium">Maker</span> plan and above.
        Generate your PCB first to preview it in 3D.
      </p>
    </div>
  );
}
