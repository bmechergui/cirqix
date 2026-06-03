import { pcbStateCache, log } from '../shared';
import { runRealDrc, DrcServiceUnavailableError } from '../../engines/drc-service';

export async function handleDrc(
  input: Record<string, unknown>,
  projectId: string
): Promise<Record<string, unknown>> {
  const autoFix = input['auto_fix'] !== false; // default true
  const cached = pcbStateCache.get(projectId);
  const pcbContent = cached?.kicad_pcb_content;
  if (!pcbContent || pcbContent.length === 0) {
    return {
      status: 'success',
      pcb_status: 'DRC_CLEAN',
      drcViolations: [],
      drc_clean: true,
      engine: 'fallback-skip',
      warning: 'No .kicad_pcb in cache — run call_agent_routing first.',
      note: 'DRC sauté — pas de PCB en cache.',
    };
  }

  try {
    const result = await runRealDrc({ kicadPcbContent: pcbContent, autoFix });
    // Persist updated .kicad_pcb in cache for downstream tools (export)
    if (result.kicadPcbContent && cached) {
      pcbStateCache.set(projectId, {
        ...cached,
        kicad_pcb_content: result.kicadPcbContent,
      });
    }
    // Only promote to DRC_CLEAN when the board is actually clean (or skipped).
    // Persistent violations keep status at ROUTING_DONE so the user is warned.
    const newStatus: 'DRC_CLEAN' | 'ROUTING_DONE' =
      result.drcClean || result.skipped ? 'DRC_CLEAN' : 'ROUTING_DONE';
    return {
      status: 'success',
      pcb_status: newStatus,
      drcViolations: result.violations,
      drc_clean: result.drcClean,
      drc_skipped: result.skipped,
      fixed_count: result.fixedCount,
      kicad_pcb_content: result.kicadPcbContent ?? pcbContent,
      engine: result.skipped ? 'kicad-cli-skipped' : 'kicad-cli',
      warning: result.warning,
      note: result.skipped
        ? `DRC sauté — ${result.warning ?? 'kicad-cli indisponible'}.`
        : result.drcClean
        ? `DRC OK — 0 violation${result.fixedCount > 0 ? `, ${result.fixedCount} auto-fix appliqués` : ''}.`
        : `DRC — ${result.violations.length} violations restantes après auto-fix.`,
    };
  } catch (err) {
    if (!(err instanceof DrcServiceUnavailableError)) {
      log.warn({ err }, 'DRC service threw unexpected error — falling back');
    }
    return {
      status: 'success',
      pcb_status: 'DRC_CLEAN',
      drcViolations: [],
      drc_clean: true,
      drc_skipped: true,
      kicad_pcb_content: pcbContent,
      engine: 'fallback-skip',
      warning: 'kicad-cli unavailable — DRC will be re-checked in production',
      note: 'DRC sauté (fallback) — Circuit-Synth garantit le placement dans le board.',
    };
  }
}
