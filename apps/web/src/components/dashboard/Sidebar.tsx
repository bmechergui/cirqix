'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { LayoutDashboard, FolderOpen, Settings, HelpCircle, Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { useAppStore } from '@/store/app-store';

const NAV = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/dashboard/projects', label: 'Projects', icon: FolderOpen },
  { href: '/dashboard/settings', label: 'Settings', icon: Settings },
];

const BOTTOM_NAV = [
  { href: '/dashboard/help', label: 'Help', icon: HelpCircle },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const projects = useAppStore((s) => s.projects);

  return (
    <aside className="w-60 min-h-screen bg-[#0a0a0a] border-r border-border flex flex-col">
      {/* Logo */}
      <div className="px-5 py-4 flex items-center gap-2">
        <span className="font-bold text-foreground">Layrix</span>
        <span className="w-1.5 h-1.5 rounded-full bg-primary" />
      </div>

      <Separator />

      {/* New project */}
      <div className="px-3 py-3">
        <Button size="sm" className="w-full gap-2 glow-cyan-sm" onClick={() => router.push('/dashboard')}>
          <Plus size={14} />
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
                  <span className="w-1.5 h-1.5 rounded-full bg-border shrink-0" />
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
