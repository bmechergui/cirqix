'use client';

import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import type { Project } from '@cirqix/types';
import { StatusBadge } from '@/features/dashboard/ui/StatusBadge';
import { CreditsBadge } from '@/features/dashboard/ui/CreditsBadge';
import { UserMenu } from '@/features/dashboard/ui/UserMenu';

export function WorkspaceHeader({ project }: { project: Project }) {
  return (
    <header className="h-12 border-b border-border bg-[#0a0a0a] flex items-center justify-between px-3 shrink-0">
      <div className="flex items-center gap-3 min-w-0">
        <Link
          href="/dashboard"
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1 rounded-md hover:bg-[#141414]"
        >
          <ArrowLeft size={12} />
          <span className="hidden sm:inline">Projects</span>
        </Link>

        <div className="w-px h-4 bg-border" />

        <div className="flex items-center gap-2 min-w-0">
          <h1 className="text-sm font-semibold text-foreground truncate">{project.name}</h1>
          <span className="text-[10px] font-mono text-muted-foreground hidden md:inline">
            v{project.iteration_count}
          </span>
        </div>

        <div className="hidden sm:block">
          <StatusBadge status={project.status} />
        </div>
      </div>

      <div className="flex items-center gap-2 shrink-0">
        <CreditsBadge />
        <UserMenu />
      </div>
    </header>
  );
}
