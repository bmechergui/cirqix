# Layrix.ai — CLAUDE.md

## Projet
SaaS 100% cloud de conception PCB par langage naturel. Agent IA autonome → PCB DRC-clean → Gerber → commande JLCPCB.
Tagline : "AI PCB Design Agent — From idea to manufacturable PCB, autonomously"

---

## ⚠️ RÈGLES ABSOLUES — NE JAMAIS VIOLER

### 1. Skill obligatoire AVANT chaque tâche

```
ÉTAPE 1 → layrix-prompt-improver   (TOUJOURS, sans exception)
ÉTAPE 2 → Sélectionner le meilleur skill parmi la liste ci-dessous
ÉTAPE 3 → Annoncer AVANT chaque appel :
         "[Skill : X] — raison"
         "[MCP : X] — raison"
         "[Agent : X] — raison"
         "[Plugin : X] — raison"
ÉTAPE 4 → Coder / implémenter
ÉTAPE 5 → pnpm type-check → 0 erreurs
ÉTAPE 6 → git commit + push + PR (automatiquement, sans attendre)
```

**NEVER** coder sans avoir invoqué un skill.
**NEVER** laisser l'utilisateur faire le git commit ou le PR — Claude le fait.
**NEVER** demander de l'aide pour des étapes que Claude peut faire seul.
**NEVER** sauter une étape du workflow complet (voir `.claude/WORKFLOW.md`).
**NEVER** sauter `layrix-prompt-improver`, même pour une tâche courte ou simple.
**NEVER** committer sans que `pnpm type-check` retourne 0 erreurs.
**NEVER** écrire `[Skill : X]` en texte sans appeler le `Skill` tool réellement — écrire le nom ne compte pas, seul l'appel au tool compte.

### 2. Niveau de planification selon la complexité

| Complexité | Action |
|------------|--------|
| Simple (1 fichier, bug fix) | Coder directement — pas de plan |
| Moyenne (feature, 2-5 fichiers) | Annoncer les étapes avant de coder |
| Complexe (feature multi-fichiers, archi) | `/everything-claude-code:plan` + doc avant de coder |
| Très complexe (nouveau système, agents, DB) | `architect` agent + `/superpowers:write-plan` |

Claude choisit seul le niveau selon la complexité — pas besoin que l'utilisateur le précise.

**NEVER** demander à l'utilisateur quel niveau de plan utiliser — Claude décide seul.
**NEVER** utiliser `/everything-claude-code:plan` pour une tâche simple (1 fichier, bug fix).
**ALWAYS** invoquer `architect` agent + `/superpowers:write-plan` pour un nouveau système ou une archi complexe.

### 3. Autonomie totale

Claude mène le projet. L'utilisateur valide. Pas l'inverse.
- Si une tâche bloque → proposer 2 solutions et choisir la meilleure
- Si un skill manque → `npx skills find "query"` puis `/skill-creator:skill-creator`
- Si une décision d'archi est nécessaire → invoquer `architect` agent et proposer

### 3. Git workflow obligatoire après chaque tâche

```bash
git add <fichiers modifiés>          # Jamais git add -A
git commit -m "feat: description"    # Conventional commits
git push -u origin <branch>
gh pr create --title "..." --body "..."
```

---

## Fichiers de référence Claude

- `.claude/WORKFLOW.md` — workflow complet, arbre de décision skills, ordre d'exécution par phase
- `.claude/SKILLS.md` — registre de TOUS les skills utilisés dans ce projet (description + quand invoquer)
- **Mettre à jour `.claude/SKILLS.md` + `CLAUDE.md` après chaque installation ou création de skill**

---

## Règle prioritaire — Prompt Improver

