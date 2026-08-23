import type { PCBState, PCBStatus, AgentStep } from '@cirqix/types';
import { followRun } from './follow-run';

export type AgentSseEvent =
  | { type: 'token'; content: string }
  | { type: 'step'; step: AgentStep }
  | { type: 'status'; status: PCBStatus }
  | { type: 'pcb_state'; state: PCBState }
  | { type: 'reasoning'; steps: string[] }
  | { type: 'error'; message: string }
  | { type: 'done' };

interface RunAgentOptions {
  projectId: string;
  prompt: string;
  onEvent: (ev: AgentSseEvent) => void;
  signal?: AbortSignal;
}

export async function runAgent({ projectId, prompt, onEvent, signal }: RunAgentOptions): Promise<void> {
  const init: RequestInit = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ projectId, prompt }),
  };
  if (signal) init.signal = signal;
  const res = await fetch('/api/agent', init);

  // Mode ASYNCHRONE : la route a depose le travail et rendu la main (`202`).
  // Il n'y a pas de flux a lire — la progression vit dans `pcb_run_events`.
  // Realtime d'abord, sondage HTTP en repli (`followRun`). C'est ce chemin qui
  // permet a un routage de 20 min d'aboutir, la ou l'invocation web etait
  // coupee a 300 s ; et il survit a la fermeture de l'onglet.
  if (res.status === 202) {
    const { runId } = (await res.json()) as { runId?: string };
    if (!runId) {
      onEvent({ type: 'error', message: 'Run accepte sans identifiant' });
      return;
    }
    const followOptions: Parameters<typeof followRun>[0] = { runId, onEvent };
    if (signal) followOptions.signal = signal;
    await followRun(followOptions);
    return;
  }

  if (!res.ok || !res.body) {
    const errText = await res.text().catch(() => '');
    onEvent({ type: 'error', message: errText || `Agent request failed (${res.status})` });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let lineEnd = buffer.indexOf('\n\n');
      while (lineEnd !== -1) {
        const chunk = buffer.slice(0, lineEnd).trim();
        buffer = buffer.slice(lineEnd + 2);

        if (chunk.startsWith('data:')) {
          const json = chunk.slice(5).trim();
          if (json) {
            try {
              const ev = JSON.parse(json) as AgentSseEvent;
              onEvent(ev);
            } catch {
              onEvent({ type: 'error', message: 'Bad SSE payload' });
            }
          }
        }
        lineEnd = buffer.indexOf('\n\n');
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export function nowTimestamp(): string {
  const d = new Date();
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
}
