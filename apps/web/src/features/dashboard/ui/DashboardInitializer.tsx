'use client';

import { useEffect } from 'react';
import { useAppStore } from '@/shared/store/app-store';

export function DashboardInitializer() {
  const fetchUser = useAppStore((s) => s.fetchUser);
  const fetchCredits = useAppStore((s) => s.fetchCredits);

  useEffect(() => {
    void fetchUser();
    void fetchCredits();
  }, [fetchUser, fetchCredits]);

  return null;
}
