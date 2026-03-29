import { Badge } from '@/components/ui/badge';
import type { PCBStatus } from '@/lib/mock-data';

const STATUS_CONFIG: Record<PCBStatus, { label: string; variant: 'default' | 'secondary' | 'success' | 'warning' | 'destructive' | 'copper' | 'outline'; pulse?: boolean }> = {
  INITIAL: { label: 'New', variant: 'secondary' },
  SCHEMA_DONE: { label: 'Schema', variant: 'default', pulse: true },
  PLACEMENT_DONE: { label: 'Placed', variant: 'default', pulse: true },
  ROUTING_DONE: { label: 'Routed', variant: 'warning' },
  DRC_CLEAN: { label: 'Ready', variant: 'success' },
  PCB_LIVRÉ: { label: 'Ordered', variant: 'copper' },
};

interface StatusBadgeProps {
  status: PCBStatus;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const config = STATUS_CONFIG[status] ?? { label: status, variant: 'secondary' as const };
  return (
    <Badge variant={config.variant} className="text-xs shrink-0">
      {config.pulse && (
        <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse mr-1.5 opacity-70" />
      )}
      {config.label}
    </Badge>
  );
}
