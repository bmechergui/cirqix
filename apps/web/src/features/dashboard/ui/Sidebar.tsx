'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { LayrixLogo } from '@/shared/ui/layrix-logo';
import { LayoutDashboard, Settings, HelpCircle, CreditCard } from 'lucide-react';
import { Separator } from '@/shared/ui/separator';

const NAV = [
  { href: '/dashboard',          label: 'Dashboard', icon: LayoutDashboard },
  { href: '/dashboard/settings', label: 'Settings',  icon: Settings },
  { href: '/dashboard/billing',  label: 'Billing',   icon: CreditCard },
  { href: '/dashboard/help',     label: 'Help',      icon: HelpCircle },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-60 min-h-screen bg-[#0a0a0a] border-r border-border flex flex-col">
      {/* Logo */}
      <div className="px-4 py-3">
        <Link href="/">
          <LayrixLogo variant="icon" height={32} />
        </Link>
      </div>

      <Separator />

      {/* Main nav */}
      <nav className="flex-1 px-2 space-y-0.5 mt-3">
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
      </nav>
    </aside>
  );
}
