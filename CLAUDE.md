# Layrix.ai — CLAUDE.md

## Projet
SaaS 100% cloud de conception PCB par langage naturel. Agent IA autonome → PCB DRC-clean → Gerber → commande JLCPCB.
Tagline : "AI PCB Design Agent — From idea to manufacturable PCB, autonomously"

---

## ⚠️ RÈGLES ABSOLUES — NE JAMAIS VIOLER

### 1. Workflow obligatoire — chaque tâche

```
Chaîne : layrix-prompt-improver → plan → TDD → code →
         code-reviewer → security-scan → type-check → verify → commit+PR
```

```
ÉTAPE 1  → layrix-prompt-improver                      (TOUJOURS — améliore le prompt + contexte Layrix + skill)
ÉTAPE 3  → Sélectionner le skill technique
ÉTAPE 3b → everything-claude-code:plan                 (feature complexe ≥ 2 fichiers)
ÉTAPE 3c → everything-claude-code:tdd                  (tests AVANT le code)
ÉTAPE 4  → Annoncer AVANT chaque appel : "[Skill : X] — raison"
ÉTAPE 5  → Coder / implémenter
ÉTAPE 5b → code-reviewer agent                         (APRÈS chaque implémentation)
ÉTAPE 5c → everything-claude-code:security-scan        (si auth / paiement / API keys)
ÉTAPE 6  → pnpm type-check → 0 erreurs
ÉTAPE 7  → git commit + push + PR (automatiquement)
```

**NEVER** coder sans avoir invoqué un skill.
**NEVER** laisser l'utilisateur faire le git commit ou le PR — Claude le fait.
**NEVER** sauter une étape de la chaîne ci-dessus.
**NEVER** sauter `layrix-prompt-improver`, même pour une tâche courte ou simple.
**NEVER** sauter `code-reviewer` après une implémentation.
**NEVER** committer sans que `pnpm type-check` retourne 0 erreurs.
**NEVER** écrire `[Skill : X]` en texte sans appeler le `Skill` tool réellement.

### 5. Prochaine étape — obligatoire après chaque tâche terminée

**TOUJOURS** terminer chaque réponse de fin de tâche par un bloc `## Prochaine étape recommandée` :

```
## Prochaine étape recommandée

**[Numéro Phase] — [Nom de la tâche]**
[Description courte de ce qu'il faut faire ensuite, pourquoi c'est la priorité, et les fichiers concernés]

Confirme pour que je démarre.
```

- Baser la recommandation sur `PLAN.md` (phase en cours) + ce qui vient d'être livré
- Toujours proposer **1 seule prochaine étape** — pas une liste de 5
- Si plusieurs candidats : choisir celle qui débloque le plus de valeur
- **NEVER** terminer sans ce bloc après un commit/PR

### 2. Niveau de planification — voir `rules/planning.md`

### 3. Autonomie totale

Claude mène le projet. L'utilisateur valide. Pas l'inverse.
- Si une tâche bloque → proposer 2 solutions et choisir la meilleure
- Si un skill manque → `npx skills find "query"` puis `/skill-creator:skill-creator`
- Si une décision d'archi est nécessaire → invoquer `architect` agent et proposer

### 4. Git workflow — voir `rules/git.md`

---

## Fichiers de référence

- `.claude/SKILLS.md` — registre de tous les skills (description + quand invoquer)
- `docs/layrix-full-resume.md` — vision produit complète, business model, stack
- `docs/agentdescription.md` — system prompts exacts des 6 agents Claude
- `PLAN.md` — plan d'implémentation complet par phases
- `docs/design/design-system.md` — tokens, couleurs, typographie, composants

**Mettre à jour `.claude/SKILLS.md` + `CLAUDE.md` après chaque installation ou création de skill**

---

## Règle prioritaire — Prompt Improver

