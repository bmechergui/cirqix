'use client';

import { useEffect, useRef } from 'react';
import { Sparkles } from 'lucide-react';
import { chatTextOfEvent, type Message } from '@cirqix/types';
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
  const setStepProgress = useAppStore((s) => s.setStepProgress);
  const setAgentBusy = useAppStore((s) => s.setAgentBusy);
  const setPcbState = useAppStore((s) => s.setPcbState);
  const setSelectedStage = useAppStore((s) => s.setSelectedStage);
  const fetchCredits = useAppStore((s) => s.fetchCredits);
  const fetchMessages = useAppStore((s) => s.fetchMessages);

  const scrollerRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // La conversation du projet revient à sa réouverture (migration 026).
  useEffect(() => {
    void fetchMessages(projectId);
  }, [projectId, fetchMessages]);

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
        // Texte de la bulle (token, bloc du Reasoner IA, erreur) : même
        // formatage que l'historique persisté, défini une seule fois.
        const chunk = chatTextOfEvent(ev);
        if (chunk !== null) patchLastAssistantMessage(projectId, chunk);

        switch (ev.type) {
          case 'step':
            setAgentStep(ev.step);
            // La progression appartient a UNE etape : la garder afficherait
            // l'avancement du routage pendant le DRC qui le suit.
            setStepProgress(null);
            break;
          case 'pcb_state':
            setPcbState(projectId, ev.state);
            break;
          case 'progress':
            // ⚠️ Le routage dure de 5 s a 20 min et son appel est bloquant :
            // sans cette ligne, l'utilisateur ne voit rien entre le debut et
            // la fin. Le service mesure son avancement depuis toujours, il ne
            // le disait a personne.
            setStepProgress({
              step: ev.step,
              percent: ev.percent,
              ...(ev.detail ? { detail: ev.detail } : {}),
            });
            break;
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
        <span className="text-xs font-medium text-foreground">Cirqix agent</span>
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
