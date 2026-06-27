'use client';

import { useMemo, useState, useRef, useLayoutEffect, useCallback, useEffect } from 'react';
import { 
  Layers, 
  ZoomIn, 
  ZoomOut, 
  Maximize2, 
  List, 
  LayoutGrid, 
  RotateCcw,
  Sparkles,
  Cpu,
  Info
} from 'lucide-react';
import type { PCBState } from '@cirqix/types';
import { Button } from '@/shared/ui/button';
import { StageHeader } from './StageHeader';
import { KiCanvasViewer } from './KiCanvasViewer';
import { ViewModeSwitch, type ViewMode } from './ViewModeSwitch';
import { layoutBoard, type PlacedComponent } from '../lib/layout-engine';
import { cn } from '@/shared/lib/utils';

// ─── Types & Constants ────────────────────────────────────────────────────────

type LayerTab = 'top' | 'bottom' | 'both';
type PcbTab   = 'canvas' | 'list';
type SolderMaskTheme = 'green' | 'black' | 'blue' | 'purple';

const PX_PER_MM = 6;
const mm = (v: number) => v * PX_PER_MM;

const KIND_STYLE: Record<PlacedComponent['kind'], { fill: string; stroke: string; ref: string; body: string }> = {
  IC:    { fill: '#0b111a', stroke: '#257fd3', ref: '#60b2ff', body: '#3c628f' },
  CAP:   { fill: '#0a1414', stroke: '#158467', ref: '#2ec4b6', body: '#1f5f4d' },
  RES:   { fill: '#140f09', stroke: '#b85c14', ref: '#ff9f1c', body: '#7d3f0f' },
  DIODE: { fill: '#140a1a', stroke: '#9b5de5', ref: '#c77dff', body: '#5c338c' },
  LED:   { fill: '#1a0a0a', stroke: '#e63946', ref: '#ff4d6d', body: '#901a1e' },
  CONN:  { fill: '#111111', stroke: '#555555', ref: '#bbbbbb', body: '#444444' },
  MISC:  { fill: '#111111', stroke: '#444444', ref: '#888888', body: '#333333' },
};

const LAYER_OPTS = [
  { id: 'top'    as const, label: 'Top',    sub: 'F.Cu', color: '#00C2FF' },
  { id: 'bottom' as const, label: 'Bottom', sub: 'B.Cu', color: '#D4820A' },
  { id: 'both'   as const, label: 'Both',   sub: 'F+B',  color: '#888'   },
];

