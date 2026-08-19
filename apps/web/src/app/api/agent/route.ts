import { NextResponse, type NextRequest } from 'next/server';
import { z } from 'zod';
import { createAdminClient, createRouteHandlerClient } from '@/shared/lib/supabase-server';
import { setProjectPlan, clearProjectPlan } from '@cirqix/agents';
import { encodeSse, sseHeaders, SseSink } from './lib/sse';
import { runSimulatorAgent } from './lib/simulator';
import { runRealOrchestrator } from './lib/orchestrator-bridge';
import { runLocalPipeline } from './lib/local-pipeline';
import { resolveAgentMode, isOrchestratorAvailable } from './lib/agent-mode';
import {
  hasEnoughPipelineCredits,
  shouldFallbackToLocalPipeline,
  reservePipelineCredits,
  releasePipelineReservation,
  InsufficientCreditsError,
  PipelineAlreadyRunningError,
} from './lib/credits';
import { checkRateLimit } from '@/shared/lib/ratelimit';
import { AGENT_RATE_LIMIT, AGENT_RATE_WINDOW_S, agentRateLimitKey } from './lib/rate-limit';
import { asyncPipelineEnabled } from './lib/async-mode';
import { createRun, RunAlreadyActiveError } from './lib/run-repository';
import { createPipelineQueue, enqueuePipelineRun } from '@cirqix/agents';
import { logger } from '@cirqix/logger';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
export const maxDuration = 300; // 5 min for orchestrator runs

const bodySchema = z.object({
  projectId: z.string().uuid(),
  prompt: z.string().min(1).max(4000).trim(),
});

