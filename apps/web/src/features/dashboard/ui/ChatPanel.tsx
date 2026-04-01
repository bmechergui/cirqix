'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Bot, User } from 'lucide-react';
import { Button } from '@/shared/ui/button';
import { Input } from '@/shared/ui/input';
import { useAppStore } from '@/shared/store/app-store';
import type { Message } from '@layrix/types';
import type { SSEEvent } from '@layrix/agents';

interface ChatPanelProps {
  projectId: string;
}

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user';
  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div
        className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${
          isUser ? 'bg-primary/20 text-primary' : 'bg-[#1a1a1a] text-muted-foreground'
        }`}
      >
        {isUser ? <User size={14} /> : <Bot size={14} />}
      </div>
      <div
        className={`max-w-[80%] rounded-xl px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap ${
          isUser
            ? 'bg-primary text-[#080808] font-medium rounded-tr-sm'
            : 'bg-[#161616] text-foreground border border-border rounded-tl-sm'
        }`}
      >
        {msg.content}
      </div>
    </div>
  );
}

function StreamingBubble({ text }: { text: string }) {
  return (
    <div className="flex gap-3">
      <div className="w-7 h-7 rounded-full bg-[#1a1a1a] flex items-center justify-center shrink-0">
        <Bot size={14} className="text-muted-foreground" />
      </div>
      <div className="max-w-[80%] rounded-xl rounded-tl-sm px-3 py-2 text-sm leading-relaxed bg-[#161616] text-foreground border border-border whitespace-pre-wrap">
        {text || (
          <span className="flex gap-1 pt-1">
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

export function ChatPanel({ projectId }: ChatPanelProps) {
  const [input, setInput] = useState('');
  const [streamingText, setStreamingText] = useState('');
  const messages = useAppStore((s) => s.messagesByProject[projectId] ?? []);
  const addMessage = useAppStore((s) => s.addMessage);
  const isAgentRunning = useAppStore((s) => s.isAgentRunning);
  const setAgentRunning = useAppStore((s) => s.setAgentRunning);
  const deductCredits = useAppStore((s) => s.deductCredits);
  const setPcbState = useAppStore((s) => s.setPcbState);
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
              addMessage(projectId, {
                id: Date.now().toString(),
                role: 'assistant',
                content: `Error: ${event.message}`,
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
  }, [input, isAgentRunning, addMessage, projectId, setAgentRunning, deductCredits, setPcbState, messages]);

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && !isAgentRunning && (
          <div className="flex flex-col items-center justify-center h-full text-center gap-3 py-12">
            <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center">
              <Bot size={24} className="text-primary" />
            </div>
            <p className="text-sm text-muted-foreground max-w-xs">
              Describe your PCB requirements and the AI agent will design it for you.
            </p>
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}
        {isAgentRunning && <StreamingBubble text={streamingText} />}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-border p-3">
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
