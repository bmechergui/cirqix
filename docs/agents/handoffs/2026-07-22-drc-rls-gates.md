# Handoff — `2026-07-22-drc-rls-gates`

- **Status:** `REVIEW`
- **Owner:** `Codex`
- **Reviewer:** `code-reviewer sub-agent + security-reviewer sub-agent`
- **Receiver:** `none`
- **Branch:** `fix/drc-rls-gates`
- **Worktree:** `C:\tmp\cirqix-drc-rls-gates`
- **Base commit:** `7da72fe5f05df261bb81489fc203394e147d63e4`
- **Content commit:** `6d573fe913a6979a286e7b46174158e385b9c578`
- **Updated UTC:** `2026-07-22T22:46:57Z`

## Objective

Prevent non-certified PCB release or manufacturing intent, client-side
mutation of credits or manufacturing status, and replayed Lemon Squeezy
payment credits.

## Completion criteria

`DRC_CLEAN` requires non-skipped official KiCad evidence. Browser clients
cannot certify boards or mutate balances. Payment processing is authenticated
and idempotent. Pipeline billing uses a durable reservation and one idempotent
final debit. Full SQL and KiCad execution evidence remains required before
promotion from `REVIEW` to `DONE`.

## Authorized scope

All changed paths are owned by this handoff: web agent/order/project/webhook
routes and export UI; agent DRC/export/state handlers and tests; DB migration
and RLS regression test; shared PCB types; and KiCad DRC router/tool/test.

## Pre-existing changes not owned

None in this isolated worktree at creation.

## Work completed

- Made DRC fail closed when `kicad-cli` is unavailable, skipped, simulated, or
  stale; a content mutation invalidates prior DRC evidence.
- Blocked exports and manufacturing intents unless the cached state contains a
  non-skipped `kicad-cli` DRC pass. Failed or skipped exports remain
  `ROUTING_DONE` and no longer fabricate Gerbers, quotes, or delivery status.
- Added migration `007_certification_and_payment_guards.sql`: column-level
  project privileges, no client credit/event writes, service-only RPCs,
  payment event idempotency, Lemon subscription mapping, and manufacturing
  intent persistence.
- Hardened Lemon Squeezy verification (required HMAC secret, `meta.custom_data`
  user mapping, resource-qualified event identity, configured IDs only).
- Replaced pipeline pre-debit/refund with durable non-debited reservations:
  concurrent holds are serialized, stale holds expire, successful completion
  debits exactly once, and failures release the hold.
- Reworded the JLCPCB interface: it records an internal intent only and never
  claims supplier submission or automatic email confirmation.

## Changed files

- `apps/web/src/app/api/agent/{route.ts,lib/credits.ts,lib/credits.test.ts,lib/local-pipeline.ts,lib/orchestrator-bridge.ts,lib/simulator.ts}`
- `apps/web/src/app/api/jlcpcb/order/{route.ts,route.test.ts}`
- `apps/web/src/app/api/projects/{route.ts,[id]/route.ts,[id]/pcb-state/route.ts}`
- `apps/web/src/app/api/webhooks/lemon-squeezy/{route.ts,route.test.ts}`
- `apps/web/src/widgets/viewer/ui/ExportView.tsx`
- `packages/agents/src/tools/{shared.ts,handlers/drc.ts,handlers/export.ts,handlers/gen-pcb.ts,handlers/reason.ts,handlers/routing.ts}`
- `packages/agents/src/tests/drc-gate.test.ts`
- `packages/db/supabase/migrations/007_certification_and_payment_guards.sql`
- `packages/db/tests/rls_isolation.sql`
- `packages/types/src/index.ts`
- `services/kicad/{routers/drc.py,tools/drc.py,tests/test_drc_auto.py}`

## Validation evidence

| Command | Result |
|---|---|
| `corepack pnpm --filter @cirqix/agents test` | PASS — 5 files, 25 tests |
| `corepack pnpm --filter @cirqix/web test` | PASS — 3 files, 8 tests |
| `corepack pnpm --filter @cirqix/types type-check` | PASS |
| `corepack pnpm --filter @cirqix/agents type-check` | PASS |
| `corepack pnpm --filter @cirqix/web type-check` | PASS |
| `python -c "compile(...)"` for the 3 changed KiCad Python files | PASS — `PYTHON_SYNTAX_OK` |
| `python -m pytest services/kicad/tests/test_drc_auto.py` | BLOCKED — `No module named pytest` |
| `corepack pnpm type-check` | BLOCKED outside owned packages — `@cirqix/db` cannot resolve `@cirqix/config-typescript/tsconfig.base.json` and reports TypeScript 6 `baseUrl` deprecation |
| `git diff --check` and `git diff --cached --check` | PASS |
| SQL RLS regression | NOT RUN — no local `docker` or `supabase` CLI / Postgres stack |

## Reviews

- Code review: no blocker after durable reservation change. Follow-up coverage
  for release/expiry route paths is desirable but non-blocking.
- Security review: no bypass found. Reservation tables and all reservation,
  payment, credit, and manufacturing RPCs are service-role only; real SQL
  execution remains pending.

## Risks and blockers

- Migration 007 and `packages/db/tests/rls_isolation.sql` have not executed on
  a real Supabase/Postgres stack in this environment.
- `pytest`, Docker, Supabase CLI, and `kicad-cli` are unavailable locally, so
  the official KiCad DRC integration has syntax/test-fixture evidence only.

## Remaining work

Apply migration 007 in an isolated Supabase environment and execute the SQL
RLS regression and KiCad DRC test suite before production deployment.

## Next atomic action

Provision a local or staging Supabase stack, apply migration 007, then run
`psql "$LOCAL_POSTGRES_URL" -f packages/db/tests/rls_isolation.sql`.

## Git

- **Content commit:** `6d573fe913a6979a286e7b46174158e385b9c578` (`fix: enforce certified pcb release gates`)
- **Documentation commit:** pending
- **PR:** pending

## Transfer log

| Date UTC | From | To | State | Note |
|---|---|---|---|---|
| `2026-07-22T21:26:01Z` | user | Codex | accepted | Isolated fix authorized after broad audit. |
| `2026-07-22T22:46:57Z` | Codex | reviewers | review | DRC/RLS/payment/manufacturing corrections committed; two independent reviews report no remaining blocker. |
