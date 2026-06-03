import Anthropic from '@anthropic-ai/sdk';

type MessageParam = Anthropic.MessageParam;
type ContentBlock = Anthropic.ContentBlock;
type ToolUseBlock = Anthropic.ToolUseBlock;
type TextBlock = Anthropic.TextBlock;
import { ORCHESTRATOR_SYSTEM_PROMPT } from './prompts';
import { ACTIVE_PCB_TOOLS, executeToolStub } from './tools';

export const MAX_ITERATIONS = 15;
const ORCHESTRATOR_MODEL = 'claude-sonnet-4-6';
const MAX_TOKENS = 4096;

export interface AgentHistoryMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface OrchestratorOptions {
  userMessage: string;
  projectId: string;
  history: AgentHistoryMessage[];
}

export type SSEEvent =
  | { type: 'text'; delta: string }
  | { type: 'step'; step: string }
  | { type: 'tool_call'; tool: string; input: Record<string, unknown> }
  | { type: 'tool_result'; tool: string; summary: string }
  | { type: 'reasoning'; steps: string[] }
  | { type: 'pcb_state'; projectId: string; state: Record<string, unknown> }
  | { type: 'iteration'; count: number }
  | { type: 'done'; fullText: string }
  | { type: 'error'; message: string };

/**
 * Décision à seuil : le routage doit-il être secouru par le reasoner ?
 * Règle métier déterministe (pct < 100), pas un jugement LLM → vit dans le code.
 */
export function shouldRescueRouting(result: Record<string, unknown>): boolean {
  const pct = result['routed_percent'];
  return typeof pct === 'number' && pct < 100;
}

function extractReasoningSteps(result: Record<string, unknown>): string[] {
  return Array.isArray(result['reasoning_steps'])
    ? (result['reasoning_steps'] as unknown[]).filter((s): s is string => typeof s === 'string')
    : [];
}

/**
 * Fusionne le résultat du reasoner dans le tool_result du routage. On garde le
 * même tool_use_id (celui du routage) → structure API Anthropic valide ; Sonnet
 * voit un seul tool_result pour le routage, reflétant le sauvetage.
 */
export function mergeRescueIntoRouting(
  routing: Record<string, unknown>,
  reason: Record<string, unknown>,
): Record<string, unknown> {
  const routingPct = typeof routing['routed_percent'] === 'number' ? routing['routed_percent'] : 0;
  const reasonPct = typeof reason['routed_percent'] === 'number' ? reason['routed_percent'] : -1;
  // Le reasoner ne peut qu'AMÉLIORER : s'il est indisponible/échoue (pct 0, pas de
  // board), on conserve le routage d'origine plutôt que de régresser (ex. 95% → 0%).
  const improved = reasonPct >= routingPct && typeof reason['kicad_pcb_content'] === 'string';
  return {
    ...routing,
    routed_percent: improved ? reasonPct : routing['routed_percent'],
    kicad_pcb_content: improved ? reason['kicad_pcb_content'] : routing['kicad_pcb_content'],
    reasoning_steps: extractReasoningSteps(reason),
    reasoner_engine: reason['engine'],
    note: `${String(routing['note'] ?? '')} | Reasoner: ${String(reason['note'] ?? '')}`,
  };
}

