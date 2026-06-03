'use client';

import { useEffect, useRef } from 'react';
import { Sparkles } from 'lucide-react';
import type { Message } from '@layrix/types';
import { useAppStore } from '@/shared/store/app-store';
import { MessageBubble } from './MessageBubble';
import { ChatInput } from './ChatInput';
import { runAgent, nowTimestamp } from '../lib/agent-client';

interface ChatRailProps {
  projectId: string;
  projectDescription?: string;
}

function makeId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

const EMPTY_MESSAGES: Message[] = [];

export function ChatRail({ projectId, projectDescription }: ChatRailProps) {
  const messages = useAppStore((s) => s.messagesByProject[projectId]) ?? EMPTY_MESSAGES;
  const agentBusy = useAppStore((s) => s.agentBusy);
  const appendMessage = useAppStore((s) => s.appendMessage);
  const patchLastAssistantMessage = useAppStore((s) => s.patchLastAssistantMessage);
  const setAgentStep = useAppStore((s) => s.setAgentStep);
  const setAgentBusy = useAppStore((s) => s.setAgentBusy);
  const setPcbState = useAppStore((s) => s.setPcbState);
  const setSelectedStage = useAppStore((s) => s.setSelectedStage);
  const fetchCredits = useAppStore((s) => s.fetchCredits);

  const scrollerRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const el = scrollerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  async function send(text: string) {
    const userMsg: Message = {
      id: makeId(),
      role: 'user',
      content: text,
      timestamp: nowTimestamp(),
    };
    appendMessage(projectId, userMsg);

    const assistantMsg: Message = {
      id: makeId(),
      role: 'assistant',
      content: '',
      timestamp: nowTimestamp(),
    };
    appendMessage(projectId, assistantMsg);

    setAgentBusy(true);
    const ac = new AbortController();
    abortRef.current = ac;

    await runAgent({
      projectId,
      prompt: text,
      signal: ac.signal,
      onEvent: (ev) => {
        switch (ev.type) {
          case 'token':
            patchLastAssistantMessage(projectId, ev.content);
            break;
          case 'step':
            setAgentStep(ev.step);
            break;
          case 'pcb_state':
            setPcbState(projectId, ev.state);
            break;
          case 'reasoning': {
            // Reasoner IA — affiche les actions de déblocage du routage en direct
            const block =
              '\n\n🤖 **Reasoner IA — déblocage du routage :**\n' +
              ev.steps.map((s) => `  ${s}`).join('\n');
            patchLastAssistantMessage(projectId, block);
            break;
          }
          case 'status': {
            const stageMap = {
              INITIAL: 'IDEA',
              SCHEMA_DONE: 'SCHEMA',
              ERC_CLEAN: 'ERC',
              PLACEMENT_DONE: 'PLACEMENT',
              ROUTING_DONE: 'ROUTING',
              DRC_CLEAN: 'DRC',
              'PCB_LIVRÉ': 'EXPORT',
            } as const;
            setSelectedStage(projectId, stageMap[ev.status]);
            break;
          }
          case 'error':
            patchLastAssistantMessage(projectId, `\n\n_Error: ${ev.message}_`);
            break;
          case 'done':
          default:
            break;
        }
      },
    });

    setAgentStep(null);
    setAgentBusy(false);
    abortRef.current = null;
    void fetchCredits();
  }

  function cancel() {
    try {
      if (abortRef.current && typeof abortRef.current.abort === 'function') {
        abortRef.current.abort();
      }
    } catch (e) {
      console.warn('Failed to abort:', e);
    }
    setAgentStep(null);
    setAgentBusy(false);
    abortRef.current = null;
  }

  const isEmpty = messages.length === 0;

  return (
    <aside className="flex flex-col h-full bg-[#0d0d0d] border-r border-border w-full md:w-[340px] shrink-0">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border shrink-0">
        <Sparkles size={14} className="text-primary" />
        <span className="text-xs font-medium text-foreground">Layrix agent</span>
        <span className="ml-auto text-[10px] font-mono uppercase tracking-wider text-muted-foreground/60">
          {agentBusy ? 'thinking…' : 'idle'}
        </span>
      </div>

      <div ref={scrollerRef} className="flex-1 overflow-y-auto px-3 py-4 space-y-3">
        {messages.map((m, i) => (
          <MessageBubble
            key={m.id}
            msg={m}
            isStreaming={agentBusy && i === messages.length - 1 && m.role === 'assistant'}
          />
        ))}
      </div>

      <ChatInput onSend={send} onCancel={cancel} busy={agentBusy} />
    </aside>
  );
}
