'use client';

import { Bell } from 'lucide-react';
import { Button } from '@/shared/ui/button';
import { CreditsBadge } from './CreditsBadge';
import { UserMenu } from './UserMenu';
import { useAppStore } from '@/shared/store/app-store';
import type { PCBStatus } from '@layrix/types';

interface HeaderProps {
  title?: string;
}

const STEP_LABELS: Record<string, string> = {
  SPEC:      'Spec',
  SCHEMA:    'Schema',
  PLACEMENT: 'Placement',
  ROUTING:   'Routing',
  DRC:       'DRC',
  EXPORT:    'Export',
};

const STATUS_META: Record<PCBStatus, { label: string; dot: string; text: string }> = {
  INITIAL:        { label: 'Draft',         dot: 'bg-[#52525B]',       text: 'text-[#A1A1AA]' },
  SCHEMA_DONE:    { label: 'Schema',        dot: 'bg-primary',         text: 'text-primary' },
  PLACEMENT_DONE: { label: 'Placement',     dot: 'bg-primary',         text: 'text-primary' },
  ROUTING_DONE:   { label: 'Routing',       dot: 'bg-amber-400',       text: 'text-amber-400' },
  DRC_CLEAN:      { label: 'DRC clean',     dot: 'bg-emerald-400',     text: 'text-emerald-400' },
  'PCB_LIVRÉ':    { label: 'Ordered',       dot: 'bg-amber-600',       text: 'text-amber-500' },
};

function AgentStatusBadge() {
  const isAgentRunning = useAppStore((s) => s.isAgentRunning);
  const agentStep = useAppStore((s) => s.agentStep);

  if (!isAgentRunning) return null;

  const label = agentStep ? STEP_LABELS[agentStep] ?? agentStep : 'Thinking…';

  return (
    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-primary/10 border border-primary/20">
      <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
      <span className="text-[11px] font-medium text-primary leading-none font-mono">{label}…</span>
    </div>
  );
}

function ProjectStatusPill() {
  const selectedProjectId = useAppStore((s) => s.selectedProjectId);
  const project = useAppStore((s) => selectedProjectId ? s.projects.find((p) => p.id === selectedProjectId) : null);
  const isAgentRunning = useAppStore((s) => s.isAgentRunning);

  if (!project || isAgentRunning) return null;
  const meta = STATUS_META[project.status] ?? STATUS_META.INITIAL;

  return (
    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[#111111] border border-[#1F1F1F]">
      <span className={`w-1.5 h-1.5 rounded-full ${meta.dot}`} />
      <span className={`text-[11px] font-mono font-medium leading-none ${meta.text}`}>{meta.label}</span>
    </div>
  );
}

export function Header({ title }: HeaderProps) {
  return (
    <header className="h-14 border-b border-border bg-[#0a0a0a] flex items-center justify-between px-6 sticky top-0 z-10">
      {title && (
        <h1 className="text-sm font-semibold text-foreground">{title}</h1>
      )}

      <div className="flex items-center gap-3 ml-auto">
        <ProjectStatusPill />
        <AgentStatusBadge />
        <div className="h-5 w-px bg-border" />
        <CreditsBadge />
        <Button variant="ghost" size="icon" className="h-8 w-8" aria-label="Notifications">
          <Bell size={16} />
        </Button>
        <UserMenu />
      </div>
    </header>
  );
}
