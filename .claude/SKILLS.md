# Layrix — Registre des Skills

> Fichier de référence : tous les skills utilisés dans ce projet.
> Mettre à jour après chaque installation ou création de skill.
> Référencé dans `CLAUDE.md` et `.claude/WORKFLOW.md`.

---

## Skills Layrix (locaux — `.claude/skills/`)

| Skill | Fichier | Description | Invoquer quand |
|-------|---------|-------------|----------------|
| `layrix-prompt-improver` | `layrix-prompt-improver/SKILL.md` | Améliore tout prompt — 9D matrix, XML, contexte Layrix Phase 2, détection skill | **TOUJOURS en premier** |
| `layrix-pcb-agent` | `layrix-pcb-agent/SKILL.md` | Boucle agentique PCB : Orchestrateur Sonnet, 15 itérations max, états INITIAL→PCB_LIVRÉ, SSE streaming, Redis | Agent / Orchestrateur / Boucle PCB |
| `layrix-footprint` | `layrix-footprint/SKILL.md` | Cascade 8 étapes : KiCad → SnapMagic → Octopart → PDF Vision → génération .kicad_mod → pgvector | Footprint manquant / librairie |
| `layrix-kicad-service` | `layrix-kicad-service/SKILL.md` | FastAPI Python + pcbnew headless : placement, Freerouting, DRC, export Gerbers, Docker, BullMQ | KiCad / placement / routage / export |
| `layrix-viewer` | `layrix-viewer/SKILL.md` | PixiJS 2D (layers, couleurs, DRC markers, zoom/pan) + Three.js 3D (STEP, matériaux FR4) | Viewer PCB / rendu / layers |
| `layrix-credits` | `layrix-credits/SKILL.md` | Déduction atomique Supabase RPC, plans Free/Maker/Pro, top-ups, webhook Lemon Squeezy, UI badge | Crédits / plans / paiement |
| `layrix-drc` | `layrix-drc/SKILL.md` | Boucle DRC max 3 itérations, system prompt Haiku, corrections pcbnew, markers viewer | DRC / violations / correction PCB |
| `layrix-frontend-verify` | `layrix-frontend-verify/SKILL.md` | Diagnostic visuel read-only : screenshots Chrome DevTools (3 breakpoints — 375px/768px/1440px), détecte chevauchements/overlaps/layout cassé, rapport structuré + corrections Tailwind | **APRÈS chaque modification UI** — responsive broken / overlap / visuel à valider |

---

## Skills PCB / Hardware (installés depuis skills.sh)

| Skill | Source | Installs | Description | Invoquer quand |
|-------|--------|----------|-------------|----------------|
| `tscircuit` | tscircuit/skill | 313 | TSCircuit — moteur PCB React-like, génération TSX native par Claude | PCB <20 composants, 2 couches |
| `eda-pcb` | l3wi/claude-eda | 93 | EDA/PCB général — schémas, netlists, conventions électroniques | Schéma électronique, netlist |
| `jlcpcb-component-finder` | takazudo | 28 | Recherche composants LCSC/JLCPCB — prix, stock, part numbers | Sélection composants, BOM |
| `kicad` | aklofas/kicad-happy | 18 | KiCad patterns — conventions fichiers .kicad_pcb, .kicad_sch, pcbnew API | KiCad, fichiers PCB |
| `jlcpcb` | aklofas/kicad-happy | 17 | Commande JLCPCB — upload Gerbers, devis, paramètres fabrication | Commande fabrication |

---

## Skills Stack Layrix (installés depuis skills.sh)

| Skill | Source | Installs | Description | Invoquer quand |
|-------|--------|----------|-------------|----------------|
| `nextjs-supabase-auth` | sickn33 | 3.7K | Next.js + Supabase Auth — middleware, RLS, sessions, routes protégées | Auth, login, sessions |
| `turborepo` | vercel/turborepo | 13.7K | Turborepo monorepo — configuration, pipelines, packages partagés | Setup monorepo, packages |
| `bullmq-specialist` | davila7 | 180 | BullMQ + Redis — workers, queues, jobs, retry, concurrency | Files d'attente, jobs KiCad |
| `prompt-master` | nidhinjs | — | Optimisation prompts pour tout outil IA — matrice 9D, XML, signal words | Avant toute tâche (avec layrix-prompt-improver) |

---

## Skills everything-claude-code (globaux)

