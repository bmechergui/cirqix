'use client';

/**
 * SchemaCanvas — datasheet-pro electronic schematic renderer.
 *
 * Layout philosophy: components are grouped into labeled functional blocks
 * (POWER INPUT / INPUT FILTER / CORE / OUTPUT FILTER / OUTPUT + optional SIGNAL
 * row above). Each block is a bordered region with an uppercase title bar,
 * mimicking manufacturer datasheets.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FileText } from 'lucide-react';
import type { PCBState } from '@layrix/types';
import { layoutSchema, type LayoutResult } from '../lib/schema-layout';

const ZOOM_FACTOR = 1.15;
const MIN_SCALE = 0.25;
const MAX_SCALE = 4;
const NET_LABEL_COLOR = '#71717A';
const BLOCK_BORDER = '#2A2A2A';
const BLOCK_LABEL = '#A1A1AA';

interface ViewBox { x: number; y: number; w: number; h: number }

export function SchemaCanvas({ pcbState }: { pcbState: PCBState | null }) {
  const components = pcbState?.components ?? [];
  const connections = pcbState?.connections ?? [];

  const layout: LayoutResult = useMemo(
    () => layoutSchema(components, connections),
    [components, connections],
  );

  const [vb, setVb] = useState<ViewBox>({ x: 0, y: 0, w: layout.width, h: layout.height });
  const dragRef = useRef<{ sx: number; sy: number; vbx: number; vby: number } | null>(null);

  useEffect(() => {
    setVb({ x: 0, y: 0, w: layout.width, h: layout.height });
  }, [layout.width, layout.height]);

  const resetView = useCallback(() => {
    setVb({ x: 0, y: 0, w: layout.width, h: layout.height });
  }, [layout.width, layout.height]);

  const onWheel = useCallback((e: React.WheelEvent<SVGSVGElement>) => {
    e.preventDefault();
    const rect = e.currentTarget.getBoundingClientRect();
    const mx = (e.clientX - rect.left) / rect.width;
    const my = (e.clientY - rect.top) / rect.height;
    setVb(prev => {
      const scale = e.deltaY < 0 ? 1 / ZOOM_FACTOR : ZOOM_FACTOR;
      const nw = Math.min(layout.width / MIN_SCALE, Math.max(layout.width / MAX_SCALE, prev.w * scale));
      const nh = Math.min(layout.height / MIN_SCALE, Math.max(layout.height / MAX_SCALE, prev.h * scale));
      return { x: prev.x + (prev.w - nw) * mx, y: prev.y + (prev.h - nh) * my, w: nw, h: nh };
    });
  }, [layout.width, layout.height]);

  const onMouseDown = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (e.button !== 0) return;
    dragRef.current = { sx: e.clientX, sy: e.clientY, vbx: vb.x, vby: vb.y };
    e.currentTarget.style.cursor = 'grabbing';
  }, [vb.x, vb.y]);

  const onMouseMove = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (!dragRef.current) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const dx = (e.clientX - dragRef.current.sx) * (vb.w / rect.width);
    const dy = (e.clientY - dragRef.current.sy) * (vb.h / rect.height);
    setVb(prev => ({ ...prev, x: dragRef.current!.vbx - dx, y: dragRef.current!.vby - dy }));
  }, [vb.w, vb.h]);

  const onMouseUp = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    dragRef.current = null;
    e.currentTarget.style.cursor = 'grab';
  }, []);

  if (!components.length) return <SchemaEmptyState />;

  // Title block dimensions
  const tbW = 260, tbH = 64;
  const tbX = layout.width - tbW - 30;
  const tbY = layout.height - tbH - 30;

  return (
    <div className="relative h-full bg-[#070707] overflow-hidden select-none">
      {/* Top-left meta */}
      <div className="absolute top-3 left-4 z-10 flex items-center gap-3 pointer-events-none">
        <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-[#A1A1AA]">Schematic</span>
        <span className="text-[10px] font-mono text-[#52525B]">
          {components.length} comp.<span className="text-[#2A2A2A]"> · </span>
          {layout.nets.length} nets<span className="text-[#2A2A2A]"> · </span>
          {layout.blocks.length} blocks
        </span>
      </div>

      <button
        type="button"
        onClick={resetView}
        className="absolute top-3 right-3 z-10 px-2 py-1 text-[10px] font-mono uppercase tracking-wider text-[#A1A1AA] border border-[#1F1F1F] rounded bg-[#0D0D0D]/80 hover:text-foreground hover:border-[#2E2E2E] transition-colors"
      >
        fit
      </button>

      <p className="absolute bottom-2 left-4 text-[9px] text-[#3D3D3D] font-mono pointer-events-none">
        scroll to zoom · drag to pan
      </p>

      <svg
        width="100%"
        height="100%"
        viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
        style={{ cursor: 'grab', display: 'block' }}
        onWheel={onWheel}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseUp}
        preserveAspectRatio="xMidYMid meet"
      >
        <defs>
          <pattern id="schDots" x="0" y="0" width="22" height="22" patternUnits="userSpaceOnUse">
            <circle cx="0.5" cy="0.5" r="0.5" fill="#1a1a1a" />
          </pattern>
        </defs>
        <rect x={0} y={0} width={layout.width} height={layout.height} fill="url(#schDots)" />

        {/* Sheet border */}
        <rect
          x={16} y={16}
          width={layout.width - 32} height={layout.height - 32}
          fill="none" stroke="#1A1A1A" strokeWidth={1}
        />

        {/* Functional blocks (drawn first so wires sit on top) */}
        {layout.blocks.map((b, i) => (
          <g key={`block-${i}`}>
            {/* Block border */}
            <rect
              x={b.x} y={b.y}
              width={b.width} height={b.height}
              fill="#0A0A0A"
              stroke={BLOCK_BORDER}
              strokeWidth={1}
              rx={2}
            />
            {/* Label band */}
            <line
              x1={b.x} y1={b.y + 24}
              x2={b.x + b.width} y2={b.y + 24}
              stroke="#1F1F1F" strokeWidth={0.8}
            />
            {/* Label */}
            <text
              x={b.x + 12} y={b.y + 16}
              fontSize={10} fontFamily="monospace"
              fontWeight={600}
              letterSpacing={1.4}
              fill={BLOCK_LABEL}
            >
              {b.label}
            </text>
            {/* Count chip on the right */}
            <text
              x={b.x + b.width - 12} y={b.y + 16}
              fontSize={9} fontFamily="monospace"
              textAnchor="end"
              fill="#52525B"
            >
              {b.componentRefs.length}
            </text>
          </g>
        ))}

        {/* Wires */}
        {layout.nets.map((net, i) => (
          <g key={`net-${i}`}>
            {net.segments.map((s, si) => (
              <line key={si}
                x1={s.x1} y1={s.y1} x2={s.x2} y2={s.y2}
                stroke={net.color}
                strokeWidth={net.isPower ? 2 : net.isGround ? 1.6 : 1.5}
                opacity={net.isPower || net.isGround ? 0.85 : 0.92}
              />
            ))}
            {net.junctions.map((j, ji) => (
              <circle key={`j${ji}`} cx={j.x} cy={j.y} r={2.5} fill={net.color} />
            ))}
            {!net.isPower && !net.isGround && net.segments.length > 0 && (() => {
              const s = net.segments[0]!;
              const mx = (s.x1 + s.x2) / 2;
              const my = Math.min(s.y1, s.y2) - 4;
              return (
                <text x={mx} y={my} textAnchor="middle" fontSize={9}
                  fontFamily="monospace" fill={NET_LABEL_COLOR}>
                  {net.name}
                </text>
              );
            })()}
          </g>
        ))}

        {/* Symbols */}
        {layout.placed.map((p) => (
          <React.Fragment key={p.ref}>
            {p.symbol.render({ ox: p.ox, oy: p.oy, ref: p.sourceRef ?? '', value: p.value })}
          </React.Fragment>
        ))}

        {/* ISO-style title block bottom-right */}
        <g>
          <rect
            x={tbX} y={tbY}
            width={tbW} height={tbH}
            fill="#0d0d0d"
            stroke="#3A3A3A"
            strokeWidth={1.2}
          />
          {/* Internal divisions */}
          <line x1={tbX} y1={tbY + 22} x2={tbX + tbW} y2={tbY + 22} stroke="#2A2A2A" strokeWidth={0.8} />
          <line x1={tbX + 130} y1={tbY + 22} x2={tbX + 130} y2={tbY + tbH} stroke="#2A2A2A" strokeWidth={0.8} />
          {/* Brand */}
          <text x={tbX + 8} y={tbY + 15} fontSize={9} fontFamily="monospace" fontWeight={600} letterSpacing={1.5} fill="#E07B39">
            LAYRIX
          </text>
          <text x={tbX + tbW - 8} y={tbY + 15} fontSize={8} fontFamily="monospace" textAnchor="end" fill="#71717A">
            AI PCB DESIGN
          </text>
          {/* Left cell: schematic info */}
          <text x={tbX + 8} y={tbY + 36} fontSize={7} fontFamily="monospace" fill="#52525B">SCHEMATIC</text>
          <text x={tbX + 8} y={tbY + 50} fontSize={9} fontFamily="monospace" fill="#C8C8CB">
            {components.length} comp · {layout.nets.length} nets
          </text>
          <text x={tbX + 8} y={tbY + 60} fontSize={7} fontFamily="monospace" fill="#52525B">
            {layout.blocks.length} blocks
          </text>
          {/* Right cell: sheet meta */}
          <text x={tbX + 138} y={tbY + 36} fontSize={7} fontFamily="monospace" fill="#52525B">SHEET</text>
          <text x={tbX + 138} y={tbY + 50} fontSize={9} fontFamily="monospace" fill="#C8C8CB">1 / 1</text>
          <text x={tbX + 138} y={tbY + 60} fontSize={7} fontFamily="monospace" fill="#52525B">REV A · {new Date().toISOString().slice(0, 10)}</text>
        </g>
      </svg>
    </div>
  );
}

function SchemaEmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 text-center p-8 bg-[#070707]">
      <div className="w-16 h-16 rounded-xl bg-[#141414] border border-border flex items-center justify-center">
        <FileText size={32} className="text-primary/30" />
      </div>
      <div className="space-y-1.5 max-w-[260px]">
        <p className="text-xs text-[#A1A1AA] font-medium">Schematic</p>
        <p className="text-[11px] text-[#52525B] leading-relaxed">
          Generated by the Schematic agent — functional blocks, EDA symbols,
          power flags and orthogonal wires.
        </p>
      </div>
      <p className="text-[9px] text-[#3D3D3D] font-mono">Describe your circuit in the chat to begin</p>
    </div>
  );
}
