import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

/**
 * Souscription Realtime au journal d'un run.
 *
 * La frontière de sécurité n'est PAS le filtre `run_id=eq.` : n'importe qui
 * peut composer un channel. RLS `pcb_run_events_select_own` (migration 019)
 * refuse les lignes d'autrui. Le filtre n'existe que pour ne pas recevoir
 * le journal de tous les runs de l'utilisateur.
 *
 * Sans URL/clé, ou si le `runId` n'est pas un UUID, on rend `null` tout de
 * suite : `followRun` bascule sur le sondage, sans attendre un timeout.
 */

const channelOn = vi.fn();
const channelSubscribe = vi.fn();
const removeChannel = vi.fn();

vi.mock('@/shared/lib/supabase-browser', () => ({
  createSupabaseBrowserClient: () => ({
    channel: () => {
      const ch: { on: typeof channelOn; subscribe: typeof channelSubscribe } = {
        on: channelOn,
        subscribe: channelSubscribe,
      };
      channelOn.mockReturnValue(ch);
      return ch;
    },
    removeChannel,
  }),
}));

describe('subscribeToRunEvents', () => {
  beforeEach(() => {
    channelOn.mockReset();
    channelSubscribe.mockReset();
    removeChannel.mockReset();
    vi.unstubAllEnvs();
    vi.stubEnv('NEXT_PUBLIC_SUPABASE_URL', 'https://example.supabase.co');
    vi.stubEnv('NEXT_PUBLIC_SUPABASE_ANON_KEY', 'anon-key-for-tests');
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('rend null sans credentials plutôt que de tenter une socket', async () => {
    vi.stubEnv('NEXT_PUBLIC_SUPABASE_URL', '');
    vi.stubEnv('NEXT_PUBLIC_SUPABASE_ANON_KEY', '');
    const { subscribeToRunEvents } = await import(
      '@/features/workspace/lib/follow-run-realtime'
    );
    const handle = await subscribeToRunEvents({
      runId: '11111111-1111-4111-8111-111111111111',
      onInsert: () => undefined,
      onLost: () => undefined,
    });
    expect(handle).toBeNull();
    expect(channelSubscribe).not.toHaveBeenCalled();
  });

  it('refuse un runId qui n est pas un UUID (filtre Realtime interpolé)', async () => {
    const { subscribeToRunEvents } = await import(
      '@/features/workspace/lib/follow-run-realtime'
    );
    const handle = await subscribeToRunEvents({
      runId: 'r1;drop',
      onInsert: () => undefined,
      onLost: () => undefined,
    });
    expect(handle).toBeNull();
    expect(channelOn).not.toHaveBeenCalled();
  });

  it('filtre la souscription sur run_id et n écoute que les INSERT', async () => {
    channelSubscribe.mockImplementation((cb: (status: string) => void) => {
      cb('SUBSCRIBED');
    });

    const { subscribeToRunEvents } = await import(
      '@/features/workspace/lib/follow-run-realtime'
    );
    const handle = await subscribeToRunEvents({
      runId: '11111111-1111-4111-8111-111111111111',
      onInsert: () => undefined,
      onLost: () => undefined,
    });

    expect(handle).not.toBeNull();
    expect(channelOn).toHaveBeenCalledWith(
      'postgres_changes',
      expect.objectContaining({
        event: 'INSERT',
        schema: 'public',
        table: 'pcb_run_events',
        filter: 'run_id=eq.11111111-1111-4111-8111-111111111111',
      }),
      expect.any(Function),
    );
    handle?.unsubscribe();
    expect(removeChannel).toHaveBeenCalled();
  });

  it('transmet la ligne INSERT au callback', async () => {
    channelSubscribe.mockImplementation((cb: (status: string) => void) => {
      cb('SUBSCRIBED');
    });

    const { subscribeToRunEvents } = await import(
      '@/features/workspace/lib/follow-run-realtime'
    );
    const seen: { seq: number; kind: string; payload: Record<string, unknown> }[] = [];
    await subscribeToRunEvents({
      runId: '11111111-1111-4111-8111-111111111111',
      onInsert: (row) => seen.push(row),
      onLost: () => undefined,
    });

    const listener = channelOn.mock.calls[0]?.[2] as
      | ((payload: { new: Record<string, unknown> }) => void)
      | undefined;
    listener?.({
      new: { seq: 9, kind: 'token', payload: { content: 'x' }, run_id: '11111111-1111-4111-8111-111111111111' },
    });
    expect(seen).toEqual([{ seq: 9, kind: 'token', payload: { content: 'x' } }]);
  });

  it('signale onLost si le channel se coupe après SUBSCRIBED', async () => {
    let statusCb: ((status: string) => void) | undefined;
    channelSubscribe.mockImplementation((cb: (status: string) => void) => {
      statusCb = cb;
      cb('SUBSCRIBED');
    });
    const { subscribeToRunEvents } = await import(
      '@/features/workspace/lib/follow-run-realtime'
    );
    let lost = false;
    await subscribeToRunEvents({
      runId: '11111111-1111-4111-8111-111111111111',
      onInsert: () => undefined,
      onLost: () => {
        lost = true;
      },
    });
    statusCb?.('CHANNEL_ERROR');
    expect(lost).toBe(true);
  });

  it('rend null si le channel n arrive pas à SUBSCRIBED', async () => {
    channelSubscribe.mockImplementation((cb: (status: string) => void) => {
      cb('CHANNEL_ERROR');
    });
    const { subscribeToRunEvents } = await import(
      '@/features/workspace/lib/follow-run-realtime'
    );
    const handle = await subscribeToRunEvents({
      runId: '11111111-1111-4111-8111-111111111111',
      onInsert: () => undefined,
      onLost: () => undefined,
    });
    expect(handle).toBeNull();
  });
});
