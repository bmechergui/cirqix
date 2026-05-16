import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  runRealErc,
  ErcServiceUnavailableError,
} from './erc-service';

const ORIGINAL_FETCH = globalThis.fetch;

function makeKiCadSch(): string {
  return '(kicad_sch (version 20231120) (generator "test"))';
}

function makeOkResponse(body: object) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('erc-service', () => {
  beforeEach(() => {
    process.env['KICAD_SERVICE_URL'] = 'http://localhost:8000';
  });
  afterEach(() => {
    delete process.env['KICAD_SERVICE_URL'];
    globalThis.fetch = ORIGINAL_FETCH;
    vi.restoreAllMocks();
  });

  it('returns clean result on 200 with no violations', async () => {
    globalThis.fetch = vi.fn(async () =>
      makeOkResponse({
        erc_clean: true,
        violations: [],
        fixed_count: 0,
        kicad_sch_b64: null,
        skipped: false,
        warning: null,
      }),
    ) as unknown as typeof fetch;

    const result = await runRealErc({
      kicadSchContent: makeKiCadSch(),
      autoFix: true,
    });
    expect(result.ercClean).toBe(true);
    expect(result.violations).toEqual([]);
    expect(result.skipped).toBe(false);
    expect(result.kicadSchContent).toBeUndefined();
  });

  it('returns updated kicad_sch_content when auto-fix applied', async () => {
    const fixedSch = '(kicad_sch updated)';
    globalThis.fetch = vi.fn(async () =>
      makeOkResponse({
        erc_clean: true,
        violations: [],
        fixed_count: 2,
        kicad_sch_b64: Buffer.from(fixedSch).toString('base64'),
        skipped: false,
        warning: null,
      }),
    ) as unknown as typeof fetch;

    const result = await runRealErc({
      kicadSchContent: makeKiCadSch(),
      autoFix: true,
    });
    expect(result.fixedCount).toBe(2);
    expect(result.kicadSchContent).toBe(fixedSch);
  });

  it('propagates skipped=true when kicad-cli unavailable', async () => {
    globalThis.fetch = vi.fn(async () =>
      makeOkResponse({
        erc_clean: true,
        violations: [],
        fixed_count: 0,
        kicad_sch_b64: null,
        skipped: true,
        warning: 'kicad-cli not available',
      }),
    ) as unknown as typeof fetch;

    const result = await runRealErc({
      kicadSchContent: makeKiCadSch(),
      autoFix: true,
    });
    expect(result.skipped).toBe(true);
    expect(result.warning).toContain('kicad-cli');
  });

  it('throws ErcServiceUnavailableError when KICAD_SERVICE_URL is missing', async () => {
    delete process.env['KICAD_SERVICE_URL'];
    await expect(
      runRealErc({ kicadSchContent: makeKiCadSch(), autoFix: true }),
    ).rejects.toBeInstanceOf(ErcServiceUnavailableError);
  });

  it('throws ErcServiceUnavailableError on HTTP 500', async () => {
    globalThis.fetch = vi.fn(async () =>
      new Response('{"detail":"boom"}', { status: 500 }),
    ) as unknown as typeof fetch;
    await expect(
      runRealErc({ kicadSchContent: makeKiCadSch(), autoFix: true }),
    ).rejects.toBeInstanceOf(ErcServiceUnavailableError);
  });

  it('throws ErcServiceUnavailableError on network error', async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError('fetch failed');
    }) as unknown as typeof fetch;
    await expect(
      runRealErc({ kicadSchContent: makeKiCadSch(), autoFix: true }),
    ).rejects.toBeInstanceOf(ErcServiceUnavailableError);
  });

  it('throws ErcServiceUnavailableError on timeout', async () => {
    globalThis.fetch = vi.fn(async () => {
      const err = new Error('aborted');
      err.name = 'AbortError';
      throw err;
    }) as unknown as typeof fetch;
    await expect(
      runRealErc({ kicadSchContent: makeKiCadSch(), autoFix: true }),
    ).rejects.toBeInstanceOf(ErcServiceUnavailableError);
  });

  it('posts request body with base64 + auto_fix flag', async () => {
    const fetchSpy = vi.fn(async () =>
      makeOkResponse({ erc_clean: true, violations: [], fixed_count: 0, skipped: false }),
    ) as unknown as typeof fetch;
    globalThis.fetch = fetchSpy;

    await runRealErc({ kicadSchContent: '(kicad_sch test)', autoFix: false });
    const call = (fetchSpy as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    const url = call?.[0] as string;
    const init = call?.[1] as RequestInit | undefined;
    expect(url).toBe('http://localhost:8000/erc');
    expect(init?.method).toBe('POST');
    const body = JSON.parse(String(init?.body)) as {
      kicad_sch_b64: string;
      auto_fix: boolean;
    };
    expect(body.auto_fix).toBe(false);
    expect(Buffer.from(body.kicad_sch_b64, 'base64').toString('utf-8')).toBe(
      '(kicad_sch test)',
    );
  });
});
