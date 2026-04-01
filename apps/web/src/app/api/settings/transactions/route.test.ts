import { describe, it, expect, vi, beforeEach } from 'vitest';
import { GET } from './route';
import { createSupabaseMock } from '@/test/mocks/supabase';

const mockCreateClient = vi.fn();
vi.mock('@/shared/lib/supabase-server', () => ({
  createRouteHandlerClient: () => mockCreateClient(),
}));

beforeEach(() => {
  mockCreateClient.mockReset();
});

const SAMPLE_TRANSACTIONS = [
  { id: 'tx-1', action: 'chat', amount: -1, created_at: '2026-01-01T10:00:00Z', projects: { name: 'My PCB' } },
  { id: 'tx-2', action: 'schema', amount: -2, created_at: '2026-01-01T09:00:00Z', projects: null },
  { id: 'tx-3', action: 'topup', amount: 100, created_at: '2026-01-01T08:00:00Z', projects: null },
];

describe('GET /api/settings/transactions', () => {
  it('returns 200 with transaction list for authenticated user', async () => {
    mockCreateClient.mockReturnValue(
      createSupabaseMock({ listData: SAMPLE_TRANSACTIONS })
    );

    const res = await GET();
    expect(res.status).toBe(200);
    const json = await res.json() as { success: boolean; data: typeof SAMPLE_TRANSACTIONS };
    expect(json.success).toBe(true);
    expect(json.data).toHaveLength(3);
    expect(json.data[0]?.id).toBe('tx-1');
  });

  it('returns empty array when user has no transactions', async () => {
    mockCreateClient.mockReturnValue(
      createSupabaseMock({ listData: [] })
    );

    const res = await GET();
    expect(res.status).toBe(200);
    const json = await res.json() as { success: boolean; data: unknown[] };
    expect(json.success).toBe(true);
    expect(json.data).toHaveLength(0);
  });

  it('returns 401 when not authenticated', async () => {
    mockCreateClient.mockReturnValue(createSupabaseMock({ user: null }));
    const res = await GET();
    expect(res.status).toBe(401);
    const json = await res.json() as { error: string };
    expect(json.error).toBe('Unauthorized');
  });

  it('returns 500 on DB error', async () => {
    mockCreateClient.mockReturnValue(
      createSupabaseMock({ listData: null, listError: { message: 'DB failure' } })
    );

    const res = await GET();
    expect(res.status).toBe(500);
    const json = await res.json() as { success: boolean; error: string };
    expect(json.success).toBe(false);
    expect(json.error).toBe('DB failure');
  });

  it('includes project name in transaction data', async () => {
    mockCreateClient.mockReturnValue(
      createSupabaseMock({ listData: SAMPLE_TRANSACTIONS })
    );

    const res = await GET();
    const json = await res.json() as { data: typeof SAMPLE_TRANSACTIONS };
    expect(json.data[0]?.projects?.name).toBe('My PCB');
    expect(json.data[1]?.projects).toBeNull();
  });
});
