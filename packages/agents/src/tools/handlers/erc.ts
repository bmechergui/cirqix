import { pcbStateCache, log } from '../shared';
import { runRealErc, ErcServiceUnavailableError } from '../../engines/erc-service';
import { runErcFallback } from '../../engines/erc-fallback';

export async function handleErc(
  input: Record<string, unknown>,
  projectId: string
): Promise<Record<string, unknown>> {
  const autoFix = input['auto_fix'] !== false; // default true
  const cached = pcbStateCache.get(projectId);
  const schContent = cached?.kicad_sch_content;
  if (!schContent || schContent.length === 0) {
    // Schema step was never run — return empty result rather than crashing
    return {
      status: 'success',
      pcb_status: 'ERC_CLEAN',
      ercViolations: [],
      erc_skipped: true,
      engine: 'fallback-skip',
      warning: 'No .kicad_sch in cache — run call_agent_schema first.',
      note: 'ERC sauté — pas de schéma en cache.',
    };
  }

  try {
    const result = await runRealErc({ kicadSchContent: schContent, autoFix });
    // Persist updated .kicad_sch in cache so downstream tools see auto-fixes
    if (result.kicadSchContent && cached) {
      pcbStateCache.set(projectId, {
        ...cached,
        kicad_sch_content: result.kicadSchContent,
      });
    }
    // Only promote status when ERC actually passes (clean or skipped).
    // Unresolved violations keep the project at SCHEMA_DONE so the
    // orchestrator can surface them and the user knows the schema is dirty.
    const newStatus: 'ERC_CLEAN' | 'SCHEMA_DONE' =
      result.ercClean || result.skipped ? 'ERC_CLEAN' : 'SCHEMA_DONE';
    return {
      status: 'success',
      pcb_status: newStatus,
      ercViolations: result.violations,
      erc_skipped: result.skipped,
      fixed_count: result.fixedCount,
      kicad_sch_content: result.kicadSchContent ?? schContent,
      engine: result.skipped ? 'kicad-cli-skipped' : 'kicad-cli',
      warning: result.warning,
      note: result.skipped
        ? `ERC sauté — ${result.warning ?? 'kicad-cli indisponible'}.`
        : result.ercClean
        ? `ERC OK — 0 violation${result.fixedCount > 0 ? `, ${result.fixedCount} auto-fix appliqués` : ''}.`
        : `ERC — ${result.violations.length} violations restantes après auto-fix. Pipeline arrêté avant placement.`,
    };
  } catch (err) {
    if (!(err instanceof ErcServiceUnavailableError)) {
      log.warn({ err }, 'ERC service threw unexpected error — falling back');
    }
    // Pass cached schema so the TS ERC can validate connectivity
    const fallback = runErcFallback(cached?.schema);
    const errorCount = fallback.violations.filter(v => v.severity === 'error').length;
    const newStatus: 'ERC_CLEAN' | 'SCHEMA_DONE' = fallback.ercClean ? 'ERC_CLEAN' : 'SCHEMA_DONE';
    return {
      status: 'success',
      pcb_status: newStatus,
      ercViolations: fallback.violations,
      erc_skipped: fallback.skipped,
      fixed_count: fallback.fixedCount,
      kicad_sch_content: schContent,
      engine: fallback.engine,
      warning: fallback.warning,
      note: fallback.skipped
        ? `ERC sauté — kicad-cli indisponible, pas de schéma en cache.`
        : fallback.ercClean
        ? `ERC TypeScript OK — 0 erreur (${fallback.violations.length} warnings). kicad-cli indisponible pour validation complète.`
        : `ERC TypeScript — ${errorCount} erreur(s) détectée(s). Corriger avant placement.`,
    };
  }
}
