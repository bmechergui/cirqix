'use client';

import { use } from 'react';
import { ChatPanel } from '@/components/dashboard/ChatPanel';
import { ViewerPanel } from '@/components/dashboard/ViewerPanel';
import { AgentProgressBar } from '@/components/dashboard/AgentProgressBar';
import { useAppStore } from '@/store/app-store';

export default function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const project = useAppStore((s) => s.projects.find((p) => p.id === id));
  const agentStep = useAppStore((s) => s.agentStep);

  if (!project) return <div className="text-muted-foreground p-6">Project not found</div>;

  return (
    <div className="flex flex-col -m-6 overflow-hidden" style={{ height: 'calc(100vh - var(--header-height, 57px))' }}>
      <AgentProgressBar step={agentStep} />
      <div className="flex flex-1 overflow-hidden">
        {/* Chat — 380px */}
        <div className="w-[380px] border-r border-border flex flex-col overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <h2 className="text-sm font-semibold text-foreground truncate">{project.name}</h2>
          </div>
          <ChatPanel projectId={id} />
        </div>
        {/* Viewer — remaining space */}
        <div className="flex-1 overflow-hidden">
          <ViewerPanel />
        </div>
      </div>
    </div>
  );
}
