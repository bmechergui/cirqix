'use client';

import { Cpu, LayoutList, Lock } from 'lucide-react';
import { cn } from '@/shared/lib/utils';

export type ViewMode = 'native' | 'spec';

interface ViewModeSwitchProps {
  mode: ViewMode;
  onChange: (mode: ViewMode) => void;
  nativeDisabled?: boolean;
}

export function ViewModeSwitch({ mode, onChange, nativeDisabled }: ViewModeSwitchProps) {
  return (
    <div className="flex items-center gap-0.5 bg-[#111111] rounded-lg p-0.5 border border-[#1e1e1e]">
      {/* Native KiCad button */}
      <button
        type="button"
        onClick={() => !nativeDisabled && onChange('native')}
        disabled={nativeDisabled}
        title={nativeDisabled ? 'Generate a design first to unlock native KiCad rendering' : 'Native KiCad render (official renderer)'}
        className={cn(
          'flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[10px] font-medium transition-all duration-150',
          mode === 'native' && !nativeDisabled
            ? 'bg-[#0c1e35] text-[#5baeff] border border-[#1d5fa0]/40 shadow-sm'
            : nativeDisabled
              ? 'text-[#2e2e2e] cursor-not-allowed'
              : 'text-[#555] hover:text-[#888] hover:bg-[#161616]',
        )}
      >
        {nativeDisabled
          ? <Lock size={9} className="shrink-0" />
          : <Cpu size={10} className="shrink-0" />
        }
        <span>KiCad</span>
        {!nativeDisabled && (
          <span className={cn(
            'text-[8px] font-mono px-1 py-px rounded leading-none',
            mode === 'native' ? 'bg-[#1d5fa0]/30 text-[#5baeff]' : 'bg-[#1a1a1a] text-[#3d3d3d]'
          )}>
            native
          </span>
        )}
      </button>

      {/* Spec button */}
      <button
        type="button"
        onClick={() => onChange('spec')}
        title="Logical view — netlist, components, diagram"
        className={cn(
          'flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[10px] font-medium transition-all duration-150',
          mode === 'spec'
            ? 'bg-primary/10 text-primary border border-primary/20 shadow-sm'
            : 'text-[#555] hover:text-[#888] hover:bg-[#161616]',
        )}
      >
        <LayoutList size={10} className="shrink-0" />
        <span>Logical</span>
      </button>
    </div>
  );
}
