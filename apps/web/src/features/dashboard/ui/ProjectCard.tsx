'use client';

import Link from 'next/link';
import { CircuitBoard, MoreHorizontal, Trash2 } from 'lucide-react';
import { useState } from 'react';
import type { Project } from '@cirqix/types';
import { Button } from '@/shared/ui/button';
import { StatusBadge } from './StatusBadge';

interface ProjectCardProps {
  project: Project;
  onDelete?: (id: string) => void;
}

function formatRelative(iso: string): string {
  const date = new Date(iso);
  const diffMs = Date.now() - date.getTime();
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return date.toLocaleDateString();
}

export function ProjectCard({ project, onDelete }: ProjectCardProps) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <Link
      href={`/dashboard/projects/${project.id}`}
      className="group relative flex flex-col gap-3 rounded-xl border border-border bg-[#111111] p-5 hover:border-primary/40 hover:bg-[#141414] transition-all"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-9 h-9 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center shrink-0">
            <CircuitBoard size={16} className="text-primary" />
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-foreground truncate">
              {project.name}
            </h3>
            <p className="text-xs text-muted-foreground font-mono">
              v{project.iteration_count} · {formatRelative(project.updated_at)}
            </p>
          </div>
        </div>
        {onDelete && (
          <div className="relative">
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setMenuOpen((v) => !v);
              }}
              aria-label="Project actions"
            >
              <MoreHorizontal size={14} />
            </Button>
            {menuOpen && (
              <div
                className="absolute right-0 top-8 w-36 z-20 rounded-md border border-border bg-[#0a0a0a] shadow-lg py-1"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                }}
              >
                <button
                  className="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-destructive hover:bg-destructive/10 transition-colors"
                  onClick={() => {
                    setMenuOpen(false);
                    onDelete(project.id);
                  }}
                >
                  <Trash2 size={12} />
                  Delete
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="flex items-center justify-between pt-2 border-t border-border/60">
        <StatusBadge status={project.status} />
        <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground/60 group-hover:text-primary transition-colors">
          Open →
        </span>
      </div>
    </Link>
  );
}
