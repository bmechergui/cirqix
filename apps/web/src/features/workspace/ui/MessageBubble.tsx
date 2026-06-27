'use client';

import { Bot, User } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Message } from '@cirqix/types';

interface MessageBubbleProps {
  msg: Message;
  isStreaming?: boolean;
}

export function MessageBubble({ msg, isStreaming }: MessageBubbleProps) {
  const isUser = msg.role === 'user';
  return (
    <div className={`flex gap-2.5 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div
        className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 ${
          isUser ? 'bg-primary/20 text-primary' : 'bg-[#1a1a1a] text-muted-foreground'
        }`}
      >
        {isUser ? <User size={12} /> : <Bot size={12} />}
      </div>
      <div className={`flex flex-col gap-0.5 min-w-0 max-w-[85%] ${isUser ? 'items-end' : 'items-start'}`}>
        <div
          className={`rounded-xl px-3 py-2 text-[13px] leading-relaxed min-w-0 ${
            isUser
              ? 'bg-primary/90 text-[#080808] font-medium rounded-tr-sm whitespace-pre-wrap break-words'
              : 'bg-[#161616] text-foreground border border-border rounded-tl-sm break-words'
          }`}
        >
          {isUser ? (
            msg.content
          ) : (
            <div className="prose prose-invert prose-sm max-w-none [&_p]:my-1 [&_p:last-child]:mb-0 [&_p:first-child]:mt-0">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  p: ({ children }) => <p className="text-foreground leading-relaxed">{children}</p>,
                  strong: ({ children }) => (
                    <strong className="font-semibold text-foreground">{children}</strong>
                  ),
                  code: ({ children }) => (
                    <code className="bg-[#0a0a0a] text-primary px-1 py-0.5 rounded text-[11px] font-mono">
                      {children}
                    </code>
                  ),
                  ul: ({ children }) => <ul className="list-disc pl-4 my-1 space-y-0.5">{children}</ul>,
                  ol: ({ children }) => <ol className="list-decimal pl-4 my-1 space-y-0.5">{children}</ol>,
                  li: ({ children }) => <li className="text-foreground">{children}</li>,
                }}
              >
                {msg.content || (isStreaming ? '…' : '')}
              </ReactMarkdown>
              {isStreaming && (
                <span className="inline-block w-1.5 h-3 bg-primary/60 animate-pulse ml-0.5 align-middle" />
              )}
            </div>
          )}
        </div>
        <span className="text-[10px] text-muted-foreground/50 px-1">{msg.timestamp}</span>
      </div>
    </div>
  );
}
