import { createClient } from '@supabase/supabase-js';
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { checkRateLimit } from '@/shared/lib/ratelimit';

const schema = z.object({
  email: z.string().email(),
});

export async function POST(request: Request) {
  // Rate limiting (PLAN.md §5.1) : endpoint public sans auth, cible de spam.
  // Le DERNIER élément de x-forwarded-for est ajouté par la plateforme
  // (Vercel) et fait foi ; le premier est contrôlé par le client (spoofable).
  const xff = request.headers.get('x-forwarded-for');
  const ip = xff?.split(',').pop()?.trim()
    || request.headers.get('x-real-ip')
    || 'unknown';
  const { success } = await checkRateLimit(`waitlist:${ip}`);
  if (!success) {
    return NextResponse.json({ success: false, error: 'rate_limited' }, { status: 429 });
  }

  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL ?? '',
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? ''
  );

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ success: false, error: 'Invalid JSON' }, { status: 400 });
  }

  const parsed = schema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ success: false, error: 'Invalid email address' }, { status: 400 });
  }

  const { email } = parsed.data;

  const { error } = await supabase.from('waitlist').insert({ email });

  if (error) {
    if (error.code === '23505') {
      return NextResponse.json({ success: false, error: 'already_registered' }, { status: 409 });
    }
    return NextResponse.json({ success: false, error: 'Server error' }, { status: 500 });
  }

  return NextResponse.json({ success: true }, { status: 201 });
}
