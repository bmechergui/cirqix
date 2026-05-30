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
**NEVER** progresser d'une étape pipeline (Schema→ERC→Place→Route→DRC→Export) sans valider avec `layrix-quality-gate`.
**NEVER** accepter ERC skipped, composants non connectés, DRC violations comme "OK" — corriger ou documenter explicitement.

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
- `docs/agentdescription.md` — system prompts exacts des 8 agents Claude
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
│   └── viewer/               ← ViewerPanel + KiCanvasViewer + PixiCanvas + Three.js 3D
├── entities/
│   ├── project/              ← Project, PCBStatus
│   ├── pcb/                  ← PCBState, DRCViolation, AgentStep
│   └── credits/              ← Credits, Plan, CREDIT_COSTS
├── shared/
│   ├── ui/                   ← shadcn/ui components
│   ├── lib/                  ← mock-data.ts, supabase-middleware.ts
│   ├── store/                ← app-store.ts (Zustand)
│   └── types/                ← kicanvas.d.ts (web component declarations)
├── middleware.ts              ← Auth Supabase JWT — protège /dashboard/*
├── processes/                ← (Phase 3+ — boucle agentique UI)
└── entities/                 ← (modèles métier)

packages/
├── @layrix/types   ← SOURCE DE VÉRITÉ unique (PCBStatus, Plan, AgentAction…)
├── @layrix/logger  ← Pino logger
├── @layrix/utils   ← cn() utility
├── @layrix/db      ← Supabase client + migrations (migrations/001_initial.sql, 002_kicad_files_bucket.sql)
├── @layrix/agents  ← Orchestrateur + agents Claude SDK
│   └── engines/    ← schematic-engine.ts (seul moteur actif) | engine-router.ts
└── @layrix/ui      ← Design system composants partagés

services/
└── kicad/          ← FastAPI Python headless KiCad
    ├── routers/schematic.py      ← /schematic/execute + /generate + /validate-symbols → .kicad_sch
    ├── routers/pcb.py            ← /pcb/generate → .kicad_pcb
    ├── routers/placement.py      ← POST /place (explicit) + POST /place/auto (base64 I/O)
    ├── routers/routing.py        ← POST /route/auto (Freerouting, base64 I/O)
    ├── routers/drc.py            ← POST /drc/auto (kicad-cli, boucle auto-fix, base64 I/O)
    ├── routers/export.py         ← POST /export/all (Gerbers + drill + CPL, zip base64)
    ├── routers/erc.py            ← POST /erc (kicad-cli sch erc, auto-fix loop)
    └── tools/      ← schematic.py | pcb.py | placement.py | routing.py | drc.py | export.py
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
- Agents : Claude SDK — Orchestrateur Sonnet 4.6 + 8 agents Haiku 4.5
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

## Stratégie moteur PCB (état actuel — Phase 4)

### Pipeline complet opérationnel — 8 agents experts

```
User → Sonnet 4.6 (orchestrateur, max 15 itérations, SSE)
  ① call_agent_schema     → Ingénieur Schéma
     Haiku 4.5 → Path A : Python circuit_synth → Docker /schematic/execute → .kicad_sch
     Haiku 4.5 → Path B : JSON → POST /schematic/generate :
       ① circuit_synth pip · ② kicad-tools Schematic · ③ TypeScript S-expr
     Stocke : kicad_sch_content dans _pcbStateCache
  ② call_agent_erc        → Ingénieur ERC
     ① kicad-tools Schematic.validate() — pur Python, toujours dispo
     ② kicad-cli sch erc — ERC officiel (si dispo), auto-fix no_connect max 3×
     ③ skipped=true → TypeScript runErcFallback()
     POST /erc → kicad-cli sch erc, auto-fix loop
  ③ call_agent_footprint  → Ingénieur Composants (1 appel par ref dans unresolved_footprints)
     Cascade : KiCad libs → pgvector → LCSC → SnapMagic → AI Haiku
     Met à jour _pcbStateCache[projectId].schema.components[ref].footprint
  ④ call_agent_gen_pcb      → Ingénieur Layout — génère .kicad_pcb
     ① kicad-tools PCBFromSchematic(.kicad_sch) — vrais footprints + nets complets
     ② pcbnew direct : BOARD() + FootprintLoad() + SetNet() → .kicad_pcb natif
     ③ TypeScript S-expr → fallback final (success=False)
     fallback : runCircuitSynthEngine() TypeScript
  ⑤ call_agent_placement  → Ingénieur Placement
     POST /place/auto (kicad_pcb_b64)
     ① kicad-tools CMA-ES place_unplaced(cluster=True, margin=1.5mm) — cluster-by-net
     ② pcbnew grille simple : LoadBoard() + SetPosition() 15mm step
     ③ status:'error' si Docker down (fail fast)
     fallback : pcbnew grille simple
  ⑥ call_agent_routing    → Ingénieur Routage
     runRealRouting() → POST /route/auto
       Path 1 : Freerouting Java .dsn → .ses → .kicad_pcb (tous les circuits)
       Path 2 : kicad-tools Python A* négocié (fallback Java absent, ≤10 nets, 60s)
     fallback : routing-fallback.ts (MST pur TS)
  ⑦ call_agent_drc        → Ingénieur Qualité (boucle max 3×)
     runRealDRC() → POST /drc/auto
       Path 1 : kicad-cli pcb drc (officiel, auto-fix, base64 I/O)
       Path 2 : kicad-tools Python DRC 27 règles JLCPCB (fallback kicad-cli absent)
  ⑧ call_agent_export     → Ingénieur Fabrication
     runRealExport() → POST /export/all (Gerbers + drill + CPL, zip base64)
     ↓ Upload Supabase Storage → signed URLs KiCanvas
```

- Génération dual-mode (schéma seulement — PCB séparé dans call_agent_gen_pcb) :
  - Path A : Haiku génère Python → Docker /schematic/execute → `.kicad_sch`
  - Path B : Haiku génère JSON → POST /schematic/generate :
      ① circuit_synth pip · ② kicad-tools Schematic.add_symbol() · ③ TypeScript S-expr inline
  - Fallback final : `schematic-engine.ts generateSchematic()` (TypeScript S-expr, 0 Docker)
- **Orchestrateur optimisé :** blobs KiCad (`kicad_sch_content`, `kicad_pcb_content`, `gerber_zip_b64`) strippés des `tool_result` Sonnet → économie ~70% tokens input

**Placement actuel :** kicad-tools `place_unplaced` CMA-ES (cluster=True, margin 1.5mm) → fallback pcbnew grille simple
**Placement futur (Phase 6+) : RL_PCB** — hybride LLM + Reinforcement Learning :
  - Sonnet analyse le schéma et suggère une stratégie (groupes fonctionnels, zones sensibles)
  - RL_PCB optimise mathématiquement les positions X/Y
  - pcbnew valide via DRC
- **KiCanvas** → charge `.kicad_sch` / `.kicad_pcb` depuis Supabase Storage (signed URL 1h)
- Client TS : `packages/agents/src/engines/placement-service.ts` | `routing-service.ts` | `drc-service.ts` | `export-service.ts`

**NEVER** TSCircuit en nouveau code — déprécié depuis v0.3.0
**NEVER** de commande JLCPCB automatique — confirmation "OUI JE CONFIRME" obligatoire

## Système de crédits

- Chat:0.5 | Schéma:2 | Placement:2 | Routage:3 | DRC:1 | Export:1 | Footprint IA:3 | Vue 3D:1 | Simulation:3
- Plans : Free (5/jour, 2 couches max) | Pro 25€/mois (100, 4 couches) | Pro Max 50€/mois (300, 8 couches) | Enterprise (illimité)
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
- `PCBState` inclut `kicad_sch_url?` + `kicad_pcb_url?` — signed URLs Supabase Storage (1h) pour KiCanvas

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

## Organisation des tests

**TOUJOURS** placer les scripts de test dans le dossier `tests/` du package concerné :

```
packages/agents/src/engines/     ← code source
packages/agents/src/tests/       ← tests unitaires *.test.ts

services/kicad/tests/            ← tests Python
apps/web/src/test/               ← tests frontend

scratch/                         ← INTERDIT — jamais de scripts ici
racine du projet                 ← INTERDIT — jamais de scripts de test à la racine
```

**NEVER** créer un script de test à la racine du projet, dans `scratch/`, ou en dehors du dossier `tests/`.
**NEVER** committer des fichiers `test_out*.kicad_pcb`, `output_*/`, ou screenshots de test.
**ALWAYS** nommer les fichiers de test : `*.test.ts` (TS) ou `test_*.py` (Python).

---

## Variables d'environnement requises

`ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `REDIS_URL`, `LEMON_SQUEEZY_API_KEY`, `KICAD_SERVICE_URL`

