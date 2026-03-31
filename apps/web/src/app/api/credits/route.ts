import { NextResponse } from 'next/server';
import { createRouteHandlerClient } from '@/shared/lib/supabase-server';

export async function GET() {
  const supabase = await createRouteHandlerClient();

  const { data: { user } } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }

  const { data, error } = await supabase
    .from('credits')
    .select('balance, plan')
    .eq('user_id', user.id)
    .single();

  if (error) {
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }

  return NextResponse.json({ success: true, data });
}
