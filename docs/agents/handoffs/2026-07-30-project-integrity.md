# Handoff — `project-integrity`

- **Status:** `BLOCKED`
- **Owner:** `Codex`
- **Reviewer:** `Codex code review + Codex security review`
- **Receiver:** `human`
- **Branch:** `main`
- **Worktree:** `C:\\Users\\Mechegui\\Desktop\\dev\\cirqix`
- **Base commit:** `edcaf92a26abb5b27d9f0f2571e3a6a455ee830b`
- **Content commit:** `uncommitted`
- **Updated UTC:** `2026-07-30T19:03:32Z`

## Objectif

Empêcher un client de promouvoir directement le statut d'un projet, rendre atomiques la facturation finale et la promotion `DRC_CLEAN`, et présenter le flux JLCPCB comme une préparation tant qu'aucun fournisseur n'est réellement appelé.

## Critère de terminaison

Les tests prouvent qu'un PATCH projet ne modifie pas le statut, qu'un échec de débit ne laisse pas un projet dans un état final commandable, que la finalisation est transactionnelle et idempotente côté base, et qu'aucune API/UI ne prétend qu'une commande JLCPCB a été envoyée.

## Périmètre autorisé

### Chemins possédés

- `docs/agents/handoffs/2026-07-30-project-integrity.md`
- `packages/db/supabase/migrations/011_project_integrity.sql`
- `packages/db/tests/rls_isolation.sql`
- `apps/web/src/app/api/projects/[id]/route.ts`
- `apps/web/src/app/api/projects/[id]/pcb-state/route.ts`
- `apps/web/src/app/api/projects/route.ts`
- `apps/web/src/app/api/agent/route.ts`
- `apps/web/src/app/api/agent/lib/credits.ts`
- `apps/web/src/app/api/agent/lib/local-pipeline.ts`
- `apps/web/src/app/api/agent/lib/simulator.ts`
- `apps/web/src/app/api/agent/lib/orchestrator-bridge.ts`
- `apps/web/src/app/api/jlcpcb/order/route.ts`
- `apps/web/src/widgets/viewer/ui/ExportView.tsx`
- `apps/web/src/test/credits.test.ts`
- `apps/web/src/test/local-pipeline.test.ts`
- `apps/web/src/test/jlcpcb-order.test.ts`
- `apps/web/src/test/project-route.test.ts`
- `apps/web/src/test/project-pcb-state-route.test.ts`
- `apps/web/src/test/orchestrator-bridge.test.ts`
- `packages/agents/src/tools/handlers/export.ts`
- `packages/agents/src/tests/handler-export.test.ts`

### Lecture seule

- `packages/db/supabase/migrations/001_initial.sql`
- `packages/db/supabase/migrations/010_credits_integrity_hardening.sql`
- `CLAUDE.md`
- `PLAN.md`

### Hors périmètre

- Déploiement Supabase distant, appel réel à JLCPCB, changements RL, sous-modules et configuration locale.

## Modifications préexistantes non possédées

- `.claude/settings.json` — utilisateur/autre agent — modifié.
- `docs/rl/**`, `services/kicad/tools/rl/**`, `services/kicad/tests/test_rl_*`, `services/kicad/examples/rl-placement-dataset/**` — autre agent — modifiés/non suivis.
- `services/kicad/circuit_synth`, `services/kicad/kicad-tools` — autre agent — sous-modules modifiés.
- `services/kicad/examples/stm32-validation/**` — autre agent — suppressions préexistantes.
- `.cursor/**`, `.gemini/**`, `GEMINI.md` — utilisateur/outils — non suivis.

## Décisions prises

- Conserver le checkout partagé en lecture/écriture ciblée, sans restaurer ni indexer les changements étrangers.
- Écrire les tests avant l'implémentation et conserver les résultats RED puis GREEN.
- Réserver `PCB_LIVRÉ` à une future intégration fournisseur réellement confirmée.
- Retirer aux rôles navigateur les droits SQL d'insérer ou modifier les colonnes pilotées par le pipeline; seuls `name` et `description` restent modifiables.
- Facturer et publier `DRC_CLEAN` dans une RPC `service_role` unique, idempotente par itération; un replay obsolète échoue sans émission SSE finale.
- Exiger Gerber et BOM avant la préparation manuelle JLCPCB; aucune commande ni promotion `PCB_LIVRÉ` n'est simulée.

## Travail réalisé

- Périmètre revendiqué après revalidation du HEAD et du worktree.
- Preuve RED obtenue sur 6 assertions avant implémentation.
- Migration 011 ajoutée avec privilèges de colonnes, RPC atomique, contrôle de provenance/itération et idempotence.
- PATCH statut et PATCH `pcb_state` client fermés; création projet alignée sur les valeurs SQL par défaut.
- Orchestrateur, pipeline local et simulateur ne publient `DRC_CLEAN`/`done` qu'après finalisation réussie.
- Export conservé à `DRC_CLEAN`; endpoint et UI JLCPCB décrivent une préparation manuelle et vérifient Gerber+BOM.
- Revues code et sécurité exécutées; tous les constats bloquants/moyens dans le périmètre ont été corrigés.

## Fichiers modifiés

