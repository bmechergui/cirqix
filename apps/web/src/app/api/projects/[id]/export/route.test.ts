import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NextRequest } from 'next/server';

// --- Hoisted mock variables --------------------------------------------------
const { mockSingle, mockGetUser, mockRunCircuitSynthEngine } = vi.hoisted(() => ({
  mockSingle: vi.fn(),
  mockGetUser: vi.fn(),
  mockRunCircuitSynthEngine: vi.fn(),
}));

// --- Supabase mock -----------------------------------------------------------
vi.mock('@/shared/lib/supabase-server', () => ({
  createRouteHandlerClient: vi.fn().mockResolvedValue({
    auth: { getUser: mockGetUser },
    from: vi.fn().mockReturnValue({
      select: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            single: mockSingle,
          }),
        }),
      }),
    }),
  }),
}));

// --- Agents mock (runCircuitSynthEngine) -------------------------------------
vi.mock('@layrix/agents', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@layrix/agents')>();
  return { ...actual, runCircuitSynthEngine: mockRunCircuitSynthEngine };
});

// --- JSZip mock --------------------------------------------------------------
vi.mock('jszip', () => {
  const mockGenerateAsync = vi.fn().mockResolvedValue(new Uint8Array([80, 75, 3, 4]));
  const mockFile = vi.fn();
  const JSZipMock = vi.fn().mockImplementation(() => ({
    file: mockFile,
    generateAsync: mockGenerateAsync,
  }));
  return { default: JSZipMock };
});

// Import after mocks
import { GET } from './route';

// --- Helpers -----------------------------------------------------------------
function makeReq() {
  return new NextRequest('http://localhost/api/projects/proj-1/export');
}

function makeParams(id = 'proj-1') {
  return { params: Promise.resolve({ id }) };
}

const PCB_STATE_WITH_COMPONENTS = {
  components: [
    { ref: 'R1', value: '330R', footprint: '0402' },
    { ref: 'LED1', value: 'LED', footprint: 'LED' },
  ],
  nets: ['GND', 'VCC'],
  board_width_mm: 50,
  board_height_mm: 50,
};

const CIRCUIT_SYNTH_RESULT = {
  kicad_sch_content: '(kicad_sch (version 20230121))',
  kicad_pcb_content: '(kicad_pcb (version 20221018))',
};

// --- Tests -------------------------------------------------------------------
describe('GET /api/projects/[id]/export', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('returns 401 when unauthenticated', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });

    const res = await GET(makeReq(), makeParams());
    const json = await res.json() as { success: boolean; error: string };

    expect(res.status).toBe(401);
    expect(json.success).toBe(false);
    expect(json.error).toBe('Unauthorized');
  });

  it('returns 404 when project not found', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-1' } } });
    mockSingle.mockResolvedValue({
      data: null,
      error: { code: 'PGRST116', message: 'Not found' },
    });

    const res = await GET(makeReq(), makeParams());
    expect(res.status).toBe(404);
  });

  it('returns 500 on unexpected DB error', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-1' } } });
    mockSingle.mockResolvedValue({
      data: null,
      error: { code: '42P01', message: 'relation does not exist' },
    });

    const res = await GET(makeReq(), makeParams());
    expect(res.status).toBe(500);
  });

  it('returns 422 when pcb_state is null', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-1' } } });
    mockSingle.mockResolvedValue({
      data: { pcb_state: null, name: 'My PCB' },
      error: null,
    });

    const res = await GET(makeReq(), makeParams());
    const json = await res.json() as { success: boolean; error: string };

    expect(res.status).toBe(422);
    expect(json.error).toContain('No PCB data');
  });

  it('returns 422 when pcb_state has no components', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-1' } } });
    mockSingle.mockResolvedValue({
      data: { pcb_state: { components: [] }, name: 'My PCB' },
      error: null,
    });

    const res = await GET(makeReq(), makeParams());
    const json = await res.json() as { success: boolean; error: string };

    expect(res.status).toBe(422);
    expect(json.error).toContain('no components');
  });

  it('returns ZIP with correct headers on success', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-1' } } });
    mockSingle.mockResolvedValue({
      data: { pcb_state: PCB_STATE_WITH_COMPONENTS, name: 'My PCB' },
      error: null,
    });
    mockRunCircuitSynthEngine.mockResolvedValue(CIRCUIT_SYNTH_RESULT);

    const res = await GET(makeReq(), makeParams());

    expect(res.status).toBe(200);
    expect(res.headers.get('Content-Type')).toBe('application/zip');
    expect(res.headers.get('Content-Disposition')).toContain('attachment');
    expect(res.headers.get('Content-Disposition')).toContain('.zip');
  });

  it('calls runCircuitSynthEngine with board dimensions from pcb_state', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-1' } } });
    mockSingle.mockResolvedValue({
      data: {
        pcb_state: { ...PCB_STATE_WITH_COMPONENTS, board_width_mm: 80, board_height_mm: 60 },
        name: 'Big Board',
      },
      error: null,
    });
    mockRunCircuitSynthEngine.mockResolvedValue(CIRCUIT_SYNTH_RESULT);

    await GET(makeReq(), makeParams());

    expect(mockRunCircuitSynthEngine).toHaveBeenCalledWith(
      expect.objectContaining({ components: expect.any(Array) }),
      80,
      60
    );
  });
});
