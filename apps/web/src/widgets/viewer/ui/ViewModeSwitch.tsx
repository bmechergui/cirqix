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
      {/* Native button */}
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
        <span>Native</span>
      </button>

      {/* Cirqix spec button */}
      <button
        type="button"
        onClick={() => onChange('spec')}
        title="Cirqix view — netlist, components, diagram"
        className={cn(
          'flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[10px] font-medium transition-all duration-150',
          mode === 'spec'
            ? 'bg-primary/10 text-primary border border-primary/20 shadow-sm'
            : 'text-[#555] hover:text-[#888] hover:bg-[#161616]',
        )}
      >
        <LayoutList size={10} className="shrink-0" />
        <span>Cirqix</span>
      </button>
    </div>
  );
}
