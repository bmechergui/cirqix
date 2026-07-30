# Handoff — `project-integrity-hardening`

- **Status:** `REVIEW`
- **Owner:** `Codex`
- **Reviewer:** `Codex code review + Codex security review`
- **Receiver:** `human`
- **Branch:** `fix/project-integrity-hardening`
- **Worktree:** `C:\\tmp\\cirqix-project-integrity-fix`
- **Base commit:** `3c3ca8ec0e4e009a13fb8f2bcff93787941f5313`
- **Content commit:** `uncommitted`
- **Updated UTC:** `2026-07-30T20:09:01Z`

## Objectif

Fermer la mutation directe des états projet, rendre atomiques la facturation et la publication `DRC_CLEAN`, verrouiller l'upsert communautaire de footprints et maintenir JLCPCB en préparation manuelle honnête.

## Périmètre réalisé

- ACL/RLS `projects` séparées par opération; `authenticated` peut lire/supprimer ses projets, insérer `user_id/name/description` et modifier seulement `name/description`.
- RPC `finalize_pipeline_success` service-only: contrôle du propriétaire et de l'état, verrou projet, anti-rejeu, débit de 8,5 crédits et publication finale dans une transaction.
- `deduct_credits` et `upsert_community_footprint` limités à `service_role`.
- États intermédiaires persistés côté serveur sans avancer `iteration_count`; aucun `done` si le DRC n'est pas propre.
- Endpoints client de mutation `status`/`pcb_state` supprimés.
- Flux JLCPCB aligné sur une préparation manuelle sans commande distante ni promotion `PCB_LIVRÉ`.
- Migration distante appliquée via MCP Supabase.
- Aucun fichier RL modifié.

## Fichiers modifiés

- `README.md`
- `apps/web/src/app/api/agent/lib/{credits,local-pipeline,orchestrator-bridge,simulator}.ts`
- `apps/web/src/app/api/agent/route.ts`
- `apps/web/src/app/api/jlcpcb/order/route.ts`
- `apps/web/src/app/api/projects/route.ts`
- `apps/web/src/app/api/projects/[id]/route.ts`
- `apps/web/src/app/api/projects/[id]/pcb-state/route.ts`
- `apps/web/src/widgets/viewer/ui/ExportView.tsx`
- `apps/web/src/test/{credits,jlcpcb-order,local-pipeline,orchestrator-bridge,project-route,project-pcb-state-route}.test.ts`
- `packages/agents/src/tools/handlers/export.ts`
- `packages/agents/src/tests/handler-export.test.ts`
- `packages/db/supabase/migrations/011_project_integrity.sql`
- `packages/db/tests/rls_isolation.sql`
- ce handoff.

## Décisions et revues

- Worktree isolé pour préserver le checkout partagé et tous les fichiers RL.
- TDD: première exécution rouge avec 8 échecs attendus, puis implémentation.
- Première revue: NO-GO sur le compteur d'itération, l'accès auth à `deduct_credits` et le faux `done`; les trois défauts ont été corrigés.
- Deuxième revue code: GO. Revue sécurité finale: GO pour application distante.
- Faiblesse UX acceptée: le `requestRef` de préparation JLCPCB n'est pas persisté; aucun effet financier ou fournisseur n'en dépend.

## Validations exactes

| Commande / outil | Résultat exact |
|---|---|
| Tests RED ciblés | 4 fichiers en échec; 8 tests échoués, 7 réussis, conformément aux nouveaux invariants |
| `vitest` ciblé final web | 6 fichiers réussis; 33/33 tests réussis |
| `pnpm --filter @cirqix/web test` | 7 fichiers réussis; 46/46 tests réussis |
| `vitest packages/agents/src/tests/handler-export.test.ts` | 1 fichier réussi; 9/9 tests réussis |
| `pnpm type-check` | 7/7 tâches réussies |
| `git diff --check` | code 0; aucune erreur whitespace |
| MCP `list_migrations` avant application | dernière migration `20260728224325 credits_integrity_hardening`; aucune 011 |
| 1re tentative `apply_migration` | refusée, rien appliqué: `42601 syntax error at or near "Exit" (LINE 4)`; préfixe shell détecté |
| MCP `list_migrations` après refus | historique inchangé, aucune 011 |
| MCP `apply_migration` avec le contenu SQL exact | `{"success":true}` |
| MCP `execute_sql` avec `packages/db/tests/rls_isolation.sql` exact | succès; résultat `[]`; transaction terminée par `ROLLBACK` |
| MCP contrôle RLS | `projects_select_own`, `projects_insert_own`, `projects_update_own`, `projects_delete_own`, toutes limitées à `authenticated` avec ownership |
| MCP contrôle ACL | table auth: `SELECT`, `DELETE`; colonnes auth INSERT: `user_id,name,description`; UPDATE: `name,description`; colonnes pipeline en lecture seule |
| MCP contrôle fonctions | `finalize_pipeline_success`, `deduct_credits`, `upsert_community_footprint`: `SECURITY DEFINER`, `search_path=""`, anon/auth execute=false, service execute=true |
| MCP historique final | `20260730200752 project_integrity` présent |
| MCP index | `idx_credit_transactions_project_id` présent |

## Advisors Supabase post-migration

### Security

- 1 INFO: `processed_webhook_events` a RLS sans policy, intentionnellement service-only.
- 9 WARN restants: extension `vector` dans `public`; waitlist anon INSERT `WITH CHECK (true)`; `rls_auto_enable` exécutable anon/auth; deux RPC de recherche footprint `SECURITY DEFINER` exécutables anon/auth; protection des mots de passe compromis désactivée.
- Les alertes concernant `update_updated_at`, `upsert_community_footprint`, `deduct_credits` et `finalize_pipeline_success` ne sont pas présentes.

### Performance

- 4 WARN `auth_rls_initplan`, tous sur les policies `footprints` historiques.
- 6 INFO `unused_index`, dont le nouvel index `idx_credit_transactions_project_id` attendu immédiatement après création.
- L'alerte d'index FK manquant sur `credit_transactions.project_id` et les alertes initplan `projects` ne sont plus présentes.

## Risques restants

- Aucun test end-to-end avec un vrai run KiCad/orchestrateur n'a été exécuté dans cette tâche.
- Les advisors historiques listés ci-dessus restent à traiter dans des migrations distinctes.
- Le `requestRef` JLCPCB est éphémère et sert seulement d'accusé de readiness; aucune commande n'est envoyée.

## Git

- **État initial:** propre sur `3c3ca8e`.
- **État actuel:** modifications uniquement dans les chemins revendiqués; aucun fichier RL.
- **Commit:** `none`
- **PR:** `none`

## Prochaine action atomique

Créer le commit de la branche, pousser et ouvrir la PR après une dernière vérification du diff.

## Journal de transfert

| Date UTC | From | To | État | Note |
|---|---|---|---|---|
| 2026-07-30T19:42:44Z | human | Codex | accepté | Correctif d'intégrité autorisé après audit NO-GO. |
| 2026-07-30T20:09:01Z | Codex | reviewers | GO | Revues code et sécurité finales sans bloquant. |
| 2026-07-30T20:09:01Z | Codex | human | REVIEW | Migration distante et validations terminées; commit/PR restent à créer. |
