'use client';

import { Sparkles, Terminal, Cpu, Settings } from 'lucide-react';
import type { Project } from '@cirqix/types';

export function IdeaView({ project }: { project: Project }) {
  return (
    <div className="flex-1 overflow-y-auto p-8 relative bg-radial-gradient">
      {/* Decorative background grid and glows */}
      <div className="absolute inset-0 bg-[linear-gradient(rgba(0,194,255,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(0,194,255,0.02)_1px,transparent_1px)] bg-[size:32px_32px] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_50%,#000_70%,transparent_100%)] pointer-events-none" />
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[350px] h-[350px] bg-primary/5 rounded-full filter blur-[100px] pointer-events-none animate-pulse" />

      <div className="max-w-3xl mx-auto py-8 relative z-10 space-y-8">
        {/* Header Hero Section */}
        <div className="flex flex-col items-center text-center space-y-4">
          <div className="relative">
            <div className="absolute inset-0 rounded-2xl bg-primary/20 filter blur-md animate-ping opacity-60" />
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-b from-primary/20 to-primary/5 border border-primary/30 flex items-center justify-center relative shadow-lg shadow-primary/10">
              <Sparkles size={24} className="text-primary animate-pulse" />
            </div>
          </div>
          <div className="space-y-2">
            <span className="text-[10px] uppercase font-mono tracking-widest text-primary/70 bg-primary/10 border border-primary/20 px-2 py-0.5 rounded-full">
              Project Initialization
            </span>
            <h2 className="text-2xl font-bold tracking-tight text-foreground bg-clip-text bg-gradient-to-r from-foreground via-foreground to-foreground/80">
              Design workspace
            </h2>
            <p className="text-xs text-muted-foreground max-w-md mx-auto">
              Welcome to your automated PCB workbench. The project is loaded and waiting for your schematic prompt.
            </p>
          </div>
        </div>

        {/* Project Card */}
        <div className="rounded-2xl border border-primary/10 bg-[#0c0d14]/75 backdrop-blur-md p-6 relative overflow-hidden shadow-2xl group hover:border-primary/20 transition-all duration-300">
          <div className="absolute top-0 left-0 w-full h-[1px] bg-gradient-to-r from-transparent via-primary/30 to-transparent" />
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-foreground font-mono">{project.name}</h3>
              <div className="flex items-center gap-1.5 text-[9px] font-mono text-primary bg-primary/10 border border-primary/20 px-2 py-0.5 rounded">
                <span className="w-1 h-1 rounded-full bg-primary animate-ping" />
                Awaiting Prompt
              </div>
            </div>
          </div>
        </div>

        {/* Workflow steps */}
        <div className="space-y-4">
          <h4 className="text-[10px] uppercase font-mono tracking-widest text-[#555] font-bold">
            How it works
          </h4>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="rounded-xl border border-white/5 bg-white/[0.02] p-4 space-y-2 hover:bg-white/[0.04] transition-colors group">
              <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/15 flex items-center justify-center text-primary">
                <Terminal size={14} />
              </div>
              <h5 className="text-xs font-semibold text-foreground">1. Prompt</h5>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                Describe the circuit in natural language. (e.g. &quot;design a small microcontroller board with a LED blinker&quot;).
              </p>
            </div>
            
            <div className="rounded-xl border border-white/5 bg-white/[0.02] p-4 space-y-2 hover:bg-white/[0.04] transition-colors">
              <div className="w-8 h-8 rounded-lg bg-green-500/10 border border-green-500/15 flex items-center justify-center text-green-500">
                <Cpu size={14} />
              </div>
              <h5 className="text-xs font-semibold text-foreground">2. Synthesis</h5>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                The AI will choose the components, create nets, place components, and route the board traces automatically.
              </p>
            </div>

            <div className="rounded-xl border border-white/5 bg-white/[0.02] p-4 space-y-2 hover:bg-white/[0.04] transition-colors">
              <div className="w-8 h-8 rounded-lg bg-amber-500/10 border border-amber-500/15 flex items-center justify-center text-amber-500">
                <Settings size={14} />
              </div>
              <h5 className="text-xs font-semibold text-foreground">3. Validate & Export</h5>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                Verify schematic electrical checks (ERC) and board layout design rules (DRC) before exporting your Gerbers.
              </p>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