export async function* runOrchestrator(
  options: OrchestratorOptions
): AsyncGenerator<SSEEvent> {
  const apiKey = process.env['ANTHROPIC_API_KEY'];
  if (!apiKey) {
    yield { type: 'error', message: 'ANTHROPIC_API_KEY non configurée.' };
    return;
  }

  const client = new Anthropic({ apiKey });

  const messages: MessageParam[] = [
    ...options.history.map((m) => ({ role: m.role, content: m.content })),
    { role: 'user', content: options.userMessage },
  ];

  let iterations = 0;
  let fullResponseText = '';

  while (iterations < MAX_ITERATIONS) {
    iterations++;
    yield { type: 'iteration', count: iterations };

    const stream = await client.messages.create({
      model: ORCHESTRATOR_MODEL,
      max_tokens: MAX_TOKENS,
      system: ORCHESTRATOR_SYSTEM_PROMPT,
      tools: ACTIVE_PCB_TOOLS,
      messages,
      stream: true,
    });

    // Accumulate streamed content
    let textDelta = '';
    const toolUseBlocks: Array<{ id: string; name: string; inputJson: string }> = [];
    let currentToolUse: { id: string; name: string; inputJson: string } | null = null;
    let stopReason: string | null = null;

    for await (const event of stream) {
      if (event.type === 'content_block_start') {
        if (event.content_block.type === 'tool_use') {
          currentToolUse = {
            id: event.content_block.id,
            name: event.content_block.name,
            inputJson: '',
          };
        }
      } else if (event.type === 'content_block_delta') {
        if (event.delta.type === 'text_delta') {
          textDelta += event.delta.text;
          fullResponseText += event.delta.text;
          yield { type: 'text', delta: event.delta.text };
        } else if (event.delta.type === 'input_json_delta' && currentToolUse) {
          currentToolUse.inputJson += event.delta.partial_json;
        }
      } else if (event.type === 'content_block_stop') {
        if (currentToolUse) {
          toolUseBlocks.push({ ...currentToolUse });
          currentToolUse = null;
        }
      } else if (event.type === 'message_delta') {
        stopReason = event.delta.stop_reason ?? null;
      }
    }

    // Build assistant content blocks for history
    const assistantContent: ContentBlock[] = [];
    if (textDelta) {
      const textBlock = { type: 'text' as const, text: textDelta } as TextBlock;
      assistantContent.push(textBlock);
    }
    for (const tool of toolUseBlocks) {
      let toolInput: Record<string, unknown> = {};
      try {
        toolInput = JSON.parse(tool.inputJson || '{}') as Record<string, unknown>;
      } catch {
        toolInput = {};
      }
      const toolBlock = {
        type: 'tool_use' as const,
        id: tool.id,
        name: tool.name,
        input: toolInput,
      } as ToolUseBlock;
      assistantContent.push(toolBlock);
      yield { type: 'tool_call', tool: tool.name, input: toolInput };

      // Emit step event for PCB pipeline steps
      const stepMap: Record<string, string> = {
        call_agent_schema: 'SCHEMA',
        call_agent_erc: 'ERC',
        call_agent_footprint: 'FOOTPRINT',
        call_agent_gen_pcb: 'KICAD',
        call_agent_placement: 'PLACEMENT',
        call_agent_routing: 'ROUTING',
        call_agent_reason: 'ROUTING', // sauvetage IA — même étape pipeline que ROUTING
        call_agent_drc: 'DRC',
        call_agent_export: 'EXPORT',
        call_agent_simulation: 'SIMULATION',
      };
      const step = stepMap[tool.name];
      if (step) yield { type: 'step', step };
    }

    messages.push({ role: 'assistant', content: assistantContent });

    // If no tool calls or end_turn, we're done
    if (stopReason === 'end_turn' || toolUseBlocks.length === 0) {
      break;
    }

    // Execute tools and add results
    const toolResults: Array<{
      type: 'tool_result';
      tool_use_id: string;
      content: string;
    }> = [];

    for (const tool of toolUseBlocks) {
      let toolInput: Record<string, unknown> = {};
      try {
        toolInput = JSON.parse(tool.inputJson || '{}') as Record<string, unknown>;
      } catch {
        toolInput = {};
      }

      let result = await executeToolStub(tool.name, toolInput, options.projectId);

      // Déclenchement DÉTERMINISTE du reasoner (hybride visible) : si le routage
      // n'est pas complet, l'orchestrateur lance LUI-MÊME call_agent_reason — règle
      // métier à seuil (routed_percent < 100), donc code et non jugement de Sonnet.
      // Le board débloqué est fusionné dans le tool_result du routage (même
      // tool_use_id → structure API valide) ; les actions IA sont émises en SSE
      // pour la visibilité temps-réel (ChatRail). Sonnet ne voit plus
      // call_agent_reason dans ses outils (ACTIVE_PCB_TOOLS) → zéro double-appel.
      if (tool.name === 'call_agent_routing' && shouldRescueRouting(result)) {
        const reason = await executeToolStub('call_agent_reason', {}, options.projectId);
        const steps = extractReasoningSteps(reason);
        if (steps.length > 0) yield { type: 'reasoning', steps };
        result = mergeRescueIntoRouting(result, reason);
      }

      yield {
        type: 'tool_result',
        tool: tool.name,
        summary: String(result['note'] ?? JSON.stringify(result).slice(0, 100)),
      };

      // Legacy : si jamais Sonnet appelait directement call_agent_reason, remonter
      // quand même ses actions (le chemin nominal est le trigger déterministe ci-dessus).
      if (tool.name === 'call_agent_reason' && Array.isArray(result['reasoning_steps'])) {
        const steps = (result['reasoning_steps'] as unknown[]).filter(
          (s): s is string => typeof s === 'string',
        );
        if (steps.length > 0) yield { type: 'reasoning', steps };
      }

      // Emit pcb_state so the frontend viewer can update in real-time
      const pcbStateTools = new Set([
        'call_agent_schema',
        'call_agent_erc',
        'call_agent_gen_pcb',
        'call_agent_placement',
        'call_agent_routing',
        'call_agent_reason',
        'call_agent_drc',
        'call_agent_export',
        'call_agent_simulation',
      ]);
      if (pcbStateTools.has(tool.name)) {
        yield {
          type: 'pcb_state',
          projectId: options.projectId,
          state: result,
        };
      }

      // Strip large KiCad file blobs before adding to Sonnet context.
      // The actual content is cached server-side (_pcbStateCache) and sent
      // to the frontend via pcb_state above — Sonnet only needs the metadata.
      const LARGE_FIELDS = [
        'kicad_sch_content',
        'kicad_pcb_content',
        'gerber_zip_b64',
        'bom_csv',
        'simulation_output_raw',
      ] as const;
      const slimResult: Record<string, unknown> = { ...result };
      for (const field of LARGE_FIELDS) {
        if (field in slimResult) {
          slimResult[field] = '[truncated — stored server-side]';
        }
      }

      toolResults.push({
        type: 'tool_result',
        tool_use_id: tool.id,
        content: JSON.stringify(slimResult),
      });
    }

    messages.push({ role: 'user', content: toolResults });
  }

  yield { type: 'done', fullText: fullResponseText };
}
