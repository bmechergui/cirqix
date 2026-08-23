# Handoff — `pcb-run-realtime`

- **Status:** `REVIEW`
- **Owner:** `Grok`
- **Reviewer:** `none`
- **Receiver:** `none`
- **Branch:** `feat/pcb-runs-foundations`
- **Worktree:** `C:\Users\Mechegui\Desktop\dev\cirqix`
- **Base commit:** `1ec4fe52e5c50c74b14deaac62f51f1e2c5511ce`
- **Content commit:** `uncommitted`
- **Updated UTC:** `2026-08-23T16:25:00Z`

## Objectif

Le suivi d'un run asynchrone utilise Supabase Realtime comme transport principal sur `pcb_run_events`. Le sondage HTTP (`GET /api/agent/runs/:runId/events`) reste le repli. Le client est alors prêt pour `CIRQIX_ASYNC_PIPELINE=1` (Redis + worker exigés). Le drapeau reste fail-closed dans le code.

## Critère de terminaison

`followRun` délivre les INSERT Realtime, déduplique par `seq`, retombe sur le sondage si la souscription échoue ou se coupe, s'arrête sur `done`/`error`/abort. La table est dans `supabase_realtime` avec `REPLICA IDENTITY FULL`. Les tests ciblés passent. `pnpm type-check` est vert. Le sous-module `kicad-tools` n'est pas stagé.

## Périmètre autorisé

### Chemins possédés

- `apps/web/src/features/workspace/lib/follow-run.ts`
- `apps/web/src/features/workspace/lib/follow-run-realtime.ts`
- `apps/web/src/features/workspace/lib/agent-client.ts`
- `apps/web/src/app/api/agent/lib/async-mode.ts`
- `apps/web/src/test/follow-run.test.ts`
- `apps/web/src/test/follow-run-realtime.test.ts`
- `packages/db/supabase/migrations/020_pcb_run_events_realtime.sql`
- `packages/db/tests/rls_isolation.sql`
- `.env.example`
- `PLAN.md`
- `CLAUDE.md`
- `docs/agents/handoffs/2026-08-22-pcb-run-realtime.md`

### Lecture seule

- `packages/db/supabase/migrations/019_pcb_runs.sql`
- `apps/web/src/app/api/agent/runs/[runId]/events/route.ts`
- `apps/web/src/app/api/agent/route.ts`
- `apps/web/src/shared/lib/supabase-browser.ts`

### Hors périmètre

- `services/kicad/kicad-tools/` (sous-module dirty, non possédé)
- Passage de `kct_route.py` en `Popen`
- Flip du défaut de `asyncPipelineEnabled` à `true`

## Modifications préexistantes non possédées

- `services/kicad/kicad-tools` — gitlink dirty / untracked — ne pas stager

## Décisions prises

- Realtime = transport principal ; sondage = repli et catch-up. Même contrat (`rowToEvent`).
- `CIRQIX_ASYNC_PIPELINE` reste explicite : un défaut `true` accepterait des jobs sans consommateur.
- Ne pas publier `pcb_runs` (heartbeats toutes les 30 s).
- Le filtre Realtime `run_id=eq.` n'est pas une frontière de sécurité : RLS `SELECT` de la migration 019 l'est.

## Travail réalisé

- `followRun` s'abonne aux INSERT `pcb_run_events` ; le sondage HTTP reste catch-up + filet (même `SUBSCRIBED`).
- Catch-up HTTP fusionné avec le tampon Realtime pour qu'un `done` live ne jette pas les lignes plus anciennes.
- `unsubscribe` dans un `finally`.
- Migration `020` : `REPLICA IDENTITY FULL`, publication du journal seulement, GRANT SELECT-only, InitPlan `(SELECT auth.uid())`.
- `CIRQIX_ASYNC_PIPELINE` documenté, toujours fail-closed.

## Fichiers modifiés

- `apps/web/src/features/workspace/lib/follow-run.ts` — Realtime + sondage
- `apps/web/src/features/workspace/lib/follow-run-realtime.ts` — souscription
- `apps/web/src/test/follow-run.test.ts` / `follow-run-realtime.test.ts`
- `packages/db/supabase/migrations/020_pcb_run_events_realtime.sql`
- `packages/db/tests/rls_isolation.sql` (AG/AH/AI) + `ci-scaffold.sql`
- `.env.example`, `CLAUDE.md`, `PLAN.md`, `async-mode.ts`, `agent-client.ts`

## Validations exactes

| Commande | Résultat | Date UTC |
|---|---|---|
| `pnpm --filter @cirqix/web exec vitest run src/test/follow-run.test.ts src/test/follow-run-realtime.test.ts` | 19 passed | 2026-08-23T16:21:31Z |
| `pnpm --filter @cirqix/web type-check` | 0 erreurs | 2026-08-23T16:22:00Z |

## Risques et blocages

- Migration `020` à appliquer sur l'instance Supabase (Realtime ne livrera rien tant que la publication n'est pas là ; le sondage tient).
- `CIRQIX_ASYNC_PIPELINE` reste à allumer là où Redis + worker tournent.

## Travail restant

- Commit, push, PR.
- Appliquer `020` en base.
- Allumer le drapeau sur l'environnement worker.

## Prochaine action atomique

Commit + push + PR, sans stager `services/kicad/kicad-tools`.

## Git

- **État initial du worktree:** `feat/pcb-runs-foundations` alignée origin ; dirty `services/kicad/kicad-tools` non possédé
- **État final du worktree:** (à remplir)
- **Commit:** `none`
- **PR:** `none`

## Journal de transfert

- `2026-08-22T12:00:00Z` — Grok revendique la tâche sur `feat/pcb-runs-foundations`.