**TOUJOURS** invoquer le skill `layrix-prompt-improver` avant d'exécuter une tâche :
1. Afficher le prompt reçu
2. Afficher le prompt amélioré et corrigé
3. Attendre confirmation (ou exécuter directement si l'utilisateur approuve)

Cette règle s'applique à TOUS les prompts — même les courts et les clairs.

---

## Docs de référence (lire avant de coder)
- `docs/layrix-full-resume.md` — vision produit complète, business model, stack
- `docs/agentdescription.md` — system prompts exacts des 6 agents Claude
- `docs/note.md` — notes techniques (pipeline, rendu, architecture)
- `PLAN.md` — plan d'implémentation complet par phases
- `docs/design/design-system.md` — tokens, couleurs, typographie, composants

## Architecture frontend
- `apps/landing` et `apps/dashboard` sont **SUPPRIMÉS** — une seule app : **`apps/web`**
- Route groups Next.js : `(marketing)` → layrix.ai · `(dashboard)` → layrix.ai/dashboard
- Dev server : `pnpm dev` à la racine (Turborepo) → démarre `apps/web` sur **port 3333**
- Commandes dev : `pnpm dev` (root) · `cd apps/web && pnpm dev` (direct)
- Package manager : **pnpm@9.0.0** — ne jamais utiliser npm ou yarn

## Stack
- Monorepo Turborepo : `apps/web`, `apps/api`, `packages/agents`, `packages/ui`, `packages/db`, `services/kicad`
- Frontend : Next.js 15 + Tailwind + shadcn/ui + Zustand
- Backend MVP : Next.js API Routes (pas de serveur séparé au MVP)
- Microservice KiCad : Python + FastAPI + pcbnew — Docker headless sur DigitalOcean (`services/kicad/`)
- Agents : Claude SDK (Anthropic) — Orchestrateur Sonnet 4.6 + 5 agents Haiku 4.5
- DB : PostgreSQL + Supabase + pgvector (extensions : uuid-ossp, pgvector)
- Queue : Redis + BullMQ (10 PCBs simultanés)
- Stockage : Supabase Storage (`/storage/{userId}/{projectId}/`)
- Auth : Supabase Auth (email + Google OAuth)
- Paiement : Lemon Squeezy (MVP) — Stripe en V2
- Viewer 2D : PixiJS (WebGL, 60 FPS)
- Viewer 3D : Three.js + STEP via occt-import-js (plan Maker+)

## Règles agents Claude
- Orchestrateur = Claude Sonnet 4.6 — max 15 itérations par PCB
- Agents spécialisés = Claude Haiku 4.5 — Schéma, Placement, Routage, DRC, Footprint, BOM/Export
- Coût cible : ~0.12€ par PCB complet
- Compression contexte : après 10 tours, Haiku résume les anciens tours
- System prompts exacts dans `docs/agentdescription.md` — ne pas réécrire, réutiliser
- JAMAIS de commande JLCPCB automatique — confirmation "OUI JE CONFIRME" obligatoire

## Stratégie moteur PCB (invisible pour l'utilisateur)
- <20 composants + 2 couches → TSCircuit (rapide, Claude génère TSX nativement)
- Sinon → KiCad + Freerouting + pcbnew
- Résultat identique dans les deux cas : fichier Gerber standard

## Système de crédits
- Chat : 0.5 | Schéma : 2 | Placement : 2 | Routage : 3 | DRC : 1 | Export : 1 | Footprint IA : 3 | Vue 3D : 1 | Simulation : 3
- Plans : Free (5/jour) | Maker 25€/mois (100) | Pro 50€/mois (300) | Enterprise (illimité)
- Vérifier le solde avant chaque action agentique

## Base de données
- RLS Supabase activée sur toutes les tables — toujours tester l'isolation entre users
- pgvector pour embeddings footprints (recherche sémantique)
- Table `credits` + `credit_transactions` pour le système de crédits
- Schéma complet dans `PLAN.md` (section Phase 0)

## Types source de vérité (`apps/web/src/lib/mock-data.ts`)
- `PCBStatus` = `'INITIAL' | 'SCHEMA_DONE' | 'PLACEMENT_DONE' | 'ROUTING_DONE' | 'DRC_CLEAN' | 'PCB_LIVRÉ'`
- `AgentStep` (store) = `'SCHEMA' | 'PLACEMENT' | 'ROUTING' | 'DRC' | 'EXPORT' | null`
- `Message.role` = `'user' | 'assistant'` (jamais `'agent'`)
- `Credits` = `{ balance, plan, daily_limit }` (pas `remaining`/`total`)
- `Project` = snake_case : `updated_at`, `iteration_count` (pas `componentCount`)

## Gotchas shadcn/ui
- `@radix-ui/react-badge` n'existe PAS — Badge est CSS pur, pas de package Radix
- Badge variants disponibles : `default | secondary | success | warning | destructive | copper | outline`

## Conventions code
- TypeScript strict sur tous les packages JS/TS
- Zod pour validation des inputs API (jamais de `any`)
- Immutabilité : créer de nouveaux objets, ne jamais muter
- Fichiers < 400 lignes — extraire si plus grand
- Pas de `console.log` en production — utiliser le logger Pino

## Design
- Design system dans `doc/design/design-system.md`
- Couleurs, typographie, composants — toujours respecter les tokens définis
- Voir logo `docs/logo/logo.jpg` pour référence visuelle

## Dépendances critiques (valider avant de coder)
1. Docker KiCad headless — builder l'image AVANT d'implémenter le microservice
2. Supabase pgvector — activer l'extension dès le setup DB
3. `ANTHROPIC_API_KEY` avec quota + `max_budget_usd` configuré
4. SnapMagic API key — pour cascade footprints
5. JLCPCB API — possible liste d'attente partenaire

## Variables d'environnement requises
`ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `REDIS_URL`, `LEMON_SQUEEZY_API_KEY`, `KICAD_SERVICE_URL`

## Phase actuelle
Phase 0 — Setup infra (semaine 1). Voir `PLAN.md` pour le détail complet.

---

## Skills à utiliser (invoquer AVANT de coder)

### Planification & Architecture
| Tâche | Skill |
|-------|-------|
| Nouvelle feature complexe | `/everything-claude-code:plan` |
| Décision d'architecture | `architect` agent |
| Brainstorm approche | `/superpowers:brainstorm` |
| Écrire un plan d'implémentation | `/superpowers:write-plan` |
| Exécuter un plan existant | `/superpowers:execute-plan` |

### Développement Frontend (Next.js + Tailwind + shadocs/ui)
| Tâche | Skill |
|-------|-------|
| Patterns Next.js / React | `/everything-claude-code:frontend-patterns` |
| Composants UI / design system | `/frontend-design:frontend-design` |
| Slides / présentation | `/everything-claude-code:frontend-slides` |
| Nuxt (si migration) | `/everything-claude-code:nuxt4-patterns` |

### Développement Backend (Next.js API Routes + FastAPI)
| Tâche | Skill |
|-------|-------|
| Design API REST | `/everything-claude-code:api-design` |
| Patterns backend Node.js | `/everything-claude-code:backend-patterns` |
| Patterns Python FastAPI | `/everything-claude-code:python-patterns` |
| Django (si besoin) | `/everything-claude-code:django-patterns` |
| Déploiement (Vercel/Railway) | `/everything-claude-code:deployment-patterns` |
| Docker KiCad service | `/everything-claude-code:docker-patterns` |

### Skills PCB & Hardware (installés depuis skills.sh)
| Tâche | Skill |
|-------|-------|
| TSCircuit (moteur <20 composants) | `tscircuit` |
| EDA / PCB général | `eda-pcb` |
| Recherche composants JLCPCB | `jlcpcb-component-finder` |
| KiCad patterns | `kicad` |
| Commande JLCPCB | `jlcpcb` |

### Stack Layrix (installés depuis skills.sh)
| Tâche | Skill |
|-------|-------|
| Next.js + Supabase Auth | `nextjs-supabase-auth` |
| Turborepo monorepo | `turborepo` |
| BullMQ queues | `bullmq-specialist` |

### Agents IA & Claude SDK
| Tâche | Skill |
|-------|-------|
| Coder avec Claude API / SDK | `/everything-claude-code:claude-api` ou `/claude-api` |
| Patterns MCP server | `/everything-claude-code:mcp-server-patterns` |
| Boucle agentique autonome | `/everything-claude-code:continuous-agent-loop` |
| Engineering IA first | `/everything-claude-code:ai-first-engineering` |
| Engineering agentique | `/everything-claude-code:agentic-engineering` |
| Dispatch agents en parallèle | `/superpowers:dispatching-parallel-agents` |
| Dev sous-agents | `/superpowers:subagent-driven-development` |
| Orchestration multi-agents | `/everything-claude-code:orchestrate` |
| Evaluation agents | `/everything-claude-code:agent-eval` |
| Harness agent | `/everything-claude-code:agent-harness-construction` |

### Base de données (Supabase + PostgreSQL + pgvector)
| Tâche | Skill |
|-------|-------|
| Patterns PostgreSQL | `/everything-claude-code:postgres-patterns` |
| Migrations DB | `/everything-claude-code:database-migrations` |
| Patterns JPA / ORM | `/everything-claude-code:jpa-patterns` |

### Tests
| Tâche | Skill |
|-------|-------|
| TDD (écrire tests en premier) | `/everything-claude-code:tdd` ou `/superpowers:test-driven-development` |
| Tests Python (FastAPI/pcbnew) | `/everything-claude-code:python-testing` |
| Tests E2E Playwright | `/everything-claude-code:e2e` ou `/e2e-testing` |
| Tests Golang (si besoin) | `/everything-claude-code:golang-testing` |
| Couverture de tests | `/everything-claude-code:test-coverage` |
| Régression IA | `/everything-claude-code:ai-regression-testing` |
| Eval harness | `/everything-claude-code:eval-harness` |

### Qualité & Review
| Tâche | Skill |
|-------|-------|
| Review code TypeScript/JS | `typescript-reviewer` agent |
| Review code Python | `python-reviewer` agent ou `/everything-claude-code:python-review` |
| Review sécurité | `security-reviewer` agent ou `/everything-claude-code:security-review` |
| Review PR complète | `/pr-review-toolkit:review-pr` |
| Simplifier le code | `/simplify` ou `/everything-claude-code:prune` |
| Nettoyer code mort | `refactor-cleaner` agent |
| Quality gate avant merge | `/everything-claude-code:quality-gate` |
| Standards de code | `/everything-claude-code:coding-standards` |
| Scan sécurité | `/everything-claude-code:security-scan` |

### Git & CI
| Tâche | Skill |
|-------|-------|
| Commit propre | `/commit-commands:commit` |
| Commit + push + PR | `/commit-commands:commit-push-pr` |
| Finir une branche | `/superpowers:finishing-a-development-branch` |
| Worktrees git | `/superpowers:using-git-worktrees` |

### Debugging & Build
| Tâche | Skill |
|-------|-------|
| Débogage systématique | `/superpowers:systematic-debugging` |
| Erreur de build TypeScript | `build-error-resolver` agent |
| Erreur de build Python | `python-reviewer` agent |
| Vérification avant PR | `/superpowers:verification-before-completion` |
| Boucle de vérification | `/everything-claude-code:verification-loop` |

### Documentation
| Tâche | Skill |
|-------|-------|
| Docs bibliothèque / API externe | `/everything-claude-code:documentation-lookup` |
| Mettre à jour les docs | `doc-updater` agent |
| Mettre à jour codemaps | `/everything-claude-code:update-codemaps` |

### Sessions & Contexte
| Tâche | Skill |
|-------|-------|
| Reprendre une session | `/everything-claude-code:resume-session` |
| Sauvegarder la session | `/everything-claude-code:save-session` |
| Voir sessions | `/everything-claude-code:sessions` |
| Gérer le budget de contexte | `/everything-claude-code:context-budget` |
| Checkpoint en cours de tâche | `/checkpoint` |

### Créer & améliorer des skills

**Créer un skill custom Layrix — À TOUT MOMENT :**
- **Tu peux et tu DOIS créer des skills dès qu'une tâche est récurrente ou complexe**
- Invoquer `/skill-creator:skill-creator` — crée un fichier `.md` dans `.claude/skills/` du projet
- Skills Layrix déjà créés dans `.claude/skills/` :
  - `layrix-pcb-agent.md` — boucle agentique PCB complète (orchestrateur + SSE + Redis)
  - `layrix-footprint.md` — cascade 8 étapes de recherche/génération footprint
  - `layrix-kicad-service.md` — microservice Python FastAPI + pcbnew + Freerouting
  - `layrix-viewer.md` — PixiJS 2D (couleurs layers, DRC markers) + Three.js 3D (STEP)
  - `layrix-credits.md` — déduction crédits, plans, top-ups, middleware, Supabase RPC
  - `layrix-drc.md` — boucle DRC max 3 itérations, corrections pcbnew, markers viewer

**Améliorer un skill existant — AVEC VALIDATION :**
- Invoquer `/skill-creator:skill-creator` en précisant le skill à améliorer
- Toujours **montrer les modifications proposées** avant d'écrire — attendre confirmation
- Après chaque feature : enrichir le skill correspondant avec les patterns découverts
- Traiter les skills comme du code vivant — ils s'améliorent avec l'expérience du projet

**Améliorer ce CLAUDE.md — À TOUT MOMENT :**
- Tu peux proposer des mises à jour de CLAUDE.md sans attendre qu'on te le demande
- Toujours **montrer les changements proposés** avant d'appliquer — attendre confirmation
- Invoquer `/claude-md-management:revise-claude-md` pour révision structurée de session
- Invoquer `/claude-md-management:claude-md-improver` pour optimiser la concision
- **Règle d'or** : si tu répètes une instruction 2 fois → l'écrire dans CLAUDE.md
- **Règle d'or** : si une tâche Layrix revient souvent → créer un skill dédié dans `.claude/skills/`

### Workflow de sélection des skills (ordre de priorité)

```
1. everything-claude-code:xxx  → priorité absolue si disponible
2. Skills installés (.claude/SKILLS.md) → tscircuit, kicad, bullmq-specialist...
3. npx skills find "query"     → chercher sur skills.sh
4. /skill-creator:skill-creator → créer si rien n'existe
```

Voir `.claude/WORKFLOW.md` pour l'arbre de décision complet par phase.
Voir `.claude/SKILLS.md` pour la liste complète avec descriptions.

### Skills prioritaires pour Layrix

1. **`layrix-prompt-improver`** — TOUJOURS en premier, avant toute tâche
2. **`prompt-master`** — optimise le prompt (invoqué par layrix-prompt-improver)
3. **`/everything-claude-code:claude-api`** — agents Claude SDK
4. **`/everything-claude-code:frontend-patterns`** — Next.js / React
5. **`/everything-claude-code:python-patterns`** — FastAPI / pcbnew
6. **`/everything-claude-code:postgres-patterns`** — Supabase / pgvector
7. **`tscircuit`** — moteur PCB <20 composants
8. **`layrix-pcb-agent`** — boucle agentique PCB
9. **`bullmq-specialist`** — queues BullMQ
10. **`/everything-claude-code:security-scan`** — avant chaque commit auth/paiement
