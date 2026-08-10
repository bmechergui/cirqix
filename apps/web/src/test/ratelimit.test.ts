import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Le module sous test lit les env à chaud et met en cache les limiters :
// chaque test repart d'un module frais via resetModules + import dynamique.

const ORIGINAL_ENV = { ...process.env };

async function importFresh() {
  vi.resetModules();
  return import('@/shared/lib/ratelimit');
}

describe('ratelimit (shared/lib)', () => {
  beforeEach(() => {
    vi.resetModules();
    delete process.env.UPSTASH_REDIS_REST_URL;
    delete process.env.UPSTASH_REDIS_REST_TOKEN;
  });

  afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
    vi.restoreAllMocks();
    vi.unmock('@upstash/ratelimit');
    vi.unmock('@upstash/redis');
  });

  it('fail-open quand UPSTASH_REDIS_REST_URL/TOKEN sont absents', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const { checkRateLimit } = await importFresh();

    const res = await checkRateLimit('waitlist:1.2.3.4');

    expect(res.success).toBe(true);
    expect(warn).toHaveBeenCalledOnce();
  });

  it('ne logue le warning fail-open qu une seule fois', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const { checkRateLimit } = await importFresh();

    await checkRateLimit('a');
    await checkRateLimit('b');
    await checkRateLimit('c');

    expect(warn).toHaveBeenCalledTimes(1);
  });

  it('utilise Upstash fixedWindow(10, 60s) par défaut quand les env sont présentes', async () => {
    process.env.UPSTASH_REDIS_REST_URL = 'https://fake.upstash.io';
    process.env.UPSTASH_REDIS_REST_TOKEN = 'token';

    const limitMock = vi.fn().mockResolvedValue({ success: true, remaining: 9 });
    const fixedWindowMock = vi.fn().mockReturnValue('fixed-window-config');
    vi.doMock('@upstash/ratelimit', () => ({
      Ratelimit: Object.assign(
        vi.fn().mockImplementation(() => ({ limit: limitMock })),
        { fixedWindow: fixedWindowMock }
      ),
    }));
    vi.doMock('@upstash/redis', () => ({ Redis: vi.fn() }));

    const { checkRateLimit } = await importFresh();
    const res = await checkRateLimit('waitlist:1.2.3.4');

    expect(fixedWindowMock).toHaveBeenCalledWith(10, '60 s');
    expect(limitMock).toHaveBeenCalledWith('waitlist:1.2.3.4');
    expect(res).toEqual({ success: true, remaining: 9 });
  });

  it('renvoie success=false quand Upstash refuse (quota dépassé)', async () => {
    process.env.UPSTASH_REDIS_REST_URL = 'https://fake.upstash.io';
    process.env.UPSTASH_REDIS_REST_TOKEN = 'token';

    const limitMock = vi.fn().mockResolvedValue({ success: false, remaining: 0 });
    vi.doMock('@upstash/ratelimit', () => ({
      Ratelimit: Object.assign(
        vi.fn().mockImplementation(() => ({ limit: limitMock })),
        { fixedWindow: vi.fn() }
      ),
    }));
    vi.doMock('@upstash/redis', () => ({ Redis: vi.fn() }));

    const { checkRateLimit } = await importFresh();
    const res = await checkRateLimit('waitlist:1.2.3.4');

    expect(res.success).toBe(false);
    expect(res.remaining).toBe(0);
  });

  it('fail-open avec warning si Upstash lève une exception (coupure réseau)', async () => {
    process.env.UPSTASH_REDIS_REST_URL = 'https://fake.upstash.io';
    process.env.UPSTASH_REDIS_REST_TOKEN = 'token';

    const limitMock = vi.fn().mockRejectedValue(new Error('fetch failed'));
    vi.doMock('@upstash/ratelimit', () => ({
      Ratelimit: Object.assign(
        vi.fn().mockImplementation(() => ({ limit: limitMock })),
        { fixedWindow: vi.fn() }
      ),
    }));
    vi.doMock('@upstash/redis', () => ({ Redis: vi.fn() }));
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});

    const { checkRateLimit } = await importFresh();
    const res = await checkRateLimit('waitlist:1.2.3.4');

    expect(res.success).toBe(true);
    expect(warn).toHaveBeenCalled();
  });
});
