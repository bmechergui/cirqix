import { describe, it, expect, vi } from 'vitest';
import { rowToEvent, nextPollDelayMs, POLL_FAST_MS, POLL_IDLE_MS } from
  '@/features/workspace/lib/follow-run';

/**
 * Suivi d'un run asynchrone côté client.
 *
 * En mode asynchrone, la route répond `202 {runId}` et rend la main : il n'y a
 * plus de flux SSE à lire. La progression vit dans `pcb_run_events`, que le
 * client relit par curseur (`?since=<seq>`).
 *
 * Deux conséquences qui n'existaient pas avec le SSE :
 *   - fermer l'onglet n'interrompt plus le run, et le rouvrir REJOUE
 *     l'historique — ce qui compte quand un routage dure 15 à 20 minutes ;
 *   - le client ne peut plus supposer qu'un silence signifie une panne. Un
 *     routage travaille des minutes sans rien émettre.
 */

describe('conversion des lignes du journal en événements', () => {
  it('reconstruit un événement à partir de sa ligne', () => {
    expect(rowToEvent({ seq: 1, kind: 'status', payload: { status: 'ROUTING_DONE' } }))
      .toEqual({ type: 'status', status: 'ROUTING_DONE' });
    expect(rowToEvent({ seq: 2, kind: 'token', payload: { content: 'Routage…' } }))
      .toEqual({ type: 'token', content: 'Routage…' });
    expect(rowToEvent({ seq: 3, kind: 'done', payload: {} }))
      .toEqual({ type: 'done' });
  });

  it('ignore une ligne dont le type est inconnu plutôt que de la faire passer', () => {
    // Une version future du worker peut écrire des types que ce client ne
    // connaît pas. Les laisser remonter tels quels ferait planter le réducteur
    // d'état sur un `type` non prévu.
    expect(rowToEvent({ seq: 4, kind: 'telemetrie_future', payload: {} })).toBeNull();
  });
});

describe('cadence de relecture', () => {
  it('interroge vite tant que des événements arrivent', () => {
    expect(nextPollDelayMs(5)).toBe(POLL_FAST_MS);
  });

  it('ralentit quand le run est silencieux', () => {
    // Un routage travaille des minutes sans rien émettre : garder la cadence
    // rapide y ferait des centaines de requêtes pour rien.
    expect(nextPollDelayMs(0)).toBe(POLL_IDLE_MS);
  });

  it('reste plus lent au repos qu en activité', () => {
    expect(POLL_IDLE_MS).toBeGreaterThan(POLL_FAST_MS);
  });
});

describe('followRun', () => {
  it('rejoue l historique puis s arrête sur done', async () => {
    const { followRun } = await import('@/features/workspace/lib/follow-run');
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          events: [
            { seq: 1, kind: 'step', payload: { step: 'ROUTING' } },
            { seq: 2, kind: 'done', payload: {} },
          ],
          cursor: 2,
          hasMore: false,
        }),
      });
    vi.stubGlobal('fetch', fetchMock);

    const seen: unknown[] = [];
    await followRun({ runId: 'r1', onEvent: (ev) => seen.push(ev) });

    expect(seen).toEqual([{ type: 'step', step: 'ROUTING' }, { type: 'done' }]);
    // Un seul appel : `done` arrête la boucle, on ne re-interroge pas un run clos.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });

  it('avance le curseur pour ne pas rejouer ce qu il a déjà vu', async () => {
    const { followRun } = await import('@/features/workspace/lib/follow-run');
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          events: [{ seq: 7, kind: 'token', payload: { content: 'a' } }],
          cursor: 7,
          hasMore: true,
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ events: [{ seq: 8, kind: 'done', payload: {} }], cursor: 8, hasMore: false }),
      });
    vi.stubGlobal('fetch', fetchMock);

    await followRun({ runId: 'r1', onEvent: () => undefined });

    expect(fetchMock.mock.calls[0]?.[0]).toContain('since=0');
    expect(fetchMock.mock.calls[1]?.[0]).toContain('since=7');
    vi.unstubAllGlobals();
  });

  it('signale une erreur de lecture sans boucler indéfiniment', async () => {
    const { followRun } = await import('@/features/workspace/lib/follow-run');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }));

    const seen: { type: string }[] = [];
    await followRun({ runId: 'r1', onEvent: (ev) => seen.push(ev as { type: string }), maxAttempts: 2 });

    expect(seen.at(-1)?.type).toBe('error');
    vi.unstubAllGlobals();
  });
});
