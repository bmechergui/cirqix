# Handoff — `2026-07-27-billing-idempotence`

- **Status:** `REVIEW`
- **Owner:** `Kimi`
- **Reviewer:** `Claude Code` (à la demande, lecture seule)
- **Receiver:** `human` (merge PR #76)
- **Branch:** `feat/billing-idempotence` (dédiée — décision utilisateur 2026-07-28)
- **Worktree:** `C:\tmp\cirqix-billing-idempotence`
- **Base commit:** `0f1e1df` (`origin/main`)
- **Content commit:** `8dc56d6`
- **Updated UTC:** `2026-07-28T22:35:30Z`

Le receiver relève le head Git courant local et distant au moment de la
réception ; ne pas le recopier ici, car le commit de ce fichier le périmerait.

## Objectif

Terminer l'étape 4.4 de `PLAN.md` (Paiement Lemon Squeezy) : le webhook
(`/api/webhooks/lemon-squeezy`), la page billing, la vérification HMAC et les
RPC crédits existent déjà — il manque **l'idempotence** (action 4 du PLAN :
« vérifier transaction_id avant insert ») et toute couverture de test du
webhook, qui est un chemin de paiement. Un retry Lemon Squeezy de
`order_created` crédite aujourd'hui deux fois le même pack.

## Critère de terminaison

Tests webhook verts (signature, JSON, user_id, top-up, subscription, replay
dédupliqué), `pnpm type-check` 0 erreur, migration 008 idempotente écrite.

## Périmètre autorisé

### Chemins possédés (Kimi)

- `apps/web/src/app/api/webhooks/lemon-squeezy/route.ts`
- `apps/web/src/test/lemon-squeezy-webhook.test.ts` (nouveau)
- `packages/db/supabase/migrations/008_webhook_idempotence.sql` (nouveau)
- `.env.example` (documentation des variables LS_* déjà consommées par le code)
- `packages/db/supabase/migrations/009_credits_rpc_lockdown.sql` (nouveau,
  ajout 2026-07-28 — lockdown des RPC crédits, décision utilisateur « ok »)
- `docs/agents/handoffs/2026-07-27-billing-idempotence.md` (ce fichier)
- Ajout 2026-07-27 (tarification Pro 29€ / Pro Max 99€, décision utilisateur) :
  - `apps/web/src/app/(dashboard)/dashboard/billing/page.tsx`
  - `apps/web/src/shared/lib/marketing-content.ts`
  - `README.md`
  - `.agents/skills/cirqix-credits/SKILL.md`, `.claude/skills/cirqix-credits/SKILL.md`
- Ajout 2026-07-27 (logo : « Layrix » → « Cirqix », signalé par l'utilisateur) :
  - `apps/web/public/logo.svg`
  - `docs/logo/logo.svg`
  - Icône circuit « L » → « C » (demande utilisateur) : `apps/web/public/icone.svg`,
    `docs/logo/icone.svg`, `apps/web/src/app/icon.svg` (favicon)

### Lecture seule

- `apps/web/src/app/(dashboard)/dashboard/billing/page.tsx`
- `packages/db/supabase/migrations/001_initial.sql`, `006_security_hotfix.sql`
- `apps/web/src/shared/lib/supabase-server.ts`

### Hors périmètre

- Tout `services/kicad/**`, `packages/agents/**`, `apps/web/src/app/api/agent/**`,
  `apps/web/src/app/api/jlcpcb/**`, `CLAUDE.md`, `PLAN.md` — chantier actif de
  Claude Code (handoff `2026-07-19-routage-100-industriel`).
- Toute mise à jour de gitlink, toute commande `git commit/push` (décision
  utilisateur en fin de tâche).

## Modifications préexistantes non possédées

- `.claude/settings.json` (modifié), `.cursor/`, `.gemini/`, `GEMINI.md`
  (untracked) — autres sessions, ne pas toucher.
- `services/kicad/tools/placement.py` (modifié), suppressions dans
  `services/kicad/examples/stm32-validation/` — chantier Claude en cours.

## Décisions prises

- **Branche partagée, fichiers disjoints** : Claude Code est actif dans ce
  worktree ; créer une branche ou un worktree dédié perturberait sa session.
  Règle dure respectée : jamais le même fichier simultanément. Le commit de mes
  fichiers (et la stratégie de branche/PR) sera tranché par l'utilisateur.
- **Clé d'idempotence** : `event_name:data.id` pour `order_created` /
  `subscription_created` (ids uniques par achat/abonnement) ;
  `event_name:data.id:sha256(body)[:16]` pour `subscription_renewed` (l'id
  abonnement est constant d'un renouvellement à l'autre — le corps change).
  Un retry renvoie le même corps → même clé → dédupliqué.
- **Marker avant traitement, suppression sur échec** : insert de la clé d'abord
  (conflit PK = doublon → 200 sans traitement) ; si le crédit échoue ensuite,
  le marker est supprimé avant de renvoyer 500 pour que le retry LS aboutisse.
- **Fail-closed (2026-07-28)** : secret absent → 500 (HMAC à clé vide
  forgeable) ; erreur d'insert du marker ≠ 23505 → 500 sans crédit (traiter
  sans marker = double crédit au retry LS). LS retente sur 5xx, donc aucun
  événement légitime n'est perdu.

