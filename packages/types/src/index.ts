// Types partagés Layrix — source de vérité unique

export type PCBStatus =
  | 'INITIAL'
  | 'SCHEMA_DONE'
  | 'PLACEMENT_DONE'
  | 'ROUTING_DONE'
  | 'DRC_CLEAN'
  | 'PCB_LIVRÉ';

export type Plan = 'free' | 'maker' | 'pro' | 'enterprise';

export type FootprintSource =
  | 'kicad_official'
  | 'snapmagic'
  | 'octopart'
  | 'ai_generated';

export type AgentAction =
  | 'chat'
  | 'schema'
  | 'placement'
  | 'routing'
  | 'drc'
  | 'export'
  | 'footprint'
  | 'view3d'
  | 'simulation';

export type AgentStep = 'SCHEMA' | 'PLACEMENT' | 'ROUTING' | 'DRC' | 'EXPORT' | null;

export interface Project {
  id: string;
  name: string;
  description: string;
  status: PCBStatus;
  iteration_count: number;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
}

export interface Credits {
  balance: number;
  plan: Plan;
  daily_limit: number | null;
}

export interface DRCViolation {
  id: string;
  severity: 'error' | 'warning';
  message: string;
  x_mm: number;
  y_mm: number;
  layer?: string;
}

// --- PCB Schematic / Netlist types ---

export interface SchemaComponent {
  ref: string;
  value: string;
  footprint: string;
  lcsc?: string;
}

export interface SchemaPin {
  /** Component reference designator, e.g. "R1" */
  ref: string;
  /** 1-indexed pad number of the footprint */
  pin: number;
}

export interface SchemaNet {
  name: string;
  pins: SchemaPin[];
}

export interface SchemaJson {
  components: SchemaComponent[];
  /** Net name strings, e.g. ["GND", "VCC", "NET1"] */
  nets: string[];
  /** Netlist connectivity — maps each net to the component pins it connects */
  connections?: SchemaNet[];
}

// --- PCB State ---

export interface PCBState {
  projectId: string;
  status: PCBStatus;
  iteration: number;
  /** Schematic components list (from schema step) */
  components?: SchemaComponent[];
  /** Net names (from schema step) */
  nets?: string[];
  /** Netlist connectivity (from schema step) */
  connections?: SchemaNet[];
  netlist?: Record<string, unknown>;
  placement?: Record<string, unknown>;
  routing?: Record<string, unknown>;
  drcViolations?: DRCViolation[];
  gerberPath?: string;
  /** Circuit-json soup produced by TSCircuit engine */
  circuit_json?: unknown[];
  board_width_mm?: number;
  board_height_mm?: number;
}

export const CREDIT_COSTS: Record<AgentAction, number> = {
  chat: 0.5,
  schema: 2,
  placement: 2,
  routing: 3,
  drc: 1,
  export: 1,
  footprint: 3,
  view3d: 1,
  simulation: 3,
};
