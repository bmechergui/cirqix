'use client';

import { Check, Loader2, Sparkles, FileText, MoveDiagonal2, Route, ShieldCheck, Download, Activity } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { PCBStatus } from '@layrix/types';
import {
  PCB_STAGE_ORDER,
  isStageReached,
  statusToStage,
  type PcbStage,
} from '@/entities/project';
import { useAppStore } from '@/shared/store/app-store';
import { cn } from '@/shared/lib/utils';

interface TimelineProps {
  projectId: string;
  status: PCBStatus;
}

const STAGE_META: Record<PcbStage, { label: string; icon: LucideIcon }> = {
  IDEA:      { label: 'Idea',     icon: Sparkles },
  SCHEMA:    { label: 'Schema',   icon: FileText },
  ERC:       { label: 'ERC',      icon: Activity },
  PLACEMENT: { label: 'Place',    icon: MoveDiagonal2 },
  ROUTING:   { label: 'Route',    icon: Route },
  DRC:       { label: 'DRC',      icon: ShieldCheck },
  EXPORT:    { label: 'Export',   icon: Download },
};

export function Timeline({ projectId, status }: TimelineProps) {
  const agentStep = useAppStore((s) => s.agentStep);
  const storedStage = useAppStore((s) => s.selectedStage[projectId]);
  const setSelectedStage = useAppStore((s) => s.setSelectedStage);

  const currentStage = statusToStage(status);
  const selectedStage: PcbStage = storedStage ?? currentStage;

  return (
    <div className="flex items-center gap-1 px-4 py-2.5 border-b border-border bg-[#0a0a0a]/60 backdrop-blur overflow-x-auto">
      {PCB_STAGE_ORDER.map((stage, i) => {
        const meta = STAGE_META[stage];
        const Icon = meta.icon;
        const reached = isStageReached(status, stage);
        const isCurrent = stage === currentStage;
        const isSelected = stage === selectedStage;
        const isAgentActive =
          agentStep === stage ||
          (agentStep === 'SCHEMA' && stage === 'SCHEMA') ||
          (agentStep === 'ERC' && stage === 'ERC') ||
          (agentStep === 'PLACEMENT' && stage === 'PLACEMENT') ||
          (agentStep === 'ROUTING' && stage === 'ROUTING') ||
          (agentStep === 'DRC' && stage === 'DRC') ||
          (agentStep === 'EXPORT' && stage === 'EXPORT');

        return (
          <div key={stage} className="flex items-center gap-1 shrink-0">
            {i > 0 && (
              <div
                className={cn(
                  'h-px w-4 sm:w-6 transition-colors',
                  reached ? 'bg-primary/40' : 'bg-border'
                )}
              />
            )}
            <button
              type="button"
              onClick={() => setSelectedStage(projectId, stage)}
              className={cn(
                'flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium transition-all',
                isSelected && 'bg-primary/15 text-primary border border-primary/30',
                !isSelected && reached && 'text-foreground hover:bg-[#141414]',
                !isSelected && !reached && 'text-muted-foreground hover:text-foreground/70 hover:bg-[#141414]/60',
                isCurrent && !isSelected && 'border border-primary/20'
              )}
            >
              <span
                className={cn(
                  'w-4 h-4 rounded-full flex items-center justify-center shrink-0 transition-all',
                  isAgentActive && 'bg-primary/20 text-primary',
                  !isAgentActive && reached && 'bg-primary/15 text-primary',
                  !isAgentActive && !reached && 'bg-[#1a1a1a] text-muted-foreground/60'
                )}
              >
                {isAgentActive ? (
                  <Loader2 size={9} className="animate-spin" />
                ) : reached && !isCurrent ? (
                  <Check size={9} />
                ) : (
                  <Icon size={9} />
                )}
              </span>
              <span className="hidden sm:inline">{meta.label}</span>
            </button>
          </div>
        );
      })}
    </div>
  );
}
