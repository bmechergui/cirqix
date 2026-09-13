'use client';

import { useEffect } from 'react';
import { Loader2 } from 'lucide-react';
import type { Project } from '@cirqix/types';
import { statusToStage, type PcbStage } from '@/entities/project';
import { useAppStore } from '@/shared/store/app-store';
import { IdeaView } from './IdeaView';
import { SchemaView } from './SchemaView';
import { ErcView } from './ErcView';
import { PcbView } from './PcbView';
import { DrcView } from './DrcView';
import { ExportView } from './ExportView';
import { SimulationView } from './SimulationView';

interface StageProps {
  project: Project;
}

export function Stage({ project }: StageProps) {
  // `undefined` = pas encore demandé ; `null` = demandé, le projet n'a pas d'état.
  // Les confondre affichait l'accueil « Awaiting Prompt » sur un projet LIVRÉ
  // le temps du chargement (constaté le 2026-09-13 au rechargement de la page).
  const entree = useAppStore((s) => s.pcbStateByProject[project.id]);
  const chargement = entree === undefined;
  const pcbState = entree ?? null;
  const storedStage = useAppStore((s) => s.selectedStage[project.id]);
  const selectedStage: PcbStage = storedStage ?? statusToStage(project.status);
  const fetchPcbState = useAppStore((s) => s.fetchPcbState);

  useEffect(() => {
    void fetchPcbState(project.id);
  }, [project.id, fetchPcbState]);

  if (chargement) {
    return (
      <div className="flex flex-col h-full items-center justify-center gap-3 bg-[#08080c]" role="status" data-testid="stage-loading">
        <Loader2 size={18} className="animate-spin text-primary/60" />
        <span className="text-[11px] font-mono text-[#3d3d3d] tracking-wider">Loading project state…</span>
      </div>
    );
  }

  // No PCB state at all: the project has not been generated yet.
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
    case 'SIMULATION':
      return <SimulationView state={pcbState} />;
  }
}
