# Handoff — `2026-07-28-credits-security-hardening`

- **Status:** `DONE`
- **Owner:** `Codex`
- **Reviewer:** `Codex code review + security review` (lecture seule)
- **Receiver:** `human`
- **Branch:** `main`
- **Worktree:** `C:\Users\Mechegui\Desktop\dev\cirqix`
- **Base commit:** `dd0650190342d8473482e202a344a9ef4618fbd5`
- **Content commit:** `uncommitted`
- **Updated UTC:** `2026-07-28T22:44:33Z`

Le receiver relève le head Git courant local et distant au moment de la
réception ; ne pas le recopier ici, car le commit de ce fichier le périmerait.

## Objectif

Fermer les chemins permettant de créer ou modifier des crédits hors des RPC
autorisées, refuser les montants invalides et aligner chaque pipeline sur son
coût réel de 8,5 crédits.

## Critère de terminaison

Les tests prouvent qu'un utilisateur authentifié ne peut ni appeler
`add_credits`, ni muter directement les tables, ni s'auto-créditer via un débit
invalide ; tous les chemins pipeline utilisent la RPC ; les tests SQL sont
exécutés sur PostgreSQL/Supabase et la migration est vérifiée sur le distant.

## Périmètre autorisé

### Chemins possédés

- `packages/db/supabase/migrations/010_credits_integrity_hardening.sql`
- `packages/db/tests/rls_isolation.sql`
- `apps/web/src/app/api/agent/lib/credits.ts`
- `apps/web/src/app/api/agent/lib/local-pipeline.ts`
- `apps/web/src/app/api/agent/lib/simulator.ts`
- `apps/web/src/app/api/agent/route.ts`
- `apps/web/src/test/credits.test.ts`
- `apps/web/src/test/local-pipeline.test.ts`
- `docs/agents/handoffs/2026-07-28-credits-security-hardening.md`

### Lecture seule

- `packages/db/supabase/migrations/001_initial.sql`
- `packages/db/supabase/migrations/006_security_hotfix.sql`
- `packages/db/supabase/migrations/009_credits_rpc_lockdown.sql`
- `apps/web/src/app/api/webhooks/lemon-squeezy/route.ts`
- `docs/agents/handoffs/2026-07-27-billing-idempotence.md`

### Hors périmètre

- Les autres fichiers billing/logo/pricing attribués à Kimi.
- Tout `services/kicad/**` et toute modification préexistante du worktree.
- Application distante sans accès administrateur explicitement disponible.

## Modifications préexistantes non possédées

- Tous les changements visibles dans `git status` hors chemins possédés —
  utilisateur, Kimi ou Claude Code — préservés.
- Migration 009 — travail Kimi transféré pour analyse, conservé intact car déjà
  annoncé comme appliqué à distance ; le correctif est donc une migration 010.

## Décisions prises

- Migration 010 séparée pour corriger les déploiements ayant déjà enregistré 009.
- Clients authentifiés : lecture seule des tables, débit uniquement via RPC.
- RPC client bornée à `8.5`, action `full_pcb_pipeline` et projet appartenant à
  l'utilisateur ; précision maximale de deux décimales pour tous les montants.
- Débit local/simulateur avant persistance du statut final `DRC_CLEAN`.
- Les erreurs de débit ne déclenchent jamais le fallback local.

## Travail réalisé

- Ajout des validations de montant/action/projet et `search_path = ''`.
- Révocation des mutations directes et remplacement des policies `FOR ALL` par
  des policies `SELECT` uniquement.
- Durcissement de `init_user_credits` et contrainte non négative sur les futures
  écritures de balance (`NOT VALID` pour ne pas bloquer sur un éventuel legacy).
- Seuil d'entrée corrigé de 0,5 à 8,5 crédits.
- Suppression du clamp direct à zéro ; erreurs RPC propagées.
- Orchestrateur, pipeline local et simulateur débitent tous via la même RPC.
- Tests SQL réparés : vrais rôles PostgreSQL, transaction avec rollback, montants
  négatif/zéro/minuscule, cross-user, mutations directes et RLS waitlist.
- Revues code et sécurité exécutées ; leurs constats sur local/simulateur,
  précision, trigger et ordre DRC/débit ont été corrigés.

## Fichiers modifiés

- `packages/db/supabase/migrations/010_credits_integrity_hardening.sql` — RPC,
  privilèges, RLS, trigger et contrainte de balance.
- `packages/db/tests/rls_isolation.sql` — tests de sécurité exécutables.
- `apps/web/src/app/api/agent/lib/credits.ts` — débit unique et helpers de garde.
- `apps/web/src/app/api/agent/{route.ts,lib/local-pipeline.ts,lib/simulator.ts}` —
  seuil et débit cohérents sur les trois chemins.
- `apps/web/src/test/{credits.test.ts,local-pipeline.test.ts}` — régressions.
- Ce handoff — propriété, décisions, validations et risques.

## Validations exactes

