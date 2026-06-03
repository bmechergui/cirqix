import type { PCBState, PCBStatus, AgentStep } from '@layrix/types';

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
