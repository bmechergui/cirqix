import { notFound, redirect } from 'next/navigation';
import { createRouteHandlerClient } from '@/shared/lib/supabase-server';
import { Workspace } from '@/features/workspace/ui/Workspace';
import type { Project } from '@cirqix/types';

export const dynamic = 'force-dynamic';

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function ProjectWorkspacePage({ params }: PageProps) {
  const { id } = await params;
  const supabase = await createRouteHandlerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect('/login');

  const { data, error } = await supabase
    .from('projects')
    .select('id, name, description, status, iteration_count, created_at, updated_at')
    .eq('id', id)
    .single();

  if (error || !data) {
    notFound();
  }

  const project: Project = {
    id: data.id,
    name: data.name,
    description: data.description ?? '',
    status: data.status,
    iteration_count: data.iteration_count ?? 0,
    created_at: data.created_at,
    updated_at: data.updated_at,
  };

  return <Workspace project={project} />;
}
