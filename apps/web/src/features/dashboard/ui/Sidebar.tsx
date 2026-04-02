'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { LayrixLogo } from '@/shared/ui/layrix-logo';
import { LayoutDashboard, FolderOpen, Settings, HelpCircle, Plus, Loader2, CreditCard } from 'lucide-react';
import { Button } from '@/shared/ui/button';
import { Separator } from '@/shared/ui/separator';
import { useAppStore } from '@/shared/store/app-store';
import { useState } from 'react';
import type { PCBStatus } from '@layrix/types';

const STATUS_DOT: Record<PCBStatus, string> = {
  INITIAL: 'bg-muted-foreground/40',
  SCHEMA_DONE: 'bg-primary',
  PLACEMENT_DONE: 'bg-primary',
  ROUTING_DONE: 'bg-amber-400',
  DRC_CLEAN: 'bg-emerald-400',
  PCB_LIVRÉ: 'bg-amber-600',
};

const NAV = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/dashboard/projects', label: 'Projects', icon: FolderOpen },
  { href: '/dashboard/settings', label: 'Settings', icon: Settings },
  { href: '/dashboard/billing',  label: 'Billing',  icon: CreditCard },
];

const BOTTOM_NAV = [
  { href: '/dashboard/help', label: 'Help', icon: HelpCircle },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const projects = useAppStore((s) => s.projects);
  const createProject = useAppStore((s) => s.createProject);
  const [creating, setCreating] = useState(false);

  const handleCreate = async () => {
    setCreating(true);
    const name = `Untitled PCB ${new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })}`;
    const project = await createProject(name);
    setCreating(false);
    if (project) router.push(`/dashboard/projects/${project.id}`);
  };

  return (
    <aside className="w-60 min-h-screen bg-[#0a0a0a] border-r border-border flex flex-col">
      {/* Logo */}
      <div className="px-4 py-3">
        <Link href="/">
          <LayrixLogo variant="icon" height={32} />
        </Link>
      </div>

      <Separator />

      {/* New project */}
      <div className="px-3 py-3">
        <Button size="sm" className="w-full gap-2 glow-cyan-sm" onClick={handleCreate} disabled={creating}>
          {creating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
          New PCB
        </Button>
      </div>

      {/* Main nav */}
      <nav className="flex-1 px-2 space-y-0.5 mt-1">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || (href !== '/dashboard' && pathname.startsWith(href));
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                active
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'text-muted-foreground hover:text-foreground hover:bg-[#141414]'
              }`}
            >
              <Icon size={16} />
              {label}
            </Link>
          );
        })}

        {/* Recent projects */}
        {projects.length > 0 && (
          <>
            <div className="px-3 pt-4 pb-1">
              <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/60">
                Recent
              </span>
            </div>
            {projects.slice(0, 5).map((p) => {
              const active = pathname === `/dashboard/projects/${p.id}`;
              const dotColor = STATUS_DOT[p.status] ?? 'bg-muted-foreground/40';
              return (
                <Link
                  key={p.id}
                  href={`/dashboard/projects/${p.id}`}
                  className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors truncate ${
                    active
                      ? 'bg-primary/10 text-primary'
                      : 'text-muted-foreground hover:text-foreground hover:bg-[#141414]'
                  }`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotColor}`} />
                  <span className="truncate">{p.name}</span>
                </Link>
              );
            })}
          </>
        )}
      </nav>

      {/* Bottom nav */}
      <div className="px-2 pb-4 space-y-0.5">
        <Separator className="mb-3" />
        {BOTTOM_NAV.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-muted-foreground hover:text-foreground hover:bg-[#141414] transition-colors"
          >
            <Icon size={16} />
            {label}
          </Link>
        ))}
      </div>
    </aside>
  );
}
