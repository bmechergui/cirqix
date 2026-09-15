import { describe, it, expect, vi } from 'vitest';
import { chatTextOfEvent } from '@cirqix/types';
import {
  TranscriptSink,
  createChatMessageWriter,
  CHAT_MESSAGE_MAX_CHARS,
} from '../pipeline/transcript-sink';
import type { RunEvent, RunSink } from '../pipeline/run-sink';

/**
 * Historique de discussion par projet.
 *
 * Le chat d'un projet vivait UNIQUEMENT dans le store Zustand du navigateur :
 * un rechargement, ou la réouverture du projet, effaçait la conversation. Le
 * pipeline produit pourtant la réponse de l'agent — c'est donc lui (route SSE
 * ou worker) qui la consigne, pas l'onglet, qu'on peut fermer pendant un
 * routage de 20 minutes.
 */

function recordingSink(): RunSink & { events: RunEvent[] } {
  const events: RunEvent[] = [];
  return {
    events,
    emit: vi.fn(async (ev: RunEvent) => {
      events.push(ev);
    }),
  };
}

describe('chatTextOfEvent — le texte qu’affiche la bulle de l’agent', () => {
  it('rend le delta d’un token tel quel', () => {
    expect(chatTextOfEvent({ type: 'token', content: 'Bonjour' })).toBe('Bonjour');
  });

  it('formate un bloc du reasoner comme la bulle en direct', () => {
    expect(chatTextOfEvent({ type: 'reasoning', steps: ['déplace C1', 'reroute'] })).toBe(
      '\n\n🤖 **Reasoner IA — déblocage du routage :**\n  déplace C1\n  reroute',
    );
  });

  it('formate une erreur comme la bulle en direct', () => {
    expect(chatTextOfEvent({ type: 'error', message: 'routage injoignable' })).toBe(
      '\n\n_Error: routage injoignable_',
    );
  });

  it('ignore les événements structurés sans texte', () => {
    const step: RunEvent = { type: 'step', step: 'ROUTING' };
    expect(chatTextOfEvent(step)).toBeNull();
    expect(chatTextOfEvent({ type: 'done' })).toBeNull();
  });
});

describe('TranscriptSink', () => {
  it('transmet chaque événement sans le modifier', async () => {
    const inner = recordingSink();
    const sink = new TranscriptSink(inner);
    const events: RunEvent[] = [
      { type: 'token', content: 'Schéma ' },
      { type: 'step', step: 'SCHEMA' },
      { type: 'done' },
    ];
    for (const ev of events) await sink.emit(ev);
    expect(inner.events).toEqual(events);
  });

  it('assemble la réponse visible de l’agent', async () => {
    const sink = new TranscriptSink(recordingSink());
    await sink.emit({ type: 'token', content: 'Schéma ' });
    await sink.emit({ type: 'status', status: 'SCHEMA_DONE' });
    await sink.emit({ type: 'token', content: 'terminé.' });
    await sink.emit({ type: 'error', message: 'DRC en erreur' });
    expect(sink.transcript()).toBe('Schéma terminé.\n\n_Error: DRC en erreur_');
  });

  it('garde le texte même si le transport lève (onglet fermé)', async () => {
    const inner: RunSink = { emit: vi.fn().mockRejectedValue(new Error('controller closed')) };
    const sink = new TranscriptSink(inner);
    await expect(sink.emit({ type: 'token', content: 'partiel' })).rejects.toThrow();
    expect(sink.transcript()).toBe('partiel');
  });
});

describe('createChatMessageWriter', () => {
  function makeClient(result: { error: { message: string } | null } = { error: null }) {
    const insert = vi.fn(async () => result);
    const from = vi.fn(() => ({ insert }));
    return { client: { from }, from, insert };
  }

  const base = {
    projectId: '22222222-2222-4222-8222-222222222222',
    userId: '33333333-3333-4333-8333-333333333333',
  };

  it('écrit une ligne dans project_messages avec ses colonnes snake_case', async () => {
    const { client, from, insert } = makeClient();
    const ok = await createChatMessageWriter(client).append({ ...base, role: 'user', content: 'un blinker' });
    expect(ok).toBe(true);
    expect(from).toHaveBeenCalledWith('project_messages');
    expect(insert).toHaveBeenCalledWith({
      project_id: base.projectId,
      user_id: base.userId,
      role: 'user',
      content: 'un blinker',
    });
  });

  it('n’écrit rien pour un message vide', async () => {
    const { client, insert } = makeClient();
    const ok = await createChatMessageWriter(client).append({ ...base, role: 'assistant', content: '   ' });
    expect(ok).toBe(false);
    expect(insert).not.toHaveBeenCalled();
  });

  it('tronque un message au-delà de la borne de la table', async () => {
    const { client, insert } = makeClient();
    await createChatMessageWriter(client).append({
      ...base,
      role: 'assistant',
      content: 'x'.repeat(CHAT_MESSAGE_MAX_CHARS + 50),
    });
    const row = (insert.mock.calls[0] as unknown as [{ content: string }])[0];
    expect(row.content.length).toBe(CHAT_MESSAGE_MAX_CHARS);
  });

  it('rend false et signale l’erreur sans jamais lever — l’historique ne casse pas un run', async () => {
    const onError = vi.fn();
    const { client } = makeClient({ error: { message: 'permission denied' } });
    const ok = await createChatMessageWriter(client, onError).append({ ...base, role: 'user', content: 'x' });
    expect(ok).toBe(false);
    expect(onError).toHaveBeenCalledTimes(1);

    const broken = { from: () => { throw new Error('client sans from'); } };
    const onError2 = vi.fn();
    await expect(
      createChatMessageWriter(broken as never, onError2).append({ ...base, role: 'user', content: 'x' }),
    ).resolves.toBe(false);
    expect(onError2).toHaveBeenCalledTimes(1);
  });
});
