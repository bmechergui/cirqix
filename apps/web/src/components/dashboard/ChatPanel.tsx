'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Bot, User } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useAppStore } from '@/store/app-store';
import type { Message } from '@/lib/mock-data';

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
        className={`max-w-[80%] rounded-xl px-3 py-2 text-sm leading-relaxed ${
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

export function ChatPanel({ projectId }: ChatPanelProps) {
  const [input, setInput] = useState('');
  const messages = useAppStore((s) => s.messagesByProject[projectId] ?? []);
  const addMessage = useAppStore((s) => s.addMessage);
  const isAgentRunning = useAppStore((s) => s.isAgentRunning);
  const setAgentRunning = useAppStore((s) => s.setAgentRunning);
  const bottomRef = useRef<HTMLDivElement>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    return () => {
      if (timeoutRef.current !== null) clearTimeout(timeoutRef.current);
    };
  }, []);

  const handleSend = useCallback(() => {
    const trimmed = input.trim();
    if (!trimmed || isAgentRunning) return;
    const now = new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
    addMessage(projectId, { id: Date.now().toString(), role: 'user', content: trimmed, timestamp: now });
    setInput('');
    setAgentRunning(true);
    // Simulate agent response
    timeoutRef.current = setTimeout(() => {
      addMessage(projectId, {
        role: 'assistant',
        content: `Processing your request: "${trimmed}". The PCB agent is analyzing the requirements…`,
        id: Date.now().toString(),
        timestamp: new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }),
      });
      setAgentRunning(false);
    }, 1500);
  }, [input, isAgentRunning, addMessage, projectId, setAgentRunning]);

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
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
        {isAgentRunning && (
          <div className="flex gap-3">
            <div className="w-7 h-7 rounded-full bg-[#1a1a1a] flex items-center justify-center">
              <Bot size={14} className="text-muted-foreground" />
            </div>
            <div className="bg-[#161616] border border-border rounded-xl rounded-tl-sm px-3 py-2">
              <span className="flex gap-1">
                {[0, 1, 2].map((i) => (
                  <span
                    key={i}
                    className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-pulse"
                    style={{ animationDelay: `${i * 200}ms` }}
                  />
                ))}
              </span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-border p-3">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
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
          <Button type="submit" size="icon" className="h-9 w-9" disabled={isAgentRunning || !input.trim()} aria-label="Send message">
            <Send size={14} />
          </Button>
        </form>
      </div>
    </div>
  );
}
