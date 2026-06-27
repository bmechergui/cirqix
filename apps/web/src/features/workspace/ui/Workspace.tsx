'use client';

import { useEffect } from 'react';
import type { Project } from '@cirqix/types';
import { ChatRail } from './ChatRail';
import { Timeline } from './Timeline';
import { WorkspaceHeader } from './WorkspaceHeader';
import { Stage } from '@/widgets/viewer';
import { useAppStore } from '@/shared/store/app-store';

interface WorkspaceProps {
  project: Project;
}

export function Workspace({ project }: WorkspaceProps) {
  const fetchUser = useAppStore((s) => s.fetchUser);
  const fetchCredits = useAppStore((s) => s.fetchCredits);
  const livePcbStatus = useAppStore((s) => s.pcbStateByProject[project.id]?.status);

  useEffect(() => {
    void fetchUser();
    void fetchCredits();
  }, [fetchUser, fetchCredits]);

  useEffect(() => {
    const origHtmlOverflow = document.documentElement.style.overflow;
    const origBodyOverflow = document.body.style.overflow;
    const origHtmlHeight = document.documentElement.style.height;
    const origBodyHeight = document.body.style.height;

    document.documentElement.style.overflow = 'hidden';
    document.body.style.overflow = 'hidden';
    document.documentElement.style.height = '100%';
    document.body.style.height = '100%';

    return () => {
      document.documentElement.style.overflow = origHtmlOverflow;
      document.body.style.overflow = origBodyOverflow;
      document.documentElement.style.height = origHtmlHeight;
      document.body.style.height = origBodyHeight;
    };
  }, []);

  const effectiveStatus = livePcbStatus ?? project.status;
  const effectiveProject: Project = { ...project, status: effectiveStatus };

  return (
    <div className="flex flex-col h-screen w-full bg-background overflow-hidden">
      <WorkspaceHeader project={effectiveProject} />
      <Timeline projectId={project.id} status={effectiveStatus} />

      <div className="flex flex-1 min-h-0 overflow-hidden">
        <ChatRail projectId={project.id} projectDescription={project.description} />
        <main className="flex-1 min-w-0 overflow-hidden flex flex-col">
          <Stage project={effectiveProject} />
        </main>
      </div>
    </div>
  );
}
