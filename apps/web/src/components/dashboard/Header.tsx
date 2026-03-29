'use client';

import { Bell, User } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { CreditsBadge } from './CreditsBadge';

interface HeaderProps {
  title?: string;
}

export function Header({ title }: HeaderProps) {
  return (
    <header className="h-14 border-b border-border bg-[#0a0a0a] flex items-center justify-between px-6 sticky top-0 z-10">
      {title && (
        <h1 className="text-sm font-semibold text-foreground">{title}</h1>
      )}

      <div className="flex items-center gap-4 ml-auto">
        <CreditsBadge />
        <Button variant="ghost" size="icon" className="h-8 w-8" aria-label="Notifications">
          <Bell size={16} />
        </Button>
        <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full" aria-label="Account">
          <User size={16} />
        </Button>
      </div>
    </header>
  );
}
