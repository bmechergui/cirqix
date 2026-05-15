'use client';

import { Bell } from 'lucide-react';
import { Button } from '@/shared/ui/button';
import { CreditsBadge } from './CreditsBadge';
import { UserMenu } from './UserMenu';

interface HeaderProps {
  title?: string;
}

export function Header({ title }: HeaderProps) {
  return (
    <header className="h-14 border-b border-border bg-[#0a0a0a] flex items-center justify-between px-6 sticky top-0 z-10">
      {title && (
        <h1 className="text-sm font-semibold text-foreground">{title}</h1>
      )}

      <div className="flex items-center gap-3 ml-auto">
        <CreditsBadge />
        <Button variant="ghost" size="icon" className="h-8 w-8" aria-label="Notifications">
          <Bell size={16} />
        </Button>
        <UserMenu />
      </div>
    </header>
  );
}
