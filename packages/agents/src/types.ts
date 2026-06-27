// Types agentiques — types partagés importés depuis @cirqix/types
export type {
  PCBStatus,
  PCBState,
  DRCViolation,
  AgentAction,
  AgentStep,
} from '@cirqix/types';
export { CREDIT_COSTS } from '@cirqix/types';

// Types spécifiques à la couche agents
export interface AgentMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ToolCall {
  id: string;
  name: string;
  input: Record<string, unknown>;
}

export interface ToolResult {
  tool_use_id: string;
  content: string;
}
