'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Bot, User, Check, AlertTriangle, AlertCircle } from 'lucide-react';
import { Button } from '@/shared/ui/button';
import { Input } from '@/shared/ui/input';
import { useAppStore } from '@/shared/store/app-store';
import type { Message, DRCViolation } from '@layrix/types';
import type { SSEEvent } from '@layrix/agents';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface ChatPanelProps {
  projectId: string;
}

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user';
  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div
        className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${
          isUser ? 'bg-primary/20 text-primary' : 'bg-[#1a1a1a] text-[#A1A1AA]'
        }`}
      >
        {isUser ? <User size={14} /> : <Bot size={14} />}
      </div>
      <div className={`flex flex-col gap-0.5 max-w-[80%] ${isUser ? 'items-end' : 'items-start'}`}>
        <div
          className={`rounded-xl px-3.5 py-2.5 text-sm leading-relaxed min-w-[64px] ${
            isUser
              ? 'bg-primary/90 text-[#080808] font-medium rounded-tr-sm whitespace-pre-wrap'
              : 'bg-[#161616] text-[#E4E4E7] border border-border rounded-tl-sm prose prose-invert prose-sm max-w-none [&_p]:text-[#E4E4E7] [&_li]:text-[#E4E4E7]'
          }`}
        >
          {isUser ? (
            msg.content
          ) : (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h1: ({ children }) => <h1 className="text-base font-bold mb-1 text-[#F4F4F5]">{children}</h1>,
                h2: ({ children }) => <h2 className="text-sm font-bold mb-1 text-[#F4F4F5]">{children}</h2>,
                h3: ({ children }) => <h3 className="text-sm font-semibold mb-1 text-[#E4E4E7]">{children}</h3>,
                p: ({ children }) => <p className="mb-1 last:mb-0 text-[#E4E4E7]">{children}</p>,
                ul: ({ children }) => <ul className="list-disc pl-4 mb-1">{children}</ul>,
                ol: ({ children }) => <ol className="list-decimal pl-4 mb-1">{children}</ol>,
                li: ({ children }) => <li className="mb-0.5 text-[#E4E4E7]">{children}</li>,
                code: ({ children }) => (
                  <code className="bg-[#0d0d0d] text-primary px-1 py-0.5 rounded text-xs font-mono">{children}</code>
                ),
                pre: ({ children }) => (
                  <pre className="bg-[#0d0d0d] p-2 rounded text-xs font-mono overflow-x-auto mb-1">{children}</pre>
                ),
                table: ({ children }) => (
                  <div className="overflow-x-auto mb-1">
                    <table className="text-xs border-collapse w-full">{children}</table>
                  </div>
                ),
                th: ({ children }) => (
                  <th className="border border-border px-2 py-1 text-left font-semibold text-[#F4F4F5]">{children}</th>
                ),
                td: ({ children }) => (
                  <td className="border border-border px-2 py-1 text-[#E4E4E7]">{children}</td>
                ),
                strong: ({ children }) => <strong className="font-semibold text-[#F4F4F5]">{children}</strong>,
                em: ({ children }) => <em className="italic">{children}</em>,
              }}
            >
              {msg.content}
            </ReactMarkdown>
          )}
        </div>
        <span className="text-[10px] text-[#52525B] px-1">{msg.timestamp}</span>
      </div>
    </div>
  );
}

// --- Agent pipeline timeline ---

const PIPELINE_STEPS = ['SCHEMA', 'PLACEMENT', 'ROUTING', 'DRC', 'EXPORT'] as const;
type PipelineStep = (typeof PIPELINE_STEPS)[number];

const STEP_LABELS: Record<PipelineStep, string> = {
  SCHEMA: 'Schema',
  PLACEMENT: 'Place',
  ROUTING: 'Route',
  DRC: 'DRC',
  EXPORT: 'Export',
};

function AgentTimeline({
  activeStep,
  completedSteps,
}: {
  activeStep: string | null;
  completedSteps: Set<string>;
}) {
  return (
    <div className="flex items-center gap-0.5 mb-2.5">
      {PIPELINE_STEPS.map((step, i) => {
        const isDone = completedSteps.has(step);
        const isActive = activeStep === step && !isDone;
        return (
          <div key={step} className="flex items-center gap-0.5">
            {i > 0 && (
              <div
                className={`w-4 h-px transition-colors ${
                  completedSteps.has(PIPELINE_STEPS[i - 1]!) || isDone
                    ? 'bg-emerald-500/40'
                    : 'bg-[#2E2E2E]'
                }`}
              />
            )}
            <div className="flex flex-col items-center gap-0.5">
              <div
                className={`w-5 h-5 rounded-full flex items-center justify-center transition-all ${
                  isDone
                    ? 'bg-emerald-500/15 border border-emerald-500/40 text-emerald-400'
                    : isActive
                      ? 'bg-primary/15 border border-primary/50 text-primary animate-pulse'
                      : 'bg-[#111111] border border-[#2A2A2A] text-[#3D3D3D]'
                }`}
              >
                {isDone ? (
                  <Check size={9} strokeWidth={3} />
                ) : (
                  <span className="text-[8px] font-bold">{i + 1}</span>
                )}
              </div>
              <span
                className={`text-[7px] font-mono ${
                  isDone
                    ? 'text-emerald-400/60'
                    : isActive
                      ? 'text-primary/70'
                      : 'text-[#2A2A2A]'
                }`}
              >
                {STEP_LABELS[step]}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StreamingBubble({
  text,
  activeStep,
  completedSteps,
}: {
  text: string;
  activeStep: string | null;
  completedSteps: Set<string>;
}) {
  const showTimeline = activeStep !== null || completedSteps.size > 0;
  return (
    <div className="flex gap-3">
      <div className="w-7 h-7 rounded-full bg-[#1a1a1a] flex items-center justify-center shrink-0">
        <Bot size={14} className="text-[#A1A1AA]" />
      </div>
      <div className="max-w-[80%] rounded-xl rounded-tl-sm px-3 py-2 text-sm leading-relaxed bg-[#161616] text-[#E4E4E7] border border-border prose prose-invert prose-sm max-w-none [&_p]:text-[#E4E4E7]">
        {showTimeline && (
          <AgentTimeline activeStep={activeStep} completedSteps={completedSteps} />
        )}
        {text ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
        ) : (
          <span className="flex gap-1 pt-0.5">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-pulse"
                style={{ animationDelay: `${i * 200}ms` }}
              />
            ))}
          </span>
        )}
      </div>
    </div>
  );
}

function DRCPanel({ violations }: { violations: DRCViolation[] }) {
  if (!violations.length) return null;
  const errors = violations.filter((v) => v.severity === 'error');
  const warnings = violations.filter((v) => v.severity === 'warning');
  return (
    <div className="mx-4 mb-2 rounded-lg border border-red-500/20 bg-red-500/5 p-2.5 space-y-1.5">
      <div className="flex items-center gap-1.5">
        <AlertCircle size={11} className="text-red-400 shrink-0" />
        <span className="text-[10px] font-mono text-red-400 font-semibold">
          DRC — {errors.length} error{errors.length !== 1 ? 's' : ''}{warnings.length ? `, ${warnings.length} warning${warnings.length !== 1 ? 's' : ''}` : ''}
        </span>
      </div>
      <div className="space-y-0.5 max-h-24 overflow-y-auto">
        {violations.slice(0, 8).map((v) => (
          <div key={v.id} className="flex items-start gap-1.5">
            {v.severity === 'error' ? (
              <AlertCircle size={9} className="text-red-400 shrink-0 mt-0.5" />
            ) : (
              <AlertTriangle size={9} className="text-amber-400 shrink-0 mt-0.5" />
            )}
            <span className="text-[9px] font-mono text-[#A1A1AA] leading-tight">{v.message}</span>
          </div>
        ))}
        {violations.length > 8 && (
          <span className="text-[9px] font-mono text-[#52525B]">
            +{violations.length - 8} more — see Routing tab
          </span>
        )}
      </div>
    </div>
  );
}

const PROMPT_SUGGESTIONS: Array<{ label: string; hint: string; prompt: string }> = [
  {
    label: 'Add USB-C',
    hint: 'power input with ESD protection',
    prompt: 'Add a USB-C power input with 5.1kΩ CC resistors and TVS ESD protection',
  },
  {
    label: '100nF decoupling',
    hint: 'on all IC VCC — prevents power noise',
    prompt: 'Add 100nF decoupling capacitors on every IC VCC pin, placed as close as possible',
  },
  {
    label: '4-layer board',
    hint: 'dedicated GND + power planes reduce EMI',
    prompt: 'Switch to a 4-layer stackup with dedicated GND and power planes',
  },
  {
    label: 'Run DRC',
    hint: 'check clearances, unconnected nets, silkscreen',
    prompt: 'Run DRC and fix all violations',
  },
  {
    label: 'Export Gerbers',
    hint: 'ready for JLCPCB fabrication',
    prompt: 'Export Gerbers, BOM and CPL for JLCPCB',
  },
];

function PromptSuggestions({ onSelect }: { onSelect: (text: string) => void }) {
  return (
    <div className="flex gap-2 overflow-x-auto pb-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      {PROMPT_SUGGESTIONS.map((s) => (
        <button
          key={s.label}
          type="button"
          onClick={() => onSelect(s.prompt)}
          title={s.hint}
          className="shrink-0 flex flex-col items-start px-3 py-1.5 text-xs rounded-lg border border-border bg-[#141414] hover:border-[#3D3D3D] hover:bg-[#1a1a1a] transition-colors text-left"
        >
          <span className="text-[#E4E4E7] font-medium whitespace-nowrap">{s.label}</span>
          <span className="text-[#71717A] whitespace-nowrap">{s.hint}</span>
        </button>
      ))}
    </div>
  );
}

const EMPTY_MESSAGES: Message[] = [];

const PCB_STATUS_TO_STEP: Record<string, string> = {
  SCHEMA_DONE:    'SCHEMA',
  PLACEMENT_DONE: 'PLACEMENT',
  ROUTING_DONE:   'ROUTING',
  DRC_CLEAN:      'DRC',
  'PCB_LIVRÉ':    'EXPORT',
};

export function ChatPanel({ projectId }: ChatPanelProps) {
  const [input, setInput] = useState('');
  const [streamingText, setStreamingText] = useState('');
  const [completedSteps, setCompletedSteps] = useState<Set<string>>(new Set());
  const messages = useAppStore((s) => s.messagesByProject[projectId] ?? EMPTY_MESSAGES);
  const addMessage = useAppStore((s) => s.addMessage);
  const isAgentRunning = useAppStore((s) => s.isAgentRunning);
  const agentStep = useAppStore((s) => s.agentStep);
  const setAgentRunning = useAppStore((s) => s.setAgentRunning);
  const deductCredits = useAppStore((s) => s.deductCredits);
  const setPcbState = useAppStore((s) => s.setPcbState);
  const updateProjectStatus = useAppStore((s) => s.updateProjectStatus);
  const drcViolations = useAppStore((s) => {
    const state = s.pcbStateByProject[projectId];
    return (state?.drcViolations ?? []) as DRCViolation[];
  });
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingText]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const handleSend = useCallback(async () => {
    const trimmed = input.trim();
    if (!trimmed || isAgentRunning) return;

    const now = new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: trimmed,
      timestamp: now,
    };
    addMessage(projectId, userMsg);
    setInput('');
    setAgentRunning(true);
    setStreamingText('');
    setCompletedSteps(new Set());

    const history = messages.map((m) => ({ role: m.role, content: m.content }));

    abortRef.current = new AbortController();

    try {
      const res = await fetch('/api/agent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ projectId, message: trimmed, history }),
        signal: abortRef.current.signal,
      });

      if (!res.ok) {
        const json = await res.json() as { error?: string };
        const errorMsg =
          json.error === 'insufficient_credits'
            ? 'Not enough credits. Please top up your balance.'
            : 'The agent encountered an error. Please try again.';
        addMessage(projectId, {
          id: Date.now().toString(),
          role: 'assistant',
          content: errorMsg,
          timestamp: new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }),
        });
        return;
      }

      const reader = res.body?.getReader();
      if (!reader) return;

      const decoder = new TextDecoder();
      let accumulated = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim();
          if (raw === '[DONE]') break;

          try {
            const event = JSON.parse(raw) as SSEEvent;

            if (event.type === 'text') {
              accumulated += event.delta;
              setStreamingText(accumulated);
            } else if (event.type === 'pcb_state') {
              setPcbState(event.projectId, event.state as Parameters<typeof setPcbState>[1]);
              const pcbStatus = (event.state as Record<string, unknown>)['pcb_status'];
              if (typeof pcbStatus === 'string') {
                updateProjectStatus(event.projectId, pcbStatus as Parameters<typeof updateProjectStatus>[1]);
                const doneStep = PCB_STATUS_TO_STEP[pcbStatus];
                if (doneStep) {
                  setCompletedSteps((prev) => new Set([...prev, doneStep]));
                }
              }
            } else if (event.type === 'step') {
              setAgentRunning(true, event.step as Parameters<typeof setAgentRunning>[1]);
            } else if (event.type === 'done') {
              const finalText = event.fullText || accumulated;
              if (finalText) {
                addMessage(projectId, {
                  id: Date.now().toString(),
                  role: 'assistant',
                  content: finalText,
                  timestamp: new Date().toLocaleTimeString('en-GB', {
                    hour: '2-digit',
                    minute: '2-digit',
                  }),
                });
                deductCredits(0.5);
              }
              setStreamingText('');
            } else if (event.type === 'error') {
              const errorContent =
                event.message === 'insufficient_credits'
                  ? 'Not enough credits. Please top up your balance.'
                  : `Error: ${event.message}`;
              addMessage(projectId, {
                id: Date.now().toString(),
                role: 'assistant',
                content: errorContent,
                timestamp: new Date().toLocaleTimeString('en-GB', {
                  hour: '2-digit',
                  minute: '2-digit',
                }),
              });
              setStreamingText('');
            }
          } catch {
            // Skip malformed SSE lines
          }
        }
      }
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') return;
      addMessage(projectId, {
        id: Date.now().toString(),
        role: 'assistant',
        content: 'Connection error. Please check your network and try again.',
        timestamp: new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }),
      });
    } finally {
      setAgentRunning(false);
      setStreamingText('');
    }
  }, [input, isAgentRunning, addMessage, projectId, setAgentRunning, deductCredits, setPcbState, updateProjectStatus, setCompletedSteps, messages]);

  return (
    <div className="flex flex-col h-full">
      {/* Context hint — shown when conversation is active */}
      {messages.length > 0 && (
        <div className="px-4 py-1.5 border-b border-border/40 bg-[#080808] shrink-0">
          <p className="text-[9px] text-[#3D3D3D] font-mono">
            Change components · resize board · iterate on routing
          </p>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && !isAgentRunning && (
          <div className="flex flex-col items-center justify-center h-full text-center gap-3 py-12">
            <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center">
              <Bot size={24} className="text-primary" />
            </div>
            <p className="text-sm text-[#71717A] max-w-xs">
              Describe your circuit. The agent generates schematic, placement, and routing.
            </p>
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}
        {isAgentRunning && (
          <StreamingBubble
            text={streamingText}
            activeStep={agentStep}
            completedSteps={completedSteps}
          />
        )}
        <div ref={bottomRef} />
      </div>

      {/* DRC violations panel — shown after agent finishes if violations exist */}
      {!isAgentRunning && drcViolations.length > 0 && (
        <DRCPanel violations={drcViolations} />
      )}

      {/* Input */}
      <div className="border-t border-border p-3 flex flex-col gap-2">
        {input.trim() === '' && !isAgentRunning && (
          <PromptSuggestions onSelect={setInput} />
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void handleSend();
          }}
          className="flex gap-2"
        >
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Describe your circuit…"
            className="flex-1 h-9 text-sm"
            disabled={isAgentRunning}
          />
          <Button
            type="submit"
            size="icon"
            className="h-9 w-9"
            disabled={isAgentRunning || !input.trim()}
            aria-label="Send message"
          >
            <Send size={14} />
          </Button>
        </form>
      </div>
    </div>
  );
}

