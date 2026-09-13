/**
 * `driver` (D-2026-09-13-b) : la route cree des runs de provenance `driver`,
 * sans retenue de credit ; le worker emprunte le porteur du driver et le
 * schema vient du fournisseur configure (Claude Code en ligne de commande).
 * Zero appel a l API Anthropic. Les boards restent NON commandables : le gate
 * JLCPCB exige `orchestrator`, et ce mode ne le touche pas.
 */
export type AgentMode = 'simulator' | 'orchestrator' | 'driver';

export function resolveAgentMode(): AgentMode {
  const raw = (process.env['CIRQIX_AGENT_MODE'] ?? '').toLowerCase().trim();
  if (raw === 'orchestrator' || raw === 'real') return 'orchestrator';
  if (raw === 'driver') return 'driver';
  return 'simulator';
}

export function isOrchestratorAvailable(): boolean {
  return Boolean(process.env['ANTHROPIC_API_KEY']);
}
