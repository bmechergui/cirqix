import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/shared/lib/supabase-browser', () => ({ createSupabaseBrowserClient: vi.fn() }));

import { useAppStore } from '@/shared/store/app-store';
import { toChatMessage } from '@/shared/lib/chat-history';

const PROJECT_ID = '22222222-2222-4222-8222-222222222222';

const ROWS = [
  { id: 'm1', role: 'user', content: 'un blinker', created_at: '2026-09-15T10:00:00Z' },
  { id: 'm2', role: 'assistant', content: 'Schéma prêt', created_at: '2026-09-15T10:00:05Z' },
];

function mockFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), { status }));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

beforeEach(() => {
  vi.unstubAllGlobals();
  useAppStore.setState({ messagesByProject: {}, historyLoadedByProject: {} });
});

describe('toChatMessage', () => {
  it('convertit une ligne en Message (rôle user | assistant, jamais agent)', () => {
    const msg = toChatMessage(ROWS[0]!);
    expect(msg).toMatchObject({ id: 'm1', role: 'user', content: 'un blinker' });
    expect(msg?.timestamp).toMatch(/^\d{2}:\d{2}$/);
  });

  it('écarte une ligne au rôle inconnu plutôt que de l’afficher de travers', () => {
    expect(toChatMessage({ ...ROWS[0]!, role: 'agent' })).toBeNull();
  });
});

describe('fetchMessages — la conversation revient à la réouverture du projet', () => {
  it('charge l’historique persisté du projet', async () => {
    const fetchMock = mockFetch({ success: true, data: { messages: ROWS } });
    await useAppStore.getState().fetchMessages(PROJECT_ID);
    expect(fetchMock).toHaveBeenCalledWith(`/api/projects/${PROJECT_ID}/messages`, expect.anything());
    const msgs = useAppStore.getState().messagesByProject[PROJECT_ID] ?? [];
    expect(msgs.map((m) => m.content)).toEqual(['un blinker', 'Schéma prêt']);
  });

  it('ne charge qu’une fois — un second montage ne duplique pas la conversation', async () => {
    const fetchMock = mockFetch({ success: true, data: { messages: ROWS } });
    await Promise.all([
      useAppStore.getState().fetchMessages(PROJECT_ID),
      useAppStore.getState().fetchMessages(PROJECT_ID),
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(useAppStore.getState().messagesByProject[PROJECT_ID]).toHaveLength(2);
  });

  it('place l’historique AVANT un message envoyé pendant le chargement', async () => {
    mockFetch({ success: true, data: { messages: ROWS } });
    const pending = useAppStore.getState().fetchMessages(PROJECT_ID);
    useAppStore.getState().appendMessage(PROJECT_ID, {
      id: 'live', role: 'user', content: 'nouvelle demande', timestamp: '10:01',
    });
    await pending;
    const msgs = useAppStore.getState().messagesByProject[PROJECT_ID] ?? [];
    expect(msgs.map((m) => m.id)).toEqual(['m1', 'm2', 'live']);
  });

  it('autorise un nouvel essai quand le chargement échoue', async () => {
    const failing = mockFetch({ success: false, error: 'boom' }, 500);
    await useAppStore.getState().fetchMessages(PROJECT_ID);
    expect(failing).toHaveBeenCalledTimes(1);
    expect(useAppStore.getState().messagesByProject[PROJECT_ID]).toBeUndefined();

    const ok = mockFetch({ success: true, data: { messages: ROWS } });
    await useAppStore.getState().fetchMessages(PROJECT_ID);
    expect(ok).toHaveBeenCalledTimes(1);
    expect(useAppStore.getState().messagesByProject[PROJECT_ID]).toHaveLength(2);
  });
});
