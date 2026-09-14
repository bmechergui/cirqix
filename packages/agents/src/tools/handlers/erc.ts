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

interface ViolationErc { readonly severity?: unknown }

/**
 * Les violations de sévérité ERREUR — les seules qui arrêtent le pipeline.
 *
 * ⚠️ Les AVERTISSEMENTS ne bloquent pas, et c'est mesuré. Sur le schéma NE555
 * du 2026-09-14, 29 des 31 violations restantes sont `lib_symbol_issues` et
 * `footprint_link_issues` : le conteneur n'a pas de table de bibliothèques.
 * Bloquer dessus arrêterait toutes les cartes pour du bruit d'environnement.
 */
function compterErreurs(violations: readonly ViolationErc[] | undefined): number {
  return (violations ?? []).filter((v) => String(v?.severity ?? '') === 'error').length;
}

/**
 * Le verdict de l'ERC, RENDU EXÉCUTOIRE.
 *
 * ⚠️ Mesuré le 2026-09-14 : le handler rendait `status: 'success'` avec la note
 * « Pipeline arrêté avant placement » alors que RIEN ne l'arrêtait —
 * `run-driver.ts` ne s'interrompt que sur `status: 'error'`, et l'orchestrateur
 * est un modèle qui lit cette note. Un schéma portant 15 erreurs ERC allait au
 * placement, au routage, au DRC et à l'export, et ressortait `PCB_LIVRÉ`.
 * Une phrase qui annonce un arrêt qui n'a pas lieu est pire qu'une phrase
 * absente : elle rassure.
 */
function verdictErc(
  base: Record<string, unknown>,
  violations: readonly ViolationErc[] | undefined,
  moteur: string,
): Record<string, unknown> {
  const erreurs = compterErreurs(violations);
  if (erreurs === 0) return base;
  const cause = `${erreurs} erreur(s) ERC (${moteur}) — le schéma n'est pas valide`;
  return {
    ...base,
    status: 'error',
    error: cause,
    note: `ERC — ${cause}. Pipeline arrêté avant placement ; corrige le schéma.`,
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
  return verdictErc({
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
      : `ERC TypeScript — ${fallback.violations.length} violation(s), aucune bloquante.`,
  }, fallback.violations, 'ERC TypeScript');
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
    return verdictErc({
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
        : `ERC — ${result.violations.length} violation(s) restantes après auto-fix, aucune bloquante.`,
    }, result.violations, 'kicad-cli');
  } catch (err) {
    if (!(err instanceof ErcServiceUnavailableError)) {
      log.warn({ err }, 'ERC service threw unexpected error');
    }
    return runDegradedErc(cached?.schema, schContent);
  }
}