## Phase actuelle

**Phase 4 — 3D + JLCPCB + Paiement** (en cours). Voir `PLAN.md`.

Phases complétées : Phase 0 ✓ · Phase 1 ✓ · Phase 2 ✓ · Phase 3 ✓ · Phase 4.1 ✓ · **Phase 4.2 ✓ · Phase 4.3 ✓**

### Phase 2 — Réalisations ✅
- ✅ Auth Supabase + middleware JWT (`/dashboard/*`)
- ✅ Chat + Viewer split layout (ChatPanel + ViewerPanel)
- ✅ Orchestrateur Sonnet 4.6 + SSE streaming
- ✅ Haiku 4.5 → JSON schema avec pin names KiCad
- ✅ `validateAndCorrectSchema()` + `/circuit-synth/validate-symbols`
- ✅ Circuit-Synth Python → `.kicad_sch` + `.kicad_pcb` natifs
- ✅ `_safe_symbol()` — 2ème filet sécurité symboles inconnus
- ✅ Bucket `kicad-files` Supabase Storage + signed URLs
- ✅ KiCanvas viewer — auto-switch tab Schematic/Routing à l'arrivée SSE
- ✅ Crédits déduction atomique Supabase RPC

### Phase 3 — Réalisations ✅
- ✅ FastAPI `POST /place/auto` → pcbnew `SetPosition()` / `SetOrientationDegrees()` (base64 I/O)
- ✅ FastAPI `POST /route/auto` → Freerouting `.kicad_pcb → .dsn → .ses → .kicad_pcb` (base64 I/O)
- ✅ FastAPI `POST /drc/auto` → kicad-cli DRC natif, boucle auto-fix max 3× (base64 I/O)
- ✅ FastAPI `POST /export/all` → Gerbers + drill + CPL, zip base64
- ✅ FastAPI `POST /erc` → kicad-cli ERC schéma, auto-fix loop
- ✅ Client TS : `placement-service.ts` | `routing-service.ts` | `drc-service.ts` | `export-service.ts`
- ✅ Fallbacks : `erc-fallback.ts` (placement-fallback.ts supprimé — fail fast)
- ✅ Auto-placement : kicad-tools CMA-ES → fallback pcbnew grille
- ✅ Agent Footprint cascade pgvector community cache (étape 1.5) + 4 étapes KiCad/SnapMagic/LCSC/AI
- ✅ Tests unitaires : `placement-service.test.ts` | `drc-service.test.ts` | `routing-service.test.ts` | etc.

