export type { Project, PCBStatus } from '@layrix/types';

export const PCB_STAGE_ORDER = [
  'IDEA',
  'SCHEMA',
  'ERC',
  'PLACEMENT',
  'ROUTING',
  'DRC',
  'EXPORT',
] as const;

export type PcbStage = (typeof PCB_STAGE_ORDER)[number];

import type { PCBStatus } from '@layrix/types';

export function statusToStage(status: PCBStatus): PcbStage {
  switch (status) {
    case 'INITIAL':         return 'IDEA';
    case 'SCHEMA_DONE':     return 'SCHEMA';
    case 'ERC_CLEAN':       return 'ERC';
    case 'PLACEMENT_DONE':  return 'PLACEMENT';
    case 'ROUTING_DONE':    return 'ROUTING';
    case 'DRC_CLEAN':       return 'DRC';
    case 'PCB_LIVRÉ':       return 'EXPORT';
  }
}

export function stageIndex(stage: PcbStage): number {
  return PCB_STAGE_ORDER.indexOf(stage);
}

export function isStageReached(current: PCBStatus, target: PcbStage): boolean {
  return stageIndex(statusToStage(current)) >= stageIndex(target);
}