| Commande | Résultat | Date UTC |
|---|---|---|
| `corepack pnpm --filter @cirqix/web exec vitest run src/test/credits.test.ts` avant implémentation | `4 failed, 1 passed` — RED attendu | `2026-07-28T22:05:24Z` |
| `corepack pnpm --filter @cirqix/web exec vitest run src/test/local-pipeline.test.ts` avant correction | `1 failed, 6 passed` — RED attendu | `2026-07-28T22:13:08Z` |
| `corepack pnpm --filter @cirqix/web test` | `37 passed, 4 fichiers` | `2026-07-28T22:21:03Z` |
| `corepack pnpm type-check` | `7/7 successful, 0 erreur` | `2026-07-28T22:21:03Z` |
| `git diff --check -- <chemins possédés>` | code 0 ; avertissements CRLF seulement | `2026-07-28T22:21:03Z` |
| MCP `apply_migration(name = credits_integrity_hardening, query = 010_credits_integrity_hardening.sql)` | `success: true`; migration distante `20260728224325` enregistrée | `2026-07-28T22:43:25Z` |
| MCP `execute_sql` avec `packages/db/tests/rls_isolation.sql` sans la méta-commande psql `\\set ON_ERROR_STOP on` | première tentative rejetée `42601` à cause de `\\set`; seconde tentative : code SQL exécuté sans erreur, résultat `[]`, transaction rollbackée | `2026-07-28T22:43:53Z` |
| Vérification catalogues ACL/RLS/contraintes via MCP `execute_sql` | RLS actif sur `credits` et `credit_transactions`; policies `SELECT` propriétaire uniquement; `authenticated` a `SELECT` mais aucun `INSERT/UPDATE/DELETE`; grants RPC et `search_path=''` conformes; 0 solde négatif; fixtures test absentes après rollback | `2026-07-28T22:44:09Z` |
| MCP `get_advisors(security)` après migration | aucun constat nouveau sur `add_credits`, `init_user_credits` ou les policies crédits; warning attendu sur `deduct_credits` exposée à `authenticated`; constats hors périmètre conservés | `2026-07-28T22:44:24Z` |
| MCP `get_advisors(performance)` après migration | anciens warnings `auth_rls_initplan` supprimés pour `credits` et `credit_transactions`; constats restants hors périmètre | `2026-07-28T22:44:24Z` |
| Vérification outils (`supabase`, `psql`, `docker`, WSL) | tous indisponibles ; aucune distribution WSL | `2026-07-28T22:24:00Z` |
| Inspection configuration sans afficher les valeurs | MCP Supabase déclaré ; URL/anon configurées ; service_role vide ; aucun outil MCP chargé | `2026-07-28T22:25:00Z` |
| RPC distante anon `add_credits` avec UUID inexistant | `HTTP 401`, code `42501`, `permission_denied`, aucune écriture | `2026-07-28T22:28:00Z` |
| RPC distante anon `deduct_credits` avec UUID inexistant | `HTTP 401`, aucune écriture ; corps non exposé par le client PowerShell | `2026-07-28T22:28:00Z` |

## Risques et blocages

- Risque élevé restant : le solde est contrôlé avant le travail et débité à la
  fin. Deux requêtes concurrentes peuvent consommer des ressources ; une seule
  sera débitée. La correction propre exige une réservation atomique avec
  remboursement contrôlé, chantier distinct.
- La contrainte `credits_balance_nonnegative` est `NOT VALID` : elle protège les
  nouvelles écritures. L'audit distant trouve 0 solde `NULL` ou négatif, mais sa
  validation globale doit rester une migration explicite séparée.
- `anon` conserve le privilège table `SELECT` hérité sur les deux tables de
  crédits, mais aucune policy ne cible `anon` : RLS retourne donc zéro ligne.
  Un futur durcissement peut révoquer ce privilège en défense en profondeur.
- `main` est `ahead 1, behind 4` et le worktree contient de nombreux changements
  multi-agents ; commit/push non sûrs sans isoler ces fichiers.

## Travail restant

- Concevoir la réservation atomique des crédits avant pipeline.
- Ajouter une migration séparée pour valider
  `credits_balance_nonnegative` et éventuellement révoquer `SELECT` à `anon`.

## Prochaine action atomique

Concevoir une RPC de réservation atomique des 8,5 crédits avant pipeline avec
remboursement contrôlé en cas d'échec.

## Git

- **État initial du worktree:** `main...origin/main [ahead 1, behind 2]`, sale,
  modifications multi-agents préexistantes.
- **État final du worktree:** `main...origin/main [ahead 1, behind 4]`, fichiers
  possédés non commités et changements étrangers préservés.
- **Commit:** `none` — branche divergente et worktree partagé.
- **PR:** `none`

## Journal de transfert

| Date UTC | From | To | État | Note |
|---|---|---|---|---|
| `2026-07-28T22:03:08Z` | `Kimi / human` | `Codex` | `accepté` | `Transfert du chantier sécurité crédits, isolé du reste du billing.` |
| `2026-07-28T22:21:59Z` | `Codex` | `Codex` | `mise à jour` | `Hotfix local validé ; migration et tests SQL bloqués par l'absence d'outils DB.` |
| `2026-07-28T22:29:47Z` | `Codex` | `Codex` | `mise à jour` | `Smoke test anon distant refusé 401 sur les deux RPC ; migration 010 toujours non appliquée faute d'accès admin/MCP.` |
| `2026-07-28T22:33:07Z` | `Codex` | `human` | `blocage` | `Troisième vérification : aucun outil Supabase chargé. Authentifier le MCP puis redémarrer/recharger réellement la session.` |
| `2026-07-28T22:44:33Z` | `human` | `Codex` | `reprise` | `MCP Supabase disponible ; migration 010 appliquée, tests SQL et contrôles distants exécutés.` |
| `2026-07-28T22:44:33Z` | `Codex` | `human` | `terminé` | `ACL/RLS conformes au modèle lecture seule + RPC, advisors sécurité/performance collectés ; chantier clos.` |
