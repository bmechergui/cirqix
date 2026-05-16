import { NextResponse, type NextRequest } from 'next/server';
import { z } from 'zod';
import { createRouteHandlerClient } from '@/shared/lib/supabase-server';

const updateSchema = z.object({
  name: z.string().min(1).max(100).trim().optional(),
  description: z.string().max(500).trim().optional(),
  status: z
    .enum(['INITIAL', 'SCHEMA_DONE', 'ERC_CLEAN', 'PLACEMENT_DONE', 'ROUTING_DONE', 'DRC_CLEAN', 'PCB_LIVRÉ'])
    .optional(),
});

async function authedClient() {
  const supabase = await createRouteHandlerClient();
  const { data: { user } } = await supabase.auth.getUser();
  return { supabase, user };
}

export async function GET(
  _req: NextRequest,
  ctx: { params: Promise<{ id: string }> }
) {
  const { supabase, user } = await authedClient();
  if (!user) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }

  const { id } = await ctx.params;
  const { data, error } = await supabase
    .from('projects')
    .select('id, name, description, status, iteration_count, created_at, updated_at')
    .eq('id', id)
    .single();

  if (error || !data) {
    return NextResponse.json({ success: false, error: 'Not found' }, { status: 404 });
  }

  return NextResponse.json({ success: true, data });
}

export async function PATCH(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> }
) {
  const { supabase, user } = await authedClient();
  if (!user) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }

  let payload: unknown;
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json({ success: false, error: 'Invalid JSON' }, { status: 400 });
  }
  const parsed = updateSchema.safeParse(payload);
  if (!parsed.success) {
    return NextResponse.json(
      { success: false, error: parsed.error.issues.map((i) => i.message).join(', ') },
      { status: 400 }
    );
  }

  const { id } = await ctx.params;
  const patch: Record<string, unknown> = { ...parsed.data, updated_at: new Date().toISOString() };

  const { data, error } = await supabase
    .from('projects')
    .update(patch)
    .eq('id', id)
    .select('id, name, description, status, iteration_count, created_at, updated_at')
    .single();

  if (error || !data) {
    return NextResponse.json({ success: false, error: error?.message ?? 'Not found' }, { status: 404 });
  }

  return NextResponse.json({ success: true, data });
}

export async function DELETE(
  _req: NextRequest,
  ctx: { params: Promise<{ id: string }> }
) {
  const { supabase, user } = await authedClient();
  if (!user) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }

  const { id } = await ctx.params;
  const { error } = await supabase.from('projects').delete().eq('id', id);
  if (error) {
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
  return NextResponse.json({ success: true });
}