### Phase 4 — Réalisations ✅
- ✅ **4.1** Viewer 3D Three.js (composants colorisés par type, board FR4, OrbitControls, 1 crédit Pro+)
- ✅ **4.2** Simulation ngspice : `POST /simulate/auto` + `call_agent_simulation` + `SimulationView` Recharts
  - kicad-cli SPICE export → ngspice batch → parsing tabular → vecteurs V/A
  - Fallback : waveformes RC synthétiques si ngspice indisponible
  - Onglet "Simulate" dans Timeline (FlaskConical), 3 crédits, plan Pro+
- ✅ **4.3** Export réel + JLCPCB :
  - `call_agent_export` dans `pcbStateTools` → SSE → frontend reçoit `gerberZipB64` + `bomCsv` + `quoteUsd`
  - Téléchargements Gerbers (blob base64) et BOM CSV réels dans ExportView
  - `POST /api/jlcpcb/order` : guard `z.literal(true)` + validation DRC_CLEAN + orderRef
  - Footprints professionnels dans `kicad_gen.py` : géométrie réelle par type (DIP-8, SOT-23, 0402…)
  - Net assignments sur chaque pad → Freerouting route correctement
  - placement : kicad-tools CMA-ES → fallback pcbnew grille
- ✅ **4.x — Refactor nommage + optimisation tokens** (session 2026-05-26) :
  - `circuit-synth-engine.ts` → `schematic-engine.ts` (évite confusion avec pip package)
  - `CircuitSynthRequest/Response` → `SchematicRequest/Response` dans le router Python
  - `schematic_gen.py` → `kicad_gen.py` (le fichier gère sch + pcb, pas que le schéma)
  - `circuit_synth` pip installé dans Docker via `pip install ./circuit_synth` + PYTHONPATH fix
  - `orchestrator.ts` : strip blobs KiCad des `tool_result` → économie ~70% tokens Sonnet (≈ $0.86 → ~$0.25/run)