const SOLDER_MASKS: Record<SolderMaskTheme, {
  name: string;
  fillGradStart: string;
  fillGradEnd: string;
  stroke: string;
  pourStroke: string;
  bgDotColor: string;
  viaRing: string;
}> = {
  green: {
    name: 'Classic Green',
    fillGradStart: '#0f3513',
    fillGradEnd: '#081d0a',
    stroke: '#1b5a22',
    pourStroke: '#0e3012',
    bgDotColor: 'rgba(34, 197, 94, 0.04)',
    viaRing: '#b89c30',
  },
  black: {
    name: 'Matte Black',
    fillGradStart: '#141414',
    fillGradEnd: '#090909',
    stroke: '#2b2b2b',
    pourStroke: '#141414',
    bgDotColor: 'rgba(255, 255, 255, 0.015)',
    viaRing: '#a3a3a3',
  },
  blue: {
    name: 'Classic Blue',
    fillGradStart: '#0d253f',
    fillGradEnd: '#051121',
    stroke: '#164375',
    pourStroke: '#0a1d33',
    bgDotColor: 'rgba(0, 194, 255, 0.04)',
    viaRing: '#b89c30',
  },
  purple: {
    name: 'Maker Purple',
    fillGradStart: '#260a3c',
    fillGradEnd: '#11031d',
    stroke: '#4e1978',
    pourStroke: '#1c072e',
    bgDotColor: 'rgba(168, 85, 247, 0.04)',
    viaRing: '#cfa930',
  },
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function sortByRef(a: PlacedComponent, b: PlacedComponent) {
  const parse = (r: string) => {
    const m = r.match(/^([A-Za-z]+)(\d+)$/);
    return m ? ([m[1]!, parseInt(m[2]!)] as [string, number]) : ([r, 0] as [string, number]);
  };
  const [pa, na] = parse(a.ref);
  const [pb, nb] = parse(b.ref);
  return pa < pb ? -1 : pa > pb ? 1 : na - nb;
}

// ─── Component Pads Renderer Helper ─────────────────────────────────────────

interface PadsProps {
  c: PlacedComponent;
  style: typeof KIND_STYLE['IC'];
}

function ComponentPads({ c, style }: PadsProps) {
  const cw = mm(c.w);
  const ch = mm(c.h);
  
  // Render pads depending on component kind
  if (c.kind === 'IC') {
    // Render dual row SOIC/DIP style pads
    const pinCount = 8; // default to 8 pins for demo layout
    const padsPerSide = pinCount / 2;
    const spacing = ch / (padsPerSide + 1);
    const pads: React.ReactNode[] = [];
    
    for (let i = 0; i < padsPerSide; i++) {
      const y = spacing * (i + 1);
      // Left side pads
      pads.push(
        <rect
          key={`l-pad-${i}`}
          x={-1.5}
          y={y - 0.75}
          width={2.2}
          height={1.5}
          fill="#c5a85c"
          stroke="#ffd700"
          strokeWidth={0.3}
          rx={0.2}
        />
      );
      // Right side pads
      pads.push(
        <rect
          key={`r-pad-${i}`}
          x={cw - 0.7}
          y={y - 0.75}
          width={2.2}
          height={1.5}
          fill="#c5a85c"
          stroke="#ffd700"
          strokeWidth={0.3}
          rx={0.2}
        />
      );
    }
    return <>{pads}</>;
  }

  if (c.kind === 'CONN') {
    // Through-hole pads
    const pinCount = 2; // assume 2 pins for connectors
    const spacing = cw / (pinCount + 1);
    const pads: React.ReactNode[] = [];
    
    for (let i = 0; i < pinCount; i++) {
      const x = spacing * (i + 1);
      pads.push(
        <g key={`conn-pad-${i}`}>
          <circle
            cx={x}
            cy={ch / 2}
            r={1.8}
            fill="#c5a85c"
            stroke="#ffd700"
            strokeWidth={0.4}
          />
          {/* Drill hole */}
          <circle
            cx={x}
            cy={ch / 2}
            r={0.9}
            fill="#060606"
          />
        </g>
      );
    }
    return <>{pads}</>;
  }

  // Passives (SMD 2-terminal packages: RES, CAP, LED, DIODE)
  // Render two large pads at the outer ends
  return (
    <>
      {/* Left Pad */}
      <rect
        x={-0.6}
        y={0.2}
        width={1.6}
        height={ch - 0.4}
        fill="#c5a85c"
        stroke="#ffd700"
        strokeWidth={0.3}
        rx={0.25}
      />
      {/* Right Pad */}
      <rect
        x={cw - 1.0}
        y={0.2}
        width={1.6}
        height={ch - 0.4}
        fill="#c5a85c"
        stroke="#ffd700"
        strokeWidth={0.3}
        rx={0.25}
      />
    </>
  );
}

// ─── Placement List Tab ───────────────────────────────────────────────────────

function PlacementList({ placed }: { placed: PlacedComponent[] }) {
  const sorted = useMemo(() => [...placed].sort(sortByRef), [placed]);

  if (sorted.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-xs text-[#3d3d3d] font-mono">
        No placements
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto">
      <table className="w-full text-xs">
        <thead className="sticky top-0 z-10">
          <tr className="text-left text-[9px] uppercase tracking-widest text-[#555] bg-[#0c0d12] border-b border-[#1c1c24]">
            <th className="px-4 py-3.5 font-medium w-16">Ref</th>
            <th className="px-4 py-3.5 font-medium">Value</th>
            <th className="px-4 py-3.5 font-medium w-24 text-right">X (mm)</th>
            <th className="px-4 py-3.5 font-medium w-24 text-right">Y (mm)</th>
            <th className="px-4 py-3.5 font-medium hidden sm:table-cell">Size</th>
            <th className="px-4 py-3.5 font-medium hidden md:table-cell">Footprint</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[#16161f]">
          {sorted.map((c) => {
            const style = KIND_STYLE[c.kind];
            return (
              <tr key={c.ref} className="hover:bg-[#14141d]/50 transition-colors">
                <td className="px-4 py-3">
                  <span className="font-mono font-bold text-[11px]" style={{ color: style.ref }}>
                    {c.ref}
                  </span>
                </td>
                <td className="px-4 py-3 text-foreground/80 text-[11px] font-medium">{c.value}</td>
                <td className="px-4 py-3 font-mono text-[10px] text-right font-semibold" style={{ color: style.ref }}>
                  {c.x.toFixed(2)}
                </td>
                <td className="px-4 py-3 font-mono text-[10px] text-right font-semibold" style={{ color: style.ref }}>
                  {c.y.toFixed(2)}
                </td>
                <td className="px-4 py-3 font-mono text-[10px] text-muted-foreground hidden sm:table-cell">
                  {c.w.toFixed(1)} × {c.h.toFixed(1)}
                </td>
                <td className="px-4 py-3 font-mono text-[10px] text-muted-foreground/60 hidden md:table-cell truncate max-w-[140px]">
                  {c.footprint}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Board SVG Canvas ─────────────────────────────────────────────────────────

interface BoardCanvasProps {
  placed: PlacedComponent[];
  widthMm: number;
  heightMm: number;
  layer: LayerTab;
  showRouting: boolean;
  maskTheme: SolderMaskTheme;
  hoveredComp: PlacedComponent | null;
  setHoveredComp: (c: PlacedComponent | null) => void;
  traces: Array<{ x1: number; y1: number; x2: number; y2: number; net: string; layer: 'F' | 'B' }>;
}

function BoardCanvas({ 
  placed, 
  widthMm, 
  heightMm, 
  layer, 
  showRouting, 
  maskTheme,
  hoveredComp,
  setHoveredComp,
  traces 
}: BoardCanvasProps) {
  const PAD = 44;
  const svgW = mm(widthMm);
  const svgH = mm(heightMm);
  const totalW = svgW + PAD * 2;
  const totalH = svgH + PAD * 2;

  const activeMask = SOLDER_MASKS[maskTheme];

  const visibleTraces = traces.filter(
    (t) => layer === 'both' || (layer === 'top' ? t.layer === 'F' : t.layer === 'B'),
  );

  return (
    <svg
      width={totalW}
      height={totalH}
      viewBox={`0 0 ${totalW} ${totalH}`}
      xmlns="http://www.w3.org/2000/svg"
      className="select-none"
    >
      <defs>
        <pattern id="pcbGrid" width="8" height="8" patternUnits="userSpaceOnUse">
          <circle cx="4" cy="4" r="0.55" fill={activeMask.bgDotColor} />
        </pattern>
        <linearGradient id="fr4-mask" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={activeMask.fillGradStart} />
          <stop offset="100%" stopColor={activeMask.fillGradEnd} />
        </linearGradient>
        <filter id="comp-glow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="1.5" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
      </defs>

      {/* Outer dot grid */}
      <rect width={totalW} height={totalH} fill="url(#pcbGrid)" />

      {/* Ruler ticks — top edge */}
      {Array.from({ length: Math.floor(widthMm / 5) + 1 }, (_, i) => i * 5).map((tick) => (
        <g key={`tx-${tick}`}>
          <line
            x1={PAD + mm(tick)} y1={PAD - 6}
            x2={PAD + mm(tick)} y2={PAD - 2}
            stroke="#1a1a24" strokeWidth={0.8}
          />
          <text
            x={PAD + mm(tick)} y={PAD - 10}
            textAnchor="middle"
            fill="#444455"
            fontSize={6.5}
            fontWeight={600}
            fontFamily="ui-monospace, monospace"
          >
            {tick}
          </text>
        </g>
      ))}
      
      {/* Ruler ticks — left edge */}
      {Array.from({ length: Math.floor(heightMm / 5) + 1 }, (_, i) => i * 5).map((tick) => (
        <g key={`ty-${tick}`}>
          <line
            x1={PAD - 6} y1={PAD + mm(tick)}
            x2={PAD - 2} y2={PAD + mm(tick)}
            stroke="#1a1a24" strokeWidth={0.8}
          />
          <text
            x={PAD - 10} y={PAD + mm(tick) + 2.5}
            textAnchor="end"
            fill="#444455"
            fontSize={6.5}
            fontWeight={600}
            fontFamily="ui-monospace, monospace"
          >
            {tick}
          </text>
        </g>
      ))}

      <g transform={`translate(${PAD}, ${PAD})`}>
        {/* Board body — Solder Mask themed */}
        <rect 
          x={0} 
          y={0} 
          width={svgW} 
          height={svgH} 
          rx={5}
          fill="url(#fr4-mask)" 
          stroke={activeMask.stroke} 
          strokeWidth={1.5} 
          className="transition-all duration-300"
          style={{ filter: 'drop-shadow(0 4px 12px rgba(0,0,0,0.35))' }}
        />

        {/* Copper pour hint (GND plane) */}
        <rect 
          x={2.5} 
          y={2.5} 
          width={svgW - 5} 
          height={svgH - 5} 
          rx={4}
          fill="none" 
          stroke={activeMask.pourStroke} 
          strokeWidth={1.0} 
          strokeDasharray="2 3" 
        />

        {/* Mounting holes */}
        {[[3.5, 3.5], [widthMm - 3.5, 3.5], [3.5, heightMm - 3.5], [widthMm - 3.5, heightMm - 3.5]].map(([x, y], i) => (
          <g key={i}>
            <circle cx={mm(x!)} cy={mm(y!)} r={4.5} fill="#0d0d12" stroke={activeMask.viaRing} strokeWidth={0.8} />
            <circle cx={mm(x!)} cy={mm(y!)} r={2.0} fill="#050508" />
          </g>
        ))}

        {/* Traces */}
        {showRouting && visibleTraces.map((t, i) => {
          const color = t.layer === 'F' ? '#ff3b30' : '#007aff'; // Red for Front, Blue for Back
          const op = t.layer === 'F' ? 0.9 : 0.6;
          const midX = (mm(t.x1) + mm(t.x2)) / 2;
          
          return (
            <g key={i}>
              <path
                d={`M ${mm(t.x1)} ${mm(t.y1)} L ${midX} ${mm(t.y1)} L ${midX} ${mm(t.y2)} L ${mm(t.x2)} ${mm(t.y2)}`}
                stroke={color} 
                strokeWidth={1.6} 
                fill="none"
                strokeLinecap="round" 
                strokeLinejoin="round" 
                opacity={op}
              />
              {/* Copper Vias at the ends for realism */}
              <circle cx={mm(t.x1)} cy={mm(t.y1)} r={1.2} fill={activeMask.viaRing} />
              <circle cx={mm(t.x2)} cy={mm(t.y2)} r={1.2} fill={activeMask.viaRing} />
            </g>
          );
        })}

        {/* Component Pads (Solder joints) */}
        {placed.map((c) => {
          const s = KIND_STYLE[c.kind];
          const cx = mm(c.x);
          const cy = mm(c.y);
          return (
            <g key={`pads-${c.ref}`} transform={`translate(${cx}, ${cy})`} opacity={hoveredComp && hoveredComp.ref !== c.ref ? 0.4 : 1.0}>
              <ComponentPads c={c} style={s} />
            </g>
          );
        })}

        {/* Component Silkscreen and Bodies */}
        {placed.map((c) => {
          const s = KIND_STYLE[c.kind];
          const cw = mm(c.w);
          const ch = mm(c.h);
          const cx = mm(c.x);
          const cy = mm(c.y);
          const isIC = c.kind === 'IC';
          const isHovered = hoveredComp?.ref === c.ref;

          return (
            <g 
              key={c.ref} 
              transform={`translate(${cx}, ${cy})`}
              className="cursor-pointer transition-opacity duration-200"
              opacity={hoveredComp && hoveredComp.ref !== c.ref ? 0.35 : 1.0}
              onMouseEnter={() => setHoveredComp(c)}
              onMouseLeave={() => setHoveredComp(null)}
            >
              {/* Silkscreen outline (rendered in white for real look) */}
              <rect 
                x={-0.6}
                y={-0.6}
                width={cw + 1.2}
                height={ch + 1.2}
                rx={2.2}
                fill="none"
                stroke="rgba(255, 255, 255, 0.45)"
                strokeWidth={0.4}
                strokeDasharray="4 2"
              />

              {/* Component Body */}
              <rect 
                width={cw} 
                height={ch} 
                rx={1.8}
                fill={s.fill} 
                stroke={isHovered ? '#00e5ff' : s.stroke} 
                strokeWidth={isHovered ? 1.4 : isIC ? 1.0 : 0.7}
                style={{
                  filter: isHovered ? 'url(#comp-glow)' : 'none',
                  transition: 'all 0.15s ease'
                }}
              />

              {/* IC Header Band & Pin 1 indicator */}
              {isIC && cw > 12 && (
                <>
                  <rect 
                    width={cw} 
                    height={Math.min(6, ch * 0.28)} 
                    rx={1}
                    fill={s.body} 
                    opacity={0.35} 
                  />
                  <circle cx={2.5} cy={2.5} r={1.0} fill={s.ref} opacity={0.9} />
                </>
              )}

              {/* Ref inside box */}
              <text
                x={cw / 2} 
                y={ch / 2 + (ch > 8 ? -2 : 2)}
                textAnchor="middle" 
                dominantBaseline="middle"
                fill={isHovered ? '#ffffff' : s.ref} 
                fontSize={Math.min(6.5, cw / 2.2)}
                fontFamily="ui-monospace, monospace" 
                fontWeight={700}
                className="transition-colors duration-150"
              >
                {c.ref}
              </text>

              {/* Value below ref */}
              {ch > 10 && (
                <text
                  x={cw / 2} 
                  y={ch / 2 + 5}
                  textAnchor="middle" 
                  dominantBaseline="middle"
                  fill={s.body} 
                  fontSize={Math.min(4.8, cw / 3)}
                  fontFamily="ui-monospace, monospace"
                  opacity={0.8}
                >
                  {c.value.length > 7 ? `${c.value.slice(0, 5)}..` : c.value}
                </text>
              )}
            </g>
          );
        })}
      </g>

      {/* Title block */}
      <text
        x={PAD} y={totalH - 12}
        fill="#3a3a4c" 
        fontSize={7.5}
        fontWeight={600}
        fontFamily="ui-monospace, monospace" 
        letterSpacing="0.12em"
      >
        CIRQIX.AI · {widthMm}×{heightMm} mm · {placed.length} COMPONENTS{showRouting ? ` · ${visibleTraces.length} COPPER TRACES` : ''}
      </text>
    </svg>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

interface PcbViewProps {
  state: PCBState;
  title?: string;
  showRouting?: boolean;
}

export function PcbView({ state, title = 'PCB Layout', showRouting = false }: PcbViewProps) {
  const [zoom, setZoom]   = useState(1.0);
  const [pan, setPan]     = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [layer, setLayer] = useState<LayerTab>('both');
  const [pcbTab, setPcbTab] = useState<PcbTab>('canvas');
  const [maskTheme, setMaskTheme] = useState<SolderMaskTheme>('green');
  const [hoveredComp, setHoveredComp] = useState<PlacedComponent | null>(null);

  const dragStart = useRef({ x: 0, y: 0 });
  const canvasContainerRef = useRef<HTMLDivElement>(null);

  const nativeUrl = state.kicad_pcb_url;
  const [mode, setMode] = useState<ViewMode>(nativeUrl ? 'native' : 'spec');
  const effectiveMode: ViewMode = nativeUrl ? mode : 'spec';

  const widthMm  = state.board_width_mm  ?? 50;
  const heightMm = state.board_height_mm ?? 40;

  // Auto-fit: compute zoom and offset so board is perfectly centered and visible
  const computeFitZoom = useCallback(() => {
    const el = canvasContainerRef.current;
    if (!el) return;
    const svgW = widthMm  * PX_PER_MM + 44 * 2;
    const svgH = heightMm * PX_PER_MM + 44 * 2;
    const fit = Math.min((el.clientWidth * 0.85) / svgW, (el.clientHeight * 0.85) / svgH);
    const z = Math.max(0.4, Math.min(3.0, fit));
    
    setZoom(z);
    setPan({
      x: (el.clientWidth - svgW * z) / 2,
      y: (el.clientHeight - svgH * z) / 2
    });
  }, [widthMm, heightMm]);

  useLayoutEffect(() => {
    if (pcbTab === 'canvas' && effectiveMode === 'spec') {
      computeFitZoom();
    }
  }, [computeFitZoom, pcbTab, effectiveMode]);

  // Handle Resize
  useEffect(() => {
    const handleResize = () => {
      if (pcbTab === 'canvas' && effectiveMode === 'spec') {
        computeFitZoom();
      }
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [computeFitZoom, pcbTab, effectiveMode]);

  // Drag handlers
  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return; // Only left click drags
    setIsDragging(true);
    dragStart.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging) return;
    setPan({
      x: e.clientX - dragStart.current.x,
      y: e.clientY - dragStart.current.y
    });
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  // Wheel zoom centered on cursor
  const handleWheel = (e: React.WheelEvent) => {
    const zoomFactor = 1.08;
    let newZoom = zoom;
    if (e.deltaY < 0) {
      newZoom = Math.min(zoom * zoomFactor, 4.0);
    } else {
      newZoom = Math.max(zoom / zoomFactor, 0.35);
    }

    const rect = canvasContainerRef.current?.getBoundingClientRect();
    if (rect) {
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      
      const svgMouseX = (mouseX - pan.x) / zoom;
      const svgMouseY = (mouseY - pan.y) / zoom;

      setZoom(newZoom);
      setPan({
        x: mouseX - svgMouseX * newZoom,
        y: mouseY - svgMouseY * newZoom
      });
    }
  };

  // Touch handlers for mobile
  const handleTouchStart = (e: React.TouchEvent) => {
    if (e.touches.length === 1) {
      const t = e.touches[0]!;
      setIsDragging(true);
      dragStart.current = { x: t.clientX - pan.x, y: t.clientY - pan.y };
    }
  };

  const handleTouchMove = (e: React.TouchEvent) => {
    if (!isDragging || e.touches.length !== 1) return;
    const t = e.touches[0]!;
    setPan({
      x: t.clientX - dragStart.current.x,
      y: t.clientY - dragStart.current.y
    });
  };

  const handleTouchEnd = () => {
    setIsDragging(false);
  };

  const components  = useMemo(() => state.components  ?? [], [state.components]);
  const connections = useMemo(() => state.connections ?? [], [state.connections]);

  const placed = useMemo(
    () => layoutBoard(components, widthMm, heightMm),
    [components, widthMm, heightMm],
  );

  const traces = useMemo(() => {
    if (!showRouting) return [];
    type Trace = { x1: number; y1: number; x2: number; y2: number; net: string; layer: 'F' | 'B' };
    const out: Trace[] = [];
    const byRef = new Map(placed.map((c) => [c.ref, c]));
    connections.forEach((conn, ci) => {
      if (conn.pins.length < 2) return;
      if (/^GND$/i.test(conn.name)) return;
      const anchors = conn.pins
        .map((p) => byRef.get(p.ref))
        .filter((c): c is PlacedComponent => Boolean(c))
        .map((c) => ({ x: c.x + c.w / 2, y: c.y + c.h / 2 }));
      for (let i = 1; i < anchors.length; i++) {
        const a = anchors[i - 1]!;
        const b = anchors[i]!;
        out.push({ x1: a.x, y1: a.y, x2: b.x, y2: b.y, net: conn.name, layer: ci % 2 === 0 ? 'F' : 'B' });
      }
    });
    return out;
  }, [connections, placed, showRouting]);

  const meta = `${widthMm}×${heightMm} mm · ${components.length} comp${components.length !== 1 ? 's' : ''}${showRouting ? ` · ${traces.length} traces` : ''}`;

  return (
    <div className="flex flex-col h-full bg-[#08080c] overflow-hidden">
      <StageHeader
        icon={<Layers size={12} />}
        title={title}
        meta={meta}
        actions={
          <div className="flex items-center gap-2">
            <ViewModeSwitch mode={effectiveMode} onChange={setMode} nativeDisabled={!nativeUrl} />
            {effectiveMode === 'spec' && pcbTab === 'canvas' && (
              <>
                {/* Solder Mask Color Picker in Header */}
                <div className="flex items-center gap-1 bg-[#16161f] rounded-lg p-0.5 border border-[#2e2e38] ml-1">
                  {(['green', 'black', 'blue', 'purple'] as SolderMaskTheme[]).map((themeName) => (
                    <button
                      key={themeName}
                      onClick={() => setMaskTheme(themeName)}
                      title={`Solder Mask: ${SOLDER_MASKS[themeName].name}`}
                      className={`w-3.5 h-3.5 rounded-full border transition-all ${
                        maskTheme === themeName ? 'border-white scale-110 shadow-lg' : 'border-transparent opacity-50 hover:opacity-100'
                      }`}
                      style={{
                        backgroundColor: SOLDER_MASKS[themeName].fillGradStart,
                      }}
                    />
                  ))}
                </div>
              </>
            )}
          </div>
        }
      />

      {effectiveMode === 'native' && nativeUrl ? (
        <KiCanvasViewer src={nativeUrl} zoom="objects" />
      ) : (
        <>
          {/* Sub-tab bar */}
          <div className="flex items-center justify-between px-3 py-2 border-b border-[#14141c] bg-[#0c0d12] shrink-0">
            <div className="flex items-center gap-1">
              {([
                { id: 'canvas' as const, icon: <LayoutGrid size={10} />, label: 'Board', count: undefined },
                { id: 'list'   as const, icon: <List size={10} />,       label: 'Placements',    count: placed.length },
              ]).map(({ id, icon, label, count }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setPcbTab(id)}
                  className={cn(
                    'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-all duration-150',
                    pcbTab === id
                      ? 'bg-primary/10 text-primary border border-primary/20'
                      : 'text-[#667] hover:text-[#99a] hover:bg-[#1a1a24]/50 border border-transparent',
                  )}
                >
                  {icon}
                  {label}
                  {typeof count === 'number' && (
                    <span className={cn(
                      'text-[9px] font-mono px-1.5 py-0.5 rounded leading-none font-bold',
                      pcbTab === id ? 'bg-primary/15 text-primary' : 'bg-[#1a1a24] text-[#445]',
                    )}>
                      {count}
                    </span>
                  )}
                </button>
              ))}
            </div>

            {/* Layer filter — only on canvas tab when routing is shown */}
            {pcbTab === 'canvas' && showRouting && (
              <div className="flex items-center gap-0.5 bg-[#14141c] rounded-lg p-0.5 border border-[#2e2e38]">
                {LAYER_OPTS.map((opt) => (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => setLayer(opt.id)}
                    className={cn(
                      'flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-medium transition-all duration-150',
                      layer === opt.id
                        ? 'text-[#e0e0e0] bg-[#22222e] border border-[#3e3e4a]'
                        : 'text-[#556] hover:text-[#889]',
                    )}
                  >
                    <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: opt.color }} />
                    {opt.label}
                    <span className="font-mono text-[8px] text-[#445]">{opt.sub}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="flex-1 min-h-0 overflow-hidden relative">
            {pcbTab === 'canvas' && (
              <div
                ref={canvasContainerRef}
                className="h-full w-full overflow-hidden bg-[#050508] relative cursor-grab active:cursor-grabbing"
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseUp={handleMouseUp}
                onMouseLeave={handleMouseUp}
                onWheel={handleWheel}
                onTouchStart={handleTouchStart}
                onTouchMove={handleTouchMove}
                onTouchEnd={handleTouchEnd}
              >
                {/* Transformed SVG wrapper */}
                <div
                  style={{
                    transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                    transformOrigin: '0 0',
                    transition: isDragging ? 'none' : 'transform 0.1s ease-out'
                  }}
                  className="pointer-events-none"
                >
                  {/* Re-enable pointer events inside BoardCanvas for hovers */}
                  <div className="pointer-events-auto">
                    <BoardCanvas
                      placed={placed}
                      widthMm={widthMm}
                      heightMm={heightMm}
                      layer={layer}
                      showRouting={showRouting}
                      maskTheme={maskTheme}
                      hoveredComp={hoveredComp}
                      setHoveredComp={setHoveredComp}
                      traces={traces}
                    />
                  </div>
                </div>

                {/* Hover HUD Tooltip in Canvas Area */}
                {hoveredComp && (
                  <div className="absolute top-4 left-4 bg-[#0a0b10]/90 border border-white/5 shadow-2xl p-4 rounded-xl backdrop-blur-md w-60 text-xs pointer-events-none space-y-2.5 animate-fade-in">
                    <div className="flex items-center justify-between border-b border-white/5 pb-1.5">
                      <span className="font-mono font-bold text-sm" style={{ color: KIND_STYLE[hoveredComp.kind].ref }}>
                        {hoveredComp.ref}
                      </span>
                      <span className="text-[9px] uppercase font-mono tracking-widest text-[#556] bg-[#1a1a24] px-1.5 py-0.5 rounded">
                        {hoveredComp.kind}
                      </span>
                    </div>
                    <div className="space-y-1 text-[#99a] font-mono text-[10px]">
                      <div className="flex justify-between">
                        <span>Value:</span>
                        <span className="text-foreground/90 font-sans font-semibold">{hoveredComp.value}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Footprint:</span>
                        <span className="truncate max-w-[120px]" title={hoveredComp.footprint}>{hoveredComp.footprint}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Dimensions:</span>
                        <span>{hoveredComp.w.toFixed(1)} × {hoveredComp.h.toFixed(1)} mm</span>
                      </div>
                      <div className="flex justify-between border-t border-white/5 pt-1.5 text-primary">
                        <span>Location (X, Y):</span>
                        <span className="font-bold">({hoveredComp.x.toFixed(2)}, {hoveredComp.y.toFixed(2)}) mm</span>
                      </div>
                    </div>
                  </div>
                )}

                {/* Floating zoom controls */}
                <div className="absolute bottom-4 right-4 flex items-center gap-1.5 p-1.5 rounded-xl border border-white/5 shadow-2xl backdrop-blur-md bg-[#0c0d12]/85">
                  <button
                    onClick={() => setZoom(z => Math.min(z * 1.1, 4.0))}
                    title="Zoom In"
                    className="p-1.5 rounded-lg text-[#889] hover:text-white hover:bg-white/[0.04] transition-colors"
                  >
                    <ZoomIn className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => setZoom(z => Math.max(z / 1.1, 0.35))}
                    title="Zoom Out"
                    className="p-1.5 rounded-lg text-[#889] hover:text-white hover:bg-white/[0.04] transition-colors"
                  >
                    <ZoomOut className="w-4 h-4" />
                  </button>
                  <button
                    onClick={computeFitZoom}
                    title="Fit to Screen"
                    className="p-1.5 rounded-lg text-[#889] hover:text-white hover:bg-white/[0.04] transition-colors"
                  >
                    <Maximize2 className="w-4 h-4" />
                  </button>
                  <div className="w-[1px] h-4 bg-white/10" />
                  <button
                    onClick={computeFitZoom}
                    title="Reset Grid"
                    className="p-1.5 rounded-lg text-[#889] hover:text-white hover:bg-white/[0.04] transition-colors"
                  >
                    <RotateCcw className="w-4 h-4" />
                  </button>
                </div>
              </div>
            )}
            {pcbTab === 'list' && <PlacementList placed={placed} />}
          </div>
        </>
      )}
    </div>
  );
}