export async function POST(req: NextRequest) {
  const supabase = await createRouteHandlerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }

  // Après l'authentification (le quota est nominatif) et avant toute requête
  // Supabase : un compte qui pilonne la route ne doit pas non plus faire
  // travailler la base. Voir ./lib/rate-limit.ts pour ce que ce quota borne —
  // et ce qu'il ne remplace pas.
  const quota = await checkRateLimit(
    agentRateLimitKey(user.id),
    AGENT_RATE_LIMIT,
    AGENT_RATE_WINDOW_S,
  );
  if (!quota.success) {
    // Retry-After = la fenêtre entière. Avec une fenêtre FIXE, la remise à zéro
    // survient au plus tard dans AGENT_RATE_WINDOW_S : annoncer cette durée fait
    // donc toujours attendre assez. C'est une borne haute — parfois plus longue
    // que nécessaire, jamais trop courte, et un client qui l'honore ne se reprend
    // pas un 429. Le vrai instant de reset n'est pas exposé par checkRateLimit.
    return NextResponse.json(
      { success: false, error: 'Too many pipeline runs, retry shortly' },
      { status: 429, headers: { 'Retry-After': String(AGENT_RATE_WINDOW_S) } },
    );
  }

  let payload: unknown;
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json({ success: false, error: 'Invalid JSON' }, { status: 400 });
  }
  const parsed = bodySchema.safeParse(payload);
  if (!parsed.success) {
    return NextResponse.json(
      { success: false, error: parsed.error.issues.map((i) => i.message).join(', ') },
      { status: 400 }
    );
  }
  const { projectId, prompt } = parsed.data;

  const { data: project } = await supabase
    .from('projects')
    .select('id, status, iteration_count, pcb_state')
    .eq('id', projectId)
    .single();
  if (!project) {
    return NextResponse.json({ success: false, error: 'Project not found' }, { status: 404 });
  }

  const { data: creditRow } = await supabase
    .from('credits')
    .select('balance, plan')
    .eq('user_id', user.id)
    .single();
  const balance = creditRow?.balance ?? 0;
  if (!hasEnoughPipelineCredits(balance)) {
    return NextResponse.json({ success: false, error: 'Insufficient credits' }, { status: 402 });
  }

  const requestedMode = resolveAgentMode();
  const useOrchestrator = requestedMode === 'orchestrator' && isOrchestratorAvailable();
  const pipelineClient = createAdminClient();

  // Le contrôle de solde ci-dessus ne réserve rien : entre lui et le débit,
  // qui n'arrive qu'à la fin des 300 s, N requêtes simultanées lisaient le même
  // solde et passaient toutes. On engage donc le crédit AVANT de démarrer —
  // poser la retenue après reviendrait à ne rien garantir.
  //
  // Uniquement en mode orchestrateur : le simulateur ne facture pas
  // (migration 012), et retenir des crédits pour une démonstration bloquerait
  // un solde que personne ne débitera jamais.
  let reservationId: string | null = null;
  if (useOrchestrator) {
    try {
      reservationId = await reservePipelineCredits(pipelineClient, user.id, projectId);
    } catch (err) {
      if (err instanceof InsufficientCreditsError) {
        return NextResponse.json({ success: false, error: 'Insufficient credits' }, { status: 402 });
      }
      if (err instanceof PipelineAlreadyRunningError) {
        return NextResponse.json(
          { success: false, error: 'A pipeline is already running for this project' },
          { status: 409 },
        );
      }
      // Une panne de réservation n'est pas un manque de crédits : répondre 402
      // enverrait l'utilisateur acheter ce qu'il possède déjà.
      return NextResponse.json(
        { success: false, error: 'Credit reservation unavailable' },
        { status: 500 },
      );
    }
  }

  // Le plan gouverne des droits réels — aujourd'hui le plafond de couches
  // appliqué par le handler de routage (Free 2 · Pro 4 · Pro Max 8). Il est
  // lu depuis la base plus haut, mais semé ICI, juste avant le flux : c'est le
  // `finally` de ce flux qui le libère, et TOUS les retours anticipés sont
  // désormais derrière nous (402 solde, 402 réservation, 409 run en cours,
  // 500 réservation indisponible).
  //
  // Semer plus tôt laissait une entrée orpheline sur chacun de ces quatre
  // chemins : un compte gratuit sans crédit qui réessaie faisait grossir la map
  // indéfiniment. Fuite mémoire non bornée, sur le chemin d'échec le plus
  // courant qui soit.
  setProjectPlan(projectId, creditRow?.plan ?? 'free');

  // ---------------------------------------------------------------------------
  // Chemin ASYNCHRONE — la route dépose et rend la main.
  // ---------------------------------------------------------------------------
  //
  // C'est ici que le plafond disparaît. Mesuré le 2026-08-19 sur le board STM32 :
  // génération 3 s + placement 175 s + routage 861 s ≈ 17 min, pour une
  // invocation plafonnée à `maxDuration = 300`. Aucun PCB complet ne peut donc
  // aboutir tant que la requête attend le résultat.
  //
  // En asynchrone, la route authentifie, réserve, ouvre le run, enfile, et
  // répond en quelques centaines de millisecondes. Le worker exécute sans
  // montre ; le navigateur suit le journal (`pcb_run_events`).
  //
  // ⚠️ La PROVENANCE est posée ICI, dans `pcb_runs.agent_mode`, et n'entre jamais
  // dans le payload du job — sinon enfiler un job reviendrait à décerner la
  // commandabilité JLCPCB, c'est-à-dire une commande réelle et payante.
  //
  // Le drapeau exige `REDIS_URL` : sans file, un job enfilé ne serait consommé
  // par personne et l'utilisateur verrait sa demande acceptée puis jamais
  // traitée — pire qu'un refus franc.
  if (useOrchestrator && asyncPipelineEnabled(process.env, { requireRedis: true })) {
    try {
      const runId = await createRun(pipelineClient, {
        projectId,
        userId: user.id,
        agentMode: 'orchestrator',
        reservationId,
        iterationStart: project.iteration_count ?? 0,
      });

      const queue = createPipelineQueue(process.env['REDIS_URL'] as string);
      try {
        await enqueuePipelineRun(queue, {
          runId,
          projectId,
          userId: user.id,
          prompt,
          iterationStart: project.iteration_count ?? 0,
        });
      } finally {
        // La route est éphémère : laisser la connexion Redis ouverte fuiterait
        // un socket par requête sur un runtime serverless.
        await queue.close();
      }

      // 202 : accepté, pas terminé. Le client suit `runId`.
      return NextResponse.json({ success: true, runId }, { status: 202 });
    } catch (err) {
      if (err instanceof RunAlreadyActiveError) {
        return NextResponse.json(
          { success: false, error: 'A pipeline is already running for this project' },
          { status: 409 },
        );
      }
      // Le run n'a pas démarré : on rend la retenue tout de suite plutôt que
      // d'attendre son TTL, sinon un échec d'enfilage gèlerait le solde.
      if (reservationId) await releasePipelineReservation(pipelineClient, reservationId);
      clearProjectPlan(projectId);
      logger.child({ module: 'agent-route' }).error(
        { err, projectId },
        'enfilage du pipeline échoué',
      );
      return NextResponse.json(
        { success: false, error: 'Could not queue the pipeline' },
        { status: 500 },
      );
    }
  }

  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      // Le pipeline n'écrit plus dans le flux : il émet dans un `RunSink`.
      // C'est ce qui le rendra exécutable dans un worker, hors de cette
      // invocation plafonnée à `maxDuration`. Ici le transport reste le SSE
      // actuel — octets identiques, comportement inchangé.
      const sink = new SseSink(controller, encoder);
      try {
        if (useOrchestrator) {
          try {
            await runRealOrchestrator({
              sink,
              supabase: pipelineClient,
              userId: user.id,
              projectId,
              prompt,
              iterationStart: project.iteration_count ?? 0,
            });
          } catch (err) {
            if (shouldFallbackToLocalPipeline(err)) {
              await runLocalPipeline({
                sink,
                supabase: pipelineClient,
                userId: user.id,
                projectId,
                prompt,
                iterationStart: project.iteration_count ?? 0,
                balanceStart: balance,
              });
            } else {
              throw err;
            }
          }
        } else {
          await runSimulatorAgent({
            sink,
            supabase: pipelineClient,
            userId: user.id,
            projectId,
            prompt,
            iterationStart: project.iteration_count ?? 0,
            balanceStart: balance,
          });
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Agent error';
        controller.enqueue(encoder.encode(encodeSse({ type: 'error', message })));
      } finally {
        // Quoi qu'il soit arrivé au pipeline. `finalize_pipeline_success` a
        // déjà levé la retenue dans la transaction du débit ; cet appel est
        // alors sans effet (l'UPDATE est conditionné à `released_at IS NULL`).
        // Il couvre les runs qui n'ont jamais finalisé — erreur, abandon — et
        // évite d'attendre le TTL pour relancer.
        if (reservationId) {
          await releasePipelineReservation(pipelineClient, reservationId);
        }
        // Contexte de run : le plan ne doit pas survivre au pipeline. Une
        // entrée oubliée servirait au run suivant, éventuellement lancé par le
        // même projet après un changement de plan.
        clearProjectPlan(projectId);
        controller.close();
      }
    },
  });

  return new Response(stream, { headers: sseHeaders() });
}
