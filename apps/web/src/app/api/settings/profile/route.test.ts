import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NextRequest } from 'next/server';
import { GET, PATCH } from './route';
import { createSupabaseMock } from '@/test/mocks/supabase';

const mockCreateClient = vi.fn();
vi.mock('@/shared/lib/supabase-server', () => ({
  createRouteHandlerClient: () => mockCreateClient(),
}));

beforeEach(() => {
  mockCreateClient.mockReset();
});

describe('GET /api/settings/profile', () => {
  it('returns 200 with profile data for authenticated user', async () => {
    mockCreateClient.mockReturnValue(
      createSupabaseMock({
        user: { id: 'user-1', email: 'a@b.com', user_metadata: { full_name: 'Alice', avatar_url: 'https://img.test/a.png' } },
      })
    );

    const res = await GET();
    expect(res.status).toBe(200);
    const json = await res.json() as { success: boolean; data: { email: string; full_name: string | null; avatar_url: string | null } };
    expect(json.success).toBe(true);
    expect(json.data.email).toBe('a@b.com');
    expect(json.data.full_name).toBe('Alice');
    expect(json.data.avatar_url).toBe('https://img.test/a.png');
  });

  it('returns null for missing metadata fields', async () => {
    mockCreateClient.mockReturnValue(
      createSupabaseMock({
        user: { id: 'user-1', email: 'a@b.com', user_metadata: {} },
      })
    );

    const res = await GET();
    const json = await res.json() as { success: boolean; data: { full_name: string | null; avatar_url: string | null } };
    expect(json.success).toBe(true);
    expect(json.data.full_name).toBeNull();
    expect(json.data.avatar_url).toBeNull();
  });

  it('returns 401 when not authenticated', async () => {
    mockCreateClient.mockReturnValue(createSupabaseMock({ user: null }));
    const res = await GET();
    expect(res.status).toBe(401);
  });
});

describe('PATCH /api/settings/profile', () => {
  function makeRequest(body: unknown) {
    return new NextRequest('http://localhost/api/settings/profile', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  }

  it('returns 200 with updated profile on valid input', async () => {
    mockCreateClient.mockReturnValue(
      createSupabaseMock({
        updateUserData: {
          user: {
            id: 'user-1',
            email: 'a@b.com',
            user_metadata: { full_name: 'Bob', avatar_url: null },
          },
        },
      })
    );

    const res = await PATCH(makeRequest({ full_name: 'Bob' }));
    expect(res.status).toBe(200);
    const json = await res.json() as { success: boolean; data: { full_name: string | null } };
    expect(json.success).toBe(true);
    expect(json.data.full_name).toBe('Bob');
  });

  it('returns 400 on invalid JSON', async () => {
    mockCreateClient.mockReturnValue(createSupabaseMock());
    const req = new NextRequest('http://localhost/api/settings/profile', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: 'not-json',
    });
    const res = await PATCH(req);
    expect(res.status).toBe(400);
    const json = await res.json() as { error: string };
    expect(json.error).toBe('Invalid JSON');
  });

  it('returns 400 when avatar_url is invalid URL', async () => {
    mockCreateClient.mockReturnValue(createSupabaseMock());
    const res = await PATCH(makeRequest({ avatar_url: 'not-a-url' }));
    expect(res.status).toBe(400);
  });

  it('returns 400 when full_name is empty string', async () => {
    mockCreateClient.mockReturnValue(createSupabaseMock());
    const res = await PATCH(makeRequest({ full_name: '' }));
    expect(res.status).toBe(400);
  });

  it('returns 401 when not authenticated', async () => {
    mockCreateClient.mockReturnValue(createSupabaseMock({ user: null }));
    const res = await PATCH(makeRequest({ full_name: 'Bob' }));
    expect(res.status).toBe(401);
  });

  it('returns 500 when updateUser fails', async () => {
    mockCreateClient.mockReturnValue(
      createSupabaseMock({ updateUserError: { message: 'Auth error' } })
    );
    const res = await PATCH(makeRequest({ full_name: 'Bob' }));
    expect(res.status).toBe(500);
    const json = await res.json() as { error: string };
    expect(json.error).toBe('Auth error');
  });

  it('accepts null avatar_url to clear avatar', async () => {
    mockCreateClient.mockReturnValue(
      createSupabaseMock({
        updateUserData: {
          user: { id: 'user-1', email: 'a@b.com', user_metadata: { full_name: 'Bob', avatar_url: null } },
        },
      })
    );
    const res = await PATCH(makeRequest({ avatar_url: null }));
    expect(res.status).toBe(200);
    const json = await res.json() as { data: { avatar_url: string | null } };
    expect(json.data.avatar_url).toBeNull();
  });
});
