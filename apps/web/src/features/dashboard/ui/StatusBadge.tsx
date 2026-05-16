import { Badge } from '@/shared/ui/badge';
import type { PCBStatus } from '@layrix/types';

const STATUS_LABEL: Record<PCBStatus, string> = {
  INITIAL: 'Draft',
  SCHEMA_DONE: 'Schema',
  ERC_CLEAN: 'ERC clean',
  PLACEMENT_DONE: 'Placed',
  ROUTING_DONE: 'Routed',
  DRC_CLEAN: 'DRC clean',
  PCB_LIVRÉ: 'Delivered',
};

const STATUS_VARIANT: Record<PCBStatus, 'secondary' | 'default' | 'success' | 'copper' | 'warning'> = {
  INITIAL: 'secondary',
  SCHEMA_DONE: 'default',
  ERC_CLEAN: 'default',
  PLACEMENT_DONE: 'default',
  ROUTING_DONE: 'copper',
  DRC_CLEAN: 'success',
  PCB_LIVRÉ: 'success',
};

interface StatusBadgeProps {
  status: PCBStatus;
  className?: string;
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  return (
    <Badge variant={STATUS_VARIANT[status]} className={className}>
      <span className="inline-block w-1.5 h-1.5 rounded-full bg-current mr-1.5" />
      {STATUS_LABEL[status]}
    </Badge>
  );
}
