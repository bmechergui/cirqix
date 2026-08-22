import type { RunEvent, RunSink } from '@cirqix/agents';

/**
 * Le type d'événement vit désormais dans `@cirqix/agents` : c'est le pipeline
 * qui le PRODUIT, le transport ne fait que le véhiculer. Alias conservé pour ne
 * pas réécrire les sites d'appel existants.
 */
export type SseEvent = RunEvent;

export function encodeSse(ev: SseEvent): string {
  return `data: ${JSON.stringify(ev)}

`;
}

export function sseHeaders(): HeadersInit {
  return {
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-cache, no-transform',
    Connection: 'keep-alive',
  };
}

/**
 * Transport SSE — le comportement actuel, désormais derrière `RunSink`.
 *
 * Écrit exactement les mêmes octets qu'avant (`data: {...}

`) : c'est ce qui
 * permet à l'étape 2 de ne rien changer au comportement observable, côté client
 * comme côté tests.
 *
 * Ce transport meurt avec l'invocation qui le porte — c'est précisément sa
 * limite, et la raison d'être de `PgSink` à l'étape 3.
 */
export class SseSink implements RunSink {
  constructor(
    private readonly controller: ReadableStreamDefaultController<Uint8Array>,
    private readonly encoder: TextEncoder = new TextEncoder(),
  ) {}

  emit(event: RunEvent): Promise<void> {
    this.controller.enqueue(this.encoder.encode(encodeSse(event)));
    return Promise.resolve();
  }
}
