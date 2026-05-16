'use client';

import { useMemo } from 'react';
import type { SchemaComponent, SchemaNet } from '@layrix/types';
import { buildSchematicLayout, netColor, type SchematicNode } from '../lib/schematic-layout';

interface SchematicGraphProps {
  components: SchemaComponent[];
  connections: SchemaNet[];
}

const NODE_WIDTH = 130;
const NODE_HEADER_H = 28;
const PIN_ROW_H = 16;
const NODE_PADDING_V = 6;
const COL_GAP = 60;
const ROW_GAP = 24;
const COL_X = [40, 220, 410, 600, 780];

function nodeHeight(pinRows: number): number {
  return NODE_HEADER_H + Math.max(pinRows, 1) * PIN_ROW_H + NODE_PADDING_V * 2;
}

function colCount(nodes: SchematicNode[], col: number): number {
  return nodes.filter((n) => n.col === col).length;
}

function nodePosition(nodes: SchematicNode[], node: SchematicNode): { x: number; y: number; h: number } {
  const x = COL_X[node.col] ?? 40 + node.col * (NODE_WIDTH + COL_GAP);
  // Stack rows in this column
  const before = nodes.filter((n) => n.col === node.col && n.row < node.row);
  const yOffset = before.reduce((sum, n) => sum + nodeHeight(n.pinRows.length) + ROW_GAP, 0);
  const h = nodeHeight(node.pinRows.length);
  return { x, y: 50 + yOffset, h };
}

function pinAnchor(
  nodes: SchematicNode[],
  ref: string,
  pin: string,
  side: 'left' | 'right',
): { x: number; y: number } | null {
  const node = nodes.find((n) => n.ref === ref);
  if (!node) return null;
  const pos = nodePosition(nodes, node);
  const pinIndex = node.pinRows.findIndex((p) => p.pin === pin);
  const rowIndex = pinIndex >= 0 ? pinIndex : 0;
  return {
    x: side === 'left' ? pos.x : pos.x + NODE_WIDTH,
    y: pos.y + NODE_HEADER_H + NODE_PADDING_V + rowIndex * PIN_ROW_H + PIN_ROW_H / 2,
  };
}

export function SchematicGraph({ components, connections }: SchematicGraphProps) {
  const { nodes, wires } = useMemo(
    () => buildSchematicLayout(components, connections),
    [components, connections]
  );

  // Canvas size: width = last col x + width + margin, height = max col height
  const maxColHeight = useMemo(() => {
    let max = 0;
    for (let c = 0; c <= 4; c++) {
      const colNodes = nodes.filter((n) => n.col === c);
      const h = colNodes.reduce((sum, n) => sum + nodeHeight(n.pinRows.length) + ROW_GAP, 0);
      max = Math.max(max, h);
    }
    return max;
  }, [nodes]);

  const svgWidth = 940;
  const svgHeight = Math.max(280, 70 + maxColHeight);

  if (nodes.length === 0) return null;

  return (
    <div className="rounded-xl border border-border bg-[#0b0b0b] overflow-hidden">
      <header className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-[#0d0d0d]">
        <span className="text-xs font-semibold text-foreground">Connectivity diagram</span>
        <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
          {nodes.length} nodes · {wires.length} wires
        </span>
      </header>
      <div className="overflow-auto bg-[#0a0a0a]">
        <svg
          width={svgWidth}
          height={svgHeight}
          viewBox={`0 0 ${svgWidth} ${svgHeight}`}
          xmlns="http://www.w3.org/2000/svg"
        >
          <defs>
            <pattern id="schemGrid" width="20" height="20" patternUnits="userSpaceOnUse">
              <circle cx="10" cy="10" r="0.5" fill="rgba(255,255,255,0.04)" />
            </pattern>
          </defs>
          <rect x={0} y={0} width={svgWidth} height={svgHeight} fill="url(#schemGrid)" />

          {/* Column labels */}
          {(['INPUT', 'DECOUPLING', 'CORE', 'OUTPUT CAPS', 'OUTPUT'] as const).map((label, col) => {
            if (colCount(nodes, col) === 0) return null;
            const x = (COL_X[col] ?? 40) + NODE_WIDTH / 2;
            return (
              <text
                key={label}
                x={x}
                y={28}
                textAnchor="middle"
                fill="#52525B"
                fontSize={9}
                fontFamily="ui-monospace, monospace"
                letterSpacing="0.1em"
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
            // Manhattan-style: horizontal → vertical → horizontal
            const midX = (from.x + to.x) / 2;
            const d = `M ${from.x} ${from.y} L ${midX} ${from.y} L ${midX} ${to.y} L ${to.x} ${to.y}`;
            return (
              <g key={`${w.fromRef}.${w.fromPin}-${w.toRef}.${w.toPin}-${i}`}>
                <path d={d} stroke={color} strokeWidth={1.2} fill="none" opacity={0.85} />
                {/* Junction dots */}
                <circle cx={from.x} cy={from.y} r={2} fill={color} />
                <circle cx={to.x} cy={to.y} r={2} fill={color} />
                {/* Net label at midpoint */}
                <text
                  x={midX}
                  y={(from.y + to.y) / 2 - 4}
                  textAnchor="middle"
                  fill={color}
                  fontSize={8}
                  fontFamily="ui-monospace, monospace"
                  opacity={0.85}
                >
                  {w.net}
                </text>
              </g>
            );
          })}

          {/* Nodes */}
          {nodes.map((node) => {
            const pos = nodePosition(nodes, node);
            return (
              <g key={node.ref} transform={`translate(${pos.x}, ${pos.y})`}>
                <rect
                  width={NODE_WIDTH}
                  height={pos.h}
                  rx={6}
                  fill="#111111"
                  stroke={node.role === 'IC' ? '#00C2FF' : '#2E2E2E'}
                  strokeWidth={node.role === 'IC' ? 1.2 : 0.8}
                />
                <rect
                  width={NODE_WIDTH}
                  height={NODE_HEADER_H}
                  rx={6}
                  fill={node.role === 'IC' ? 'rgba(0,194,255,0.08)' : '#0d0d0d'}
                />
                <text
                  x={NODE_WIDTH / 2}
                  y={12}
                  textAnchor="middle"
                  fill="#00C2FF"
                  fontSize={10}
                  fontWeight={700}
                  fontFamily="ui-monospace, monospace"
                >
                  {node.ref}
                </text>
                <text
                  x={NODE_WIDTH / 2}
                  y={23}
                  textAnchor="middle"
                  fill="#A1A1AA"
                  fontSize={9}
                  fontFamily="ui-monospace, monospace"
                >
                  {node.value}
                </text>
                {/* Pin rows */}
                {node.pinRows.map((p, i) => {
                  const py = NODE_HEADER_H + NODE_PADDING_V + i * PIN_ROW_H + PIN_ROW_H / 2;
                  const color = netColor(p.net);
                  return (
                    <g key={`${node.ref}-${p.pin}-${i}`}>
                      {/* Pin number — left */}
                      <text
                        x={6}
                        y={py + 3}
                        fill="#71717A"
                        fontSize={8}
                        fontFamily="ui-monospace, monospace"
                      >
                        {p.pin}
                      </text>
                      {/* Net color dot */}
                      <circle cx={NODE_WIDTH - 12} cy={py} r={2.5} fill={color} />
                      {/* Net name — right */}
                      <text
                        x={NODE_WIDTH - 20}
                        y={py + 3}
                        textAnchor="end"
                        fill="#D4D4D8"
                        fontSize={8}
                        fontFamily="ui-monospace, monospace"
                      >
                        {p.net}
                      </text>
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
