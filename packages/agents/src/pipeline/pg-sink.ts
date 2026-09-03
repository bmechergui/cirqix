/**
 * Transport durable des événements d'un run — remplace le SSE dans le worker.
 *
 * Le flux SSE meurt avec l'invocation qui le porte. Quand le pipeline part dans
 * un worker persistant, il n'a plus de connexion vers le navigateur du tout :
 * il ÉCRIT dans `pcb_run_events` (migration 019), et le navigateur LIT cette
 * table en Supabase Realtime.
 *
 * Trois propriétés que le SSE n'avait pas :
 *   - le worker n'a besoin d'AUCUNE surface réseau vers le client ;
 *   - un rechargement de page rejoue l'historique complet ;
 *   - l'utilisateur peut fermer son onglet et revenir — ce qui compte d'autant
 *     plus qu'un routage complexe dure 15 à 20 minutes.
 *
 * Deux exigences contradictoires gouvernent cette classe :
 *
 *   1. VOLUMÉTRIE. L'orchestrateur émet un événement par delta de token. Une
 *      ligne par delta produirait des dizaines de milliers d'INSERT par run —
 *      table noyée, quota Realtime ruiné. D'où l'agrégation.
 *   2. ORDRE. Le journal est rejoué tel quel. Un `status` écrit pendant que du
 *      texte dort encore en tampon afficherait « terminé » AVANT la phrase qui
 *      l'explique.
 *
 * La règle qui les concilie : on agrège le texte, mais **tout événement
 * structuré vide le tampon avant d'être écrit**. L'agrégation ne s'applique
 * donc qu'entre deux événements structurés, jamais à travers l'un d'eux.
 */

import type { RunEvent, RunSink } from './run-sink';

/**
 * Fenêtre d'agrégation des deltas texte. Assez courte pour que le texte
 * paraisse fluide à la lecture, assez longue pour effondrer le nombre de
 * lignes — c'est le seul réglage qui arbitre entre les deux.
 */
export const TOKEN_FLUSH_MS = 250;

/** Une ligne de `pcb_run_events`. `seq` est attribué par la base. */
export interface RunEventRow {
  run_id: string;
  kind: RunEvent['type'];
  payload: Record<string, unknown>;
}

/**
 * Écriture des lignes. Interface étroite À DESSEIN : `PgSink` ne connaît ni
 * Supabase ni Postgres, donc il se teste sans base. Le porteur (route web ou
 * worker) fournit l'adaptateur.
 */
export interface RunEventWriter {
  insert(rows: RunEventRow[]): Promise<void>;
}

/** Le contenu d'un événement, moins son discriminant. */
function payloadOf(event: RunEvent): Record<string, unknown> {
  const { type: _type, ...rest } = event as RunEvent & Record<string, unknown>;
  return rest;
}

export class PgSink implements RunSink {
  private buffer = '';
  private bufferOpenedAt: number | null = null;

  constructor(
    private readonly runId: string,
    private readonly writer: RunEventWriter,
    /** Horloge injectable — les tests raisonnent sur un temps déterministe. */
    private readonly now: () => number = Date.now,
  ) {}

  async emit(event: RunEvent): Promise<void> {
    if (event.type === 'token') {
      // Vider AVANT d'accumuler : la fenêtre se juge sur l'ouverture du tampon,
      // pas sur le dernier delta reçu — sinon un flot continu de tokens ne la
      // dépasserait jamais et rien ne serait jamais écrit.
      if (
        this.bufferOpenedAt !== null &&
        this.now() - this.bufferOpenedAt >= TOKEN_FLUSH_MS
      ) {
        await this.flush();
      }
      if (this.bufferOpenedAt === null) this.bufferOpenedAt = this.now();
      this.buffer += event.content;
      return;
    }

    // Événement structuré : le texte en attente le précède forcément dans le
    // temps, il doit donc le précéder dans le journal.
    await this.flush();
    await this.writer.insert([
      { run_id: this.runId, kind: event.type, payload: payloadOf(event) },
    ]);
  }

  /** Écrit le texte en attente, s'il y en a. Sans effet sur un tampon vide. */
  private async flush(): Promise<void> {
    if (this.buffer === '') {
      this.bufferOpenedAt = null;
      return;
    }
    const content = this.buffer;
    this.buffer = '';
    this.bufferOpenedAt = null;
    await this.writer.insert([
      { run_id: this.runId, kind: 'token', payload: { content } },
    ]);
  }

  /**
   * Fin de run : rien ne doit rester en tampon. Idempotent — un second appel
   * n'écrit pas de ligne fantôme.
   */
  async close(): Promise<void> {
    await this.flush();
  }
}