- ✅ **4.x — Pipeline 8 agents experts** (session 2026-05-26) :
  - `call_agent_gen_pcb` créé — sépare génération PCB `.kicad_pcb` de la génération schéma `.kicad_sch`
  - `call_agent_erc` intégré dans le pipeline obligatoire (entre schéma et footprint)
  - `call_agent_footprint` met à jour `_pcbStateCache` avec footprint résolu par ref
  - `prompts.ts` entièrement réécrit : Orchestrateur = "Chef de Projet PCB Senior 15 ans d'expérience"
  - `tools.ts` : descriptions expertes pour chaque agent (Ingénieur Schéma, ERC, Composants, Layout…)
  - `orchestrator.ts` : `stepMap` mis à jour (`call_agent_gen_pcb → 'KICAD'`), `pcbStateTools` étendu
  - Bug `_resolve_pin` Python 3 corrigé (`UnboundLocalError` scope exception variable)
  - Stratégie connecteurs Path B : ESP32 → `Conn_02x19_Odd_Even`, Arduino → `Conn_02x15_Odd_Even`
  - Validation Path A : rejet silencieux si Haiku retourne du texte au lieu de Python circuit_synth
  - kicad_gen.py → split : `routers/schematic.py` + `routers/pcb.py` + `tools/schematic.py` + `tools/pcb.py`
  - `placement_layout.py` supprimé → kicad-tools CMA-ES primaire + pcbnew grille fallback
  - `placement-fallback.ts` supprimé → fail fast si service Docker down
  - `call_agent_kicad` renommé `call_agent_gen_pcb` + appelle POST /pcb/generate
- ✅ **4.x — Fix génération schéma** (session 2026-05-29) :
  - `generateSchemaWithHaiku` : `max_tokens 2048 → 4096` — JSON tronqué pour circuits complexes causait fallback sur faux schéma hardcodé
  - `call_agent_schema` Path A : prompt Haiku corrigé (`os.chdir(_PROJECT_PATH)` + `project_name="project"`) — ancienne version passait le chemin comme nom de projet → Docker échouait silencieusement
  - `call_agent_schema` Path C : pour `complexity='complex'`, retourne maintenant une `{status:'error'}` au lieu du faux schéma "2 IC · 15 passives · 11 nets"
  - Logs améliorés : Path A log `success=false` Docker + Path B log `stop_reason=max_tokens`
  - **Cause racine** : les 3 chemins échouaient en cascade → `parseSchemaFromDescription('complex')` retournait `ESP32 + LDO + 15×100nF` hardcodé

### Prochaine étape Phase 4
- **4.4** — Paiement Lemon Squeezy (webhook + page billing + top-ups)

---

## Skills — sélection et création

**Ordre de priorité :**
1. `everything-claude-code:xxx` — priorité absolue
2. Skills installés → voir `.claude/SKILLS.md`
3. `npx skills find "query"` → skills.sh
4. `/skill-creator:skill-creator` → créer si rien n'existe

**Skills prioritaires Phase 4 :**
1. `layrix-prompt-improver` — TOUJOURS en premier
2. `layrix-circuit-synth` — génération schéma KiCad, mapping symbols, pin names
3. `layrix-kicad-service` — FastAPI pcbnew : placement, Freerouting, DRC, export
4. `layrix-pcb-agent` — boucle agentique + états machine
5. `layrix-footprint` — cascade LCSC/SnapMagic/Octopart/AI + pgvector community cache
6. `layrix-drc` — boucle DRC max 3×, corrections pcbnew
7. `layrix-credits` — déduction crédits Supabase
8. `layrix-viewer` — KiCanvas dual-mode + Three.js 3D
9. `/everything-claude-code:python-patterns` — FastAPI / pcbnew / ngspice
10. `/everything-claude-code:security-scan` — avant commit (auth / paiement)

**Créer un skill :** `/skill-creator:skill-creator` → `.claude/skills/layrix-xxx/`
**Améliorer un skill :** montrer les changements proposés → attendre confirmation
**Règle d'or :** instruction répétée 2× → l'écrire dans CLAUDE.md ou créer un skill

---

## Persona

Architecte logiciel senior full-stack, 15 ans d'expérience, spécialisé agents IA + PCB AI.
Maîtrise : Next.js 15 · TypeScript strict · Turborepo · Supabase · Claude SDK · Lemon Squeezy · Circuit-Synth · KiCanvas · KiCad/FastAPI · Docker.
Principes : FSD · clean architecture · atomic design · tests · sécurité · coût agentique <0.12€/PCB.

Tu penses étape par étape. Tu annonces les skills avant chaque action. Tu contredis les mauvaises pratiques. Tu proposes des solutions modernes même si non demandées.
