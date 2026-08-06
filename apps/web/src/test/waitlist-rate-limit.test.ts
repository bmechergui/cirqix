import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NextRequest } from 'next/server';

// Rate limiting de /api/waitlist (PLAN.md §5.1) : 429 au-delà du quota,
// sans jamais atteindre Supabase.

const checkRateLimitMock = vi.fn();
const insertMock = vi.fn().mockResolvedValue({ error: null });

vi.mock('@/shared/lib/ratelimit', () => ({
  checkRateLimit: (...args: unknown[]) => checkRateLimitMock(...args),
}));

vi.mock('@supabase/supabase-js', () => ({
  createClient: () => ({ from: () => ({ insert: insertMock }) }),
}));

function makeRequest(body: unknown, ip = '1.2.3.4'): NextRequest {
  return new NextRequest('http://localhost:3333/api/waitlist', {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-forwarded-for': ip },
    body: JSON.stringify(body),
  });
}

describe('POST /api/waitlist — rate limiting', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://fake.supabase.co';
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'anon';
  });

  it('renvoie 429 sans toucher Supabase quand le quota est dépassé', async () => {
    checkRateLimitMock.mockResolvedValue({ success: false, remaining: 0 });
    const { POST } = await import('@/app/api/waitlist/route');

    const res = await POST(makeRequest({ email: 'a@b.co' }));

    expect(res.status).toBe(429);
    expect(insertMock).not.toHaveBeenCalled();
  });

  it('identifie le quota par le dernier IP x-forwarded-for (ajouté par la plateforme)', async () => {
    checkRateLimitMock.mockResolvedValue({ success: true, remaining: 9 });
    const { POST } = await import('@/app/api/waitlist/route');

    // Le 1er élément est contrôlé par le client (spoofable) ; le dernier est
    // ajouté par le proxy/Vercel et fait foi.
    const req = new NextRequest('http://localhost:3333/api/waitlist', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-forwarded-for': '6.6.6.6, 9.8.7.6',
      },
      body: JSON.stringify({ email: 'a@b.co' }),
    });
    await POST(req);

    expect(checkRateLimitMock).toHaveBeenCalledWith('waitlist:9.8.7.6');
  });

  it('laisse passer et insère quand le quota le permet', async () => {
    checkRateLimitMock.mockResolvedValue({ success: true, remaining: 9 });
    const { POST } = await import('@/app/api/waitlist/route');

    const res = await POST(makeRequest({ email: 'a@b.co' }));

    expect(res.status).toBe(201);
    expect(insertMock).toHaveBeenCalledWith({ email: 'a@b.co' });
  });
});
