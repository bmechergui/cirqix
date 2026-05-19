'use client';

import { useMemo } from 'react';
import type { SchemaComponent, SchemaNet } from '@layrix/types';
import { buildSchematicLayout, netColor, type SchematicNode } from '../lib/schematic-layout';

interface SchematicGraphProps {
  components: SchemaComponent[];
  connections: SchemaNet[];
}

// Layout constants — EDA-grade proportions
const NODE_W = 162;
const HDR_H = 40;
const PIN_H = 17;
const PIN_PAD = 6;
const PIN_STUB = 8;        // stub length extending outside box
const COL_GAP = 88;
const ROW_GAP = 32;
const COL_X = [20, 228, 448, 668, 878];
const SVG_MARGIN_TOP = 56;
const SVG_MARGIN_BOTTOM = 24;

function nodeH(pinCount: number): number {
  return HDR_H + Math.max(pinCount, 1) * PIN_H + PIN_PAD * 2;
}

function nodePos(nodes: SchematicNode[], node: SchematicNode) {
  const x = COL_X[node.col] ?? 20 + node.col * (NODE_W + COL_GAP);
  const before = nodes.filter((n) => n.col === node.col && n.row < node.row);
  const y = SVG_MARGIN_TOP + before.reduce((s, n) => s + nodeH(n.pinRows.length) + ROW_GAP, 0);
  return { x, y, h: nodeH(node.pinRows.length) };
}

function pinY(pos: { y: number }, rowIndex: number): number {
  return pos.y + HDR_H + PIN_PAD + rowIndex * PIN_H + PIN_H / 2;
}

function pinAnchor(
  nodes: SchematicNode[],
  ref: string,
  pin: string,
  side: 'left' | 'right',
): { x: number; y: number } | null {
  const node = nodes.find((n) => n.ref === ref);
  if (!node) return null;
  const pos = nodePos(nodes, node);
  const idx = node.pinRows.findIndex((p) => p.pin === pin);
  const py = pinY(pos, idx >= 0 ? idx : 0);
  return {
    x: side === 'left' ? pos.x - PIN_STUB : pos.x + NODE_W + PIN_STUB,
    y: py,
  };
}

// True if the net is a power supply rail
function isPowerNet(name: string) {
  return /^(VCC|VDD|VIN|VBUS|VBAT|3V3|5V|12V|PWR)/i.test(name);
}
function isGndNet(name: string) {
  return /^GND$/i.test(name);
}

