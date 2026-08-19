/**
 * Cycle de vie d'un run et écriture de son journal — adaptateur Supabase.
 *
 * Sépare ce que `packages/agents` ne doit PAS connaître (Supabase, la forme des
 * tables) de ce qu'il consomme (`RunEventWriter`, une interface à une méthode).
 * C'est ce qui rend `PgSink` testable sans base.
 *
 * ⚠️ La provenance (`agent_mode`) est écrite ICI, par la route, à la création du
 * run — jamais transportée dans le payload du job. Elle gouverne le gate de
 * `POST /api/jlcpcb/order`, donc une commande réelle et payante : si enfiler un
 * job suffisait à la porter, enfiler reviendrait à décerner la commandabilité.
 */

import type { SupabaseClient } from '@supabase/supabase-js';
import type { RunEventRow, RunEventWriter } from '@cirqix/agents';
import { logger } from '@cirqix/logger';

const log = logger.child({ module: 'run-repository' });

export type AgentMode = 'orchestrator' | 'local_fallback' | 'simulator';

export interface CreateRunInput {
  projectId: string;
  userId: string;
  agentMode: AgentMode;
  reservationId: string | null;
  iterationStart: number;
}

/** Un run vit déjà sur ce projet — l'appelant doit répondre 409. */
export class RunAlreadyActiveError extends Error {
  constructor() {
    super('A run is already active for this project');
    this.name = 'RunAlreadyActiveError';
  }
}

/**
 * Ouvre un run. Échoue si un run vit déjà sur ce projet — garanti en base par
 * l'index unique partiel `pcb_runs_one_alive_per_project` (migration 019), et
 * non par une lecture préalable qui laisserait une fenêtre entre le contrôle et
 * l'insertion.
 */
export async function createRun(
  supabase: SupabaseClient,
  input: CreateRunInput,
): Promise<string> {
  const { data, error } = await supabase
    .from('pcb_runs')
    .insert({
      project_id: input.projectId,
      user_id: input.userId,
      agent_mode: input.agentMode,
      reservation_id: input.reservationId,
      iteration: input.iterationStart,
      status: 'queued',
    })
    .select('id')
    .single();

  if (error) {
    // 23505 = violation d'unicité, donc l'index partiel ci-dessus.
    if ((error as { code?: string }).code === '23505') {
      log.info({ projectId: input.projectId }, 'run refusé : un run est déjà actif');
      throw new RunAlreadyActiveError();
    }
    log.error({ err: error, projectId: input.projectId }, 'création du run échouée');
    throw error;
  }

  return (data as { id: string }).id;
}

/**
 * Écrit les lignes du journal.
 *
 * L'insertion se fait par LOT : `PgSink` agrège déjà les deltas texte, mais un
 * run reste bavard et un aller-retour par ligne dominerait le coût.
 *
 * Une écriture de journal qui échoue ne doit JAMAIS interrompre le pipeline :
 * perdre une ligne de progression est un désagrément, perdre 17 minutes de
 * routage pour cette raison serait absurde. L'erreur est donc journalisée, pas
 * propagée.
 */
export function createRunEventWriter(
  supabase: SupabaseClient,
  runId: string,
): RunEventWriter {
  return {
    async insert(rows: RunEventRow[]): Promise<void> {
      if (rows.length === 0) return;
      const { error } = await supabase.from('pcb_run_events').insert(rows);
      if (error) {
        log.error({ err: error, runId, count: rows.length }, 'journal du run : insert échoué');
      }
    },
  };
}

/**
 * Le run a-t-il été annulé par son porteur ?
 *
 * Consulté aux frontières d'étape. En cas d'échec de lecture on répond `false` :
 * une panne de base ne doit pas ressembler à une annulation, sous peine
 * d'interrompre un routage légitime de 20 minutes.
 */
export async function isRunCancelled(
  supabase: SupabaseClient,
  runId: string,
): Promise<boolean> {
  const { data, error } = await supabase
    .from('pcb_runs')
    .select('cancel_requested')
    .eq('id', runId)
    .single();

  if (error) {
    log.warn({ err: error, runId }, 'lecture de cancel_requested échouée — run poursuivi');
    return false;
  }
  return (data as { cancel_requested: boolean }).cancel_requested === true;
}

/**
 * Battement de cœur du worker.
 *
 * C'est la seule preuve fiable qu'un run vit encore : sans plafond de durée, un
 * job de 30 minutes est indiscernable d'un worker figé. Un run `running` sans
 * battement récent est réconcilié en `failed`.
 */
export async function heartbeatRun(
  supabase: SupabaseClient,
  runId: string,
  lastCompletedStep?: string,
): Promise<void> {
  const patch: Record<string, unknown> = { heartbeat_at: new Date().toISOString() };
  if (lastCompletedStep) patch['last_completed_step'] = lastCompletedStep;

  const { error } = await supabase.from('pcb_runs').update(patch).eq('id', runId);
  if (error) log.warn({ err: error, runId }, 'heartbeat échoué');
}

/** Clôt le run. `error` n'est renseigné que sur `failed`. */
export async function finishRun(
  supabase: SupabaseClient,
  runId: string,
  status: 'succeeded' | 'failed' | 'cancelled',
  errorMessage?: string,
): Promise<void> {
  const { error } = await supabase
    .from('pcb_runs')
    .update({
      status,
      finished_at: new Date().toISOString(),
      ...(errorMessage ? { error: errorMessage } : {}),
    })
    .eq('id', runId);
  if (error) log.error({ err: error, runId, status }, 'clôture du run échouée');
}
