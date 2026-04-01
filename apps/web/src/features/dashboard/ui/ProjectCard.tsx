'use client';

import React, { useState, useRef, useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Clock, Cpu, MoreHorizontal, Trash2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card';
import { StatusBadge } from './StatusBadge';
import { useAppStore } from '@/shared/store/app-store';
import type { Project } from '@layrix/types';

interface ProjectCardProps {
  project: Project;
}

export const ProjectCard = React.memo(function ProjectCard({ project }: ProjectCardProps) {
  const router = useRouter();
  const removeProject = useAppStore((s) => s.removeProject);
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function onClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
        setConfirming(false);
      }
    }
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, [menuOpen]);

  const handleDelete = async () => {
    removeProject(project.id);
    setMenuOpen(false);
    router.refresh();
    await fetch(`/api/projects/${project.id}`, { method: 'DELETE' });
  };

  const date = new Date(project.updated_at).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });

  return (
    <div className="relative group/card">
      <Link href={`/dashboard/projects/${project.id}`}>
        <Card className="group hover:border-primary/50 transition-all duration-200 cursor-pointer h-full">
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-2">
              <CardTitle className="text-base font-semibold truncate group-hover:text-primary transition-colors">
                {project.name}
              </CardTitle>
              <StatusBadge status={project.status} />
            </div>
            {project.description && (
              <p className="text-xs text-muted-foreground line-clamp-2 mt-1">
                {project.description}
              </p>
            )}
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <Cpu size={12} />
                iter {project.iteration_count}
              </span>
              <span className="flex items-center gap-1.5">
                <Clock size={12} />
                {date}
              </span>
            </div>
          </CardContent>
        </Card>
      </Link>

      {/* ⋯ menu — positioned over the card, stops link propagation */}
      <div
        ref={menuRef}
        className="absolute top-2 right-2 z-10"
        onClick={(e) => e.preventDefault()}
      >
        <button
          type="button"
          onClick={(e) => { e.preventDefault(); setMenuOpen((v) => !v); setConfirming(false); }}
          className="w-7 h-7 rounded-md flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-[#1a1a1a] opacity-0 group-hover/card:opacity-100 transition-all"
          aria-label="Project options"
        >
          <MoreHorizontal size={14} />
        </button>

        {menuOpen && (
          <div className="absolute right-0 top-8 w-44 bg-[#111111] border border-border rounded-xl shadow-xl overflow-hidden z-20">
            {!confirming ? (
              <button
                type="button"
                onClick={() => setConfirming(true)}
                className="flex items-center gap-2.5 w-full px-3 py-2.5 text-sm text-red-400 hover:bg-red-500/10 hover:text-red-300 transition-colors"
              >
                <Trash2 size={13} />
                Delete project
              </button>
            ) : (
              <div className="p-3 space-y-2">
                <p className="text-xs text-muted-foreground">Delete forever?</p>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => { void handleDelete(); }}
                    className="flex-1 py-1.5 text-xs rounded-md bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors font-medium"
                  >
                    Delete
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirming(false)}
                    className="flex-1 py-1.5 text-xs rounded-md bg-[#1a1a1a] text-muted-foreground hover:text-foreground transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
});
