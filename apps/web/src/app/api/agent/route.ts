import { NextResponse, type NextRequest } from 'next/server';
import { z } from 'zod';
import { createRouteHandlerClient } from '@/shared/lib/supabase-server';
import { encodeSse, sseHeaders } from './lib/sse';
import { runSimulatorAgent } from './lib/simulator';
import { runRealOrchestrator } from './lib/orchestrator-bridge';
import { runLocalPipeline } from './lib/local-pipeline';
import { resolveAgentMode, isOrchestratorAvailable } from './lib/agent-mode';

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
  if (balance < 0.5) {
    return NextResponse.json({ success: false, error: 'Insufficient credits' }, { status: 402 });
  }

  const requestedMode = resolveAgentMode();
  const useOrchestrator = requestedMode === 'orchestrator' && isOrchestratorAvailable();

  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      try {
        if (useOrchestrator) {
          try {
            await runRealOrchestrator({
              controller,
              encoder,
              supabase,
              userId: user.id,
              projectId,
              prompt,
              iterationStart: project.iteration_count ?? 0,
            });
          } catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            if (msg.includes('credit') || msg.includes('402')) {
              await runLocalPipeline({
                controller,
                encoder,
                supabase,
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
            supabase,
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
        controller.close();
      }
    },
  });

  return new Response(stream, { headers: sseHeaders() });
}
