'use client';

import React from 'react';
import { Check, Loader2, FileText, Cpu, Route, ShieldCheck, Download, Sparkles, type LucideIcon } from 'lucide-react';
import type { PCBState, PCBStatus } from '@layrix/types';

export type ViewerMode = 'schematic' | 'routing' | '3d' | 'components';

type AgentStep = 'SPEC' | 'SCHEMA' | 'PLACEMENT' | 'ROUTING' | 'DRC' | 'EXPORT';

interface StepDef {
  id: AgentStep;
  label: string;
  agent: string;
  description: string;
  icon: LucideIcon;
  targetMode: ViewerMode | null;
}

const STEPS: readonly StepDef[] = [
  { id: 'SPEC',      label: 'Spec',      agent: 'Spec Parser',    description: 'Description → DesignJson',          icon: Sparkles,    targetMode: null },
  { id: 'SCHEMA',    label: 'Schema',    agent: 'Schematic Agent', description: 'Netlist + symbols KiCad',          icon: FileText,    targetMode: 'schematic' },
  { id: 'PLACEMENT', label: 'Placement', agent: 'Placement Agent', description: 'Composants X/Y/rotation',          icon: Cpu,         targetMode: 'routing' },
  { id: 'ROUTING',   label: 'Routing',   agent: 'Routing Agent',   description: 'Freerouting + ground planes',      icon: Route,       targetMode: 'routing' },
  { id: 'DRC',       label: 'DRC',       agent: 'DRC Agent',       description: 'Design Rule Check + corrections',  icon: ShieldCheck, targetMode: 'routing' },
  { id: 'EXPORT',    label: 'Export',    agent: 'Export Agent',    description: 'Gerbers + BOM + JLCPCB',           icon: Download,    targetMode: 'components' },
];

const STATUS_ORDER: Record<PCBStatus, number> = {
  INITIAL: 0,
  SCHEMA_DONE: 2,
  PLACEMENT_DONE: 3,
  ROUTING_DONE: 4,
  DRC_CLEAN: 5,
  'PCB_LIVRÉ': 6,
};

function computeDone(pcbState: PCBState | null, activeStep: AgentStep | null): Set<AgentStep> {
  const done = new Set<AgentStep>();
  const status = pcbState?.status;
  const maxDone = status ? STATUS_ORDER[status] ?? 0 : 0;

  if (maxDone >= 1 || pcbState) done.add('SPEC');
  if (maxDone >= 2 || pcbState?.kicad_sch_url) done.add('SCHEMA');
  if (maxDone >= 3) done.add('PLACEMENT');
  if (maxDone >= 4) done.add('ROUTING');
  if (maxDone >= 5) done.add('DRC');
  if (maxDone >= 6) done.add('EXPORT');

  // Don't mark the currently-active step as done
  if (activeStep) done.delete(activeStep);
  return done;
}

interface PipelineBarProps {
  pcbState: PCBState | null;
  activeStep: AgentStep | null;
  mode: ViewerMode;
  onModeChange: (mode: ViewerMode) => void;
}

export function PipelineBar({ pcbState, activeStep, mode, onModeChange }: PipelineBarProps) {
  const done = computeDone(pcbState, activeStep);
  const activeIdx = activeStep ? STEPS.findIndex((s) => s.id === activeStep) : -1;

  return (
    <div className="shrink-0 px-6 py-3 border-b border-border bg-[#0a0a0a]">
      <div className="flex items-center gap-1">
        {STEPS.map((step, i) => {
          const isDone = done.has(step.id);
          const isActive = step.id === activeStep;
          const Icon = step.icon;
          const linksToCurrent = step.targetMode === mode;
          const clickable = step.targetMode !== null;

          const stateClass = isDone
            ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
            : isActive
              ? 'bg-primary/15 border-primary/40 text-primary shadow-[0_0_12px_rgba(0,194,255,0.25)]'
              : 'bg-[#0d0d0d] border-[#1F1F1F] text-[#52525B]';

          const ringClass = linksToCurrent && (isDone || isActive)
            ? 'ring-1 ring-primary/30'
            : '';

          return (
            <React.Fragment key={step.id}>
              {i > 0 && (
                <div
                  className={`flex-1 h-px max-w-[40px] ${
                    done.has(STEPS[i - 1]!.id) || isDone || isActive
                      ? 'bg-emerald-500/30'
                      : 'bg-[#1F1F1F]'
                  }`}
                />
              )}
              <button
                type="button"
                onClick={() => { if (step.targetMode) onModeChange(step.targetMode); }}
                disabled={!clickable}
                title={`${step.agent} — ${step.description}`}
                className={`group flex items-center gap-2 px-3 py-1.5 rounded-md border transition-all ${stateClass} ${ringClass} ${
                  clickable ? 'cursor-pointer hover:brightness-125' : 'cursor-default'
                }`}
              >
                <span className="relative flex items-center justify-center w-4 h-4">
                  {isDone ? (
                    <Check size={11} strokeWidth={3} />
                  ) : isActive ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <Icon size={11} />
                  )}
                </span>
                <span className="text-[10px] font-mono font-medium whitespace-nowrap">
                  {step.label}
                </span>
              </button>
            </React.Fragment>
          );
        })}
      </div>

      {/* Status line — only when an agent is running */}
      {activeStep && (
        <div className="flex items-center justify-between mt-2 pl-1">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
            <span className="text-[10px] text-[#A1A1AA] font-mono">
              {STEPS[activeIdx]?.agent}
              <span className="text-[#52525B]"> — </span>
              <span className="text-primary">{STEPS[activeIdx]?.description}</span>
            </span>
          </div>
          <span className="text-[10px] font-mono text-[#52525B]">
            {activeIdx + 1} / {STEPS.length}
          </span>
        </div>
      )}
    </div>
  );
}
