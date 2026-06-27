// Types partagés Cirqix — source de vérité unique

export type PCBStatus =
  | 'INITIAL'
  | 'SCHEMA_DONE'
  | 'ERC_CLEAN'
  | 'PLACEMENT_DONE'
  | 'ROUTING_DONE'
  | 'DRC_CLEAN'
  | 'PCB_LIVRÉ';

export type Plan = 'free' | 'pro' | 'pro_max' | 'enterprise';

export type FootprintSource =
  | 'kicad_official'
  | 'snapmagic'
  | 'octopart'
  | 'ai_generated';

export type AgentAction =
  | 'chat'
  | 'spec'
  | 'schema'
  | 'erc'
  | 'placement'
  | 'routing'
  | 'drc'
  | 'export'
  | 'footprint'
  | 'view3d'
  | 'simulation';

export type AgentStep = 'SPEC' | 'SCHEMA' | 'FOOTPRINT' | 'ERC' | 'PLACEMENT' | 'ROUTING' | 'DRC' | 'EXPORT' | 'SIMULATION' | null;

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

/**
 * Electrical Rules Check violation from kicad-cli sch erc.
 * Severity reflects KiCad's report severity. `ref`/`pin` point to the offending
 * symbol pin; coordinates (in mm) are in the schematic page space.
 */
export interface ERCViolation {
  id: string;
  severity: 'error' | 'warning';
  /** Free-form description from KiCad (e.g. "Pin not connected") */
  message: string;
  /** ERC violation type identifier from KiCad (e.g. "pin_not_connected", "different_net_no_marker") */
  type?: string;
  ref?: string;
  pin?: string;
  x_mm?: number;
  y_mm?: number;
}

// --- PCB Design types (high-level circuit context) ---

/**
 * High-level circuit design specification produced by the Design Agent.
 * Generated from the user prompt before any schematic/component decisions.
 * Provides context (type, layers, rules, constraints) that downstream agents
 * (Schematic, Footprint, Placement, Routing, DRC) consume to make informed choices.
 */
export interface DesignJson {
  /** Circuit category — e.g. "power_supply", "iot_sensor", "motor_driver". */
  type: string;
  /** Functional blocks identified — e.g. ["Power", "Decoupling", "MCU"]. */
  blocks: string[];
  /** Number of PCB copper layers — decided by the routing agent, bounded by user plan
   *  (Free: 2 max · Pro: 4 max · Pro Max: 8 max · Enterprise: unlimited). */
  layers: 2 | 4 | 8;
  /** Design rules adapted to the circuit type. */
  rules: {
    trace_width_mm: number;
    clearance_mm: number;
    via_drill_mm: number;
    min_text_mm: number;
  };
  /** Functional constraints derived from the prompt. */
  constraints: {
    output_voltage?: number;
    max_current_A?: number;
    /** [width_mm, height_mm] — board dimensions hint. */
    max_board_mm?: [number, number];
    /** Free-form additional constraints (e.g. {"power": "low", "connectivity": "wifi"}). */
    [key: string]: number | string | [number, number] | undefined;
  };
}

// --- PCB Schematic / Netlist types ---

export interface SchemaComponent {
  ref: string;
  value: string;
  /** Simplified footprint key: "0402", "0603", "DIP-8", "SOT-23", "LED", etc. */
  footprint: string;
  /** KiCad symbol id — e.g. "Device:R", "Timer:NE555P", "Regulator_Linear:LM7805" */
  symbol?: string;
  lcsc?: string;
}

export interface SchemaPin {
  /** Component reference designator, e.g. "R1" */
  ref: string;
  /**
   * Pin identifier — either a 1-indexed pad number (passives: R, C, LED, J)
   * or a KiCad pin name string (ICs: "IN", "GND", "OUT", "TR", "R", "Q"…).
   * circuit-synth accepts both: comp["IN"] and comp[1] are equivalent.
   */
  pin: number | string;
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
  /** High-level design context (from design step — first agent). */
  design?: DesignJson;
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
  ercViolations?: ERCViolation[];
  /** True when the ERC check was skipped (e.g. kicad-cli unavailable in dev). */
  erc_skipped?: boolean;
  board_width_mm?: number;
  board_height_mm?: number;
  /** Supabase Storage signed URL for .kicad_sch file (Circuit-Synth output) */
  kicad_sch_url?: string;
  /** Supabase Storage signed URL for .kicad_pcb file (Circuit-Synth output) */
  kicad_pcb_url?: string;
  /** Base64-encoded gerbers+drill ZIP from kicad-cli export */
  gerberZipB64?: string;
  /** BOM CSV with LCSC part numbers for JLCPCB PCBA */
  bomCsv?: string;
  /** PCB-only price estimate in USD from kicad-cli export service */
  quoteUsd?: number;
  /** Estimated lead time in days from export service */
  leadTimeDays?: number;
  /** ngspice simulation waveform data */
  simulationData?: SimulationData;
}

export interface SimulationVector {
  name: string;
  unit: 'V' | 'A' | 's' | '';
  time: number[];
  values: number[];
}

export interface SimulationData {
  sim_type: string;
  vectors: SimulationVector[];
  excluded_components?: string[];
}

export const CREDIT_COSTS: Record<AgentAction, number> = {
  chat: 0.5,
  spec: 0.5,
  schema: 2,
  erc: 0.5,
  placement: 2,
  routing: 3,
  drc: 1,
  export: 1,
  footprint: 3,
  view3d: 1,
  simulation: 3,
};
