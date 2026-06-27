import { NextResponse, type NextRequest } from 'next/server';
import { createRouteHandlerClient } from '@/shared/lib/supabase-server';
import type { PCBState } from '@cirqix/types';

const BUCKET = 'kicad-files';
const SIGNED_URL_TTL = 60 * 60; // 1h

/**
 * Regenerates signed URLs for any KiCad artifacts stored in pcb_state.
 * Stored signed URLs expire after 1h — always refresh them on read so the
 * viewer gets a valid URL regardless of when the project was last generated.
 */
async function refreshSignedUrls(
  supabase: Awaited<ReturnType<typeof createRouteHandlerClient>>,
  state: PCBState,
  userId: string,
  projectId: string,
): Promise<PCBState> {
  const results = await Promise.all([
    state.kicad_sch_url
      ? supabase.storage.from(BUCKET).createSignedUrl(`${userId}/${projectId}/schematic.kicad_sch`, SIGNED_URL_TTL)
      : null,
    state.kicad_pcb_url
      ? supabase.storage.from(BUCKET).createSignedUrl(`${userId}/${projectId}/pcb.kicad_pcb`, SIGNED_URL_TTL)
      : null,
  ]);

  const [schResult, pcbResult] = results;
  // Conditional spread avoids setting optional properties to `undefined`
  // (exactOptionalPropertyTypes strictness).
  return {
    ...state,
    ...(schResult?.data?.signedUrl ? { kicad_sch_url: schResult.data.signedUrl } : {}),
    ...(pcbResult?.data?.signedUrl ? { kicad_pcb_url: pcbResult.data.signedUrl } : {}),
  };
}

export async function GET(
  _req: NextRequest,
  ctx: { params: Promise<{ id: string }> }
) {
  const supabase = await createRouteHandlerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }

  const { id } = await ctx.params;
  const { data, error } = await supabase
    .from('projects')
    .select('pcb_state')
    .eq('id', id)
    .single();

  if (error || !data) {
    return NextResponse.json({ success: false, error: 'Not found' }, { status: 404 });
  }

  const rawState = data.pcb_state as PCBState | null;
  const pcbState = rawState
    ? await refreshSignedUrls(supabase, rawState, user.id, id)
    : null;

  return NextResponse.json({ success: true, data: { pcb_state: pcbState } });
}

export async function PATCH(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> }
) {
  const supabase = await createRouteHandlerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }

  let payload: unknown;
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json({ success: false, error: 'Invalid JSON' }, { status: 400 });
  }

  if (typeof payload !== 'object' || payload === null) {
    return NextResponse.json({ success: false, error: 'Payload must be an object' }, { status: 400 });
  }

  const { id } = await ctx.params;
  const { data, error } = await supabase
    .from('projects')
    .update({ pcb_state: payload, updated_at: new Date().toISOString() })
    .eq('id', id)
    .select('pcb_state')
    .single();

  if (error || !data) {
    return NextResponse.json({ success: false, error: error?.message ?? 'Not found' }, { status: 404 });
  }

  return NextResponse.json({ success: true, data: { pcb_state: data.pcb_state } });
}
