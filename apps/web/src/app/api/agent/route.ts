import { NextResponse, type NextRequest } from 'next/server';
import { z } from 'zod';
import { createAdminClient, createRouteHandlerClient } from '@/shared/lib/supabase-server';
import { encodeSse, sseHeaders } from './lib/sse';
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

  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      try {
        if (useOrchestrator) {
          try {
            await runRealOrchestrator({
              controller,
              encoder,
              supabase: pipelineClient,
              userId: user.id,
              projectId,
              prompt,
              iterationStart: project.iteration_count ?? 0,
            });
          } catch (err) {
            if (shouldFallbackToLocalPipeline(err)) {
              await runLocalPipeline({
                controller,
                encoder,
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
            controller,
            encoder,
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
        controller.close();
      }
    },
  });

  return new Response(stream, { headers: sseHeaders() });
}
