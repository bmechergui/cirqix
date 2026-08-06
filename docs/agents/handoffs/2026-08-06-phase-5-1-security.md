# Handoff — `phase-5-1-security`

- **Status:** `HANDOFF`
- **Owner:** `Kimi`
- **Reviewer:** `aucun`
- **Receiver:** `human`
- **Branch:** `feat/phase-5-1-security`
- **Worktree:** `C:\tmp\cirqix-phase-5-1`
- **Base commit:** `f62ff71`
- **Content commit:** `b97ec04`
- **Updated UTC:** `2026-08-06T12:49:54Z`

## Objectif

Étape 5.1 de `PLAN.md` (Sécurité) limitée aux chemins disjoints du chantier
Claude Code (`2026-07-30-project-integrity`, actif dans le worktree principal) :
headers de sécurité (CSP, HSTS, X-Frame-Options…), infrastructure de rate
limiting Upstash appliquée aux endpoints possédés, audit RLS en lecture seule.

Constats d'entrée (audit 2026-08-06) :

- Zod déjà présent sur tous les endpoints hors périmètre Claude Code
  (`waitlist`, `settings/profile` ; `credits` et `settings/transactions` sont
  des GET sans entrée). Volet conforme, rien à faire.
- `ANTHROPIC_API_KEY` : serveur uniquement, aucun composant `'use client'`
  n'importe `@cirqix/agents`. Conforme, rien à faire.
- Headers de sécurité : totalement absents de `next.config.ts` → livré ici.
- Rate limiting : `@upstash/ratelimit` non installé → livré ici.

## Critère de terminaison

Tests verts (rate limiter + headers + waitlist 429), `pnpm type-check`
7/7 sans erreur, headers présents dans la config Next, rate limiting actif sur
`/api/waitlist`, audit RLS consigné ci-dessous. **Tous atteints.**

## Périmètre autorisé

### Chemins possédés

- `apps/web/next.config.ts`
- `apps/web/src/shared/lib/ratelimit.ts` (nouveau)
- `apps/web/src/app/api/waitlist/route.ts`
- `apps/web/src/test/ratelimit.test.ts` (nouveau)
- `apps/web/src/test/security-headers.test.ts` (nouveau)
- `apps/web/src/test/waitlist-rate-limit.test.ts` (nouveau)
- `apps/web/package.json` + `pnpm-lock.yaml` (deps `@upstash/ratelimit`, `@upstash/redis`)
- `.env.example` (documentation `UPSTASH_REDIS_REST_*`)
- `docs/agents/handoffs/2026-08-06-phase-5-1-security.md` (ce fichier)

### Lecture seule

- `apps/web/src/middleware.ts`, `apps/web/src/shared/lib/supabase-server.ts`
- MCP Supabase `get_advisors` (audit RLS, aucune écriture distante)

### Hors périmètre

- `apps/web/src/app/api/agent/**`, `api/projects/**`, `api/jlcpcb/**`,
  `packages/db/**`, `packages/agents/**`, `ExportView.tsx`, `CLAUDE.md`,
  `PLAN.md`, `services/kicad/**` — chantier Claude Code
  (`2026-07-30-project-integrity`) et chantiers RL.
- **Câblage du rate limiting sur `/api/agent/run`** (cible 10 req/min du
  PLAN) : le fichier appartient à Claude Code. L'infra est livrée ici ; le
  câblage est une action post-merge (une ligne + un garde 429, voir
  `waitlist/route.ts` comme modèle).
- Toute commande `git commit/push` (décision utilisateur en fin de tâche).

## Décisions prises

- **Worktree dédié** (`C:\tmp\cirqix-phase-5-1`) pour ne pas perturber la
  session Claude Code active dans le worktree principal — même méthode que
  le chantier `2026-07-27-billing-idempotence`.
