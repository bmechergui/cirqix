# Cirqix — Registre des Skills

> Fichier de référence : tous les skills utilisés dans ce projet.
> Mettre à jour après chaque installation ou création de skill.
> Référencé dans `CLAUDE.md`.

---

## Skills Cirqix (locaux — `.claude/skills/`)

| Skill | Fichier | Description | Invoquer quand |
|-------|---------|-------------|----------------|
| `cirqix-prompt-improver` | `cirqix-prompt-improver/SKILL.md` | Améliore le prompt reçu : contexte Cirqix de la phase en cours (lu dans `CLAUDE.md` et `PLAN.md`), choix du skill | **En premier, à chaque tâche** |
| `cirqix-pcb-agent` | `cirqix-pcb-agent/SKILL.md` | Boucle agentique PCB : Orchestrateur Sonnet, 15 itérations max, états INITIAL→PCB_LIVRÉ, SSE streaming, Redis | Agent / Orchestrateur / Boucle PCB |
| `cirqix-footprint` | `cirqix-footprint/SKILL.md` | Cascade `findFootprint` : bibliothèque KiCad → cache pgvector → SnapMagic → LCSC → génération Haiku 4.5, puis repli générique | Footprint manquant / librairie |
| `cirqix-kicad-service` | `cirqix-kicad-service/SKILL.md` | FastAPI Python + pcbnew headless : placement, Freerouting, DRC, export Gerbers, Docker, BullMQ | KiCad / placement / routage / export |
| `cirqix-viewer` | `cirqix-viewer/SKILL.md` | KiCanvas (.kicad_sch + .kicad_pcb natifs, `controls="full"`) + 3D par GLB (`Board3DView`) + rendus PNG kicad-cli | Viewer PCB / schéma / rendu KiCanvas / 3D |
| `cirqix-credits` | `cirqix-credits/SKILL.md` | Déduction atomique Supabase RPC, plans Free/Pro/Pro Max, top-ups, webhook Lemon Squeezy, UI badge | Crédits / plans / paiement |
| `cirqix-drc` | `cirqix-drc/SKILL.md` | Chaîne DRC réelle : `POST /drc/auto`, kicad-cli fait foi, auto-correction ≤ 3× dans le service, fail-closed, aucun modèle ; markers viewer | DRC / violations / correction PCB |
| `cirqix-frontend-verify` | `cirqix-frontend-verify/SKILL.md` | Diagnostic visuel read-only : screenshots Chrome DevTools (3 breakpoints — 375px/768px/1440px), détecte chevauchements/overlaps/layout cassé, rapport structuré + corrections Tailwind | **APRÈS chaque modification UI** — responsive broken / overlap / visuel à valider |
| `cirqix-circuit-synth` | `cirqix-circuit-synth/SKILL.md` | Génération `.kicad_sch` via circuit_synth Python : `@circuit` pattern, mapping symbol (Device:R/Timer:NE555P/etc.), KICAD_SYMBOL_DIR setup, erreurs classiques + fixes, router FastAPI primary/fallback | **Toute génération schéma KiCad** — circuit_synth, mapping symbol, pin names, setup libs |
| `cirqix-quality-gate` | `cirqix-quality-gate/SKILL.md` | Grille de validation entre les étapes du pipeline PCB (Schema → ERC → Place → Route → DRC → Export) | Après chaque étape du pipeline, avant d'avancer |

---

## Skills PCB / Hardware (installés depuis skills.sh)

| Skill | Source | Installs | Description | Invoquer quand |
|-------|--------|----------|-------------|----------------|
| `tscircuit` | tscircuit/skill | 313 | TSCircuit — moteur PCB React-like, déprécié depuis v0.3.0 | Jamais en nouveau code (`CLAUDE.md`) ; seulement pour lire un ancien code TSCircuit |
| `eda-pcb` | l3wi/claude-eda | 93 | EDA/PCB général — schémas, netlists, conventions électroniques | Schéma électronique, netlist |
| `jlcpcb-component-finder` | takazudo | 28 | Recherche composants LCSC/JLCPCB — prix, stock, part numbers | Sélection composants, BOM |
| `kicad` | aklofas/kicad-happy | 18 | KiCad patterns — conventions fichiers .kicad_pcb, .kicad_sch, pcbnew API | KiCad, fichiers PCB |
| `jlcpcb` | aklofas/kicad-happy | 17 | Commande JLCPCB — upload Gerbers, devis, paramètres fabrication | Commande fabrication |

