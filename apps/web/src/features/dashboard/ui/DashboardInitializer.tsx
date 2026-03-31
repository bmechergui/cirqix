'use client';

import { useEffect } from 'react';
import { useAppStore } from '@/shared/store/app-store';

export function DashboardInitializer() {
  const fetchCredits = useAppStore((s) => s.fetchCredits);

  useEffect(() => {
    void fetchCredits();
  }, [fetchCredits]);

  return null;
}
