import Anthropic from '@anthropic-ai/sdk';

type MessageParam = Anthropic.MessageParam;
type ContentBlock = Anthropic.ContentBlock;
type ToolUseBlock = Anthropic.ToolUseBlock;
type TextBlock = Anthropic.TextBlock;
import { ORCHESTRATOR_SYSTEM_PROMPT } from './prompts';
import { PCB_TOOLS, executeToolStub } from './tools';

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
  | { type: 'pcb_state'; projectId: string; state: Record<string, unknown> }
  | { type: 'iteration'; count: number }
  | { type: 'done'; fullText: string }
  | { type: 'error'; message: string };

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
      tools: PCB_TOOLS,
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
        call_agent_spec: 'SPEC',
        call_agent_schema: 'SCHEMA',
        call_agent_footprint: 'FOOTPRINT',
        call_agent_erc: 'ERC',
        call_agent_placement: 'PLACEMENT',
        call_agent_routing: 'ROUTING',
        call_agent_drc: 'DRC',
        call_agent_export: 'EXPORT',
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

      const result = await executeToolStub(tool.name, toolInput, options.projectId);
      const resultStr = JSON.stringify(result);

      yield {
        type: 'tool_result',
        tool: tool.name,
        summary: String(result['note'] ?? resultStr.slice(0, 100)),
      };

      // Emit pcb_state so the frontend viewer can update in real-time
      const pcbStateTools = new Set([
        'call_agent_schema',
        'call_agent_erc',
        'call_agent_placement',
        'call_agent_routing',
        'call_agent_drc',
      ]);
      if (pcbStateTools.has(tool.name)) {
        yield {
          type: 'pcb_state',
          projectId: options.projectId,
          state: result,
        };
      }

      toolResults.push({
        type: 'tool_result',
        tool_use_id: tool.id,
        content: resultStr,
      });
    }

    messages.push({ role: 'user', content: toolResults });
  }

  yield { type: 'done', fullText: fullResponseText };
}
