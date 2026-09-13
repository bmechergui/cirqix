import type { SchemaJson } from '../../engines/engine-router';
import { log, getAnthropicClient } from '../shared';
import { SCHEMA_SYSTEM_PROMPT, parseSchemaText } from './schema-prompt';

// --- Haiku schema generator ----------------------------------------------

export async function generateSchemaWithHaiku(description: string): Promise<SchemaJson | null> {
  // Review fix HIGH-1: reuse module-level singleton client.
  const client = getAnthropicClient();
  if (!client) {
    log.warn('schema agent: ANTHROPIC_API_KEY missing, using complexity-based fallback');
    return null;
  }

  try {
    const response = await client.messages.create({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 4096,
      system: SCHEMA_SYSTEM_PROMPT,
      messages: [{ role: 'user', content: `Circuit: ${description}` }],
    });

    const text = response.content[0]?.type === 'text' ? response.content[0].text.trim() : '';
    if (!text) {
      log.warn({ stop_reason: response.stop_reason }, 'Path B: Haiku returned empty text');
      return null;
    }
    if (response.stop_reason === 'max_tokens') {
      log.warn({ len: text.length }, 'Path B: Haiku hit max_tokens — JSON likely truncated');
    }

    // Strip accidental markdown fences if model adds them
    return parseSchemaText(text);
  } catch (err) {
    // Graceful fallback — never let a Haiku failure block the pipeline.
    // Review fix HIGH-2: log warning so silent fallbacks stay observable.
    log.warn({ err }, 'schema agent: Haiku call or JSON parse failed, using fallback');
    return null;
  }
}
