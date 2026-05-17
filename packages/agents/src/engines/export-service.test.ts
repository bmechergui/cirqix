import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  runRealExport,
  ExportServiceUnavailableError,
} from './export-service';

const ORIGINAL_FETCH = globalThis.fetch;

function makeOkResponse(body: object) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('export-service', () => {
  beforeEach(() => {
    process.env['KICAD_SERVICE_URL'] = 'http://localhost:8000';
  });
  afterEach(() => {
    delete process.env['KICAD_SERVICE_URL'];
    globalThis.fetch = ORIGINAL_FETCH;
    vi.restoreAllMocks();
  });

  it('returns manufacturing files + quote on success', async () => {
    const zipB64 = Buffer.from('FAKE-ZIP-DATA').toString('base64');
    globalThis.fetch = vi.fn(async () =>
      makeOkResponse({
        files: ['F_Cu.gbr', 'B_Cu.gbr'],
        zip_b64: zipB64,
        quote_usd: 12.5,
        lead_time_days: 7,
        skipped: false,
      }),
    ) as unknown as typeof fetch;

    const result = await runRealExport({
      kicadPcbContent: '(kicad_pcb x)',
      projectId: 'p1',
    });
    expect(result.skipped).toBe(false);
    expect(result.files).toEqual(['F_Cu.gbr', 'B_Cu.gbr']);
    expect(result.quoteUsd).toBe(12.5);
    expect(result.leadTimeDays).toBe(7);
    expect(result.zipB64).toBe(zipB64);
  });

  it('propagates skipped when kicad-cli unavailable', async () => {
    globalThis.fetch = vi.fn(async () =>
      makeOkResponse({
        files: [],
        zip_b64: null,
        quote_usd: 0,
        lead_time_days: 0,
        skipped: true,
        warning: 'kicad-cli not available',
      }),
    ) as unknown as typeof fetch;

    const result = await runRealExport({
      kicadPcbContent: '(kicad_pcb x)',
      projectId: 'p1',
    });
    expect(result.skipped).toBe(true);
    expect(result.warning).toContain('kicad-cli');
    expect(result.zipB64).toBeUndefined();
  });

  it('throws ExportServiceUnavailableError when KICAD_SERVICE_URL missing', async () => {
    delete process.env['KICAD_SERVICE_URL'];
    await expect(
      runRealExport({ kicadPcbContent: '(kicad_pcb x)', projectId: 'p1' }),
    ).rejects.toBeInstanceOf(ExportServiceUnavailableError);
  });

  it('throws on HTTP 500', async () => {
    globalThis.fetch = vi.fn(async () =>
      new Response('{"detail":"boom"}', { status: 500 }),
    ) as unknown as typeof fetch;
    await expect(
      runRealExport({ kicadPcbContent: '(kicad_pcb x)', projectId: 'p1' }),
    ).rejects.toBeInstanceOf(ExportServiceUnavailableError);
  });

  it('throws on network failure', async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError('fetch failed');
    }) as unknown as typeof fetch;
    await expect(
      runRealExport({ kicadPcbContent: '(kicad_pcb x)', projectId: 'p1' }),
    ).rejects.toBeInstanceOf(ExportServiceUnavailableError);
  });

  it('posts request with base64 + project_id', async () => {
    const fetchSpy = vi.fn(async () =>
      makeOkResponse({ files: [], zip_b64: null, quote_usd: 0, lead_time_days: 0, skipped: false }),
    ) as unknown as typeof fetch;
    globalThis.fetch = fetchSpy;

    await runRealExport({ kicadPcbContent: '(kicad_pcb test)', projectId: 'my-proj' });
    const call = (fetchSpy as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    const url = call?.[0] as string;
    const init = call?.[1] as RequestInit | undefined;
    expect(url).toBe('http://localhost:8000/export/all');
    const body = JSON.parse(String(init?.body)) as {
      kicad_pcb_b64: string;
      project_id: string;
    };
    expect(body.project_id).toBe('my-proj');
    expect(Buffer.from(body.kicad_pcb_b64, 'base64').toString('utf-8')).toBe('(kicad_pcb test)');
  });
});