export function SchematicGraph({ components, connections }: SchematicGraphProps) {
  const { nodes, wires } = useMemo(
    () => buildSchematicLayout(components, connections),
    [components, connections],
  );

  const svgH = useMemo(() => {
    let max = 0;
    for (let c = 0; c <= 4; c++) {
      const col = nodes.filter((n) => n.col === c);
      const h = col.reduce((s, n) => s + nodeH(n.pinRows.length) + ROW_GAP, 0);
      max = Math.max(max, h);
    }
    return Math.max(300, SVG_MARGIN_TOP + max + SVG_MARGIN_BOTTOM);
  }, [nodes]);

  const svgW = 1060;

  if (nodes.length === 0) return null;

  const colLabels = ['INPUT', 'DECOUPLING', 'CORE', 'OUTPUT CAPS', 'OUTPUT'] as const;

  return (
    <div className="rounded-xl border border-border bg-[#080808] overflow-hidden">
      <header className="flex items-center justify-between px-4 py-2.5 border-b border-[#1e1e1e] bg-[#0b0b0b]">
        <span className="text-xs font-semibold text-foreground tracking-wide">Connectivity</span>
        <span className="text-[10px] font-mono text-[#3d3d3d] uppercase tracking-widest">
          {nodes.length} components · {wires.length} connections
        </span>
      </header>

      <div className="overflow-auto">
        <svg
          width={svgW}
          height={svgH}
          viewBox={`0 0 ${svgW} ${svgH}`}
          xmlns="http://www.w3.org/2000/svg"
        >
          <defs>
            {/* Fine dot grid — KiCad dark theme style */}
            <pattern id="eda-grid" width="16" height="16" patternUnits="userSpaceOnUse">
              <circle cx="8" cy="8" r="0.6" fill="rgba(255,255,255,0.045)" />
            </pattern>
            {/* IC header gradient */}
            <linearGradient id="ic-hdr" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#0c1e35" />
              <stop offset="100%" stopColor="#070d18" />
            </linearGradient>
            {/* Passive header gradient */}
            <linearGradient id="pass-hdr" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#131313" />
              <stop offset="100%" stopColor="#0d0d0d" />
            </linearGradient>
            {/* IC glow filter */}
            <filter id="ic-glow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur in="SourceGraphic" stdDeviation="2.5" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
          </defs>

          {/* Background grid */}
          <rect width={svgW} height={svgH} fill="url(#eda-grid)" />

          {/* Column zone dividers */}
          {colLabels.map((label, col) => {
            if (nodes.filter((n) => n.col === col).length === 0) return null;
            const x = (COL_X[col] ?? 0) - 8;
            return (
              <line
                key={col}
                x1={x}
                y1={SVG_MARGIN_TOP - 12}
                x2={x}
                y2={svgH - SVG_MARGIN_BOTTOM}
                stroke="#1a1a1a"
                strokeWidth={1}
                strokeDasharray="3 4"
              />
            );
          })}

          {/* Column labels */}
          {colLabels.map((label, col) => {
            if (nodes.filter((n) => n.col === col).length === 0) return null;
            const x = (COL_X[col] ?? 0) + NODE_W / 2;
            return (
              <text
                key={label}
                x={x}
                y={SVG_MARGIN_TOP - 14}
                textAnchor="middle"
                fill="#2e2e2e"
                fontSize={8.5}
                fontFamily="ui-monospace, monospace"
                letterSpacing="0.12em"
                fontWeight={600}
              >
                {label}
              </text>
            );
          })}

          {/* Wires */}
          {wires.map((w, i) => {
            const from = pinAnchor(nodes, w.fromRef, w.fromPin, 'right');
            const to = pinAnchor(nodes, w.toRef, w.toPin, 'left');
            if (!from || !to) return null;
            const color = netColor(w.net);
            // Bezier curve for organic look, clamp midX between the two endpoints
            const midX = Math.max(from.x + 4, Math.min(to.x - 4, (from.x + to.x) / 2));
            const d = `M ${from.x} ${from.y} C ${midX} ${from.y}, ${midX} ${to.y}, ${to.x} ${to.y}`;
            const isPwr = isPowerNet(w.net);
            const isGnd = isGndNet(w.net);
            return (
              <g key={`w-${i}`}>
                <path
                  d={d}
                  stroke={color}
                  strokeWidth={isPwr || isGnd ? 1.4 : 1.1}
                  fill="none"
                  opacity={0.75}
                  strokeDasharray={isGnd ? '3 2' : undefined}
                />
                {/* Endpoint junction dots */}
                <circle cx={from.x} cy={from.y} r={2.2} fill={color} opacity={0.9} />
                <circle cx={to.x} cy={to.y} r={2.2} fill={color} opacity={0.9} />
              </g>
            );
          })}

          {/* Nodes */}
          {nodes.map((node) => {
            const pos = nodePos(nodes, node);
            const isIC = node.role === 'IC';
            const borderColor = isIC ? '#1d5fa0' : '#2a2a2a';
            const hdrFill = isIC ? 'url(#ic-hdr)' : 'url(#pass-hdr)';
            const refColor = isIC ? '#5baeff' : '#00C2FF';

            return (
              <g key={node.ref}>
                {/* Optional glow for IC */}
                {isIC && (
                  <rect
                    x={pos.x - 1}
                    y={pos.y - 1}
                    width={NODE_W + 2}
                    height={pos.h + 2}
                    rx={5}
                    fill="none"
                    stroke="#1a4878"
                    strokeWidth={2}
                    opacity={0.5}
                    filter="url(#ic-glow)"
                  />
                )}
                {/* Body */}
                <rect
                  x={pos.x}
                  y={pos.y}
                  width={NODE_W}
                  height={pos.h}
                  rx={4}
                  fill="#0e0e0e"
                  stroke={borderColor}
                  strokeWidth={isIC ? 1.2 : 0.8}
                />
                {/* Header band */}
                <rect
                  x={pos.x}
                  y={pos.y}
                  width={NODE_W}
                  height={HDR_H}
                  rx={4}
                  fill={hdrFill}
                />
                {/* Header bottom border */}
                <line
                  x1={pos.x}
                  y1={pos.y + HDR_H}
                  x2={pos.x + NODE_W}
                  y2={pos.y + HDR_H}
                  stroke={borderColor}
                  strokeWidth={0.6}
                />
                {/* Role badge */}
                {isIC && (
                  <text
                    x={pos.x + NODE_W - 6}
                    y={pos.y + 10}
                    textAnchor="end"
                    fill="#1d5fa0"
                    fontSize={7}
                    fontFamily="ui-monospace, monospace"
                    fontWeight={700}
                    letterSpacing="0.08em"
                  >
                    IC
                  </text>
                )}
                {/* Reference designator */}
                <text
                  x={pos.x + 8}
                  y={pos.y + 16}
                  fill={refColor}
                  fontSize={11}
                  fontWeight={700}
                  fontFamily="ui-monospace, monospace"
                >
                  {node.ref}
                </text>
                {/* Value */}
                <text
                  x={pos.x + 8}
                  y={pos.y + 30}
                  fill="#6b6b6b"
                  fontSize={9}
                  fontFamily="ui-monospace, monospace"
                >
                  {node.value}
                </text>

                {/* Pin rows */}
                {node.pinRows.map((p, i) => {
                  const py = pinY(pos, i);
                  const color = netColor(p.net);
                  const isPwr = isPowerNet(p.net);
                  const isGnd = isGndNet(p.net);
                  return (
                    <g key={`${node.ref}-pin-${i}`}>
                      {/* Row separator */}
                      {i > 0 && (
                        <line
                          x1={pos.x + 1}
                          y1={py - PIN_H / 2}
                          x2={pos.x + NODE_W - 1}
                          y2={py - PIN_H / 2}
                          stroke="#161616"
                          strokeWidth={0.6}
                        />
                      )}
                      {/* Pin stub — left side */}
                      <line
                        x1={pos.x - PIN_STUB}
                        y1={py}
                        x2={pos.x}
                        y2={py}
                        stroke="#2e2e2e"
                        strokeWidth={0.8}
                      />
                      {/* Pin number */}
                      <text
                        x={pos.x + 6}
                        y={py + 3}
                        fill="#3a3a3a"
                        fontSize={8}
                        fontFamily="ui-monospace, monospace"
                      >
                        {p.pin}
                      </text>
                      {/* Net name */}
                      <text
                        x={pos.x + NODE_W - PIN_STUB - 14}
                        y={py + 3}
                        textAnchor="end"
                        fill={isGnd ? '#525252' : isPwr ? '#D4820A' : '#8a8a8a'}
                        fontSize={8}
                        fontFamily="ui-monospace, monospace"
                      >
                        {p.net}
                      </text>
                      {/* Net color dot — right side */}
                      <circle cx={pos.x + NODE_W - 10} cy={py} r={2.5} fill={color} opacity={0.85} />
                      {/* Pin stub — right side */}
                      <line
                        x1={pos.x + NODE_W}
                        y1={py}
                        x2={pos.x + NODE_W + PIN_STUB}
                        y2={py}
                        stroke={color}
                        strokeWidth={0.8}
                        opacity={0.5}
                      />
                    </g>
                  );
                })}
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
