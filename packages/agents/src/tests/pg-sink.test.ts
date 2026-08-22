import { describe, it, expect, vi } from 'vitest';
import { PgSink, TOKEN_FLUSH_MS } from '../pipeline/pg-sink';
import type { RunEventRow, RunEventWriter } from '../pipeline/pg-sink';

/**
 * `PgSink` — le transport qui remplace le SSE quand le pipeline part dans un
 * worker. Deux exigences le gouvernent, et elles se contredisent :
 *
 *   1. VOLUMÉTRIE. L'orchestrateur émet un événement par delta de token. Une
 *      ligne par delta produirait des dizaines de milliers d'INSERT par run —
 *      table noyée, quota Realtime ruiné. Les deltas texte doivent être agrégés.
 *   2. ORDRE. Le journal est rejoué tel quel par le navigateur. Un `status` qui
 *      doublerait le texte encore en tampon afficherait « terminé » avant la
 *      phrase qui l'explique.
 *
 * D'où la règle : on agrège le texte, mais tout événement structuré VIDE le
 * tampon avant d'être écrit.
 */

function makeWriter() {
  const rows: RunEventRow[] = [];
  const writer: RunEventWriter = {
    insert: vi.fn(async (batch: RunEventRow[]) => {
      rows.push(...batch);
    }),
  };
  return { writer, rows };
}

describe('agrégation des deltas texte', () => {
  it('fusionne les deltas consécutifs en une seule ligne', async () => {
    const { writer, rows } = makeWriter();
    const sink = new PgSink('run-1', writer);

    await sink.emit({ type: 'token', content: 'Bon' });
    await sink.emit({ type: 'token', content: 'jour' });
    await sink.emit({ type: 'token', content: ' !' });
    await sink.close();

    const tokens = rows.filter((r) => r.kind === 'token');
    expect(tokens).toHaveLength(1);
    expect(tokens[0]!.payload).toEqual({ content: 'Bonjour !' });
  });

  it('n écrit rien tant que le tampon n a pas de raison d être vidé', async () => {
    const { writer, rows } = makeWriter();
    const sink = new PgSink('run-1', writer);

    await sink.emit({ type: 'token', content: 'a' });
    await sink.emit({ type: 'token', content: 'b' });

    expect(rows).toHaveLength(0);
    await sink.close();
    expect(rows).toHaveLength(1);
  });

  it('vide le tampon quand la fenêtre d agrégation est dépassée', async () => {
    const { writer, rows } = makeWriter();
    let now = 1_000;
    const sink = new PgSink('run-1', writer, () => now);

    await sink.emit({ type: 'token', content: 'a' });
    now += TOKEN_FLUSH_MS + 1;
    await sink.emit({ type: 'token', content: 'b' });

    // Le premier delta est parti ; le second attend son tour.
    expect(rows).toHaveLength(1);
    expect(rows[0]!.payload).toEqual({ content: 'a' });
  });
});

describe('ordre du journal', () => {
  it('vide le texte en tampon AVANT d écrire un événement structuré', async () => {
    const { writer, rows } = makeWriter();
    const sink = new PgSink('run-1', writer);

    await sink.emit({ type: 'token', content: 'Routage en cours' });
    await sink.emit({ type: 'status', status: 'ROUTING_DONE' });
    await sink.close();

    expect(rows.map((r) => r.kind)).toEqual(['token', 'status']);
  });

  it('préserve l ordre d une séquence mixte', async () => {
    const { writer, rows } = makeWriter();
    const sink = new PgSink('run-1', writer);

    await sink.emit({ type: 'token', content: 'un' });
    await sink.emit({ type: 'step', step: 'ROUTING' });
    await sink.emit({ type: 'token', content: 'deux' });
    await sink.emit({ type: 'done' });
    await sink.close();

    expect(rows.map((r) => r.kind)).toEqual(['token', 'step', 'token', 'done']);
  });
});

describe('contrat de ligne', () => {
  it('étiquette chaque ligne avec le run et son type', async () => {
    const { writer, rows } = makeWriter();
    const sink = new PgSink('run-42', writer);

    await sink.emit({ type: 'error', message: 'service injoignable' });

    expect(rows[0]).toMatchObject({
      run_id: 'run-42',
      kind: 'error',
      payload: { message: 'service injoignable' },
    });
  });

  it('close est idempotent — un tampon vide n écrit pas de ligne fantôme', async () => {
    const { writer, rows } = makeWriter();
    const sink = new PgSink('run-1', writer);

    await sink.emit({ type: 'token', content: 'x' });
    await sink.close();
    await sink.close();

    expect(rows).toHaveLength(1);
  });
});
