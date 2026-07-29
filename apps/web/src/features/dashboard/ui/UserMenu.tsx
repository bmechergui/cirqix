'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { LogOut, Settings, User } from 'lucide-react';
import { useAppStore } from '@/shared/store/app-store';
import { createSupabaseBrowserClient } from '@/shared/lib/supabase-browser';

export function UserMenu() {
  const user = useAppStore((s) => s.user);
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, []);

  const handleSignOut = async () => {
    if (signingOut) return;
    setSigningOut(true);
    try {
      const supabase = createSupabaseBrowserClient();
      await supabase.auth.signOut();
    } finally {
      // Hard reload — clears Zustand store, forces middleware to re-check
      // Supabase auth cookies server-side, and bypasses Next.js client cache.
      // router.push() alone left stale user state in the Zustand store and
      // sometimes failed to trigger the middleware redirect.
      window.location.assign('/login');
    }
  };

  const initials = user?.full_name
    ? user.full_name.split(' ').map((n) => n[0]).join('').toUpperCase().slice(0, 2)
    : user?.email?.slice(0, 2).toUpperCase() ?? '??';

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-8 h-8 rounded-full bg-primary/20 border border-primary/30 flex items-center justify-center text-xs font-bold text-primary hover:bg-primary/30 transition-colors overflow-hidden"
        aria-label="User menu"
        aria-expanded={open}
        aria-haspopup="true"
      >
        {user?.avatar_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={user.avatar_url} alt={initials} className="w-full h-full object-cover" />
        ) : (
          initials
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-10 w-56 bg-[#111111] border border-border rounded-xl shadow-xl z-50 overflow-hidden" role="menu">
          {/* User info */}
          <div className="px-4 py-3 border-b border-border">
            <p className="text-sm font-medium text-foreground truncate">
              {user?.full_name ?? 'My account'}
            </p>
            <p className="text-xs text-muted-foreground truncate">{user?.email}</p>
          </div>

          {/* Actions */}
          <div className="py-1">
            <button
              type="button"
              role="menuitem"
              onClick={() => { router.push('/dashboard/settings'); setOpen(false); }}
              className="flex items-center gap-3 w-full px-4 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-[#1a1a1a] transition-colors"
            >
              <Settings size={14} />
              Settings
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => { router.push('/dashboard/settings#profile'); setOpen(false); }}
              className="flex items-center gap-3 w-full px-4 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-[#1a1a1a] transition-colors"
            >
              <User size={14} />
              Profile
            </button>
          </div>

          <div className="border-t border-border py-1">
            <button
              type="button"
              role="menuitem"
              onClick={handleSignOut}
              disabled={signingOut}
              className="flex items-center gap-3 w-full px-4 py-2.5 text-sm text-red-400 hover:text-red-300 hover:bg-red-500/10 transition-colors disabled:opacity-50 disabled:cursor-wait"
            >
              <LogOut size={14} />
              {signingOut ? 'Signing out…' : 'Sign out'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
