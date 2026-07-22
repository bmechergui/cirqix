import { NextResponse, type NextRequest } from 'next/server';
import { z } from 'zod';
import { createAdminClient, createRouteHandlerClient } from '@/shared/lib/supabase-server';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const bodySchema = z.object({
  projectId: z.string().uuid(),
  qty: z.number().int().min(1).max(1000),
  confirmation: z.literal('OUI JE CONFIRME', {
    errorMap: () => ({ message: 'OUI JE CONFIRME is required to place an order' }),
  }),
});

type DrcEvidence = {
  drc_clean?: boolean;
  drc_skipped?: boolean;
  drc_validation?: string;
};

export function hasOfficialDrc(state: unknown): boolean {
  if (!state || typeof state !== 'object') return false;
  const evidence = state as DrcEvidence;
  return evidence.drc_clean === true
    && evidence.drc_skipped !== true
    && evidence.drc_validation === 'kicad-cli';
}

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

  const { projectId, qty, confirmation } = parsed.data;

  const { data: project } = await supabase
    .from('projects')
    .select('id, status, pcb_state')
    .eq('id', projectId)
    .single();

  if (!project) {
    return NextResponse.json({ success: false, error: 'Project not found' }, { status: 404 });
  }
  if (!hasOfficialDrc(project.pcb_state)) {
    return NextResponse.json(
      { success: false, error: 'Official KiCad DRC evidence is required before ordering' },
      { status: 422 },
    );
  }
  if (project.status !== 'DRC_CLEAN') {
    return NextResponse.json(
      { success: false, error: 'DRC must pass before ordering' },
      { status: 422 },
    );
  }

  const orderRef = `CIRQIX-${Date.now().toString(36).toUpperCase()}-${Math.random().toString(36).slice(2, 6).toUpperCase()}`;
  const admin = createAdminClient();
  const { error: intentError } = await admin.rpc('record_manufacturing_intent', {
    p_reference: orderRef,
    p_project_id: projectId,
    p_user_id: user.id,
    p_qty: qty,
    p_confirmation: confirmation,
  });
  if (intentError) {
    return NextResponse.json(
      { success: false, error: 'Unable to record manufacturing intent' },
      { status: 500 },
    );
  }

  return NextResponse.json({
    success: true,
    data: {
      orderRef,
      qty,
      message: 'Manufacturing intent recorded. Supplier submission is not configured.',
    },
  });
}
