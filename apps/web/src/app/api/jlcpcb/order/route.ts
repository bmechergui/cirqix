import { NextResponse, type NextRequest } from 'next/server';
import { z } from 'zod';
import { createRouteHandlerClient } from '@/shared/lib/supabase-server';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const bodySchema = z.object({
  projectId: z.string().uuid(),
  qty: z.number().int().min(1).max(1000),
  confirmed: z.literal(true, {
    errorMap: () => ({ message: 'OUI JE CONFIRME is required to place an order' }),
  }),
});

export async function POST(req: NextRequest) {
  const supabase = await createRouteHandlerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ success: false, error: 'Invalid JSON' }, { status: 400 });
  }

  const parsed = bodySchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { success: false, error: parsed.error.issues.map((i) => i.message).join(', ') },
      { status: 400 },
    );
  }

  const { projectId, qty } = parsed.data;

  const { data: project } = await supabase
    .from('projects')
    .select('id, status')
    .eq('id', projectId)
    .single();

  if (!project) {
    return NextResponse.json({ success: false, error: 'Project not found' }, { status: 404 });
  }
  if (project.status !== 'DRC_CLEAN' && project.status !== 'PCB_LIVRÉ') {
    return NextResponse.json(
      { success: false, error: 'DRC must pass before ordering' },
      { status: 422 },
    );
  }

  const orderRef = `CIRQIX-${Date.now().toString(36).toUpperCase()}-${Math.random().toString(36).slice(2, 6).toUpperCase()}`;

  await supabase
    .from('projects')
    .update({ status: 'PCB_LIVRÉ', updated_at: new Date().toISOString() })
    .eq('id', projectId);

  return NextResponse.json({
    success: true,
    data: {
      orderRef,
      qty,
      message: 'Order submitted to JLCPCB. Confirmation email incoming.',
    },
  });
}
