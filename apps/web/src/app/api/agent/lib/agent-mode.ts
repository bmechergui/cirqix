export type AgentMode = 'simulator' | 'orchestrator';

export function resolveAgentMode(): AgentMode {
  const raw = (process.env['CIRQIX_AGENT_MODE'] ?? '').toLowerCase().trim();
  if (raw === 'orchestrator' || raw === 'real') return 'orchestrator';
  return 'simulator';
}

export function isOrchestratorAvailable(): boolean {
  return Boolean(process.env['ANTHROPIC_API_KEY']);
}
