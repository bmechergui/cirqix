'use client';

import { useEffect } from 'react';
import type { Project } from '@layrix/types';
import { statusToStage, type PcbStage } from '@/entities/project';
import { useAppStore } from '@/shared/store/app-store';
import { IdeaView } from './IdeaView';
import { SchemaView } from './SchemaView';
import { ErcView } from './ErcView';
import { PcbView } from './PcbView';
import { DrcView } from './DrcView';
import { ExportView } from './ExportView';

interface StageProps {
  project: Project;
}

export function Stage({ project }: StageProps) {
  const pcbState = useAppStore((s) => s.pcbStateByProject[project.id]) ?? null;
  const storedStage = useAppStore((s) => s.selectedStage[project.id]);
  const selectedStage: PcbStage = storedStage ?? statusToStage(project.status);
  const fetchPcbState = useAppStore((s) => s.fetchPcbState);

  useEffect(() => {
    void fetchPcbState(project.id);
  }, [project.id, fetchPcbState]);

  // Until we have a PCB state, always show Idea regardless of stage selected
  if (!pcbState) {
    return <IdeaView project={project} />;
  }

  const stage: PcbStage = selectedStage;

  switch (stage) {
    case 'IDEA':
      return <IdeaView project={project} />;
    case 'SCHEMA':
      return <SchemaView state={pcbState} />;
    case 'ERC':
      return <ErcView state={pcbState} />;
    case 'PLACEMENT':
      return <PcbView state={pcbState} title="Component placement" showRouting={false} />;
    case 'ROUTING':
      return <PcbView state={pcbState} title="Routing" showRouting />;
    case 'DRC':
      return <DrcView state={pcbState} />;
    case 'EXPORT':
      return <ExportView state={pcbState} />;
  }
}