---

## Skills Stack Cirqix (installés depuis skills.sh)

| Skill | Source | Installs | Description | Invoquer quand |
|-------|--------|----------|-------------|----------------|
| `nextjs-supabase-auth` | sickn33 | 3.7K | Next.js + Supabase Auth — middleware, RLS, sessions, routes protégées | Auth, login, sessions |
| `turborepo` | vercel/turborepo | 13.7K | Turborepo monorepo — configuration, pipelines, packages partagés | Setup monorepo, packages |
| `bullmq-specialist` | davila7 | 180 | BullMQ + Redis — workers, queues, jobs, retry, concurrency | Files d'attente, jobs KiCad |
| `prompt-master` | nidhinjs | — | Rédaction de prompts pour d'autres outils IA (matrice 9D, XML) | Sur demande, pour un prompt destiné à un outil tiers — pas avant chaque tâche (le contexte Cirqix passe par `cirqix-prompt-improver`) |

---

## Skills d'analyse du code

| Skill | Source | Description | Invoquer quand |
|-------|--------|-------------|----------------|
| `graphify` | safishamsi/graphify | Knowledge graph AST, relations inter-fichiers, requêtes `query`, `path` et `explain` | Question d'architecture ou « qui appelle quoi » ; jamais pendant un banc ou une mesure (~1 Go par requête) |

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
| `/everything-claude-code:security-scan` | Audit de la configuration Claude Code (AgentShield) : `CLAUDE.md`, settings, hooks, MCP | Après une modification de `.claude/`, de `CLAUDE.md` ou des MCP — pas pour le code auth/paiement (agent `security-reviewer`) |
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
# Créer dans : .claude/skills/cirqix-xxx/SKILL.md
# Puis ajouter dans ce fichier + CLAUDE.md
```

---

## Historique des installations

| Date | Skill | Source | Raison |
|------|-------|--------|--------|
| 2026-03-28 | `cirqix-pcb-agent` | skill-creator | Boucle agentique PCB Cirqix |
| 2026-03-28 | `cirqix-footprint` | skill-creator | Cascade 8 étapes footprint |
| 2026-03-28 | `cirqix-kicad-service` | skill-creator | Microservice Python KiCad |
| 2026-03-28 | `cirqix-viewer` | skill-creator | Viewer PixiJS + Three.js |
| 2026-03-28 | `cirqix-credits` | skill-creator | Système crédits Supabase |
| 2026-03-28 | `cirqix-drc` | skill-creator | Boucle DRC correction auto |
| 2026-03-28 | `cirqix-prompt-improver` | skill-creator | Amélioration prompts Cirqix |
| 2026-03-28 | `prompt-master` | nidhinjs/prompt-master | Optimisation prompts universelle |
| 2026-03-28 | `tscircuit` | tscircuit/skill | Moteur PCB <20 composants |
| 2026-03-28 | `eda-pcb` | l3wi/claude-eda | EDA/PCB général |
| 2026-03-28 | `jlcpcb-component-finder` | takazudo | Recherche composants LCSC |
| 2026-03-28 | `kicad` | aklofas/kicad-happy | KiCad patterns |
| 2026-03-28 | `jlcpcb` | aklofas/kicad-happy | Commande fabrication |
| 2026-03-28 | `nextjs-supabase-auth` | sickn33 | Auth Next.js + Supabase |
| 2026-03-28 | `turborepo` | vercel/turborepo | Monorepo Turborepo |
| 2026-03-28 | `bullmq-specialist` | davila7 | BullMQ + Redis queues |
| 2026-07-19 | `graphify` | safishamsi/graphify | Navigation du monorepo par knowledge graph |
