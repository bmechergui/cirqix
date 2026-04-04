import { Check } from 'lucide-react';

const STEPS = ['SCHEMA', 'PLACEMENT', 'ROUTING', 'DRC', 'EXPORT'] as const;

const STEP_LABELS: Record<(typeof STEPS)[number], string> = {
  SCHEMA:    'Schema',
  PLACEMENT: 'Placement',
  ROUTING:   'Routing',
  DRC:       'DRC',
  EXPORT:    'Export',
};

type AgentStep = (typeof STEPS)[number] | null;

const STEP_INDEX: Record<NonNullable<AgentStep>, number> = {
  SCHEMA:    0,
  PLACEMENT: 1,
  ROUTING:   2,
  DRC:       3,
  EXPORT:    4,
};

interface AgentProgressBarProps {
  step: AgentStep;
}

export function AgentProgressBar({ step }: AgentProgressBarProps) {
  if (!step) return null;

  const activeIdx = STEP_INDEX[step];
  // Progress fills to the center of the active step dot
  const pct = Math.round(((activeIdx + 0.5) / STEPS.length) * 100);

  return (
    <div className="px-4 py-3 border-b border-border bg-[#0a0a0a]">
      {/* Step dots + connector line */}
      <div className="relative flex items-center justify-between mb-3">
        {/* Background connector */}
        <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-px bg-border mx-4" />

        {/* Animated fill connector */}
        <div
          className="absolute top-1/2 -translate-y-1/2 h-px bg-primary transition-all duration-700 ease-in-out mx-4"
          style={{ width: `calc(${pct}% - 2rem)` }}
        />

        {STEPS.map((s, i) => {
          const isDone   = i < activeIdx;
          const isActive = i === activeIdx;

          return (
            <div key={s} className="relative z-10 flex flex-col items-center gap-1.5">
              {/* Dot */}
              <div
                className={`
                  w-5 h-5 rounded-full flex items-center justify-center border transition-all duration-300
                  ${isDone
                    ? 'bg-primary border-primary'
                    : isActive
                      ? 'bg-primary/20 border-primary shadow-[0_0_8px_rgba(0,194,255,0.4)]'
                      : 'bg-[#0d0d0d] border-border'
                  }
                `}
              >
                {isDone ? (
                  <Check size={10} className="text-[#080808] stroke-[3]" />
                ) : isActive ? (
                  <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
                ) : (
                  <span className="w-1.5 h-1.5 rounded-full bg-border" />
                )}
              </div>

              {/* Label — always visible, highlight active */}
              <span
                className={`text-[9px] font-mono whitespace-nowrap transition-colors duration-300 ${
                  isDone
                    ? 'text-primary/60'
                    : isActive
                      ? 'text-primary font-semibold'
                      : 'text-muted-foreground/30'
                }`}
              >
                {STEP_LABELS[s]}
              </span>
            </div>
          );
        })}
      </div>

      {/* Status line */}
      <div className="flex items-center justify-between mt-1">
        <span className="text-[10px] text-muted-foreground">
          Agent running —{' '}
          <span className="text-primary font-medium">{STEP_LABELS[step]}</span>
        </span>
        <span className="text-[10px] font-mono text-muted-foreground/60">
          {activeIdx + 1}/{STEPS.length}
        </span>
      </div>
    </div>
  );
}