## Travail réalisé

- **Lockdown RPC crédits — migration 009 (2026-07-28)** : les advisors ont
  révélé que la base distante exécutait encore les versions 001 de
  `add_credits` / `deduct_credits` — SECURITY DEFINER, SANS garde, EXECUTE
  explicite pour anon + authenticated (la 006 n'a jamais été appliquée en
  distant). La clé anon publique permettait un self-mint arbitraire via
  `/rest/v1/rpc/add_credits`. La 009 ré-applique les corps gardés de 006
  (verbatim) et remplace le `REVOKE FROM PUBLIC` (insuffisant — grants
  explicites) par des REVOKE nommés : `add_credits` → service_role only ;
  `deduct_credits` → authenticated (bridge, p_user_id = self, vérifié dans
  `apps/web/src/app/api/agent/route.ts:20`) + service_role ;
  `init_user_credits` → plus aucun EXECUTE (fonction de trigger). Appliquée
  en distant (version `20260728201728_009_credits_rpc_lockdown`) et vérifiée :
  gardes présentes dans pg_get_functiondef, grantees EXECUTE =
  service_role / authenticated+service_role / postgres seul, et smoke test
  transactionnel → les deux RPC lèvent bien `forbidden:` sans écrire.
- **Fail-closed (2026-07-28)** : deux trous de sécurité colmatés avant
  activation du webhook. (1) `LEMON_SQUEEZY_WEBHOOK_SECRET` absent → la
  vérification HMAC utilisait une clé vide, forgeable par n'importe qui ;
  la requête renvoie désormais 500 avant toute vérification. (2) Erreur
  d'insert du marker ≠ 23505 (table absente, DB down) → l'événement était
  traité comme non-dupliqué et crédité SANS marker, donc un retry LS
  créditait une seconde fois ; la requête renvoie désormais 500 sans crédit
  (`claimEvent` tri-état `duplicate | claimed | error`).
- **Migration 008 appliquée sur Supabase** (2026-07-28, version
  `20260728193336_008_webhook_idempotence`) — table vérifiée présente.
- **TDD** : `lemon-squeezy-webhook.test.ts` écrit d'abord — 7 RED (crédit
  top-up ignoré car config lue au chargement du module, 5 cas d'idempotence,
  libération du marker sur échec), puis implémentation → 11/11 verts, puis
  13/13 après les 2 tests fail-closed.
- **Idempotence** : marker `processed_webhook_events` inséré avant tout crédit
  (conflit PK 23505 = doublon → 200 `duplicate:true` sans écriture), supprimé
  si le crédit échoue pour laisser passer le retry LS. Clé
  `event_name:data.id` (+ hash du corps pour `subscription_renewed`, dont
  data.id est constant d'une échéance à l'autre).
- **Config env lue par requête** (fonctions `topupPacks()`/`subscriptionPlans()`)
  au lieu du chargement du module — rend le route handler testable et reflète
  l'env réelle.
- **`.env.example`** : les 10 variables LS_* / NEXT_PUBLIC_LS_CHECKOUT_*
  consommées par le code mais non documentées sont ajoutées.

