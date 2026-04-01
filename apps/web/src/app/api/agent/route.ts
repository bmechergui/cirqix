import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { createRouteHandlerClient } from '@/shared/lib/supabase-server';
import { runOrchestrator } from '@layrix/agents';
import type { SSEEvent } from '@layrix/agents';
import { CREDIT_COSTS } from '@layrix/types';

const bodySchema = z.object({
  projectId: z.string().uuid(),
  message: z.string().min(1).max(4000),
  history: z
    .array(
      z.object({
        role: z.enum(['user', 'assistant']),
        content: z.string(),
      })
    )
    .default([]),
});

const AGENT_CREDIT_COST = CREDIT_COSTS.chat;

export async function POST(req: NextRequest) {
  // Parse + validate body
  let body: z.infer<typeof bodySchema>;
  try {
    const raw: unknown = await req.json();
    body = bodySchema.parse(raw);
  } catch {
    return NextResponse.json({ success: false, error: 'Invalid request body' }, { status: 400 });
  }

  const supabase = await createRouteHandlerClient();

  // Auth check
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }

  // Credits check — BEFORE running the agent
  const { data: credits, error: creditsError } = await supabase
    .from('credits')
    .select('balance')
    .eq('user_id', user.id)
    .single();

  if (creditsError ?? !credits) {
    return NextResponse.json({ success: false, error: 'Could not fetch credits' }, { status: 500 });
  }

  if (credits.balance < AGENT_CREDIT_COST) {
    return NextResponse.json(
      { success: false, error: 'insufficient_credits' },
      { status: 402 }
    );
  }

  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    async start(controller) {
      const send = (event: SSEEvent) => {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
      };

      try {
        for await (const event of runOrchestrator({
          userMessage: body.message,
          projectId: body.projectId,
          history: body.history,
        })) {
          send(event);

          // Deduct credits on successful completion
          if (event.type === 'done') {
            await supabase.rpc('deduct_credits', {
              p_user_id: user.id,
              p_amount: AGENT_CREDIT_COST,
              p_action: 'chat',
              p_project_id: body.projectId,
            });
          }
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Agent error';
        send({ type: 'error', message });
      } finally {
        controller.enqueue(encoder.encode('data: [DONE]\n\n'));
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
}
