import type Anthropic from '@anthropic-ai/sdk';
import type { SchemaJson } from '../../engines/engine-router';
import { log, getAnthropicClient } from '../shared';
import { SCHEMA_SYSTEM_PROMPT, SCHEMA_JSON_SCHEMA, parseSchemaText, messageUtilisateur } from './schema-prompt';

// --- Haiku schema generator ----------------------------------------------

export async function generateSchemaWithHaiku(description: string, retour?: string): Promise<SchemaJson | null> {
  // Review fix HIGH-1: reuse module-level singleton client.
  const client = getAnthropicClient();
  if (!client) {
    log.warn('schema agent: ANTHROPIC_API_KEY missing, using complexity-based fallback');
    return null;
  }

  try {
    const response = await client.messages.create({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 16000,
      system: SCHEMA_SYSTEM_PROMPT,
      messages: [{ role: 'user', content: messageUtilisateur(description, retour) }],
      // Sorties structurees : l API garantit un JSON conforme au contrat.
      output_config: { format: { type: 'json_schema', schema: SCHEMA_JSON_SCHEMA } },
    });
    log.info({ surface: 'schema', usage: response.usage }, 'llm usage');

    // max_tokens ou refusal : le JSON peut etre partiel ou hors schema. On ne s en
    // sert pas ; le handler refuse alors le run, rien n est fabrique.
    if (response.stop_reason !== 'end_turn') {
      log.warn({ stop_reason: response.stop_reason }, 'Path B: Haiku stopped before end_turn — schema not used');
      return null;
    }
    const text = response.content.find((b): b is Anthropic.TextBlock => b.type === 'text')?.text.trim() ?? '';
    if (!text) {
      log.warn({ stop_reason: response.stop_reason }, 'Path B: Haiku returned empty text');
      return null;
    }

    return parseSchemaText(text);
  } catch (err) {
    // Graceful fallback — never let a Haiku failure block the pipeline.
    // Review fix HIGH-2: log warning so silent fallbacks stay observable.
    log.warn({ err }, 'schema agent: Haiku call or JSON parse failed, using fallback');
    return null;
  }
}