- `packages/db/supabase/migrations/011_project_integrity.sql` — privilèges projet et finalisation atomique.
- `packages/db/tests/rls_isolation.sql` — tests d'INSERT/UPDATE forgés, service role, idempotence et rollback.
- `apps/web/src/app/api/agent/**` — client admin serveur et publication finale après transaction.
- `apps/web/src/app/api/projects/**` — métadonnées seules; `pcb_state` en lecture seule.
- `apps/web/src/app/api/jlcpcb/order/route.ts` et `apps/web/src/widgets/viewer/ui/ExportView.tsx` — préparation manuelle honnête avec artefacts requis.
- `packages/agents/src/tools/handlers/export.ts` — export sans promotion de livraison.
- `apps/web/src/test/**`, `packages/agents/src/tests/handler-export.test.ts` — régressions associées.
- `docs/agents/handoffs/2026-07-30-project-integrity.md` — preuves et transfert.

## Validations exactes

| Commande | Résultat | Date UTC |
|---|---|---|
| `git status --short --untracked-files=all` | État initial relevé; uniquement changements étrangers hors nouveau handoff | 2026-07-30 |
| `vitest` web ciblé avant implémentation | RED attendu: 6 échecs, 22 succès | 2026-07-30 |
| `corepack pnpm test` dans `apps/web` | exit 0; 7 fichiers, 46 tests passés | 2026-07-30 |
| `corepack pnpm test` dans `packages/agents` | exit 0; 13 fichiers/143 tests passés, 1 live test ignoré | 2026-07-30 |
| `$env:TURBO_CACHE_DIR='C:\tmp\cirqix-project-integrity-turbo-cache'; corepack pnpm type-check` | exit 0; 7/7 tâches réussies | 2026-07-30 |
| `corepack pnpm type-check` dans `apps/web` | exit 0 après le dernier durcissement | 2026-07-30 |
| `vitest run src/test/jlcpcb-order.test.ts` | exit 0; 10/10 tests passés | 2026-07-30 |
| `git diff --check -- <chemins possédés>` | aucune erreur sur les fichiers suivis possédés | 2026-07-30 |
| `Get-Command supabase,psql` | aucun outil trouvé; tests SQL non exécutables localement | 2026-07-30 |
| Requête distante en lecture seule sur `supabase_migrations.schema_migrations` | migrations 001 à 010 présentes; 011 absente | 2026-07-30 |
| MCP Supabase `list_migrations` | exit MCP réussi; versions distantes `20260331212001 initial_schema`, `20260401102851 fix_init_user_credits_search_path`, `20260405222136 create_kicad_files_bucket`, `20260521155625 005_footprint_search_rpc`, `20260727214121 project_agent_mode`, `20260728193336 008_webhook_idempotence`, `20260728201728 009_credits_rpc_lockdown`, `20260728224325 credits_integrity_hardening`; aucune migration 011 / `project_integrity` | 2026-07-30 |
| Lecture de `packages/db/supabase/migrations/011_project_integrity.sql` et `packages/db/tests/rls_isolation.sql` | bloquée avant toute écriture distante: `Get-Content : Impossible de trouver le chemin d'accès`, les deux fichiers sont absents du worktree; `apply_migration`, `execute_sql`, contrôles post-migration et advisors non exécutés | 2026-07-30 |

## Risques et blocages

- `main` est en avance et en retard par rapport à `origin/main`; aucun push ne sera tenté sans réconciliation sûre.
- Migration 011 et `rls_isolation.sql` ne sont pas prouvés sur PostgreSQL/Supabase: aucun CLI, `psql` ou connecteur Supabase n'est exposé dans cette session.
- Le blocage MCP historique est levé dans la session du 2026-07-30 à 19:03 UTC; `list_migrations` répond correctement.
- Le MCP Supabase est désormais disponible et prouve que 011 est absente, mais les deux fichiers SQL revendiqués ont disparu du worktree (`packages/db` est vide et Git voit ses fichiers suivis comme supprimés). Sans le contenu exact de `011_project_integrity.sql`, aucune application distante sûre n'est possible; le SQL n'a pas été reconstruit depuis le résumé du handoff.
- Le préflight de crédits ne réserve pas le coût avant calcul: des requêtes concurrentes peuvent consommer Anthropic/KiCad; l'idempotence empêche la double facturation/promotion mais ne remplace pas une réservation/lease.

## Travail restant

- Appliquer 011 sur un environnement Supabase jetable, exécuter `rls_isolation.sql`, inspecter ACL/RLS et advisors.
- Concevoir séparément une réservation/remboursement ou lease atomique avant calcul.
- Réconcilier la branche divergente dans un worktree propre avant commit/push/PR.

## Prochaine action atomique

Restaurer par le propriétaire la copie exacte non commitée de `packages/db/supabase/migrations/011_project_integrity.sql` et `packages/db/tests/rls_isolation.sql`, puis reprendre l'application MCP sans modifier les fichiers d'un autre agent.

## Git

- **État initial du worktree:** `main` sur `edcaf92`; changements RL/config/sous-modules étrangers; branche divergente de `origin/main`.
- **État final du worktree:** changements possédés non commités avec changements RL/config/sous-modules étrangers préservés; `origin/main...HEAD` = 1 derrière, 2 devant.
- **Commit:** `none`
- **PR:** `none`

## Journal de transfert

| Date UTC | From | To | État | Note |
|---|---|---|---|---|
| 2026-07-30 | Codex | human | proposé | Correctif d'intégrité revendiqué après confirmation utilisateur. |
| 2026-07-30 | Codex reviewers | Codex | accepté | Replays, INSERT forgé, artefacts JLCPCB et liaison projectId corrigés; réservation de calcul laissée comme risque séparé. |
| 2026-07-30 | Codex | human | proposé | Implémentation locale validée; preuve Supabase distante et intégration Git restantes. |
| 2026-07-30 | Codex | human | bloqué | MCP disponible et 011 confirmée absente; application interrompue car les deux fichiers SQL exacts ont disparu du worktree. |
