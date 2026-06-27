'use client';

import { useEffect } from 'react';
import { Loader2, CircuitBoard } from 'lucide-react';
import { useAppStore } from '@/shared/store/app-store';
import { ProjectCard } from './ProjectCard';
import { NewProjectDialog } from './NewProjectDialog';

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center gap-5 py-20 px-6 rounded-2xl border border-dashed border-border bg-[#0a0a0a]/40">
      <div className="w-14 h-14 rounded-xl bg-primary/5 border border-primary/20 flex items-center justify-center">
        <CircuitBoard size={22} className="text-primary/70" />
      </div>
      <div className="text-center max-w-sm">
        <h2 className="text-base font-semibold text-foreground mb-1">
          No projects yet
        </h2>
        <p className="text-sm text-muted-foreground">
          Start with a sentence. Cirqix turns it into a manufacturable PCB.
        </p>
      </div>
      <NewProjectDialog />
    </div>
  );
}

export function ProjectsGrid() {
  const projects = useAppStore((s) => s.projects);
  const loading = useAppStore((s) => s.projectsLoading);
  const error = useAppStore((s) => s.projectsError);
  const fetchProjects = useAppStore((s) => s.fetchProjects);
  const deleteProject = useAppStore((s) => s.deleteProject);

  useEffect(() => {
    void fetchProjects();
  }, [fetchProjects]);

  if (loading && projects.length === 0) {
    return (
      <div className="flex items-center justify-center py-20 gap-2 text-sm text-muted-foreground">
        <Loader2 size={14} className="animate-spin" />
        Loading projects…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        {error}
      </div>
    );
  }

  if (projects.length === 0) {
    return <EmptyState />;
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {projects.map((p) => (
        <ProjectCard
          key={p.id}
          project={p}
          onDelete={(id) => {
            if (confirm('Delete this project? This cannot be undone.')) {
              void deleteProject(id);
            }
          }}
        />
      ))}
    </div>
  );
}
