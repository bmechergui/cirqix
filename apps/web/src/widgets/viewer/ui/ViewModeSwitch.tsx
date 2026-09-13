'use client';

import { Cpu, LayoutList, Lock, Image as ImageIcon, Box } from 'lucide-react';
import { cn } from '@/shared/lib/utils';

/**
 * `native` — KiCanvas (le rendu officiel, sélection, couches, nets, propriétés) ;
 * `spec`   — la vue Cirqix (netlist, composants) ;
 * `png`    — le rendu PNG de KiCad (`kicad-cli pcb render`, top / bottom) ;
 * `3d`     — la vue 3D de KiCad (perspective, iso / front / back / left / right).
 * Les trois vues du board exigent un `.kicad_pcb` livré ; sans lui, seule `spec`.
 */
export type ViewMode = 'native' | 'spec' | 'png' | '3d';

interface ViewModeSwitchProps {
  mode: ViewMode;
  onChange: (mode: ViewMode) => void;
  nativeDisabled?: boolean;
  /** PNG et 3D ne valent que pour un BOARD ; l'étape Schéma les cache. */
  renders?: boolean;
}

export function ViewModeSwitch({ mode, onChange, nativeDisabled, renders = true }: ViewModeSwitchProps) {
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

      {renders && ([['png', <ImageIcon key="png" size={10} className="shrink-0" />, 'PNG', 'KiCad PNG render — top / bottom'],
         ['3d', <Box key="3d" size={10} className="shrink-0" />, '3D', 'KiCad 3D render — iso, front, back, sides']] as const
      ).map(([id, icon, label, title]) => (
        <button
          key={id}
          type="button"
          onClick={() => !nativeDisabled && onChange(id)}
          disabled={nativeDisabled}
          title={nativeDisabled ? 'Generate a design first to unlock KiCad renders' : title}
          className={cn(
            'flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[10px] font-medium transition-all duration-150',
            mode === id && !nativeDisabled
              ? 'bg-[#1a2a14] text-[#8be05a] border border-[#3f7a2a]/40 shadow-sm'
              : nativeDisabled
                ? 'text-[#2e2e2e] cursor-not-allowed'
                : 'text-[#555] hover:text-[#888] hover:bg-[#161616]',
          )}
        >
          {nativeDisabled ? <Lock size={9} className="shrink-0" /> : icon}
          <span>{label}</span>
        </button>
      ))}
    </div>
  );
}
