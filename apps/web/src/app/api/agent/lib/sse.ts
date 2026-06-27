import type { AgentStep, PCBState, PCBStatus } from '@cirqix/types';

export type SseEvent =
  | { type: 'token'; content: string }
  | { type: 'step'; step: AgentStep }
  | { type: 'status'; status: PCBStatus }
  | { type: 'pcb_state'; state: PCBState }
  | { type: 'reasoning'; steps: string[] }
  | { type: 'error'; message: string }
  | { type: 'done' };

export function encodeSse(ev: SseEvent): string {
  return `data: ${JSON.stringify(ev)}\n\n`;
}

export function sseHeaders(): HeadersInit {
  return {
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-cache, no-transform',
    Connection: 'keep-alive',
  };
}