- **Tarification (décision utilisateur 2026-07-27)** : Pro 25€ → **29€/mois**,
  Pro Max 50€ → **99€/mois**, crédits inclus inchangés (100/300). Appliqué à la
  page billing, au pricing marketing, au README et aux deux skills
  `cirqix-credits`. NON appliqué (hors périmètre / territoire Claude, signalé à
  l'utilisateur) : `CLAUDE.md:446`, `PLAN.md:124-125,843` (25€/50€),
  `docs/cirqix-full-resume.md` (projections MRR calculées sur les anciens prix —
  recalcul = décision business).

- **Logo « Cirqix »** : le wordmark du `logo.svg` était « Layrix » vectorisé en
  paths (police non identifiée — comparaison chamfer sur Syne/Orbitron/Russo
  One/Michroma/Viga/Chakra Petch, aucune proche). Stratégie : réutilisation des
  glyphes existants `i`/`r`/`x` (style exact), synthèse du `q` (`a` + descendante
  arrondie, union pathops) et du `C` (anneau rect arrondi, stroke 58 comme les
  autres lettres, hauteur de capitale du L original). Fond knockouts reconstruit
  aux nouvelles positions, split couleurs conservé (3 lettres blanches + 3
  cyan). Vérifié par rendu headless Chrome à taille navbar (112×32) et plein
  cadre — lisible et cohérent. Script de génération : `tmp/build_logo.py`
  (tmp/ gitignoré).

## Fichiers modifiés

- `apps/web/src/app/api/webhooks/lemon-squeezy/route.ts` — idempotence + config par requête + fail-closed (secret, marker)
- `apps/web/src/test/lemon-squeezy-webhook.test.ts` — 13 tests (nouveau)
- `packages/db/supabase/migrations/008_webhook_idempotence.sql` — table markers (nouveau)
- `packages/db/supabase/migrations/009_credits_rpc_lockdown.sql` — gardes RPC + grants explicites (nouveau, 2026-07-28)
- `.env.example` — variables Lemon Squeezy documentées
- `apps/web/src/app/(dashboard)/dashboard/billing/page.tsx` — Pro 29€, Pro Max 99€
- `apps/web/src/shared/lib/marketing-content.ts` — Pro 29€, Pro Max 99€
- `README.md` — tableau des plans à jour
- `.agents/skills/cirqix-credits/SKILL.md` + `.claude/skills/cirqix-credits/SKILL.md` — price_eur 29/99
- `apps/web/public/logo.svg` + `docs/logo/logo.svg` — wordmark « Cirqix »
- `docs/agents/handoffs/2026-07-27-billing-idempotence.md` — ce fichier

## Validations exactes

| Commande | Résultat | Date UTC |
|---|---|---|
| `pnpm vitest run src/test/lemon-squeezy-webhook.test.ts` (avant impl.) | `7 failed, 4 passed — RED attendu` | `2026-07-27T21:37:00Z` |
| `pnpm vitest run src/test/lemon-squeezy-webhook.test.ts` (après impl.) | `11 passed` | `2026-07-27T21:39:00Z` |
| `pnpm --filter @cirqix/web test` | `26 passed (3 fichiers — dont jlcpcb-order + local-pipeline intacts)` | `2026-07-27T21:39:42Z` |
| `pnpm type-check` | `7/7 successful, 0 erreur` | `2026-07-27T21:40:30Z` |
| `pnpm --filter @cirqix/web lint` | `No ESLint warnings or errors` | `2026-07-27T21:41:00Z` |
| `pnpm vitest run src/test/lemon-squeezy-webhook.test.ts` (fail-closed) | `13 passed` | `2026-07-28T19:29:43Z` |
| `pnpm --filter @cirqix/web test` (fail-closed) | `28 passed (3 fichiers)` | `2026-07-28T19:30:07Z` |
| `pnpm type-check` (fail-closed) | `7/7 successful, 0 erreur` | `2026-07-28T19:30:20Z` |
| `pnpm --filter @cirqix/web lint` (fail-closed) | `No ESLint warnings or errors` | `2026-07-28T19:30:35Z` |
| Supabase MCP `apply_migration 008_webhook_idempotence` | `success — version 20260728193336, table vérifiée` | `2026-07-28T19:33:00Z` |
| Supabase MCP `get_advisors security` | `INFO rls_enabled_no_policy sur processed_webhook_events (intentionnel) ; WARN préexistants SECURITY DEFINER (add_credits, deduct_credits…) exécutables par anon/authenticated` | `2026-07-28T19:33:30Z` |
| Supabase MCP `apply_migration 009_credits_rpc_lockdown` | `success — version 20260728201728` | `2026-07-28T20:17:28Z` |
| Vérif `pg_get_functiondef` + `aclexplode(proacl)` | `gardes présentes ; EXECUTE : add_credits→service_role, deduct_credits→authenticated+service_role, init_user_credits→aucun` | `2026-07-28T20:17:45Z` |
| Smoke test gardes (DO block, sans JWT) | `add_credits → "forbidden: requires service role" ; deduct_credits → "forbidden: must own these credits" — aucune écriture` | `2026-07-28T20:18:00Z` |
| Supabase MCP `get_advisors security` (post-009) | `add_credits / init_user_credits sortis des alertes ; deduct_credits authenticated = voulu (garde en corps) ; restent footprint RPC + waitlist (préexistants, hors périmètre)` | `2026-07-28T20:18:10Z` |
| `pnpm vitest run src/test/lemon-squeezy-webhook.test.ts` (re-validation reprise) | `13 passed` | `2026-07-28T22:25:47Z` |
| `pnpm --filter @cirqix/web test` (re-validation reprise) | `37 passed (4 fichiers — inclut credits.test.ts de Codex, intact)` | `2026-07-28T22:26:42Z` |
| `pnpm type-check` (re-validation reprise) | `7/7 successful, 0 erreur` | `2026-07-28T22:26:58Z` |

## Risques et blocages

- **Migration 006 jamais appliquée en distant** : seule sa partie RPC a été
  reprise par la 009. Restent de 006 : la policy waitlist
  (`waitlist_insert` — le distant a une policy équivalente
  `allow_public_insert` créée hors migrations) et le constat général que les
  fichiers de migration locaux ne reflètent pas l'historique distant
  (versions ≠ noms). À régulariser lors d'un futur alignement db.
- **Advisors restants (hors périmètre, préexistants)** : RPC footprint
  (`search_footprint_*`, `upsert_community_footprint`) et `rls_auto_enable`
  SECURITY DEFINER exécutables par anon/authenticated ; waitlist INSERT
  `WITH CHECK (true)` (voulu pour le formulaire landing) ; leaked password
  protection désactivée.
- Variables LS_* à renseigner côté déploiement (voir `.env.example`) — sinon
  packs/plans inconnus → webhook acquitte sans créditer, et secret absent →
  500 (fail-closed voulu).
- Fichiers non commités dans un worktree partagé avec Claude Code — staging
  accidentel possible tant que le commit n'est pas fait.

## Travail restant

- Commit des fichiers possédés (stratégie branche/PR à trancher par
  l'utilisateur — branche actuellement partagée avec le chantier Claude).
- Création des produits/variants Lemon Squeezy (action 1 du PLAN — console LS,
  hors code), puis activation du webhook côté console LS.

## Prochaine action atomique

Utilisateur : review + merge de la PR #76, puis activer le webhook dans la
console Lemon Squeezy une fois les variables LS_* déployées (création des
produits/variants = action 1 du PLAN, console LS, hors code).

## Git

- **Branche dédiée:** `feat/billing-idempotence` depuis `origin/main` (`0f1e1df`),
  worktree `C:\tmp\cirqix-billing-idempotence` — fichiers Codex et préexistants
  du worktree principal NON embarqués (décision utilisateur 2026-07-28).
- **Commits:** `799946e` (idempotence webhook + migrations 008/009),
  `cff4fad` (pricing 29/99), `ee513ad` (wordmark Cirqix + icône C),
  `8dc56d6` (ce handoff).
- **PR:** `#76` — https://github.com/bmechergui/cirqix/pull/76
- **Worktree principal:** les mêmes fichiers y restent non commités (copies de
  travail) — ne pas les stager depuis `main`.

## Journal de transfert

| Date UTC | From | To | État | Note |
|---|---|---|---|---|
| `2026-07-27T21:34:48Z` | `human` | `Kimi` | `accepté` | `Phase 4.4 restante, périmètre disjoint du chantier Claude` |
| `2026-07-28T19:34:17Z` | `Kimi` | `Kimi` | `mise à jour` | `Fail-closed (secret + marker), 13/13 tests, migration 008 appliquée (20260728193336)` |
| `2026-07-28T20:18:26Z` | `Kimi` | `Kimi` | `mise à jour` | `Migration 009 lockdown RPC crédits appliquée (20260728201728) — self-mint anon fermé, gardes vérifiées` |
| `2026-07-28T22:27:05Z` | `Kimi` | `Kimi` | `mise à jour` | `Reprise de session : fichiers possédés intacts, re-validation 13/13 + 37/37 + type-check 0 erreur. Reste : décision utilisateur sur stratégie de commit` |
| `2026-07-28T22:35:30Z` | `Kimi` | `human` | `REVIEW` | `Branche dédiée feat/billing-idempotence (4 commits), poussée, PR #76 ouverte. Validations rejouées dans le worktree propre : 13/13 + type-check 0 erreur` |