| Skill | Description | Invoquer quand |
|-------|-------------|----------------|
| `/everything-claude-code:frontend-patterns` | Patterns Next.js / React / Tailwind | UI, composants, pages |
| `/everything-claude-code:python-patterns` | Patterns Python / FastAPI | Microservice KiCad |
| `/everything-claude-code:postgres-patterns` | PostgreSQL / Supabase / pgvector | DB, migrations, RLS |
| `/everything-claude-code:claude-api` | Claude SDK / Anthropic API | Agents, tool_use, streaming |
| `/everything-claude-code:api-design` | Design endpoints REST | Nouvelles routes API |
| `/everything-claude-code:docker-patterns` | Docker, Dockerfile, compose | KiCad headless, services |
| `/everything-claude-code:deployment-patterns` | Vercel, Railway, DigitalOcean | Deploy, CI/CD |
| `/everything-claude-code:tdd` | Test-Driven Development | Avant chaque feature |
| `/everything-claude-code:e2e` | Tests E2E Playwright | Flows critiques |
| `/everything-claude-code:security-scan` | Audit sécurité | Avant commit (auth, paiement) |
| `/everything-claude-code:security-review` | Review sécurité complète | Avant merge |
| `/everything-claude-code:plan` | Planification feature | Feature complexe |
| `/everything-claude-code:save-session` | Sauvegarde session | Fin de session |
| `/everything-claude-code:resume-session` | Reprend session | Début de session |
| `/everything-claude-code:context-budget` | Gestion contexte | Contexte long |

---

## Agents globaux

| Agent | Description | Invoquer quand |
|-------|-------------|----------------|
| `code-reviewer` | Review qualité, bugs, sécurité | Après chaque implémentation |
| `security-reviewer` | Vulnérabilités, OWASP | Avant chaque commit |
| `build-error-resolver` | Erreurs de build TypeScript | Build cassé |
| `typescript-reviewer` | Review TypeScript strict | Code TS modifié |
| `python-reviewer` | Review Python / FastAPI | Code Python modifié |
| `refactor-cleaner` | Code mort, doublons | Maintenance |

---

## Comment ajouter un skill

### 1. Depuis everything-claude-code (priorité 1)
```bash
# Vérifier dans la liste des skills disponibles
# Invoquer directement : /everything-claude-code:nom-du-skill
```

### 2. Depuis skills.sh (priorité 2)
```bash
npx skills find "query"
npx skills add owner/repo@skill -g -y
# Puis ajouter dans ce fichier + CLAUDE.md
```

### 3. Créer avec skill-creator (priorité 3)
```bash
# Invoquer : /skill-creator:skill-creator
# Créer dans : .claude/skills/layrix-xxx.md
# Puis ajouter dans ce fichier + CLAUDE.md
```

---

## Historique des installations

| Date | Skill | Source | Raison |
|------|-------|--------|--------|
| 2026-03-28 | `layrix-pcb-agent` | skill-creator | Boucle agentique PCB Layrix |
| 2026-03-28 | `layrix-footprint` | skill-creator | Cascade 8 étapes footprint |
| 2026-03-28 | `layrix-kicad-service` | skill-creator | Microservice Python KiCad |
| 2026-03-28 | `layrix-viewer` | skill-creator | Viewer PixiJS + Three.js |
| 2026-03-28 | `layrix-credits` | skill-creator | Système crédits Supabase |
| 2026-03-28 | `layrix-drc` | skill-creator | Boucle DRC correction auto |
| 2026-03-28 | `layrix-prompt-improver` | skill-creator | Amélioration prompts Layrix |
| 2026-03-28 | `prompt-master` | nidhinjs/prompt-master | Optimisation prompts universelle |
| 2026-03-28 | `tscircuit` | tscircuit/skill | Moteur PCB <20 composants |
| 2026-03-28 | `eda-pcb` | l3wi/claude-eda | EDA/PCB général |
| 2026-03-28 | `jlcpcb-component-finder` | takazudo | Recherche composants LCSC |
| 2026-03-28 | `kicad` | aklofas/kicad-happy | KiCad patterns |
| 2026-03-28 | `jlcpcb` | aklofas/kicad-happy | Commande fabrication |
| 2026-03-28 | `nextjs-supabase-auth` | sickn33 | Auth Next.js + Supabase |
| 2026-03-28 | `turborepo` | vercel/turborepo | Monorepo Turborepo |
| 2026-03-28 | `bullmq-specialist` | davila7 | BullMQ + Redis queues |