- **Rate limiter fail-open si env absentes** : sans `UPSTASH_REDIS_REST_URL`,
  le limiter est un no-op avec warning logué une fois (dev local sans Redis ;
  la protection s'active dès que les variables sont posées en prod). Bloquer
  sur config manquante transformerait une coupure Upstash en panne totale.
- **Rate limiting appliqué à `/api/waitlist`** (seul endpoint public sans auth
  dans le périmètre ; le webhook Lemon Squeezy est déjà protégé par HMAC),
  quota par IP `x-forwarded-for`, 10 req/60 s (défaut PLAN).
- **HSTS en production uniquement** : le poser en dev casserait
  `http://localhost`.
- **CSP avec `'unsafe-inline'`/`'unsafe-eval'`/`'wasm-unsafe-eval'`** :
  requis par l'hydratation Next.js ; `https://kicanvas.org` autorisé en
  `script-src`/`connect-src` (viewer KiCanvas chargé depuis son CDN + assets
  WASM) ; `connect-src` et `img-src` autorisent `*.supabase.co` (+ `wss:`
  Realtime) ; `object-src 'none'`.
- **IP de quota = dernier élément `x-forwarded-for`** (revue 2026-08-06) :
  le premier est contrôlé par le client et spoofable ; le dernier est ajouté
  par la plateforme (Vercel). Fallback `x-real-ip` puis `unknown`.
- **Fail-open étendu aux exceptions réseau Upstash** (revue 2026-08-06) :
  `limiter.limit()` est entouré d'un try/catch → avertissement + admission,
  cohérent avec la justification du fail-open (une panne Upstash ne doit pas
  devenir une panne totale).

## Revue (sous-agent lecture seule, 2026-08-06)

- **BLOQUANT corrigé** : la CSP initiale bloquait le script CDN KiCanvas
  (`kicanvas-loader.ts`) — `https://kicanvas.org` ajouté à `script-src` et
  `connect-src`, test de garde ajouté.
- **MOYEN corrigé** : extraction IP spoofable → dernier élément XFF.
- **MOYEN corrigé** : exception Upstash non gérée (500) → fail-open + warn.
- **MINEUR corrigé** : `object-src 'none'` ajouté ; commentaire CSP rectifié
  (WASM = KiCanvas, pas occt-import-js).
- MINEUR accepté : bucket `waitlist:unknown` partagé si aucun header IP
  (proxies sans XFF) — auto-blocage collectif possible, impact limité à un
  endpoint de waitlist.

## Travail réalisé

- `next.config.ts` : règle globale `/:path*` — CSP, X-Frame-Options DENY,
  X-Content-Type-Options nosniff, Referrer-Policy, Permissions-Policy,
  HSTS (prod).
- `shared/lib/ratelimit.ts` : `checkRateLimit(identifier, limit=10,
  windowSeconds=60)`, fixed window Upstash, instances mises en cache,
  fail-open documenté (env absentes + exception réseau).
- `api/waitlist/route.ts` : 429 `rate_limited` avant tout accès Supabase.
- TDD : RED prouvé (6 échecs sur 7) avant implémentation, GREEN après ;
  correctifs de revue couverts par 3 tests supplémentaires (CDN KiCanvas +
  `object-src`, exception Upstash, XFF multi-éléments).
- `.env.example` : `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN`.

## Audit RLS (MCP `get_advisors security`, lecture seule, 2026-08-06)

| Niveau | Constat | Recommandation |
|---|---|---|
| WARN | `public.rls_auto_enable()` exécutable par `anon` **et** `authenticated` en `SECURITY DEFINER` | Révoquer EXECUTE ou passer en `SECURITY INVOKER` — prioritaire |
| WARN | `search_footprint_by_embedding` / `search_footprint_by_part_number` exécutables par `anon` en `SECURITY DEFINER` | Probablement intentionnel (recherche publique) — à confirmer |
| WARN | Extension `vector` installée dans le schéma `public` | La déplacer dans un schéma dédié |
| WARN | Protection contre les mots de passe compromis désactivée (Auth) | Activer dans Supabase Auth (HaveIBeenPwned) |
| INFO | `processed_webhook_events` : RLS activée sans policy | Voulu (table service-role only, migration 008) — aucune action |

Ces correctifs exigent des migrations SQL : `packages/db/**` appartient au
chantier `project-integrity` — à coordonner avec Claude Code, pas de doublon.

## Fichiers modifiés

- `apps/web/next.config.ts` — headers de sécurité globaux.
- `apps/web/src/shared/lib/ratelimit.ts` — infrastructure Upstash (nouveau).
- `apps/web/src/app/api/waitlist/route.ts` — garde 429 par IP.
- `apps/web/src/test/{ratelimit,security-headers,waitlist-rate-limit}.test.ts` — 11 tests (nouveaux).
- `apps/web/package.json`, `pnpm-lock.yaml` — `@upstash/ratelimit@^2.0.8`, `@upstash/redis@^1.38.2`.
- `.env.example` — variables Upstash documentées.
- `docs/agents/handoffs/2026-08-06-phase-5-1-security.md` — ce fichier.

## Validations exactes

| Commande | Résultat | Date UTC |
|---|---|---|
| `git worktree add C:/tmp/cirqix-phase-5-1 -b feat/phase-5-1-security` | OK, HEAD `f62ff71` | 2026-08-06 |
| `corepack pnpm install && pnpm -C apps/web add @upstash/ratelimit @upstash/redis` | exit 0 | 2026-08-06 |
| `vitest run` (3 nouveaux fichiers) avant implémentation | RED attendu : 6 échecs / 7 | 2026-08-06 |
| `vitest run src/test/{ratelimit,security-headers,waitlist-rate-limit}.test.ts` | exit 0, 11/11 | 2026-08-06 |
| `corepack pnpm test` dans `apps/web` | exit 0, 7 fichiers / 48 tests | 2026-08-06 |
| `corepack pnpm type-check` (racine, turbo) | exit 0, 7/7 tâches | 2026-08-06 |
| MCP Supabase `get_advisors security` | 4 WARN + 1 INFO (tableau ci-dessus) | 2026-08-06 |
| Revue sous-agent lecture seule | 1 BLOQUANT + 2 MOYEN + mineurs — corrigés | 2026-08-06 |
| `vitest run` complet `apps/web` après correctifs de revue | exit 0, 7 fichiers / 50 tests | 2026-08-06 |
| `corepack pnpm type-check` (racine, turbo) après correctifs | exit 0, 7/7 tâches | 2026-08-06 |
| `git status --short` | uniquement les chemins possédés | 2026-08-06 |

## Risques et blocages

- La CSP peut casser le viewer (KiCanvas web components, Three.js, WASM
  `occt-import-js`) malgré les directives permissives : validation visuelle
  requise après merge (`skill cirqix-frontend-verify`).
- Sans `UPSTASH_REDIS_REST_*` en prod, le rate limiting reste inactif
  (fail-open par design) — poser les variables Vercel au déploiement.

## Travail restant

- Câblage `/api/agent/run` (10 req/min) après libération du périmètre par
  Claude Code.
- Correctifs RLS de l'audit (migrations SQL) — coordination project-integrity.
- Validation visuelle CSP post-merge.

## Prochaine action atomique

Décision utilisateur : commit de `feat/phase-5-1-security` (chemins possédés
uniquement) puis PR, ou relecture d'abord.

## Git

- **État initial du worktree:** `feat/phase-5-1-security` sur `f62ff71`, propre.
- **État final du worktree:** 5 fichiers modifiés + 5 nouveaux, tous possédés.
- **Commit:** `b97ec04`
- **PR:** `none`

## Journal de transfert

| Date UTC | From | To | État | Note |
|---|---|---|---|---|
| 2026-08-06T12:43:45Z | Kimi | human | proposé | Revendication des chemins 5.1 disjoints de project-integrity. |
| 2026-08-06T12:49:54Z | Kimi | human | proposé | Implémentation terminée, tests et type-check verts, audit RLS consigné. |
