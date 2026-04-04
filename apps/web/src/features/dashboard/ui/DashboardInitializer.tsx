'use client';

import { useEffect } from 'react';
import { useAppStore } from '@/shared/store/app-store';

export function DashboardInitializer() {
  const fetchUser = useAppStore((s) => s.fetchUser);
  const fetchCredits = useAppStore((s) => s.fetchCredits);
  const fetchProjects = useAppStore((s) => s.fetchProjects);

  useEffect(() => {
    void fetchUser();
    void fetchCredits();
    void fetchProjects();
  }, [fetchUser, fetchCredits, fetchProjects]);

  return null;
}
