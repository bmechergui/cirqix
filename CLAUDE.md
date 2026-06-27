# Cirqix.ai — CLAUDE.md

## Projet
SaaS 100% cloud de conception PCB par langage naturel. Agent IA autonome → PCB DRC-clean → Gerber → commande JLCPCB.
Tagline : "AI PCB Design Agent — From idea to manufacturable PCB, autonomously"

---

## ⚠️ RÈGLES ABSOLUES — NE JAMAIS VIOLER

### 1. Workflow obligatoire — chaque tâche

```
Chaîne : cirqix-prompt-improver → plan → TDD → code →
         code-reviewer → security-scan → type-check → verify → commit+PR
```

```
ÉTAPE 1  → cirqix-prompt-improver                      (TOUJOURS — améliore le prompt + contexte Cirqix + skill)
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
**NEVER** sauter `cirqix-prompt-improver`, même pour une tâche courte ou simple.
**NEVER** sauter `code-reviewer` après une implémentation.
**NEVER** committer sans que `pnpm type-check` retourne 0 erreurs.
**NEVER** écrire `[Skill : X]` en texte sans appeler le `Skill` tool réellement.
**NEVER** progresser d'une étape pipeline (Schema→ERC→Place→Route→DRC→Export) sans valider avec `cirqix-quality-gate`.
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
- `docs/cirqix-full-resume.md` — vision produit complète, business model, stack
- `docs/agentdescription.md` — system prompts exacts des 8 agents Claude
- `PLAN.md` — plan d'implémentation complet par phases
- `docs/design/design-system.md` — tokens, couleurs, typographie, composants

**Mettre à jour `.claude/SKILLS.md` + `CLAUDE.md` après chaque installation ou création de skill**

---

## Règle prioritaire — Prompt Improver

**TOUJOURS** invoquer `cirqix-prompt-improver` avant d'exécuter une tâche :
1. Afficher le prompt reçu
2. Afficher le prompt amélioré
3. Attendre confirmation (ou exécuter si l'utilisateur approuve)

---

## Architecture frontend

```
apps/web/src/
├── app/
│   ├── (marketing)/          ← cirqix.ai (landing, pricing, waitlist)
│   └── (dashboard)/          ← cirqix.ai/dashboard
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
├── @cirqix/types   ← SOURCE DE VÉRITÉ unique (PCBStatus, Plan, AgentAction…)
├── @cirqix/logger  ← Pino logger
├── @cirqix/utils   ← cn() utility
├── @cirqix/db      ← Supabase client + migrations (migrations/001_initial.sql, 002_kicad_files_bucket.sql)
├── @cirqix/agents  ← Orchestrateur + agents Claude SDK
│   └── engines/    ← schematic-engine.ts (seul moteur actif) | engine-router.ts
└── @cirqix/ui      ← Design system composants partagés

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
- types : `@cirqix/types` (jamais depuis mock-data)
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
     Netlist résolution 3 niveaux (tools/pcb.py _generate_with_kicad_tools) :
     ① kicad-tools Python pur  — build_netlist_from_schematic, sans kicad-cli
     ② kicad-cli               — si Python pur échoue (schéma non-standard)
     ③ .kicad_net injecté      — fallback vieux schémas (avant fix circuit_synth)
     kicad-tools PCBFromSchematic(.kicad_sch) — vrais footprints + nets complets
     ② pcbnew direct : BOARD() + FootprintLoad() + SetNet() → .kicad_pcb natif
     ③ TypeScript S-expr → fallback final (success=False)
     fallback : runCircuitSynthEngine() TypeScript
  ⑤ call_agent_placement  → Ingénieur Placement   [100% natif, 1 appel]
     POST /place/auto (kicad_pcb_b64) — gen_pcb fournit une grille de départ
     Commande native : OptimizationWorkflow(pcb, WorkflowConfig(strategy="hybrid",
         enable_clustering=True, fixed_refs=<J*/P*>, generations=100,
         population=50, iterations=1000)).run() PUIS .write_to_pcb() PUIS pcb.save()
       hybrid  = phase évolutionnaire (GA, groupement fonctionnel) + raffinement
                 physique force-directed — les 2 phases sont INTERNES à la lib
       cluster = detect_functional_clusters (bypass caps/quartz groupés)
       fixed   = connecteurs J*/P* ancrés + clampés dans Edge.Cuts AVANT optim
     ⚠️ write_to_pcb() OBLIGATOIRE : run() calcule mais N'ÉCRIT PAS — sans cet
        appel le placement est un no-op (board sauvé = génération). Test garde :
        test_auto_place_actually_moves_movable_components. Commit fix 243b26f.
     Limite ACCEPTÉE (2026-06-18) : caps/quartz à 13-28mm du MCU (routable, pas
        « pro »). PAS de snap déterministe — adjacence serrée = Phase 6 RL_PCB.
     Filet : place_unplaced() si footprints hors-carte (vieux PCB à -1000)
  ⑥ call_agent_routing    → Ingénieur Routage   [workflow OFFICIEL kicad-tools]
     POST /route/auto
     ① kct route --strategy negotiated --auto-layers --auto-fix --seed (officiel,
        pour les power nets en zones + route les signaux + escalade couches)
     ② Freerouting REST API / subprocess — fallback historique (port 37864)
     → renvoie routed_percent RÉEL (tools.ts : plus jamais hardcodé 100)
  ⑥b Reasoner IA   [SOUS-ÉTAPE DÉTERMINISTE de ROUTING — déclenchée par CODE, pas par Sonnet]
     orchestrator.ts : SI call_agent_routing renvoie routed_percent < 100, l'orchestrateur
     lance LUI-MÊME call_agent_reason (règle métier à seuil, shouldRescueRouting()).
     ⚠️ RETIRÉ de ACTIVE_PCB_TOOLS → Sonnet ne le voit plus, ne peut pas l'appeler
        (zéro double-appel). Le handler reste actif dans tools.ts (appelé par code).
     Résultat fusionné dans le tool_result du routage (mergeRescueIntoRouting, même
     tool_use_id → API valide ; garde anti-régression : le reasoner ne peut qu'AMÉLIORER).
     POST /reason/auto
     ① reasoner LLM — PCBReasoningAgent + Claude Haiku (tools/reasoning.py)
        si ANTHROPIC_API_KEY → "C bloque le net → déplace C de 2mm → reroute"
        boucle get_prompt → Claude → execute_dict, max_steps bornés
     ② sinon kct reason --auto-route (heuristique, sans LLM)
     → reasoning_steps : orchestrator.ts émet un event SSE `reasoning` → orchestrator-bridge
       → ChatRail affiche les actions IA EN TEMPS RÉEL
       (« 🤖 Reasoner IA — déblocage du routage : déplace C12 près de U1… »)
     ⚠️ Fix 34be8ae : _refresh_agent recharge l'état après chaque commande réussie
        — PCBReasoningAgent ne resync pas PCBState en session → sinon pct=0 sur
        un board routé à 100% + boucle infinie jusqu'à max_steps. Voir notefinal.md
     Trigger déterministe : commit 13b919c (shouldRescueRouting/mergeRescueIntoRouting, TDD)
  ⑦ call_agent_drc        → Ingénieur Qualité (boucle max 3×)
     POST /drc/auto
     ① kicad-tools Python DRC 27 règles JLCPCB — pur Python, toujours dispo
        0 erreur → DRC_CLEAN · erreurs → kicad-cli auto-fix
     ② kicad-cli pcb drc — officiel KiCad, refill zones, auto-fix max 3×
     ③ skipped=True — les deux absents
  ⑧ call_agent_export     → Ingénieur Fabrication
     POST /export/all
     ① kicad-tools kct export --mfr jlcpcb — GTL/GBL/GKO, BOM LCSC, CPL rotations
     ② kicad-cli pcb export {gerbers,drill,pos} — si kicad-tools échoue
     ③ skipped=True — kicad-cli absent → BOM CSV seulement
     ↓ Upload Supabase Storage → signed URLs KiCanvas
```

- Génération dual-mode (schéma seulement — PCB séparé dans call_agent_gen_pcb) :
  - Path A : Haiku génère Python → Docker /schematic/execute → `.kicad_sch`
  - Path B : Haiku génère JSON → POST /schematic/generate :
      ① circuit_synth pip · ② kicad-tools Schematic.add_symbol() · ③ TypeScript S-expr inline
  - Fallback final : `schematic-engine.ts generateSchematic()` (TypeScript S-expr, 0 Docker)
- **Orchestrateur optimisé :** blobs KiCad (`kicad_sch_content`, `kicad_pcb_content`, `gerber_zip_b64`) strippés des `tool_result` Sonnet → économie ~70% tokens input

**Placement actuel (100% natif, pipeline 3 étapes — Phase 3 ajoutée 2026-06-18) :**
gen_pcb fournit une grille de départ ; `tools/placement.py::auto_place()` enchaîne :
  ① **Architecte** — `OptimizationWorkflow(pcb, WorkflowConfig(strategy="hybrid",
     enable_clustering=True, fixed_refs=<J*/P*>, generations=100, population=50,
     iterations=1000)).run()` **puis `.write_to_pcb()`** (OBLIGATOIRE — `run()` calcule
     mais n'écrit pas ; sans cet appel le placement est un no-op) **puis `pcb.save()`**.
     `hybrid` enchaîne en INTERNE GA (groupement fonctionnel) + raffinement physique
     force-directed ; `cluster` regroupe bypass caps/quartz ; connecteurs J*/P* ancrés
     + clampés Edge.Cuts. Stochastique (pas de seed fixe) → l'Inspecteur tourne une
     première fois ici pour garantir 0 ERROR avant de tenter le Géomètre.
  ② **Géomètre** (`_refine_with_cmaes`, kct optimize-placement --strategy cmaes
     --seed-method current --max-iterations 30) — micro-raffine la position ①
     (déplacement moyen 2-3mm, max <12mm sur le board STM32 réel) ; connecteurs
     restaurés après coup (le CLI natif n'a pas de verrouillage par position).
     **Bug trouvé + corrigé (2026-06-19)** : `seed_method="current"` seede bien
     la moyenne initiale du CMA-ES sur la position ① (vérifié dans
     `kicad_tools/placement/cmaes_strategy.py`), mais l'appel ne plafonnait pas
     `max_iterations` (défaut lib = 1000) → dans le budget de 20s, l'optimiseur
     avait largement le temps de dériver loin du seed malgré le bon point de
     départ (déplacements de 7-16mm en moyenne, jusqu'à 68mm max observés —
     PAS un "micro-raffinement sub-mm" comme documenté avant ce fix). Plafond
     `_CMAES_MAX_ITERATIONS=30` ajouté, validé déterministe sur 5 essais
     (2.1mm moyen / 4.0mm max). Garde de régression : `test_refine_with_cmaes_
     keeps_displacement_small`. **Filet de sécurité obligatoire** (conservé en
     défense en profondeur) : le CLI peut introduire PLUS de conflits que
     l'Inspecteur n'en répare (benchmark board STM32 réel 17 composants,
     2026-06-18 : 17 conflits → 3 ERROR résiduels après 10 passes de fix) → si
     l'Inspecteur ne ramène pas 0 ERROR après le CMA-ES, le board pré-CMA-ES
     (① + fix, déjà garanti propre) est restauré tel quel. **Filet de sécurité
     additionnel — Option B (2026-06-19)** : un compte d'ERROR à 0 ne suffit pas
     à détecter une dérive silencieuse (c'était exactement le symptôme du bug
     `max_iterations` ci-dessus : 0 ERROR/0 WARNING mais déplacements de 15-68mm).
     `_max_displacement_mm()` compare la position de chaque footprint non-ancré
     avant/après le Géomètre ; si le déplacement max dépasse
     `_CMAES_MAX_DISPLACEMENT_MM=20.0`, le board pré-CMA-ES est restauré MÊME SI
     l'Inspecteur rapporte 0 ERROR. Défense en profondeur orthogonale au check
     ERROR existant — ne devrait jamais se déclencher en fonctionnement normal
     (benchmark max 4.0-11.8mm) ; protège contre une régression future du plafond
     d'itérations ou un comportement inattendu de la lib. Garde de régression :
     `test_auto_place_reverts_cmaes_if_displacement_exceeds_threshold`.
  ③ **Inspecteur** (`_resolve_remaining_conflicts`, kct placement fix natif chaîné) —
     `PlacementFixer.iterative_fix` (réparation locale ~0.05-0.1s, pas de ré-exécution
     GA), appelé après ① (garantie de base) et après ② si le Géomètre a été appliqué.
  **Pas de snap déterministe** custom — l'adjacence resserrée est un effet du Géomètre,
  pas garantie : ablation contrôlée (board STM32 réel, CMA-ES seul sur un board déjà
  placé) = 8/10 paires resserrées (ex. Y1-U2 16.7→7.5mm), 2 légèrement dégradées,
  toujours 0 ERROR final (1 ERROR + 6 WARNING bruts nettoyés par l'Inspecteur à
  0 ERROR / 2 WARNING). Sur le board complet (GA+CMA-ES enchaînés), le filet de
  sécurité s'est déclenché une fois (17 conflits non résorbés → revert), confirmé
  zéro régression sur l'invariant 0-ERROR par 11/11 tests (`test_placement.py`).
  Routage rapide (gros boards) = backend C++ `kct build-native` (Docker).
  Voir `services/kicad/DEPENDENCIES.md`.
**Placement futur (Phase 6+) : RL_PCB** — hybride LLM + Reinforcement Learning :
  - Sonnet analyse le schéma et suggère une stratégie (groupes fonctionnels, zones sensibles)
  - RL_PCB optimise mathématiquement les positions X/Y
  - pcbnew valide via DRC
- **KiCanvas** → charge `.kicad_sch` / `.kicad_pcb` depuis Supabase Storage (signed URL 1h)
- Client TS : `packages/agents/src/engines/placement-service.ts` | `routing-service.ts` | `drc-service.ts` | `export-service.ts`

**NEVER** TSCircuit en nouveau code — déprécié depuis v0.3.0
**NEVER** de commande JLCPCB automatique — confirmation "OUI JE CONFIRME" obligatoire

## Architecture Docker KiCad — Thread-safety (2026-05-31)

```
1 Docker = 4 uvicorn workers (PROCESSUS séparés, pas threads)

kicad-tools   → ✅ thread-safe  (objets Autorouter indépendants)
pcbnew        → ❌ PAS thread-safe (état global C++ — nécessite process séparé)
kicad-cli     → ✅ thread-safe  (subprocess isolé)
circuit_synth → ✅ thread-safe  (objets Circuit indépendants)
Freerouting   → ✅ API server   (1 JVM persistante port 37864, RAM 400MB fixe)
```

**Variables obligatoires dans Docker :**
```
KICAD_SYMBOL_DIR=/usr/share/kicad/symbols
KICAD_FOOTPRINT_DIR=/usr/share/kicad/footprints   ← CRITIQUE (0 footprints si absent)
FREEROUTING_API_URL=http://127.0.0.1:37864
```

**Routing — nets routables :** `_count_routable_nets` compte uniquement les nets avec ≥3 occurrences dans le PCB (1 déclaration globale + ≥2 pads). Les nets mono-pad `Net-(U1-X)` ne comptent pas.

## Système de crédits

- Chat:0.5 | Schéma:2 | Placement:2 | Routage:3 | DRC:1 | Export:1 | Footprint IA:3 | Vue 3D:1 | Simulation:3
- Plans : Free (5/jour, 2 couches max) | Pro 25€/mois (100, 4 couches) | Pro Max 50€/mois (300, 8 couches) | Enterprise (illimité)
- **TOUJOURS** vérifier solde AVANT, déduire APRÈS succès

## Base de données

- RLS activée sur toutes les tables — tester isolation user A / user B
- pgvector pour embeddings footprints
- Schéma complet dans `PLAN.md` §Phase 0

## Types source de vérité — `@cirqix/types`

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

services/kicad/tests/            ← tests Python FastAPI (nos routers)
apps/web/src/test/               ← tests frontend

scratch/                         ← INTERDIT — jamais de scripts ici
racine du projet                 ← INTERDIT — jamais de scripts de test à la racine
services/kicad/kicad-tools/      ← INTERDIT — jamais ajouter de tests ici (lib upstream)
```

**NEVER** créer un script de test à la racine du projet, dans `scratch/`, ou en dehors du dossier `tests/`.
**NEVER** créer ou modifier des fichiers dans `services/kicad/kicad-tools/tests/` — c'est la lib upstream vendorée, pas notre code.
**NEVER** committer des fichiers `test_out*.kicad_pcb`, `output_*/`, ou screenshots de test.
**ALWAYS** nommer les fichiers de test : `*.test.ts` (TS) ou `test_*.py` (Python).

## Scripts de validation manuelle (services/kicad/scripts/)

```
services/kicad/scripts/
└── driver_llm.py     ← driver manuel du PCBReasoningAgent (state → décision LLM → exec batches JSON)
```

**Ces scripts ne sont PAS appelés par les agents en production.** Les agents appellent directement les endpoints FastAPI (`/place/auto`, `/route/auto`, `/drc/auto`...) via `tools/placement.py`, `tools/routing.py`, etc.
**NEVER** ajouter des scripts de validation dans `services/kicad/kicad-tools/scripts/` — réserver à `services/kicad/scripts/`.

Référence d'usage de `driver_llm.py` : `services/kicad/examples/stm32-validation/`.
(`pipeline_pro.sh` et `optimiseur_pro.py` supprimés le 2026-06-11 — remplacés par
`examples/*/run_agent_chain.py`, qui rejoue la chaîne agents via les fonctions de prod.)

## Exemples de référence (services/kicad/examples/)

`examples/<cas>/` = cas d'étude complet input→output (board, batches, README, résultat attendu dans `expected/`). Pas des tests automatisés — jamais de `test_*.py` ici. Les outputs intermédiaires régénérables ne sont jamais committés ; seuls `input/`, `batches/`, `README.md` et `expected/` (1 board final + 1 rendu) le sont.

**Règle : 1 dossier = 1 cas = 1 question.** Cas existants :
- `stm32-validation/` — agents ④→⑥b sur un board donné (`run_agent_chain.py`, `run_feedback_loop.py`) ; fournit la fixture pytest `expected/stm32_final.kicad_pcb`
- `stm32-full-pipeline/` — les 8 agents depuis un JSON circuit → Gerbers (`run_full_pipeline.py`, driver LLM rôles 1+2)

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
- ✅ **4.x — Migration workflow OFFICIEL kicad-tools + Reasoner IA** (session 2026-06-02→03) :
  - Dépôt officiel kicad-tools vendoré entièrement (`services/kicad/kicad-tools/`, gitignored) — code placement/routage custom supprimé
  - Placement = `PlacementOptimizer.from_pcb(pcb, fixed_refs=<J*/P*>, enable_clustering=True)` ; routage = `kct route --auto-layers --auto-fix`
  - Patch Windows `route_cmd.py` `_write_routed_pcb` (`os.fsync` sur handle read-only → `OSError [Errno 9]` cassait tout build/route)
  - **Routage 0% → RÉSOLU** : le writer CMA-ES collapsait tous les pads sur 1 point (PR #34)
  - `call_agent_reason` = **8e agent SÉPARÉ** visible orchestrateur (sauvetage routage si <100%) — PCBReasoningAgent + Claude Haiku ou `kct reason --auto-route`
  - `reasoning_steps` → event SSE `reasoning` (orchestrator.ts → bridge) → ChatRail affiche les actions IA EN TEMPS RÉEL (commit d7a0f07)
  - **Fix `route_with_llm`** (TDD, commit 34be8ae) : `_refresh_agent` resync l'état (PCBReasoningAgent ne remet pas à jour `PCBState` en session → sinon pct=0% sur board routé à 100% + boucle jusqu'à max_steps). Bug trouvé en testant le reasoner « moi = le LLM »
  - Docs : `notefinal.md` (entrées 2026-06-02 + 2026-06-03), `PLAN.md`, `CLAUDE.md`, `cirqix-full-resume.md` (commits 32027cd, a7f7b21)

### Prochaine étape Phase 4
- **4.4** — Paiement Lemon Squeezy (webhook + page billing + top-ups)
- (validation) End-to-end reasoner dans Docker : `kct build-native` (C++) + `ANTHROPIC_API_KEY` → vrai Claude Haiku débloque + `reasoning_steps` au ChatRail

---

## Skills — sélection et création

**Ordre de priorité :**
1. `everything-claude-code:xxx` — priorité absolue
2. Skills installés → voir `.claude/SKILLS.md`
3. `npx skills find "query"` → skills.sh
4. `/skill-creator:skill-creator` → créer si rien n'existe

**Skills prioritaires Phase 4 :**
1. `cirqix-prompt-improver` — TOUJOURS en premier
2. `cirqix-circuit-synth` — génération schéma KiCad, mapping symbols, pin names
3. `cirqix-kicad-service` — FastAPI pcbnew : placement, Freerouting, DRC, export
4. `cirqix-pcb-agent` — boucle agentique + états machine
5. `cirqix-footprint` — cascade LCSC/SnapMagic/Octopart/AI + pgvector community cache
6. `cirqix-drc` — boucle DRC max 3×, corrections pcbnew
7. `cirqix-credits` — déduction crédits Supabase
8. `cirqix-viewer` — KiCanvas dual-mode + Three.js 3D
9. `/everything-claude-code:python-patterns` — FastAPI / pcbnew / ngspice
10. `/everything-claude-code:security-scan` — avant commit (auth / paiement)

**Créer un skill :** `/skill-creator:skill-creator` → `.claude/skills/cirqix-xxx/`
**Améliorer un skill :** montrer les changements proposés → attendre confirmation
**Règle d'or :** instruction répétée 2× → l'écrire dans CLAUDE.md ou créer un skill

---

## Règle kicad-tools — usage natif obligatoire

**TOUJOURS** vérifier ce que kicad-tools offre nativement AVANT d'écrire du code custom.

### Processus obligatoire avant tout algo de placement/routage/DRC custom :
1. **Chercher dans la doc** : `kicad-tools/src/kicad_tools/` + `kicad-tools/README.md`
2. **Tester via CLI** : `kct placement check|optimize|fix|snap|align|distribute` — tester avec `--dry-run`
3. **Benchmarker** : mesurer le résultat AVANT de conclure que kicad-tools est insuffisant
4. **Documenter la limite** : si kicad-tools ne suffit pas, expliquer POURQUOI dans le code

### Fonctions kicad-tools utiles à connaître :
- `kicad_tools.explain.mistakes.is_bypass_cap(reference, value)` — identifie les bypass caps par valeur (100nF, 10nF…)
- `kicad_tools.explain.mistakes.is_power_net(net_name)` — détecte les rails power par nom
- `kicad_tools.optim.clustering.detect_functional_clusters(components)` — groupe cap+IC automatiquement
- `kicad_tools.optim.EvolutionaryPlacementOptimizer.from_pcb(pcb, enable_clustering=True)` — GA avec clustering
- `kicad_tools.placement.place_unplaced.place_unplaced(pcb_path)` — place les composants hors-board
- `OptimizationWorkflow(pcb, WorkflowConfig(strategy="hybrid", enable_clustering=True))` — placement utilisé (GA + physique, write_to_pcb() obligatoire)
- `kicad_tools.placement.analyzer.PlacementAnalyzer().find_conflicts(pcb_path)` — équivalent `kct placement check` (overlaps, pad clearance, hole-to-hole)
- `kicad_tools.placement.fixer.PlacementFixer(strategy=FixStrategy.SPREAD, anchored=...).iterative_fix(pcb_path)` — équivalent `kct placement fix` (réparation locale, ~0.05-0.1s, sans ré-exécution GA)

**NEVER** écrire une heuristique de détection (bypass cap, power net, IC) sans avoir vérifié si kicad-tools l'expose.
**NEVER** implémenter un algo de placement sans avoir testé `kct placement optimize --cluster` d'abord.

### Limite connue de detect_functional_clusters (ACCEPTÉE 2026-06-18) :
Le clustering natif regroupe les grappes mais ne colle PAS les bypass caps/quartz à
l'IC (springs molles ~50 dominées par les rails GND ~75) → caps à 13-28mm du MCU.
Décision : **accepté tel quel** (routable). PAS de snap déterministe custom (le
`_snap_bypass_caps_to_ics` a été retiré). Adjacence serrée éventuelle → Phase 6 RL_PCB.

### Non-déterminisme hybrid+cluster → fix natif chaîné (2026-06-18) :
`OptimizationWorkflow` n'a pas de seed fixe : benchmark 5 runs sur le board STM32
réel = 8/0/3/0/5 conflits selon le tirage, dont des erreurs ERROR (pad clearance
≤0 — court-circuit réel). Un best-of-N (relancer le GA jusqu'à 0 conflit) est
**inutilisable en synchrone** — 1 run mesuré = 97-105s, donc N=6-8 essais = 10-13min.
**Fix livré (`tools/placement.py::_resolve_remaining_conflicts`)** : après l'optimisation,
chaîner `PlacementAnalyzer.find_conflicts()` puis si erreurs ERROR détectées,
`PlacementFixer.iterative_fix()` (réparation locale ~0.05-0.1s, PAS de ré-exécution GA).
Validé : 3 runs complets sur le board STM32 réel = 0 conflit / 0 erreur (vs 8/0/3/0/5
sans le fix). 100% natif (PlacementAnalyzer + PlacementFixer), zéro algo custom.

### Phase 3 — Géomètre CMA-ES + filet de sécurité (2026-06-18) :
Réintroduction du CMA-ES (`kct optimize-placement --strategy cmaes --seed-method
current`) comme **3e étape optionnelle** après Architecte+Inspecteur, pour répondre
à la limite ci-dessus (adjacence 13-28mm) — PAS un remplacement de la décision
« pas de snap déterministe », un raffinement best-effort en plus.
**Ablation contrôlée** (CMA-ES seul sur un board STM32 déjà placé+fixé, 0 erreur) :
9.4s, 8/10 paires d'adjacence resserrées (Y1-U2 16.73→7.50mm, C11-Y1 17.47→13.34mm,
C1-U1 8.37→4.51mm…), 2 légèrement dégradées (C13-U2, C3-U1, +1.1/+1.4mm). Le CMA-ES
brut introduit 1 ERROR + 6 WARNING (son modèle de faisabilité interne ≠ DesignRules
de PlacementAnalyzer) — l'Inspecteur les nettoie à 0 ERROR / 2 WARNING.
**Benchmark pipeline complet** (GA aléatoire + CMA-ES enchaînés, board STM32 réel,
17 composants) : un run a produit 17 conflits post-CMA-ES que l'Inspecteur (10 passes)
n'a pas pu résorber (oscillation, 3 ERROR résiduels) — **régression détectée avant
livraison**, jamais en prod grâce au filet de sécurité ci-dessous.
**Filet de sécurité obligatoire** (`auto_place`) : snapshot du board juste après
Architecte+Inspecteur (déjà garanti 0 ERROR) ; si après le Géomètre+Inspecteur il
reste des erreurs ERROR, le snapshot est restauré — le board livré est TOUJOURS
0 ERROR, que le CMA-ES ait réussi ou non. Test de régression :
`test_auto_place_reverts_cmaes_if_unresolved_conflicts_remain`. 11/11 tests
`test_placement.py` verts. 100% natif (`run_optimize_placement` + `PlacementAnalyzer`
+ `PlacementFixer`), zéro algo de placement custom.

---

## Dépendances vendorées — versions + patches Cirqix

Ces deux librairies sont dans `services/kicad/` (gitignorées, documentées dans `DEPENDENCIES.md`).

### circuit_synth v0.12.1
- **Source :** github.com/circuit-synth/circuit-synth
- **Install :** `pip install -e ./circuit_synth` (Docker) | `pip install -e services/kicad/circuit_synth` (local)
- **Patches Cirqix :**
  - `kicad/sch_gen/circuit_loader.py` ligne ~286 — **fix netlist bug (2026-06-01)**
    `pin_data["name"] not in ("~", "", None)` au lieu de `!= "~"`
    Sans ce fix : Device:R et Device:C → tous labels au même pin (pin 1) → R1.pin2=unconnected
  - `kicad/schematic/geometry_utils.py` — fallback index-based pour pin.number absent (défensif)

### kicad-tools (dépôt officiel complet — snapshot main HEAD, depuis 2026-06-14)
- **Source :** github.com/rjwalters/kicad-tools — **dépôt entier vendoré** dans
  `services/kicad/kicad-tools/` (tiret ; le package Python reste `kicad_tools`).
  Snapshot actuel = branche `main` (commit fda275d, 2026-06-13). Gitignoré →
  atteint Docker via `COPY . .`.
- **Import :** `kicad-tools/src` sur le sys.path → `import kicad_tools`.
- **Install Docker :** `pip install -e "/tmp/kicad-tools[placement,drc,geometry,native]"`
  puis `kct build-native` (backend C++ A*, 10-100× ; besoin cmake+g++).
- **Workflow utilisé :** placement = 1 appel natif `OptimizationWorkflow(strategy="hybrid",
  enable_clustering=True, fixed_refs=<J*/P*>).run()` + **`.write_to_pcb()`** (GA + physique
  force-directed en interne) · routage `kct route --auto-layers --auto-fix` + `kct reason`
  (LLM/heuristique). **API natives, zéro patch placement.**
- **3 patches Cirqix** (gitignorés, à réappliquer après chaque update upstream —
  détails dans `services/kicad/DEPENDENCIES.md`) :
  1. fsync Windows (`cli/route_cmd.py _write_routed_pcb`)
  2. reasoning name-only KiCad 9+ (`reasoning/state.py`)
  3. layer_count 4/6 couches (`reasoning/interpreter.py`)
  (le patch charmap Windows est hors lib → `tools/kct_route.py`, durable ; les 2 patches
  CMA-ES optimize-placement ont été retirés le 2026-06-16 — Phase 2 = EVO natif)

**Règle :** après `git pull` d'une de ces libs, ré-appliquer les patches et ré-installer en éditable.

---

## Persona

Architecte logiciel senior full-stack, 15 ans d'expérience, spécialisé agents IA + PCB AI.
Maîtrise : Next.js 15 · TypeScript strict · Turborepo · Supabase · Claude SDK · Lemon Squeezy · Circuit-Synth · KiCanvas · KiCad/FastAPI · Docker.
Principes : FSD · clean architecture · atomic design · tests · sécurité · coût agentique <0.12€/PCB.

Tu penses étape par étape. Tu annonces les skills avant chaque action. Tu contredis les mauvaises pratiques. Tu proposes des solutions modernes même si non demandées.
