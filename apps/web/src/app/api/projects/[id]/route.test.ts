import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NextRequest } from 'next/server';
import { PATCH, DELETE } from './route';
import { createSupabaseMock } from '@/test/mocks/supabase';

const mockCreateClient = vi.fn();
vi.mock('@/shared/lib/supabase-server', () => ({
  createRouteHandlerClient: () => mockCreateClient(),
}));

const MOCK_PARAMS = Promise.resolve({ id: 'proj-123' });

function makeRequest(body: unknown) {
  return new NextRequest('http://localhost/api/projects/proj-123', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

const UPDATED_PROJECT = {
  id: 'proj-123',
  name: 'My LED Circuit',
  status: 'INITIAL',
  description: null,
  iteration_count: 0,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
};

beforeEach(() => {
  mockCreateClient.mockReset();
});

describe('PATCH /api/projects/[id]', () => {
  it('returns 200 with updated project on valid name', async () => {
    const mock = createSupabaseMock();
    mock.from = vi.fn().mockReturnValue({
      update: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            select: vi.fn().mockReturnValue({
              single: vi.fn().mockResolvedValue({ data: UPDATED_PROJECT, error: null }),
            }),
          }),
        }),
      }),
    });
    mockCreateClient.mockReturnValue(mock);

    const res = await PATCH(makeRequest({ name: 'My LED Circuit' }), { params: MOCK_PARAMS });
    expect(res.status).toBe(200);
    const json = await res.json() as { success: boolean; data: typeof UPDATED_PROJECT };
    expect(json.success).toBe(true);
    expect(json.data.name).toBe('My LED Circuit');
  });

  it('returns 400 when name is empty string', async () => {
    mockCreateClient.mockReturnValue(createSupabaseMock());
    const res = await PATCH(makeRequest({ name: '' }), { params: MOCK_PARAMS });
    expect(res.status).toBe(400);
  });

  it('returns 400 when name exceeds 100 chars', async () => {
    mockCreateClient.mockReturnValue(createSupabaseMock());
    const res = await PATCH(makeRequest({ name: 'x'.repeat(101) }), { params: MOCK_PARAMS });
    expect(res.status).toBe(400);
  });

  it('returns 400 on invalid JSON', async () => {
    mockCreateClient.mockReturnValue(createSupabaseMock());
    const req = new NextRequest('http://localhost/api/projects/proj-123', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: 'not-json',
    });
    const res = await PATCH(req, { params: MOCK_PARAMS });
    expect(res.status).toBe(400);
    const json = await res.json() as { error: string };
    expect(json.error).toBe('Invalid JSON');
  });

  it('returns 401 when not authenticated', async () => {
    mockCreateClient.mockReturnValue(createSupabaseMock({ user: null }));
    const res = await PATCH(makeRequest({ name: 'New name' }), { params: MOCK_PARAMS });
    expect(res.status).toBe(401);
  });

  it('returns 404 when project not found (PGRST116)', async () => {
    const mock = createSupabaseMock();
    mock.from = vi.fn().mockReturnValue({
      update: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            select: vi.fn().mockReturnValue({
              single: vi.fn().mockResolvedValue({
                data: null,
                error: { code: 'PGRST116', message: 'Row not found' },
              }),
            }),
          }),
        }),
      }),
    });
    mockCreateClient.mockReturnValue(mock);

    const res = await PATCH(makeRequest({ name: 'New name' }), { params: MOCK_PARAMS });
    expect(res.status).toBe(404);
  });

  it('returns 500 on unexpected DB error', async () => {
    const mock = createSupabaseMock();
    mock.from = vi.fn().mockReturnValue({
      update: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            select: vi.fn().mockReturnValue({
              single: vi.fn().mockResolvedValue({
                data: null,
                error: { code: '42P01', message: 'DB error' },
              }),
            }),
          }),
        }),
      }),
    });
    mockCreateClient.mockReturnValue(mock);

    const res = await PATCH(makeRequest({ name: 'New name' }), { params: MOCK_PARAMS });
    expect(res.status).toBe(500);
  });
});

describe('DELETE /api/projects/[id]', () => {
  function makeDeleteRequest() {
    return new NextRequest('http://localhost/api/projects/proj-123', { method: 'DELETE' });
  }

  it('returns 200 on successful delete', async () => {
    const mock = createSupabaseMock();
    mock.from = vi.fn().mockReturnValue({
      delete: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockResolvedValue({ error: null }),
        }),
      }),
    });
    mockCreateClient.mockReturnValue(mock);

    const res = await DELETE(makeDeleteRequest(), { params: MOCK_PARAMS });
    expect(res.status).toBe(200);
    const json = await res.json() as { success: boolean };
    expect(json.success).toBe(true);
  });

  it('returns 401 when not authenticated', async () => {
    mockCreateClient.mockReturnValue(createSupabaseMock({ user: null }));
    const res = await DELETE(makeDeleteRequest(), { params: MOCK_PARAMS });
    expect(res.status).toBe(401);
  });

  it('returns 500 on DB error', async () => {
    const mock = createSupabaseMock();
    mock.from = vi.fn().mockReturnValue({
      delete: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockResolvedValue({ error: { message: 'DB error' } }),
        }),
      }),
    });
    mockCreateClient.mockReturnValue(mock);

    const res = await DELETE(makeDeleteRequest(), { params: MOCK_PARAMS });
    expect(res.status).toBe(500);
  });
});
