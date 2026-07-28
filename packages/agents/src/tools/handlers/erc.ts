import { pcbStateCache, log } from '../shared';
import { runRealErc, ErcServiceUnavailableError } from '../../engines/erc-service';
import { runErcFallback } from '../../engines/erc-fallback';
import type { SchemaJson } from '../../engines/engine-router';

/**
 * Aucun contrôle électrique n'a pu statuer → échec explicite.
 * `ERC_CLEAN` ne peut être accordé que par un contrôle réellement exécuté et
 * réellement passé — jamais par l'absence de contrôle.
 */
function ercFailure(cause: string): Record<string, unknown> {
  return {
    status: 'error',
    error: cause,
    note:
      `ERC impossible — le schéma n'a PAS été validé (${cause}). Vérifie que le ` +
      'conteneur Docker KiCad tourne (KICAD_SERVICE_URL).',
  };
}

/**
 * Repli quand kicad-cli ne statue pas (indisponible, ou service injoignable).
 *
 * Contrairement aux autres handlers, il existe ici un vérificateur de repli
 * RÉEL : `runErcFallback` (ERC TypeScript pur — refs dupliquées, nets flottants,
 * GND manquant, composants non connectés). La bonne réponse n'est donc pas
 * d'échouer, mais de faire tourner ce contrôle et d'en honorer le verdict.
 * On n'échoue que s'il n'a lui-même rien à contrôler (`skipped`) — c'était
 * précisément le cas qui remontait un ERC_CLEAN sans aucune vérification.
 */
function runDegradedErc(
  schema: SchemaJson | undefined,
  schContent: string,
): Record<string, unknown> {
  const fallback = runErcFallback(schema);
  if (fallback.skipped) {
    return ercFailure('kicad-cli indisponible et aucun schéma à contrôler');
  }
  const errorCount = fallback.violations.filter((v) => v.severity === 'error').length;
  return {
    status: 'success',
    pcb_status: fallback.ercClean ? 'ERC_CLEAN' : 'SCHEMA_DONE',
    ercViolations: fallback.violations,
    erc_skipped: false,
    fixed_count: fallback.fixedCount,
    kicad_sch_content: schContent,
    engine: fallback.engine,
    warning: fallback.warning,
    note: fallback.ercClean
      ? `ERC TypeScript OK — 0 erreur (${fallback.violations.length} warnings). ` +
        'kicad-cli indisponible pour validation complète.'
      : `ERC TypeScript — ${errorCount} erreur(s) détectée(s). Corriger avant placement.`,
  };
}

export async function handleErc(
  input: Record<string, unknown>,
  projectId: string
): Promise<Record<string, unknown>> {
  const autoFix = input['auto_fix'] !== false; // default true
  const cached = pcbStateCache.get(projectId);
  const schContent = cached?.kicad_sch_content;
  if (!schContent || schContent.length === 0) {
    return ercFailure('aucun .kicad_sch en cache — lance call_agent_schema d\'abord');
  }

  try {
    const result = await runRealErc({ kicadSchContent: schContent, autoFix });

    // kicad-cli n'a pas statué → on bascule sur l'ERC TypeScript, qui contrôle
    // réellement. Promouvoir ERC_CLEAN sur un `skipped` reviendrait à valider un
    // schéma que personne n'a vérifié.
    if (result.skipped) {
      log.warn({ projectId, warning: result.warning }, 'ERC skipped — falling back to TS ERC');
      return runDegradedErc(cached?.schema, schContent);
    }

    // Persist updated .kicad_sch in cache so downstream tools see auto-fixes
    if (result.kicadSchContent && cached) {
      pcbStateCache.set(projectId, {
        ...cached,
        kicad_sch_content: result.kicadSchContent,
      });
    }
    // Only promote status when ERC actually passes. Unresolved violations keep
    // the project at SCHEMA_DONE so the orchestrator can surface them and the
    // user knows the schema is dirty.
    return {
      status: 'success',
      pcb_status: result.ercClean ? 'ERC_CLEAN' : 'SCHEMA_DONE',
      ercViolations: result.violations,
      erc_skipped: false,
      fixed_count: result.fixedCount,
      kicad_sch_content: result.kicadSchContent ?? schContent,
      engine: 'kicad-cli',
      warning: result.warning,
      note: result.ercClean
        ? `ERC OK — 0 violation${result.fixedCount > 0 ? `, ${result.fixedCount} auto-fix appliqués` : ''}.`
        : `ERC — ${result.violations.length} violations restantes après auto-fix. Pipeline arrêté avant placement.`,
    };
  } catch (err) {
    if (!(err instanceof ErcServiceUnavailableError)) {
      log.warn({ err }, 'ERC service threw unexpected error');
    }
    return runDegradedErc(cached?.schema, schContent);
  }
}
