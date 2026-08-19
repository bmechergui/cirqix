/**
 * Worker de pipeline PCB — point d'entrée.
 *
 * C'est le processus qui lève le plafond. Le pipeline y tourne sans invocation
 * qui l'enserre : un routage complexe peut prendre 20 minutes ou davantage,
 * là où la route web était coupée à 300 s.
 *
 * Il ne publie aucun port et n'est joignable par personne. Il consomme une file
 * Redis et écrit dans Postgres — c'est tout. Le navigateur lit le journal en
 * Supabase Realtime, sans jamais parler au worker.
 *
 * Démarrage : `pnpm --filter @cirqix/worker start`
 */

import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import {
  createPipelineWorker,
  createRunEventWriterFactory,
  type PipelineJobPayload,
} from './adapters.js';
import { runJob } from './run-job.js';
import { logger } from '@cirqix/logger';

const log = logger.child({ module: 'worker' });

/** Échoue au démarrage plutôt qu'au premier job : un worker à moitié configuré
 *  accepterait des jobs pour les faire tous échouer, en consommant leurs
 *  réservations de crédits au passage. */
function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} est requis pour démarrer le worker`);
  return value;
}

async function main(): Promise<void> {
  const redisUrl = requireEnv('REDIS_URL');
  const supabaseUrl = requireEnv('SUPABASE_URL');
  const serviceKey = requireEnv('SUPABASE_SERVICE_KEY');

  // Client service-role : le worker n'agit au nom d'aucune session, il écrit
  // pour le compte du run. RLS ne s'applique donc pas — d'où l'importance que
  // ce processus n'expose aucune surface réseau.
  const supabase: SupabaseClient = createClient(supabaseUrl, serviceKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  const deps = createRunEventWriterFactory(supabase);

  const worker = createPipelineWorker(redisUrl, async (payload: PipelineJobPayload) => {
    log.info({ runId: payload.runId, projectId: payload.projectId }, 'job reçu');
    await runJob(payload, deps);
  });

  worker.on('failed', (job: { id?: string } | undefined, err: unknown) => {
    log.error({ err, jobId: job?.id }, 'job échoué');
  });
  worker.on('error', (err: unknown) => {
    log.error({ err }, 'erreur du worker');
  });

  log.info('worker démarré — en attente de jobs');

  // Arrêt propre : on laisse le job en cours aller à son terme plutôt que de le
  // tuer. Un routage interrompu à 18 minutes serait entièrement perdu — BullMQ
  // ne le rejouera pas (`maxStalledCount: 0`, `attempts: 1`).
  const shutdown = async (signal: string): Promise<void> => {
    log.info({ signal }, 'arrêt demandé — attente de la fin du job en cours');
    await worker.close();
    process.exit(0);
  };
  process.on('SIGTERM', () => void shutdown('SIGTERM'));
  process.on('SIGINT', () => void shutdown('SIGINT'));
}

main().catch((err: unknown) => {
  log.error({ err }, 'démarrage du worker impossible');
  process.exit(1);
});
