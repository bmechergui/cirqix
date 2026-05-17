import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  runRealDrc,
  DrcServiceUnavailableError,
} from './drc-service';

const ORIGINAL_FETCH = globalThis.fetch;

function makeKiCadPcb(): string {
  return '(kicad_pcb (version 20240108) (generator pcbnew))';
}

function makeOkResponse(body: object) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('drc-service', () => {
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
        drc_clean: true,
        violations: [],
        fixed_count: 0,
        kicad_pcb_b64: null,
        skipped: false,
      }),
    ) as unknown as typeof fetch;

    const result = await runRealDrc({
      kicadPcbContent: makeKiCadPcb(),
      autoFix: true,
    });
    expect(result.drcClean).toBe(true);
    expect(result.violations).toEqual([]);
    expect(result.skipped).toBe(false);
  });

  it('returns updated pcb_content when auto-fix applied', async () => {
    const fixedPcb = '(kicad_pcb fixed)';
    globalThis.fetch = vi.fn(async () =>
      makeOkResponse({
        drc_clean: true,
        violations: [],
        fixed_count: 2,
        kicad_pcb_b64: Buffer.from(fixedPcb).toString('base64'),
        skipped: false,
      }),
    ) as unknown as typeof fetch;

    const result = await runRealDrc({
      kicadPcbContent: makeKiCadPcb(),
      autoFix: true,
    });
    expect(result.fixedCount).toBe(2);
    expect(result.kicadPcbContent).toBe(fixedPcb);
  });

  it('propagates skipped state when kicad-cli unavailable', async () => {
    globalThis.fetch = vi.fn(async () =>
      makeOkResponse({
        drc_clean: true,
        violations: [],
        fixed_count: 0,
        kicad_pcb_b64: null,
        skipped: true,
        warning: 'kicad-cli not available',
      }),
    ) as unknown as typeof fetch;

    const result = await runRealDrc({
      kicadPcbContent: makeKiCadPcb(),
      autoFix: true,
    });
    expect(result.skipped).toBe(true);
    expect(result.warning).toContain('kicad-cli');
  });

  it('throws DrcServiceUnavailableError when KICAD_SERVICE_URL is missing', async () => {
    delete process.env['KICAD_SERVICE_URL'];
    await expect(
      runRealDrc({ kicadPcbContent: makeKiCadPcb(), autoFix: true }),
    ).rejects.toBeInstanceOf(DrcServiceUnavailableError);
  });

  it('throws DrcServiceUnavailableError on HTTP 500', async () => {
    globalThis.fetch = vi.fn(async () =>
      new Response('{"detail":"boom"}', { status: 500 }),
    ) as unknown as typeof fetch;
    await expect(
      runRealDrc({ kicadPcbContent: makeKiCadPcb(), autoFix: true }),
    ).rejects.toBeInstanceOf(DrcServiceUnavailableError);
  });

  it('throws DrcServiceUnavailableError on network failure', async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError('fetch failed');
    }) as unknown as typeof fetch;
    await expect(
      runRealDrc({ kicadPcbContent: makeKiCadPcb(), autoFix: true }),
    ).rejects.toBeInstanceOf(DrcServiceUnavailableError);
  });

  it('posts request with base64 + auto_fix flag', async () => {
    const fetchSpy = vi.fn(async () =>
      makeOkResponse({ drc_clean: true, violations: [], fixed_count: 0, skipped: false }),
    ) as unknown as typeof fetch;
    globalThis.fetch = fetchSpy;

    await runRealDrc({ kicadPcbContent: '(kicad_pcb x)', autoFix: false });
    const call = (fetchSpy as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    const url = call?.[0] as string;
    const init = call?.[1] as RequestInit | undefined;
    expect(url).toBe('http://localhost:8000/drc/auto');
    expect(init?.method).toBe('POST');
    const body = JSON.parse(String(init?.body)) as {
      kicad_pcb_b64: string;
      auto_fix: boolean;
    };
    expect(body.auto_fix).toBe(false);
    expect(Buffer.from(body.kicad_pcb_b64, 'base64').toString('utf-8')).toBe('(kicad_pcb x)');
  });
});
