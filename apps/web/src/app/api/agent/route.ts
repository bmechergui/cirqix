import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { createRouteHandlerClient } from '@/shared/lib/supabase-server';
import { runOrchestrator } from '@layrix/agents';
import type { SSEEvent } from '@layrix/agents';
import { CREDIT_COSTS } from '@layrix/types';
import type { AgentAction } from '@layrix/types';

// Map tool name → AgentAction for per-step credit deduction
const TOOL_ACTION_MAP: Record<string, AgentAction> = {
  call_agent_schema:    'schema',
  call_agent_placement: 'placement',
  call_agent_routing:   'routing',
  call_agent_drc:       'drc',
  call_agent_export:    'export',
  call_agent_footprint: 'footprint',
};

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

          // Pre-step credit guard — check balance before each PCB tool executes
          if (event.type === 'tool_call') {
            const action = TOOL_ACTION_MAP[event.tool];
            if (action) {
              const { data: currentCredits } = await supabase
                .from('credits')
                .select('balance')
                .eq('user_id', user.id)
                .single();
              if (!currentCredits || currentCredits.balance < CREDIT_COSTS[action]) {
                send({ type: 'error', message: 'insufficient_credits' });
                break;
              }
            }
          }

          // Persist PCB state to DB — merge with existing so circuit_json is never lost
          // (DRC/export results don't carry circuit_json; a plain replace would wipe it)
          if (event.type === 'pcb_state') {
            const { data: current } = await supabase
              .from('projects')
              .select('pcb_state')
              .eq('id', body.projectId)
              .eq('user_id', user.id)
              .single();
            const merged = {
              ...(current?.pcb_state as Record<string, unknown> ?? {}),
              ...event.state,
            };

            // Derive project-level status from pcb_status (e.g. 'DRC_CLEAN' → projects.status)
            const pcbStatus = event.state['pcb_status'] as string | undefined;
            const projectUpdate: Record<string, unknown> = {
              pcb_state: merged,
              updated_at: new Date().toISOString(),
            };
            if (pcbStatus) {
              projectUpdate['status'] = pcbStatus;
            }

            await supabase
              .from('projects')
              .update(projectUpdate)
              .eq('id', body.projectId)
              .eq('user_id', user.id);
          }

          // Deduct credits per PCB pipeline step (schema, placement, routing, drc, export)
          if (event.type === 'tool_result') {
            const action = TOOL_ACTION_MAP[event.tool];
            if (action) {
              await supabase.rpc('deduct_credits', {
                p_user_id: user.id,
                p_amount: CREDIT_COSTS[action],
                p_action: action,
                p_project_id: body.projectId,
              });
            }
          }

          // Deduct chat credit on completion
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