**TOUJOURS** invoquer `layrix-prompt-improver` avant d'exécuter une tâche :
1. Afficher le prompt reçu
2. Afficher le prompt amélioré
3. Attendre confirmation (ou exécuter si l'utilisateur approuve)

---

## Architecture frontend

```
apps/web/src/
├── app/
│   ├── (marketing)/          ← layrix.ai (landing, pricing, waitlist)
│   └── (dashboard)/          ← layrix.ai/dashboard
├── features/
│   ├── marketing/ui/         ← Hero, Navbar, Pricing, WaitlistForm…
│   └── dashboard/ui/         ← ChatPanel, Sidebar, ProjectCard, StatusBadge…
├── widgets/
│   └── viewer/               ← ViewerPanel (KiCanvas schéma+PCB + Three.js 3D)
├── entities/
│   ├── project/              ← Project, PCBStatus
│   ├── pcb/                  ← PCBState, DRCViolation, AgentStep
│   └── credits/              ← Credits, Plan, CREDIT_COSTS
├── shared/
│   ├── ui/                   ← shadcn/ui components
│   ├── lib/                  ← mock-data.ts, supabase-middleware.ts
│   └── store/                ← app-store.ts (Zustand)
├── middleware.ts              ← Auth Supabase JWT — protège /dashboard/*
├── processes/                ← (Phase 3+ — boucle agentique UI)
└── entities/                 ← (modèles métier)

packages/
├── @layrix/types   ← SOURCE DE VÉRITÉ unique (PCBStatus, Plan, AgentAction…)
├── @layrix/logger  ← Pino logger
├── @layrix/utils   ← cn() utility
├── @layrix/db      ← Supabase client + migrations
├── @layrix/agents  ← Orchestrateur + agents Claude SDK
└── @layrix/ui      ← Design system composants partagés
```

**Import paths :**
- shadcn : `@/shared/ui/button`
- types : `@layrix/types` (jamais depuis mock-data)
- store : `@/shared/store/app-store`
- widgets : `@/widgets/viewer`
- entities : `@/entities/project`, `@/entities/pcb`, `@/entities/credits`

**Dev server :** `pnpm dev` (root) → port **3333**
**Package manager :** pnpm@9.0.0 — jamais npm ou yarn

---

## Stack

- Monorepo Turborepo : `apps/web`, `apps/api`, `packages/agents`, `packages/ui`, `packages/db`, `services/kicad`
- Frontend : Next.js 15 + Tailwind + shadcn/ui + Zustand
- Backend MVP : API Routes dans `apps/api/`
- Microservice KiCad : Python + FastAPI + pcbnew — Docker headless (`services/kicad/`)
- Agents : Claude SDK — Orchestrateur Sonnet 4.6 + 5 agents Haiku 4.5
- DB : PostgreSQL + Supabase + pgvector (uuid-ossp, pgvector)
- Queue : Redis + BullMQ (10 PCBs simultanés)
- Auth : Supabase Auth (email + Google OAuth)
- Paiement : Lemon Squeezy (MVP)
- Viewer Schéma + PCB : KiCanvas (rendu natif .kicad_sch / .kicad_pcb depuis Supabase Storage)
- Viewer 3D : Three.js + STEP via occt-import-js

## Règles agents Claude

- Orchestrateur = Sonnet 4.6 — max 15 itérations par PCB
- Agents spécialisés = Haiku 4.5
- Coût cible : ~0.12€ par PCB complet
- System prompts dans `docs/agentdescription.md` — ne pas réécrire
- **JAMAIS** de commande JLCPCB automatique — confirmation "OUI JE CONFIRME" obligatoire

## Stratégie moteur PCB

- **Circuit-Synth** (Python) → Claude génère code Python → KiCad Docker → `.kicad_sch` + `.kicad_pcb` natifs
- Fallback → KiCad + Freerouting + pcbnew (PCB Pro multi-couches)
- Viewer → **KiCanvas** charge les fichiers depuis Supabase Storage (signed URL 1h)
- JAMAIS TSCircuit en nouveau code — déprécié depuis v0.3.0

## Système de crédits

- Chat:0.5 | Schéma:2 | Placement:2 | Routage:3 | DRC:1 | Export:1 | Footprint IA:3 | Vue 3D:1 | Simulation:3
- Plans : Free (5/jour) | Maker 25€/mois (100) | Pro 50€/mois (300) | Enterprise (illimité)
- **TOUJOURS** vérifier solde AVANT, déduire APRÈS succès

## Base de données

- RLS activée sur toutes les tables — tester isolation user A / user B
- pgvector pour embeddings footprints
- Schéma complet dans `PLAN.md` §Phase 0

## Types source de vérité — `@layrix/types`

- `PCBStatus` = `'INITIAL' | 'SCHEMA_DONE' | 'PLACEMENT_DONE' | 'ROUTING_DONE' | 'DRC_CLEAN' | 'PCB_LIVRÉ'`
- `Message.role` = `'user' | 'assistant'` (jamais `'agent'`)
- `Credits` = `{ balance, plan, daily_limit }` (pas `remaining`/`total`)
- `Project` = snake_case : `updated_at`, `iteration_count`

## Gotchas shadcn/ui

- `@radix-ui/react-badge` n'existe PAS — Badge est CSS pur
- Badge variants : `default | secondary | success | warning | destructive | copper | outline`

## Design

- Design system : `docs/design/design-system.md`
- Logo : `docs/logo/logo.svg` + `docs/logo/icone.svg`

## Responsive — Règles obligatoires

```tsx
// Headings — JAMAIS taille fixe
text-2xl sm:text-3xl md:text-4xl        // sections
text-[1.8rem] sm:text-[2.4rem] md:text-[3rem]  // hero h1

// Grilles
grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3   // features
grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4   // pricing

// Forms
flex flex-col sm:flex-row gap-2   // input + button

// Navbar
hidden md:flex   // nav links desktop
md:hidden        // hamburger

// Dashboard sidebar
hidden md:block shrink-0
```

**NEVER** taille texte fixe sur heading visible.
**ALWAYS** tester mentalement mobile 375px avant de valider.

## Variables d'environnement requises

`ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `REDIS_URL`, `LEMON_SQUEEZY_API_KEY`, `KICAD_SERVICE_URL`

## Phase actuelle

**Phase 2 — Dashboard + Auth + Chat Agent MVP** (semaines 3–4). Voir `PLAN.md`.

Phases complétées : Phase 0 ✓ (infra) · Phase 1 ✓ (landing)

---

## Skills — sélection et création

**Ordre de priorité :**
1. `everything-claude-code:xxx` — priorité absolue
2. Skills installés → voir `.claude/SKILLS.md`
3. `npx skills find "query"` → skills.sh
4. `/skill-creator:skill-creator` → créer si rien n'existe

**Skills prioritaires Phase 2 :**
1. `layrix-prompt-improver` — TOUJOURS en premier (améliore + contexte Layrix + skill)
2. `layrix-pcb-agent` — boucle agentique PCB
4. `layrix-credits` — déduction crédits Supabase
5. `layrix-viewer` — PixiJS 2D + Three.js 3D
6. `/everything-claude-code:claude-api` — Claude SDK agents
7. `/everything-claude-code:frontend-patterns` — Next.js / React
8. `/everything-claude-code:postgres-patterns` — Supabase / pgvector
9. `/everything-claude-code:security-scan` — avant commit auth/paiement

**Créer un skill :** `/skill-creator:skill-creator` → `.claude/skills/layrix-xxx/`
**Améliorer un skill :** montrer les changements proposés → attendre confirmation
**Règle d'or :** instruction répétée 2× → l'écrire dans CLAUDE.md ou créer un skill

---

## Persona

Architecte logiciel senior full-stack, 15 ans d'expérience, spécialisé agents IA + PCB AI.
Maîtrise : Next.js 15 · TypeScript strict · Turborepo · Supabase · Claude SDK · Lemon Squeezy · TSCircuit · KiCad/FastAPI · Docker.
Principes : FSD · clean architecture · atomic design · tests · sécurité · coût agentique <0.12€/PCB.

Tu penses étape par étape. Tu annonces les skills avant chaque action. Tu contredis les mauvaises pratiques. Tu proposes des solutions modernes même si non demandées.
