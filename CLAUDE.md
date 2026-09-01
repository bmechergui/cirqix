# Cirqix.ai — CLAUDE.md

> **Source canonique transitoire.** Les règles projet, l’architecture et les
> contraintes métier Cirqix sont maintenues ici une seule fois. Les adaptateurs
> des autres assistants ne doivent pas en conserver une copie divergente.

## Collaboration multi-agent

Avant toute tâche partagée, parallèle ou reprise depuis un autre assistant :

1. Lire `docs/agents/COLLABORATION.md`.
2. Lire le handoff concerné dans `docs/agents/handoffs/`.
3. Vérifier la branche, le content commit, le head Git courant, le diff et les
   résultats de validation annoncés.
4. Ne modifier que les chemins explicitement transférés ou revendiqués.
5. Si l’assistant est l’owner, mettre à jour le handoff avant de rendre la
   main ; sinon, transmettre ses constats à l’owner sans modifier le fichier.

Le handoff transporte l’état du travail ; il ne remplace jamais Git, les tests,
les quality gates ni les règles de sécurité de ce fichier.

## Worktrees — la chaîne worktree → branche → commit

Tout travail mené dans un worktree doit reposer sur une **branche nommée**, et
tout ce qui compte doit finir en **commit**. Un worktree peut techniquement être
en `detached HEAD` : c’est acceptable pour une inspection jetable — lire un vieil
état, comparer deux révisions — jamais pour du travail destiné à durer.

```
worktree  →  branche nommée  →  commit  →  push
```

Un `detached HEAD` n’est référencé par rien : la sortie du worktree suffit à
rendre les commits invisibles, et seul le reflog les retient, ~90 jours.
Une branche nommée, elle, survit à la suppression du worktree.

**Le worktree est un plan de travail, pas un lieu de stockage.** Ce qui n’est pas
commité y est invisible pour tout le monde — y compris pour l’assistant qui
reprendra le sujet, puisque `git log` et `git diff` ne montrent rien.

Mesuré le 2026-08-09 en vidant 12 worktrees de `C:\tmp` :
- **4 handoffs** n’existaient que là, absents de `main` (`git cat-file -e`) —
  dont le compte rendu d’une PR fusionnée le jour même ;
- **4 fichiers de test** dans le même état ;
- **42 fichiers modifiés** dans un worktree dont le `git stash` échouait, sauvés
  par un patch de 173 ko.

Tout cela partait à la première suppression de dossier.

**ALWAYS** créer la branche AVANT de commencer : `git worktree add <chemin> -b <branche>`.
**ALWAYS** committer un handoff dans le dépôt, pas seulement dans le worktree qui l’a produit.
**ALWAYS** vérifier `git status` d’un worktree avant de le supprimer — et sauvegarder ce qui n’est pas ailleurs.
**NEVER** laisser du travail durable en `detached HEAD`.
**NEVER** considérer qu’un worktree conserve quoi que ce soit : seul un commit poussé conserve.

Rappel utile : `MERGED` ne veut pas dire « sur `main` » (une PR peut viser une
autre branche), et `git merge-base --is-ancestor` renvoie faux pour une branche
parfaitement intégrée, puisque les PR sont fusionnées en **squash**. Vérifier le
**contenu**, pas la parenté.

## Projet
SaaS 100% cloud de conception PCB par langage naturel. Agent IA autonome → PCB DRC-clean → Gerber → commande JLCPCB.
Tagline : "AI PCB Design Agent — From idea to manufacturable PCB, autonomously"

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- Before the first codebase question in a session, run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/graphify-refresh.ps1 -Mode Ensure`; it rebuilds only stale graphs and refreshes the aggregate when needed.
- Use Graphify by default before source browsing. Select `graphify-out/graph.json` for Cirqix SaaS, `graphify-out/scopes/kicad-tools/graphify-out/graph.json` for `kicad-tools`, `graphify-out/scopes/circuit-synth/graphify-out/graph.json` for `circuit_synth`, and `graphify-out/full-graph.json` for a search spanning all three corpora. Pass non-default graphs with `--graph`.
- Run `graphify query "<question>"` first. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run the refresh script with `-Mode Root`, `-Mode KicadTools`, `-Mode CircuitSynth`, or `-Mode All` according to the owned paths. It updates the affected graph and regenerates the aggregate.
- `full-graph.json` is an aggregate of three disconnected components: it supports common search but does not invent cross-repository edges for `graphify path`.

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

### 2. Niveau de planification — voir `.claude/rules/planning.md`

### 3. Autonomie bornée (révisée le 2026-08-30)

Claude mène l'EXÉCUTION. Les DÉCISIONS PRODUIT appartiennent à l'utilisateur.

**Autonome (sans validation) — technique et réversible :**
- Bug fixes, câblage, refactor, tests, documentation technique
- Si une tâche bloque → proposer 2 solutions et choisir la meilleure
- Si un skill manque → `npx skills find "query"` puis `/skill-creator:skill-creator`

**Validation obligatoire AVANT exécution — décision produit :**
- Stratégie de placement/routage (ordre des moteurs, levier d'optimisation)
- Tout seuil chiffré qui change le comportement livré (budgets GA, `_SEUIL_REDRAW_PCT`,
  `_CAPACITE_ECHAPPEMENT`, paliers de couches…)
- Lever ou rétablir une limite précédemment acceptée
- Gate de sécurité, droits liés au plan, comportement de facturation
- Toute décision d'architecture (`architect` agent → proposition, jamais application directe)

Chaque décision produit est journalisée dans `docs/DECISIONS.md` avec son statut
(`validée` / `en attente`). **NEVER** marquer `validée` sans validation explicite de
l'utilisateur dans la conversation. **NEVER** implémenter une décision `en attente`.
Une mesure peut étayer une proposition ; elle ne la valide pas.

### 4. Git workflow — voir `.claude/rules/git.md`

---

## Fichiers de référence

- `.claude/SKILLS.md` — registre de tous les skills (description + quand invoquer)
- `docs/cirqix-full-resume.md` — vision produit complète, business model, stack
- `docs/agentdescription.md` — system prompts exacts des 8 agents Claude
- `PLAN.md` — plan d'implémentation complet par phases
- `docs/design/design-system.md` — tokens, couleurs, typographie, composants
- `docs/graphify.md` — graphes séparés Cirqix, `kicad-tools`, `circuit_synth` et agrégat multi-repo.
  Question d'architecture / « qui appelle quoi » → interroger le graphe d'abord
  (`graphify query|path|explain`, skill `graphify`) au lieu de grepper.
  Le hook SessionStart appelle `scripts/graphify-refresh.ps1 -Mode Ensure`; le
  watcher PID-géré utilise `-Mode Watcher`. Après modification, choisir `-Mode Root`,
  `-Mode KicadTools`, `-Mode CircuitSynth` ou `-Mode All` selon les chemins touchés.

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
│   ├── engines/    ← schematic-engine.ts (seul moteur actif) | engine-router.ts
│   └── tools/      ← definitions.ts + index.ts + handlers/* (12 handlers : schema, erc, footprint, gen-pcb, placement, routing, reason, drc, export, simulation, misc, schema-haiku) — ex-tools.ts refactoré
└── @cirqix/ui      ← Design system composants partagés

services/
└── kicad/          ← FastAPI Python headless KiCad
    ├── routers/schematic.py      ← /schematic/generate + /validate-symbols → .kicad_sch
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

- Monorepo Turborepo : `apps/web` (frontend + API routes), `packages/agents`, `packages/ui`, `packages/db`, `services/kicad`
- Frontend : Next.js 15 + Tailwind + shadcn/ui + Zustand
- Backend MVP : Next.js API Routes dans `apps/web/src/app/api/` (⚠️ `apps/api/` est une coquille vide héritée — ne rien y créer)
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
     Haiku 4.5 → JSON typé → POST /schematic/generate :
       ① circuit_synth pip · ② kicad-tools Schematic · ③ TypeScript S-expr
     Stocke : kicad_sch_content dans _pcbStateCache
  ② call_agent_erc        → Ingénieur ERC
     ① kicad-tools Schematic.validate() — pur Python, toujours dispo
     ② kicad-cli sch erc — ERC officiel (si dispo), auto-fix no_connect max 3×
     ⚠️ (2026-08-20) `parse_erc_report` exigeait un `violations` de PREMIER
        NIVEAU — la forme du rapport DRC. `kicad-cli sch erc --format json`
        (schéma `erc.v1`) range les siennes sous `sheets[].violations` : le
        parseur levait à CHAQUE exécution, `POST /erc` renvoyait 500, et l'ERC
        d'autorité n'a JAMAIS rendu un verdict en production — seul
        `runErcFallback()` travaillait. Le fail-closed a tenu (rien de faux
        promu `ERC_CLEAN`), mais le contrôle principal était mort. Les deux
        formes sont acceptées désormais ; une forme inconnue lève toujours.
        Vérifié sur un vrai rapport : 40 violations parsées là où le parseur
        levait. Garde : tests/test_fail_closed_drc_erc.py.
     ③ skipped=true → TypeScript runErcFallback()
     POST /erc → kicad-cli sch erc, auto-fix loop
     ⚠️ (2026-07-27) `ERC_CLEAN` ne peut être accordé que par un contrôle
        réellement exécuté et réellement passé. Auparavant `skipped` figurait dans
        le OU qui promeut `ERC_CLEAN`, et l'absence de `.kicad_sch` en cache
        renvoyait `ERC_CLEAN` — deux validations sans le moindre contrôle.
        Désormais : `skipped` bascule sur `runErcFallback()` (ERC TypeScript RÉEL
        — refs dupliquées, nets flottants, GND manquant, composants non
        connectés) et son verdict fait foi ; on n'échoue que si lui-même n'a rien
        à contrôler. Contrairement au routage/DRC/export, le repli n'est donc PAS
        un fail fast : il existe ici un vérificateur de secours légitime.
        Garde : tests/handler-erc.test.ts.
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
     ⚠️ 3 bugs de CÂBLAGE corrigés le 2026-07-27, tous invisibles aux tests
        mockés (les mocks reproduisaient l'hypothèse du client, pas la réalité du
        service) et révélés par `packages/agents/src/tests/pipeline-live.test.ts`,
        premier test à faire tourner la chaîne TS contre le service réel :
        1. `handlePlacement` RÉGÉNÉRAIT le board via le générateur TS
           (`runPCBEngine`), écrasant celui que `gen_pcb` venait de produire — que
           le service ne parvenait même pas à parser (`500 ParseError`). Il
           utilise désormais le board du cache, comme `handleRouting`.
        2. `PLACEMENT_TIMEOUT_MS` valait 10 s pour une étape mesurée à 34-45 s :
           le placement expirait SYSTÉMATIQUEMENT en production. Porté à 180 s.
           (`ROUTING_TIMEOUT_MS` 90 s → 330 s pour la même raison : le service
           s'accorde 300 s.)
        3. `/place/auto` renvoyait `{ref, x, y}` alors que son propre modèle de
           réponse et le client TS documentent `{ref, x_mm, y_mm}` : le client
           filtrait TOUTES les positions et `placements` sortait vide.
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
     ⚠️ **LA LIMITE « 13-28 mm » EST LEVÉE (2026-08-29).** Elle était acceptée
        depuis le 2026-06-18 faute de levier ; le levier existait, inutilisé :
        `FunctionalCluster.max_distance_mm`, que le clustering natif calcule
        déjà et que PERSONNE ne faisait respecter. Le GA ne peut pas y arriver
        seul — sa fonction de coût est une longueur de fil globale que les
        rails GND dominent (ressort ~75 contre ~50 pour un cluster), et aucun
        réglage n'en dévie. Le snap n'optimise donc rien : il APPLIQUE une
        règle. Voir « Snap bypass » plus bas.
     Filet : place_unplaced() si footprints hors-carte (vieux PCB à -1000)
     ⚠️ **UN RAPPORT DRC VIDE SE LISAIT « 0 ERREUR » (2026-08-27).** Le board
        sorti du placement portait des valeurs de keepout entre guillemets —
        l'écriture de `kicad_tools`. KiCad refuse alors le fichier ENTIER. Le
        défaut était déjà réparé, mais dans le seul CHARGEUR pcbnew : `kicad-cli`
        est un SECOND lecteur, sans ce filet, et répondait `Failed to load board`
        **avec rc=0**, sans écrire de rapport. `_rapport_drc_placement` rendait
        `{}`, et `_compter_conflits_erreur` y lisait zéro conflit.
        Mesuré sur l'ESP32 du banc, même board, trois étapes :

        | étape | rapport | lu comme |
        |---|---|---|
        | board PLACÉ | vide | 0 erreur |
        | après `_expand_stackup` | vide | 0 erreur |
        | après coulée + `_fill_zones` | **20 erreurs** (12 `courtyards_overlap`) | 20 |

        Les vingt erreurs étaient dans le board placé **depuis le début**. Le
        passage par pcbnew ne les CRÉAIT pas — il les RÉVÉLAIT, en réparant à la
        lecture et en réécrivant un fichier lisible. J'ai accusé la coulée du
        plan de masse plusieurs heures pour cette raison.
        Entre les deux, la boucle de re-tirage acceptait au premier tirage un
        board condamné, et la chaîne routait 25 min dessus. C'est l'explication
        complète de l'instabilité ESP32 : **la boucle était correcte, on lui
        mentait.**
        Corrigé à la SOURCE : la règle vit dans `tools/sexp_quote.py`, aux côtés
        de son symétrique `quote_bare_property_values`, et le placement répare
        AVANT de mesurer et de rendre. `_rapport_drc_placement` lève
        `DrcInexecutable` au lieu de rendre `{}`, et le compteur rend une
        sentinelle qui force le re-tirage.
        **NEVER** réparer un défaut de format chez un lecteur : on en oublie
        toujours un, et sa cécité passe pour un verdict favorable.
        Gardes : `tests/test_keepout_a_la_source.py`, `tests/test_drc_ne_ment_jamais.py`.
  ⑥ call_agent_routing    → Ingénieur Routage   [workflow OFFICIEL kicad-tools]
     POST /route/auto
     ① kct route --strategy negotiated --auto-layers --auto-fix --seed (officiel,
        pour les power nets en zones + route les signaux + escalade couches)
     ② Freerouting REST API / subprocess — fallback historique (port 37864)
     → renvoie routed_percent RÉEL (tools/handlers/routing.ts : plus jamais hardcodé 100)

     **SÉQUENCE À L'INTÉRIEUR D'UN PALIER** (demandée par l'utilisateur, livrée
     le 2026-08-29) — `routers/routing.py::route_auto`, pour chaque palier :

        ① plan de masse COULÉ ET REMPLI, sur les deux faces extérieures
        ② vias d'échappement réservés (déclarés dans le DSN)
        ③ routage des signaux (GND est confié au plan, `_NETS_CONFIES_AU_PLAN`)
        ④ replacement des vias réservés (le round-trip Specctra les efface)
        ⑤ plans re-coulés + remplis, fanout des pastilles isolées
        ⑥ couture des îlots de plan, RÉPÉTÉE jusqu'à épuisement

     ⚠️ **LE PLAN EST COULÉ AVANT LE ROUTAGE, PAS APRÈS.** On le coulait après :
     le routeur ne voyait donc jamais le cuivre de masse et routait comme si la
     carte était vide. Mesure sur la Nucleo, même placement : 68-71 % (plan
     après) contre 94 % (plan avant). C'est ce seul changement d'ordre qui a
     débloqué le 100 % sur six cartes du banc.

     ⚠️ Un plan **non rempli** n'est qu'un contour, dont le routeur ne tient
     aucun compte — même défaut que le 2026-08-23. `_fill_zones` est obligatoire.

     ⚠️ La couture se RÉPÈTE : joindre deux îlots de plan en révèle un troisième.
     Une passe unique laissait des îlots. Garde : `tests/test_couture_repetee.py`.

     ⚠️ **LE NOMBRE D'ÎLOTS N'EST PAS UN CRITÈRE DE CONNECTIVITÉ** (2026-08-30).
     `_PLAN_FRAGMENTE_AU_DELA = 2` et l'avertissement « plan de masse FRAGMENTÉ »
     mesurent la qualité de la RÉFÉRENCE DE RETOUR, jamais la connectivité — et
     rien ne l'écrivait. Analyse géométrique du board `stm32-100` **livré à
     100 %, 0 connexion manquante, 0 erreur** :

         GND  F.Cu  6 îlots   ·   B.Cu  1 îlot
         151 vias  →  25 GND, dont **0 borgne**, 126 hors plan

     (« borgne » = via posé dans un îlot mais ne touchant le cuivre de son net
     que sur UNE couche — il ne relie rien. Il n'y en a aucun.)

     Une carte parfaitement connectée et fabricable porte donc **six** îlots.
     Le tirage à 99 % de la même carte en avait 5 à 9 : **le compte ne
     distingue pas le succès de l'échec.** Ce qui les distingue est le rapport
     DRC — « 1 net incomplet ; net(s) : GND » — et c'est le seul critère
     recevable.

     J'ai moi-même lu cet avertissement comme un diagnostic et cherché la panne
     dans la couture pendant une heure ; un agent délégué a proposé « coudre
     jusqu'à ≤ 1 îlot » sur la même lecture. C'est la faute déjà inscrite plus
     haut : **NEVER** relayer le message d'une garde comme un diagnostic.

     ⚠️ Défaut latent voisin, non corrigé : `_router_en_incluant_gnd` remplace
     le board **sans jamais comparer**. C'est le seul mécanisme de la chaîne
     dépourvu de garde « ne peut qu'améliorer » — un secours moins bon
     écraserait un meilleur résultat. Il ne s'est encore jamais déclenché.

     **ESCALADE DES COUCHES** — méthode demandée : tirages au palier courant,
     puis +2 couches, en gardant TOUJOURS le meilleur (jamais le dernier).

        `_layer_ladder`            2, 4, 6, 8 … jusqu'au plafond du plan
        `_TIRAGES_ROUTAGE_PAR_PALIER = 3`   Freerouting est STOCHASTIQUE
        `_palier_meilleur`         classe sur (pourcentage, erreurs DRC)
        `_escalade_epuisee`        arrêt après 2 paliers entiers sans gain

     ⚠️ Freerouting est stochastique : 65, 77 et 91 % sur le MÊME board placé de
     la Nucleo. Un palier jugé insuffisant ne l'était peut-être que ce tirage-là
     — et on montait d'une couche pour rien, ce qui coûte plus cher à fabriquer.
     Un seul tirage par palier était donc un pari, pas une mesure.

     ⚠️ **NE PAS RE-TIRER UN PALIER HORS D'ATTEINTE** (`_SEUIL_REDRAW_PCT = 80`,
     2026-08-29). `stm32-100` (100 composants, 208×156 mm) n'a JAMAIS essayé
     4 couches : ses trois tirages à 2 couches ont consommé les 3600 s —
     60 %, 70 %, puis « budget épuisé avant le Niveau 4 ». Verdict rendu : 70 %,
     27 connexions manquantes. Le budget n'était pas trop court, il a été
     dépensé au mauvais endroit.
     Le seuil se DÉDUIT de l'écart mesuré entre tirages (26 points au plus, cf.
     Nucleo) : `100 - 26 = 74`, on prend 80. À 91 % le rattrapage est mesuré, on
     ne coupe pas dessus. Garde : `tests/test_escalade_precoce.py`.

     ⚠️ Un **ZÉRO ne déclenche pas l'escalade** : « 0 % (aucun moteur) » n'est
     pas un verdict de routage mais une panne. Monter d'une couche là-dessus
     reviendrait à payer du cuivre pour un défaut d'infrastructure.

     ⚠️ **LE PALIER DE DÉPART SE DÉDUIT DU BOARD** (`_couches_pour_echapper`,
     2026-08-29). L'échelle ne commence plus toujours à 2. `stm32-100` brûlait
     45 minutes sur un palier qu'aucun tirage ne pouvait réussir.

     La cause est **LOCALE, pas globale** — et le journal Freerouting la
     désigne sans ambiguïté. Sur trois jobs, **un seul composant porte 20 à
     28 % des échecs de connexion**, les 85 autres 2 % chacun : le LQFP-48, et
     sa part égale sa part des connexions. Ce n'est donc ni la taille de la
     carte (mon hypothèse, fausse), ni la dispersion du placement, ni un
     réglage du routeur : c'est l'**échappement d'un boîtier fine-pitch** —
     36 signaux à sortir d'un 7 × 7 mm au pas de 0,5 mm.

     Capacité calibrée sur nos cartes, `_CAPACITE_ECHAPPEMENT = 3.0` signaux
     par côté et par couche :

     | carte | signaux | /côté | couches | ok | C requis |
     |---|---|---|---|---|---|
     | stm32-baseline | 7 | 1.8 | 2 | oui | 0.88 |
     | esp32-baseline | 7 | 1.8 | 2 | oui | 0.88 |
     | stm32-30 | 13 | 3.2 | 4 | oui | 0.81 |
     | arduino-uno | 2 | 0.5 | 2 | oui | 0.25 |
     | nucleo-f401 | 37 | 9.2 | 4 | oui | 2.31 |
     | stm32-60 | 26 | 6.5 | 4 | oui | 1.63 |
     | **stm32-100** | **36** | **9.0** | **2** | **NON** | **4.50** |

     Les réussites exigent C ≥ 2,31, l'échec C < 4,50. On prend 3,0, qui
     reproduit **en plus** le besoin réel de 4 couches de `stm32-60`.

     ⚠️ **Les nets confiés au plan ne comptent PAS.** Ils sortent par-dessous,
     pas latéralement ; les compter ajouterait 58 signaux sur `stm32-100` et
     ferait démarrer TOUTES les cartes trop haut — on vendrait des couches
     inutiles. Et le **plafond du plan reste maître** : un compte Free est
     limité à 2 couches, on ne lui en vend pas 4 parce que ça routerait mieux.

     C'est un **PLANCHER, pas une prédiction** : il dit ce qui est hors
     d'atteinte, jamais ce qui suffira. L'escalade garde le dernier mot.

     ⚠️ Deux défauts dans la première version, tous deux trouvés en vérifiant
     sur de VRAIS boards — jamais par les tests unitaires, qui passaient :
     **une pastille n'est pas une liaison** (chaque pastille porte un net, y
     compris les orphelines nommées `Net-(U1-Pad3)` : tout LQFP-48 rendait
     ~45 signaux et `stm32-baseline` se voyait imposer 4 couches) ; et la
     **calibration était faite sur `circuit.json` quand le code lit le board**
     — 43 signaux d'un côté, 36 de l'autre, écart suffisant pour laisser
     `stm32-100` redémarrer à 2. Gardes : `tests/test_palier_plancher.py`.

     ⚠️ **NEVER partager le budget entre les essais.** Essayé le 2026-08-28 :
     1800 s / 12 essais = 150 s chacun, trop court pour router 100 composants —
     TOUS les paliers à 0 %, contre 96 % avec le budget entier. Chaque essai
     reçoit tout le restant ; sur une carte rapide il n'en prend que 40 s.

     **Temps mesuré (2026-08-29)** — le routage n'est lent que sur les grandes
     cartes, et le nombre de couches n'y est pour rien :

        17 composants, 2 couches    31,7 s   100 %
        17 composants, 4 couches    33,6 s   100 %
       100 composants, 2 couches   ~1700 s   60-70 %

     6× plus de composants coûtent 38× plus de temps — l'espace de recherche
     d'un routeur croît avec la SURFACE × le nombre de nets. `stm32-100` fait
     324 cm², dix fois les autres. Piste non encore mesurée : le générateur
     dimensionne la carte au NOMBRE de composants sans lire leur encombrement,
     donc une carte de 100 passifs est essentiellement vide — et ce vide se paie
     en cases de grille explorées, sans rien apporter.
     ⚠️ FAIL FAST (2026-07-27) : si le service est injoignable ou renvoie skipped,
        handleRouting retourne `status:'error'` — PAS un `routed_percent: 100` avec
        un simple plan de masse comme avant. L'ancien repli désarmait à la fois
        shouldRescueRouting ET shouldRetryPlacement (pourcentage fantôme) et faisait
        enchaîner Sonnet sur DRC/export en annonçant « routé à 100% » un board sans
        aucune piste. Le cache n'est plus écrasé par le board non routé. Même contrat
        que handlePlacement. Gardes : tests/handler-routing.test.ts (describe
        « fail fast quand aucun routage n'a eu lieu »).
  ⑥b Reasoner IA   [SOUS-ÉTAPE DÉTERMINISTE de ROUTING — déclenchée par CODE, pas par Sonnet]
     orchestrator.ts : SI call_agent_routing renvoie routed_percent < 100, l'orchestrateur
     lance LUI-MÊME call_agent_reason (règle métier à seuil, shouldRescueRouting()).
     ⚠️ RETIRÉ de ACTIVE_PCB_TOOLS → Sonnet ne le voit plus, ne peut pas l'appeler
        (zéro double-appel). Le handler reste actif dans tools/handlers/reason.ts (appelé par code).
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
     ⚠️ RETRY PLACEMENT PILOTÉ PAR LE DRC (2026-07-27) — jumelle du retry
        routage : `shouldRetryForDrc`/`keepBestDrc` dans orchestrator.ts. Le
        re-tirage déterministe n'était armé que par `routed_percent < 100`, or un
        board peut être routé à 100 % ET refusé par le DRC. Mesuré sur
        `examples/led-blinker-full-pipeline` : 3 tirages GA à 100 % routé donnent
        0, 12 et 4 violations — le placement est stochastique et sans seed, donc
        re-tirer est le levier. Anti-régression : un board clean l'emporte
        toujours ; à égalité, le moins de violations. Pas de retry sur
        `status:'error'` (re-placer ne répare pas un service éteint).
     ① kicad-tools 27 règles JLCPCB — pré-filtre seulement, ne court-circuite
        JAMAIS kicad-cli (faux négatif mesuré 2026-07-04 : 25 courts invisibles)
     ② kicad-cli pcb drc — TOUJOURS exécuté si dispo, fait foi, auto-fix max 3×
     ③ skipped=True — les deux absents
     ⚠️ FAIL FAST (2026-07-27) : `DRC_CLEAN` ne peut être émis QUE par un DRC
        réellement exécuté ET réellement propre. Les 3 chemins qui renvoyaient
        auparavant `pcb_status:'DRC_CLEAN'` + `drc_clean:true` sans qu'aucun DRC
        n'ait tourné (pas de PCB en cache · `skipped` · service en erreur, dont
        `KICAD_SERVICE_URL` non configurée) renvoient désormais `status:'error'`.
        Enjeu : orchestrator-bridge persiste `pcb_status` dans `projects.status`
        et `POST /api/jlcpcb/order` autorise la commande dès que le statut vaut
        `DRC_CLEAN` — un DRC fantôme débloquait donc une commande JLCPCB réelle
        sur un board jamais validé. Garde : tests/handler-drc.test.ts
        (describe « jamais DRC_CLEAN sans DRC exécuté »).
     ⚠️ `local-pipeline.ts` (repli sans orchestrateur, sur erreur crédit/402)
        écrivait un statut CODÉ EN DUR par étape, en ignorant le résultat du
        handler : un DRC en erreur — ou trouvant de vraies violations — était
        malgré tout persisté `DRC_CLEAN`. Le handler fait foi désormais
        (`pcb_status` prioritaire, `status:'error'` interrompt la chaîne sans
        rien persister). Garde : apps/web/src/test/local-pipeline.test.ts.
  ⑧ call_agent_export     → Ingénieur Fabrication
     POST /export/all
     ① kicad-tools kct export --mfr jlcpcb — GTL/GBL/GKO, BOM LCSC, CPL rotations
     ② kicad-cli pcb export {gerbers,drill,pos} — si kicad-tools échoue
     ③ skipped=True — kicad-cli absent → BOM CSV seulement
     ⚠️ FAIL FAST (2026-07-27) : `PCB_LIVRÉ` ne peut être émis QUE par un export
        ayant réellement produit des fichiers. Les 3 chemins dégradés (pas de PCB
        en cache · `skipped` · service en erreur) renvoyaient `PCB_LIVRÉ` — statut
        qui fait AUSSI partie du gate de `POST /api/jlcpcb/order` — et deux d'entre
        eux FABRIQUAIENT `gerber_layers: 7` + `quote_usd: 12.5`, un prix inventé
        présenté comme réel, avec une note invitant à répondre « OUI JE CONFIRME ».
        ExportView distingue pourtant déjà un vrai devis d'un placeholder
        (`quoteIsReal = state.quoteUsd != null`) : le montant fabriqué défaisait
        cette logique. Ces chemins renvoient `status:'error'` ; le `bom_csv` est
        conservé (donnée réelle dérivée du schéma), sans promotion de statut.
        Garde : tests/handler-export.test.ts.
     ↓ Upload Supabase Storage → signed URLs KiCanvas
```

- Génération du schéma (PCB séparé dans call_agent_gen_pcb) :
  - Haiku génère un JSON typé → POST /schematic/generate :
      ① circuit_synth pip · ② kicad-tools Schematic.add_symbol() · ③ TypeScript S-expr inline
  - Fallback final : `schematic-engine.ts generateSchematic()` (TypeScript S-expr, 0 Docker)
- **Orchestrateur optimisé :** blobs KiCad (`kicad_sch_content`, `kicad_pcb_content`, `gerber_zip_b64`) strippés des `tool_result` Sonnet → économie ~70% tokens input

**Placement actuel (100% natif, 5 étapes — snap ajouté le 2026-08-29) :**
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
     ⚠️ **S'exécute dans un PROCESSUS ENFANT** (`tools/cmaes_runner.py`, appelé
     par `_run_cmaes_in_subprocess`) depuis le 2026-07-27. `run_optimize_placement`
     installe des handlers de signal dès son entrée, or `signal.signal` est
     interdit hors thread principal — et uvicorn exécute `auto_place` dans un
     thread de worker. En appel direct, `ValueError: signal only works in main
     thread of the main interpreter` tombait AVANT toute itération : le filet de
     sécurité conservait le board pré-CMA-ES et **le Géomètre ne tournait JAMAIS
     en production**, alors que ses tests passaient (pytest, thread principal).
     Mesuré en conteneur en validant `examples/led-blinker-full-pipeline/`.
     Le CLI `kct optimize-placement` ne convient PAS comme substitut — mais
     ⚠️ **plus pour la raison longtemps écrite ici.** On lisait que son parseur
     n'acceptait que `--seed force-directed|random` et que `seed_method="current"`
     était un patch Cirqix réservé à l'API Python. **C'est faux depuis le rebase
     du 2026-08-10** : upstream accepte `--seed force-directed|random|current` et
     implémente le warm-start lui-même (`_read_current_vector` +
     `config.extra["mean"]`, avec validation de forme et clamp aux bornes).
     La vraie raison, la seule, est le `signal.signal` ci-dessus : le sous-
     processus n'est pas un contournement du CLI, c'est un contournement du
     thread. Ne pas « simplifier » `cmaes_runner.py` en repassant au CLI.
     Garde de régression : `test_refine_with_cmaes_works_off_the_main_thread`
     (exécute le raffinement dans un `threading.Thread`).
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
  ④ **Halo d'escape** (`_reserve_escape_halos`, 5 mm) — écarte les voisins mobiles
     des boîtiers fine-pitch (≥16 pads) pour dégager leur canal de sortie. No-op
     sur une carte sans composant dense.
  ⑤ **Snap bypass** (`tools/placement_bypass.py::snap_cluster_members`) — TÉLÉPORTE
     chaque membre de cluster à portée de son ancre, puis l'Inspecteur repasse.
     Détection 100 % native (`detect_functional_clusters`) ; le plafond lu est
     celui du cluster, jamais une constante : POWER 3 mm · TIMING 5 · DRIVER 6 ·
     INTERFACE 8. Mesure sur `examples/stm32-validation/output/2_placement` :
     **8 règles violées sur 9 avant, 0 après** ; écart libre moyen 7,2 → 4,7 mm.

     ⚠️ **L'ORDRE EST CONTRAINT DES DEUX CÔTÉS**, et c'est tout l'intérêt.
     Avant le Géomètre, le snap serait défait — le CMA-ES reprend sa fonction de
     coût et renvoie la capa au loin. Avant le halo, défait aussi — le halo
     écarte précisément ces voisins-là. Le snap vient donc en DERNIER des
     déplacements, et **connaît le halo** : sur une ancre dense il garde les
     5 mm du canal d'escape au lieu de le reboucher. Sans cela : deux correctifs
     qui se combattent, comme le clamp et le centrage des dominants le 2026-08-27.

     ⚠️ La distance se mesure entre les **CORPS**, jamais entre les origines.
     L'origine d'un module est sur sa pastille 1 — courtyard ESP32-WROOM :
     y de -30,74 à +10,51. « Coller à 3 mm de l'origine » poserait la capa EN
     PLEIN DANS le module. `_boite_locale_fp` porte déjà ce décalage, ce qui rend
     l'« offset courtyard » inutile comme étape distincte.

     ⚠️ **Limite connue, non corrigée.** `FunctionalCluster` n'a qu'UNE ancre :
     rien ne contraint la distance entre deux MEMBRES. Sur le board STM32 les
     capas de charge du quartz restent à 5,6 et 10,2 mm de Y1 (et à 15,1 mm
     l'une de l'autre) alors qu'elles devraient le serrer à 2-3 mm : la règle
     native est respectée, l'intention électrique ne l'est pas. Prochain levier :
     ancrer les membres d'un cluster TIMING sur Y1, et utiliser `anchor_pin`
     (déjà exposé, jamais lu) pour POWER.

     Gardes : `tests/test_placement_bypass_snap.py` (le comportement) et
     `tests/test_snap_apres_geometre.py` (l'ORDRE dans `auto_place` — un snap
     correct mais jamais appelé est indistinguable d'un snap absent).

  Historique de la décision inverse, conservé : ablation contrôlée (board STM32 réel, CMA-ES seul sur un board déjà
  placé) = 8/10 paires resserrées (ex. Y1-U2 16.7→7.5mm), 2 légèrement dégradées,
  toujours 0 ERROR final (1 ERROR + 6 WARNING bruts nettoyés par l'Inspecteur à
  0 ERROR / 2 WARNING). Sur le board complet (GA+CMA-ES enchaînés), le filet de
  sécurité s'est déclenché une fois (17 conflits non résorbés → revert), confirmé
  zéro régression sur l'invariant 0-ERROR par 11/11 tests (`test_placement.py`).
  Routage rapide (gros boards) = backend C++ `kct build-native` (Docker).
  ⚠️ **CE BACKEND N'EST PAS LE CHEMIN EMPRUNTÉ** (mesuré le 2026-08-30). Il
  appartient à `kct route`, c'est-à-dire au Niveau 1 de la cascade — et la
  cascade bascule sur Freerouting dès que le Niveau 1 rend moins de
  `_MIN_ROUTED_PCT`. Comptage sur trois journaux (remesure en cours, run qui a
  livré `stm32-100` à 100 %, banc des 7 cartes) :

      16 routages effectués :  16 × (freerouting-api)  ·  0 × (kicad-tools)

  Le compiler ou non ne change donc RIEN aux résultats actuels. Deux agents
  délégués ont proposé `kct build-native` comme correctif prioritaire, en
  s'appuyant sur cette ligne : elle décrivait une capacité, ils l'ont lue comme
  une description du chemin réel.
  **NEVER** conclure qu'un moteur est en cause sans avoir compté, dans les
  journaux, lequel a effectivement routé.
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

⚠️ **Les 4 workers N'ISOLENT PAS `pcbnew` à eux seuls (constat 2026-08-09).**
Ils isolent bien les requêtes **entre** workers, mais **pas à l'intérieur** d'un
worker : les onze routes du service sont déclarées `def` et non `async def`, donc
FastAPI les exécute dans son pool de threads. Deux requêtes reçues par le même
worker peuvent donc appeler `pcbnew` **simultanément, dans le même processus**.

Preuve dans l'historique du projet : l'incident CMA-ES documenté plus haut
(`ValueError: signal only works in main thread of the main interpreter`) ne peut
se produire que si le handler s'exécute hors du thread principal — donc dans un
thread du pool. Le raccourci « 4 workers = sûr » se lisait comme une garantie
qu'il n'apportait pas.

L'isolation réelle passe par un **processus enfant par opération** :
`tools/cmaes_runner.py` (déjà en place), puis `drc_pcbnew_runner.py` et
`placement_pcbnew_runner.py`. Toute nouvelle route appelant `pcbnew` doit suivre
ce schéma.

**NEVER** conclure qu'un appel `pcbnew` est isolé au seul motif que le service
tourne avec plusieurs workers uvicorn.

**Variables obligatoires dans Docker :**
```
KICAD_SYMBOL_DIR=/usr/share/kicad/symbols
KICAD_FOOTPRINT_DIR=/usr/share/kicad/footprints   ← CRITIQUE (0 footprints si absent)
FREEROUTING_API_URL=http://127.0.0.1:37864
KICAD_SERVICE_TOKEN=<secret partagé serveur-à-serveur>  ← requis sauf /health
```

Toutes les routes KiCad sauf `/health` exigent
`Authorization: Bearer $KICAD_SERVICE_TOKEN`. L'absence de jeton côté service
échoue fermée. Le service ne fournit ni CORS ni endpoint d'exécution de Python
généré. Hors localhost/réseau Docker privé, le transport doit être HTTPS.

**Routing — nets routables :** `_count_routable_nets` compte uniquement les nets avec ≥3 occurrences dans le PCB (1 déclaration globale + ≥2 pads). Les nets mono-pad `Net-(U1-X)` ne comptent pas.

## Pipeline asynchrone — le plafond de 300 s (migration en cours)

**Mesure fondatrice (2026-08-19, board STM32 de `examples/stm32-validation`,
chaîne réelle dans le conteneur) :** génération 3 s · placement 175 s ·
**routage 861 s** — soit ~17 min. `apps/web/src/app/api/agent/route.ts` déclare
`maxDuration = 300`.

**Le routage seul dure presque trois fois le budget entier de l'invocation.**
Aucun PCB complet ne peut donc aboutir pour un utilisateur réel : la chaîne ne
fonctionne aujourd'hui qu'exécutée à la main dans le conteneur, où rien ne la
chronomètre.

⚠️ `async` n'y change RIEN. `await` libère la boucle d'événements de Node, il ne
rend pas la main à la plateforme : la fonction reste ouverte tant qu'elle tient
le flux SSE. `maxDuration` est un plafond d'HORLOGE MURALE sur l'invocation.

**NEVER** conclure qu'une étape longue « passe » parce qu'elle est asynchrone.

### Le plafond n'était pas UN endroit, mais QUATRE (corrigés)

`routing-service.ts` accordait au routeur
`Math.min(60 + layers * 30, ROUTING_TIMEOUT_MS / 1000)` — soit **180 s sur
4 couches**, alors que la courbe mesurée donne 300 s → 36 % de complétion. Ni
les 600 s du service Python, ni les 300 s de Vercel : c'était cette heuristique,
cinq fois plus serrée que tout le reste. Voir `engines/routing-budget.ts`.

⚠️ `--timeout` du routeur n'est PAS une limite de patience, c'est une
**ressource** : `kct route` rend la main dès 100 % atteint et conserve ce qu'il a
routé à l'échéance. Le relever ne coûte rien sur un board simple.
`_ROUTE_TIMEOUT_S` = 3600 s, `_WATCHDOG_MARGIN_S` = 600 s — le garde-fou ne doit
JAMAIS tirer avant le routeur, sinon on tue un processus qui allait rendre un
routage partiel valide. Garde : `tests/test_route_budget.py`.

⚠️ **Ce diagnostic était incomplet, et l'a été jusqu'au 2026-08-20.** Relever le
budget côté client ne suffisait pas : le même nombre traverse QUATRE frontières,
et il suffit qu'une seule reste serrée pour que tout le reste soit décoratif.
Trouvées en enfilant de vrais jobs dans la file — jamais par les tests, qui
mockent le service de part et d'autre :

| Frontière | Valeur trouvée | Effet |
|---|---|---|
| `routingSearchBudgetS` (client) | 180 s sur 4 couches | routage tronqué à 36 % |
| `RouteAutoRequest.timeout_s` (`le=`) | 900 s | **422** — le routage n'a pas lieu |
| `_route_with_kicad_tools` | `_PYTHON_ROUTER_TIMEOUT_S` = 300 s codé en dur | budget de la requête **jeté** |
| `_ROUTE_TIMEOUT_S` (`kct_route.py`) | 3600 s | seule des quatre à être correcte |

La troisième est la plus coûteuse : la route acceptait le budget, répondait 200,
et routait quand même 300 s. Rien dans la réponse ne trahissait la substitution.

**NEVER** relever un budget à une seule extrémité : le vérifier sur toute la
chaîne client → validation HTTP → appel au routeur, et laisser une garde de
câblage à chaque saut (`tests/test_route_budget.py`).

⚠️ Deux autres plafonds de la même famille, trouvés au même endroit :
- `PLACEMENT_TIMEOUT_MS` valait 180 s pour un placement mesuré > 215 s sur un
  board STM32 de 21 composants — le run se terminait sans qu'aucun composant
  soit placé, donc sans jamais atteindre le routage
  (`engines/placement-budget.ts`, 900 s) ;
- `jobIdForProject` renvoyait `project:<uuid>`, refusé par BullMQ (`Custom Id
  cannot contain :`) : **aucun job ne pouvait être enfilé**. Séparateur tiret.

### Architecture cible

```
Route (Vercel)  ──202 {runId}──>  file BullMQ (Redis)  ──>  worker (DigitalOcean)
                                                              │ sans plafond
navigateur  <──Realtime──  pcb_run_events (Postgres)  <───────┘
```

- `packages/agents/src/pipeline/` — `run-sink.ts` (transport), `pg-sink.ts`
  (journal agrégé), `store.ts` (persistance), `run-orchestrator.ts` (le pipeline
  lui-même), `job.ts` + `queue.ts` (file).
- `services/worker/` — image dédiée, **aucun port publié**, client service-role.
- Migration `019_pcb_runs.sql` — `pcb_runs` + `pcb_run_events`, RLS lecture seule.
- Migration `020_pcb_run_events_realtime.sql` — `REPLICA IDENTITY FULL` +
  publication `supabase_realtime` (no-op si la publication n'existe pas).

**NEVER** faire voyager `agent_mode` dans le payload du job : il gouverne le gate
JLCPCB, donc une commande réelle et payante. Enfiler un job ne doit pas décerner
la commandabilité. Il est posé par la ROUTE dans `pcb_runs`.
**NEVER** dériver le gate JLCPCB de `pcb_runs` : un run est une tentative, seul
`projects` porte un résultat prouvé.
**NEVER** laisser `maxStalledCount` à son défaut (1) : sur 20 min de routage, le
verrou de 30 s expire et BullMQ rejoue le job EN PARALLÈLE du premier.
**ALWAYS** garder `CIRQIX_ASYNC_PIPELINE` fail-closed dans le code : le défaut
est inactif. Le client a basculé (Realtime + sondage) ; allumer le drapeau
(`1` / `true`) seulement là où Redis ET le worker tournent. Sans file, un
`202` accepterait un job que personne ne consomme.

### Le plafond est tombé — mesuré (2026-08-20)

Board STM32 placé non routé (`examples/stm32-validation/output/2_placement.kicad_pcb`),
envoyé à `POST /route/auto` avec le contrat exact du client (`timeout_s: 1800`,
4 couches) :

| État | Résultat |
|---|---|
| `fetch` global (undici) | mort à 300 s — `UND_ERR_HEADERS_TIMEOUT` |
| échéances de transport désarmées | 605 s → **500**, le partiel jeté |
| repli Niveau 4 rétabli | **2547 s → 200, routé à 91 %** |

**Une requête de 42 minutes va au bout de la chaîne** — 8,5× l'ancien plafond,
avec un routage RÉEL (`routed_percent: 91`, le plancher connu sans LLM), pas un
succès de façade.

Le service, lui, routait déjà au-delà de 300 s avant le correctif : c'est le
client qui raccrochait. La preuve la plus nette vient du premier essai — après
l'abandon à 300 s, le service a continué et n'a rendu sa réponse que sept
minutes plus tard, dans le vide.

⚠️ **Le budget est compté PAR NIVEAU, pas par appel.** Les 2547 s se répartissent
entre le Niveau 1, Freerouting, puis le Niveau 4 qui relance `kct route` avec les
mêmes 1800 s. Chaque niveau reçoit le budget entier, donc un appel peut valoir
plusieurs fois `timeout_s`. Acceptable dans un worker sans plafond, à revoir si
la borne devient contractuelle.

### « Freerouting perd la netlist » était FAUX (2026-08-20)

Ce diagnostic, écrit ici le matin même, disait : *round-trip Specctra, 99 nets en
entrée, 0 en sortie*. Il venait du message de la garde, relayé sans être vérifié.

**La netlist était intacte.** Deux écritures coexistent pour la même information :

    (net 3 "TRIG_THR")   ← kicad-tools, et KiCad ≤ 9
    (net "TRIG_THR")     ← pcbnew de KiCad 10 (`generator_version "10.0"`)

`_NET_DECL_RE` n'acceptait que la première. Tout board réécrit par pcbnew 10 —
donc tout board sorti du round-trip Specctra, donc de Freerouting — comptait
ZÉRO net et se faisait refuser.

La preuve qui tranche : `kicad-cli pcb drc` sur ce board « sans netlist » répond
**« Found 0 unconnected items »**. Valide, routé, entièrement connecté.

Après correction, même board via l'API : nets déclarés 30 → 76, nets routables
6 → 6, segments 0 → 53, **en 2 s**.

⚠️ La garde reste juste et nécessaire (issue #72 : un board réellement vidé était
annoncé « routé à 100 % »). C'est sa MESURE qui était fausse — on corrige la
mesure, jamais la garde. Gardes : `tests/test_net_counting_kicad10.py`.

**NEVER** relayer le message d'une garde comme un diagnostic : il dit ce que la
garde a MESURÉ, pas ce qui s'est passé.

### Le Niveau 2 (API Freerouting) n'avait jamais servi

La JVM persistante (~400 Mo, port 37864) répondait correctement depuis toujours.
`_find_freerouting_api` sondait `/api/v1/system/status` — un chemin que
Freerouting v2.1.0 ne sert pas ; le vrai préfixe est `/v1`. La sonde renvoyait
donc toujours `None` et chaque routage repartait sur le Niveau 3, un `java -jar`
complet avec démarrage de JVM.

Quatre erreurs indépendantes du client, chacune suffisante seule : préfixe
`/api`, absence des en-têtes d'identité (`Freerouting-Profile-ID`…, sinon 500),
envoi du DSN en multipart (415 au lieu de `{"data": <b64>}`), et comparaison
d'état en minuscules (le serveur sérialise `"COMPLETED"`). `POST …/start` répond
405 : c'est un `PUT`. Gardes : `tests/test_freerouting_api_contract.py`.

⚠️ **`api_server-endpoints` ne peut PAS se passer en ligne de commande** :
`ApiServerSettings.endpoints` est un `String[]`. L'option levait
« Failed to set property value » à chaque démarrage depuis le 2026-07-27 sans
jamais s'appliquer — une erreur rouge, réelle, mais SANS RAPPORT avec le 404.
Elle m'a fait conclure à un serveur mort pendant des heures. Pour changer le
port, il faut un `freerouting.json` sous `--user_data_path`.

⚠️ `via_count` et `track_length_mm` ressortaient à **0** sur le chemin Niveau 4 :
il ne les calculait pas et laissait les défauts du modèle. Ce ne sont pas des
indicateurs manquants mais des chiffres FAUX présentés comme réels — et un zéro
est plausible, donc rien ne distinguait « mesuré à zéro » de « jamais mesuré ».
**Corrigé** : les deux sont recalculés sur le board FINAL à la fin de
`route_auto`, après le fanout, la coulée et les replis. Garde :
`tests/test_routing_metrics.py`.

### Banc de routage STM32 — 6 tirages (2026-08-21)

Board `examples/stm32-validation/output/2_placement.kicad_pcb`, budget 900 s par
tirage, **même instrument pour les deux** (`kicad-cli pcb drc`, connexions
manquantes), et le board placé non routé en TÉMOIN — sans lui on attribuerait au
routage des défauts qui préexistent.

| | Connexions manquantes | Durée | Violations | Vias |
|---|---|---|---|---|
| témoin (placé non routé) | 43 | — | 25 | — |
| **Freerouting API** ×3 | **0 · 0 · 0** | **4-5 s** | 27-28 | 7-8 |
| **kicad-tools** ×3 | **7 · 7 · 7** | 568-750 s | 197-198 | 69 |

Constance remarquable des deux côtés — contrairement au PLACEMENT, qui reste
stochastique (6, 8 et 12 connexions manquantes selon le tirage).

`kicad-tools` rend exactement **91 %**, le plancher documenté. C'est SOUS
`_MIN_ROUTED_PCT` (95 %), donc la cascade bascule d'elle-même sur Freerouting :
l'ordre actuel produit déjà le bon résultat, mais paie ~10 min de Niveau 1 dont
le produit est ensuite jeté.

⚠️ **Les 198 violations de kicad-tools ne sont pas cosmétiques.** Ventilation
face au témoin (25 violations, toutes des `warning` préexistants) :

| Type | Sévérité | Ajoutées par kicad-tools |
|---|---|---|
| `hole_to_hole` | warning | +113 |
| `drill_out_of_range` | **error** | +42 |
| `clearance` | **error** | +10 |
| `annular_width` | **error** | +4 |
| `track_width` | **error** | +2 |

**58 ERREURS de fabricabilité.** `drill_out_of_range` et `annular_width` font
refuser la carte par JLCPCB ; `clearance` est un court-circuit potentiel. La
cause tient dans un rapport : **69 vias contre 5**. Freerouting, lui, rend
exactement le board du témoin plus le cuivre : 25 violations avant, 25 après.

« 91 % routé » ne dit donc pas ce qu'on croit : ce n'est pas une carte
incomplète à 9 %, c'est une carte **non fabricable**. Et c'est ce qui explique
les six cycles place → route → DRC du run complet — le board ne passait pas le
DRC, donc la chaîne re-tirait le placement.

### ⚠️ PÉRIMÉ — kicad-tools n'est PLUS devant (constat 2026-09-01)

**Le code dit l'inverse de cette section**, et ce depuis un moment :

```
routers/routing.py:4027   # --- Niveau 1 : Freerouting REST API server ---
routers/routing.py:4124   # --- Niveau 3 : kicad-tools A* (≤30 nets/comps) ---
routers/routing.py:4167   logger.info("kicad-tools A* (no limit): ...")   ← Niveau 4
```

Freerouting est **Niveau 1**, conformément à la décision de l'utilisateur du
2026-09-01 (« toujours par défaut niveau 1 est Freerouting »), et l'argument
qui gardait `kicad-tools` devant est **caduc** : l'escalade pose elle-même
l'empilage (`_expand_stackup(pcb_bytes, palier)`, `routing.py:4409`), donc
`kicad-tools --auto-layers` n'est plus le seul chemin vers 4 ou 8 couches.

⚠️ Cette section périmée a réellement induit en erreur : l'utilisateur a lu un
journal où `kicad-tools A* (no limit)` tournait et en a conclu que la cascade
était mal ordonnée. La vraie cause était le **budget à zéro** — le Niveau 1
est sauté quand `_budget_suffisant` est faux, et la chaîne tombe au Niveau 4.
**NEVER** laisser dans CLAUDE.md une description d'ordre d'exécution sans
l'avoir revérifiée dans le code : un lecteur l'utilise comme un diagnostic.

Mesures conservées ci-dessous — elles restent vraies et expliquent POURQUOI
Freerouting doit passer en premier.

Décision produit du 2026-08-21, avec sa vraie justification, mesurée :

```
board placé (entrée) : 2 couches   F.Cu, B.Cu
sortie kicad-tools   : 4 couches   F.Cu, B.Cu, In1.Cu, In2.Cu   ← il en AJOUTE
sortie Freerouting   : 2 couches   F.Cu, B.Cu                    ← inchangé
```

**Freerouting n'ajoute aucune couche** : il route dans l'empilage reçu.
**kicad-tools escalade** (`kct route --auto-layers`).

Or `tools/pcb.py` (ligne ~778) code en dur `(0 "F.Cu") (31 "B.Cu")` : le
générateur produit **toujours** 2 couches cuivre. **kicad-tools est donc le seul
chemin par lequel une carte Cirqix devient 4 ou 8 couches** — c'est-à-dire le
seul qui puisse honorer les plans Pro (4) et Pro Max (8).

Sur une carte que 2 couches suffisent à router, Freerouting gagne sur tous les
critères. Sur une carte qui en exige davantage, Freerouting seul **ne peut pas
y arriver**, faute du levier.

**NEVER** conclure de la comparaison de qualité qu'il faut inverser les niveaux :
les deux routeurs ne résolvent pas le même problème.

⚠️ Enchaîner Freerouting **sur** la sortie de kicad-tools ne se produit jamais :
le Niveau 2 reçoit le board PLACÉ, pas le résultat du Niveau 1. Tenté à la main,
l'export Specctra du board kicad-tools fait d'ailleurs échouer le processus
pcbnew. Le routage incrémental avait déjà été mesuré et écarté
(`--preserve-existing` perdait la moitié du cuivre reçu).

Artefacts d'inspection (non versionnés, `output/` est gitignoré) :
`examples/stm32-validation/output/freerouting/` — les deux boards, leurs rendus
et le tableau complet.

### Pipeline complet par la file — validé de bout en bout (2026-08-21)

Run `4290007c` enfilé dans BullMQ, consommé par le worker, **19 minutes**, tous
les appels en 200 :

```
02:27:15  /schematic/validate-symbols  200
02:27:17  /schematic/generate          200
02:27:47  /erc                         200   ← l'ERC d'autorité rend un verdict
02:28:09  /pcb/generate                200
          … 6 cycles place → route → drc, tous 200
02:44:28  /export/all                  200
```

C'est la validation qui englobe les autres : elle exerce le transport undici
désarmé, les budgets de placement et de routage, l'API Freerouting réparée, le
compteur de nets, le requotage ERC, et le worker sans plafond d'invocation.

**19 min > 300 s** — l'ancienne route web n'aurait livré aucun de ces boards.

⚠️ Le routage prend désormais **5 à 12 s** par cycle (Freerouting via l'API) au
lieu de 600-2500 s : c'est ce qui rend six re-tirages de placement tenables dans
un run de 19 minutes. Le temps du run est aujourd'hui dominé par le PLACEMENT
(~2,5 min par tirage), plus par le routage.

⚠️ Non couvert : la persistance Supabase, testée avec `SUPABASE_URL` bidon —
tous les `dépôt de l artefact échoué` et `persistance intermédiaire échouée` du
journal sont attendus. La moitié « journal + Realtime » reste à valider avec une
vraie `SUPABASE_SERVICE_KEY`.

### État

Livré : migration `019` **appliquée** (`20260820095437 pcb_runs`), conteneurs, `RunSink`/`PgSink`, budgets, contrat de job,
annulation (bloque reasoner et re-tirages), worker (image dédiée, vérifié en
conteneur : consomme la file, valide par Zod, ne rejoue pas un job échoué),
branche asynchrone de la route derrière drapeau, suivi de run côté client.

Reste :
- **Progression pendant le routage.** `kct_route.py` utilise
  `subprocess.run(capture_output=True)` : la sortie du routeur n'est lue qu'à la
  FIN. Sur 20 minutes, l'utilisateur ne voit donc rien. Le passage en `Popen`
  avec lecture incrémentale servirait deux fins — l'affichage, et la détection
  de blocage par ABSENCE DE PROGRESSION plutôt que par temps écoulé, qui est la
  bonne mesure. ⚠️ Refactor à faire à froid : chemin critique de 1692 lignes,
  non testable sans un routage réel de ~14 min.
- ~~**Supabase Realtime** en transport principal~~ — **livré.** `followRun`
  s'abonne aux INSERT de `pcb_run_events` ; le sondage HTTP reste le repli et
  le catch-up. Publication : migration `020`. Le drapeau
  `CIRQIX_ASYNC_PIPELINE` reste à allumer là où Redis + worker tournent.
- ~~Freerouting perd la netlist~~ — **FAUX, corrigé le 2026-08-20.** Voir
  ci-dessous : c'était notre compteur qui était aveugle.
- **Budget par niveau** — voir l'avertissement ci-dessus.
- ~~`via_count`/`track_length_mm` à 0~~ — **corrigé.** Les deux mesures sont
  recalculées sur le board FINAL avant de répondre (`routers/routing.py`, fin de
  `route_auto`), après le fanout, la coulée et les replis. Garde :
  `tests/test_routing_metrics.py`.

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
**NEVER** créer ou modifier des fichiers dans `services/kicad/kicad-tools/tests/` — c'est le sous-module du fork upstream, pas notre code.
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
- `stm32-validation/` — agents ④→⑥b sur un board donné (`run_agent_chain.py`, `run_feedback_loop.py`) ; fournit la fixture pytest `expected/stm32_final.kicad_pcb` ; cas de **stress DFM** (LQFP-48 fine-pitch)
- `led-blinker-full-pipeline/` — pipeline **complet** ①→⑧ description → Gerbers (`run_pipeline.py`) ; board simple NE555+LED (8 composants, **6 nets** dans `input/schema.json`, 60×45 mm) ; `expected/led_blinker_final.kicad_pcb` = 100 % routé / DRC-clean (2026-07-27). **Terrain d'apprentissage RL routing** documenté dans `docs/rl/routing/` — ne plus écrire que la fixture « n'existe pas »

(`stm32-full-pipeline/` supprimé au commit `8faf685` — ne plus y faire référence.)

---

## Variables d'environnement requises

`ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `REDIS_URL`, `LEMON_SQUEEZY_API_KEY`, `KICAD_SERVICE_URL`, `KICAD_SERVICE_TOKEN`

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
  - ⚠️ **`canView3D` est appliqué CÔTÉ CLIENT seulement (2026-08-11)**, et c'est
    assumé. `View3D` ne consomme AUCUN artefact serveur : il dessine à partir du
    `PCBState` que le client possède déjà (reçu par SSE, nécessaire au reste du
    viewer). Il n'y a donc rien à ne pas lui envoyer, et aucune route ne rendrait
    ce droit exécutoire — un contrôle serveur ici serait du théâtre.
    C'est un **différenciateur produit, pas une frontière de sécurité**.
    Le rendre exécutoire supposerait d'en faire un vrai artefact serveur (export
    STEP/GLB par le service KiCad) : décision produit, pas refactor.
    Contraste utile : `maxLayers` (handleRouting) et `canSimulate`
    (handleSimulation) sont, eux, appliqués côté serveur.
    Garde : `apps/web/src/test/view3d-plan-gate.test.tsx`.
- ✅ **4.2** Simulation ngspice : `POST /simulate/auto` + `call_agent_simulation` + `SimulationView` Recharts
  - kicad-cli SPICE export → ngspice batch → parsing tabular → vecteurs V/A
  - ⚠️ **FAIL FAST côté SERVICE PYTHON (2026-08-12)** — le correctif du 11/08
    ci-dessous ne couvrait que la couche TypeScript. `tools/simulation.py`
    renvoyait `status: "ok"` sur ses QUATRE chemins dégradés : kicad-cli absent
    (netlist **stub** — un circuit RC sans rapport avec le schéma reçu),
    ngspice absent, ngspice en échec, sortie non parsable. Le client TS
    n'échouant que si `status != 'ok'`, les mesures inventées traversaient toute
    la chaîne et s'affichaient comme réelles.
    Le cas du stub est le pire : avec ngspice fonctionnel, le service simulait
    **correctement un autre circuit** — sortie authentique, chiffres plausibles,
    aucun rapport avec le produit du client.
    Pourquoi c'était invisible : **aucun test ne touchait `simulation.py`**, et
    le test TypeScript mockait entièrement `runSimulation` — la fabrication
    vivait sous le mock. `_stub_netlist` supprimé (code mort après correction).
    Garde : `services/kicad/tests/test_simulation_fail_closed.py`.
  - ⚠️ **FAIL FAST (2026-08-11, issue #129)** : ngspice indisponible → `status:'error'`,
    AUCUNE donnée. Le handler renvoyait auparavant `status:'success'` avec des
    waveformes RC **synthétiques** — plausibles, jamais calculées à partir du
    circuit — sous les seuls indices `engine:'demo'` et `warning`, précisément
    ceux qu'une interface graphique n'affiche pas. Un compte Pro pouvait donc
    décider sur une mesure inventée. `handleSimulation` était le DERNIER handler
    du pipeline à fabriquer un succès, après l'assainissement de l'ERC, du DRC,
    du routage et de l'export. Le mode démo survit en **opt-in explicite**
    (`CIRQIX_SIMULATION_DEMO=1`), utile en local, jamais un repli sur erreur.
    Garde : `tests/simulation-fail-closed.test.ts`.
  - ⚠️ **Droit lié au plan (2026-08-11)** : la simulation exige `canSimulate`
    (`PLAN_ENTITLEMENTS`, plans payants). Le contrôle est dans le HANDLER, pas
    dans le prompt — un modèle à qui l'on demande de ne pas appeler un outil
    finit par l'appeler — et AVANT le repli démo, sinon un compte gratuit
    refusé recevrait quand même une courbe. Un plan absent refuse aussi.
    Garde : `tests/simulation-plan-gate.test.ts`.
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
  - `tools.ts` (depuis refactoré en `tools/definitions.ts` + `tools/handlers/*`) : descriptions expertes pour chaque agent (Ingénieur Schéma, ERC, Composants, Layout…)
  - `orchestrator.ts` : `stepMap` mis à jour (`call_agent_gen_pcb → 'KICAD'`), `pcbStateTools` étendu
  - Bug `_resolve_pin` Python 3 corrigé (`UnboundLocalError` scope exception variable)
  - Stratégie connecteurs Path B : ESP32 → `Conn_02x19_Odd_Even`, Arduino → `Conn_02x15_Odd_Even`
  - Ancienne Path A Python (supprimée en Phase 4) : rejet silencieux si Haiku retournait du texte
  - kicad_gen.py → split : `routers/schematic.py` + `routers/pcb.py` + `tools/schematic.py` + `tools/pcb.py`
  - `placement_layout.py` supprimé → kicad-tools CMA-ES primaire + pcbnew grille fallback
  - `placement-fallback.ts` supprimé → fail fast si service Docker down
  - `call_agent_kicad` renommé `call_agent_gen_pcb` + appelle POST /pcb/generate
- ✅ **4.x — Fix génération schéma** (session 2026-05-29) :
  - `generateSchemaWithHaiku` : `max_tokens 2048 → 4096` — JSON tronqué pour circuits complexes causait fallback sur faux schéma hardcodé
  - Ancienne Path A Python (supprimée en Phase 4) : prompt Haiku corrigé à l'époque
  - `call_agent_schema` Path C : pour `complexity='complex'`, retourne maintenant une `{status:'error'}` au lieu du faux schéma "2 IC · 15 passives · 11 nets"
  - Logs améliorés : ancienne Path A + génération JSON `stop_reason=max_tokens`
  - **Cause racine** : les 3 chemins échouaient en cascade → `parseSchemaFromDescription('complex')` retournait `ESP32 + LDO + 15×100nF` hardcodé
- ✅ **4.x — Migration workflow OFFICIEL kicad-tools + Reasoner IA** (session 2026-06-02→03) :
  - Fork kicad-tools complet en sous-module (`services/kicad/kicad-tools/`) — code placement/routage custom supprimé
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

### Leçons inscrites le 2026-08-29 — chacune payée par une mesure

**NEVER** conclure qu'un levier natif n'existe pas sans avoir lu les CHAMPS des
objets rendus. `FunctionalCluster.max_distance_mm` et `anchor_pin` étaient
publics, calculés à chaque appel, jamais lus — et leur absence supposée a fondé
deux mois de renoncement (« adjacence serrée = Phase 6 »). Lire la signature
d'une fonction ne suffit pas : ce qu'elle REND porte souvent la réponse.

**NEVER** ajouter un correctif qui déplace des composants sans vérifier ce que
font ceux qui l'entourent. Le snap posé avant le Géomètre est défait par le
CMA-ES ; posé avant le halo d'escape, défait par le halo. Deux correctifs
justes peuvent s'annuler — c'était déjà arrivé le 2026-08-27 entre le clamp et
le centrage des dominants. L'ordre fait partie du correctif, pas de son emballage.

**NEVER** mesurer une distance entre footprints depuis leurs ORIGINES. L'origine
d'un module est sur sa pastille 1 : le courtyard de l'ESP32-WROOM va de -30,74 à
+10,51 en y. « À 3 mm de l'origine » place le voisin DANS le module.
`_boite_locale_fp` porte ce décalage — s'en servir, toujours.

**NEVER** livrer une règle sans une garde qui prouve qu'elle est APPELÉE. Une
règle correcte jamais invoquée est indistinguable d'une règle absente : c'est
exactement ce qui a masqué pendant des semaines le fait que le Géomètre ne
tournait jamais en production. Tester le comportement ET le câblage.

**NEVER** lire un `0 %` comme un verdict de routage. « 0 % (aucun moteur) » est
une panne — moteur injoignable, budget épuisé avant le repli. Escalader
là-dessus revient à payer une couche de cuivre pour un défaut d'infrastructure.
Distinguer toujours « mesuré à zéro » de « jamais mesuré ».

**NEVER** conclure qu'un processus est bloqué en comparant l'horloge à la date
d'un journal. La machine de développement se met en veille : le 2026-08-29,
deux fois, un banc a paru muet pendant 39 minutes alors qu'il avait 8 minutes
de temps d'exécution réel. La seule mesure fiable est `etime` du processus, ou
sa consommation CPU — jamais l'écart entre deux horodatages.

**NEVER** faire tourner une mesure longue dans un conteneur qu'une autre session
peut redémarrer. Deux mesures de `stm32-100` ont été perdues ainsi (redémarrages
à 07:10 et 07:17, `restarts=0` — donc voulus, pas des plantages). Un banc se
lance dans SON conteneur, monté sur les mêmes sources.

**NEVER** faire confiance aux tests présents dans l'image Docker : ils datent du
build. Huit « régressions » lues le 2026-08-29 n'étaient que des tests périmés ;
après copie de ceux du disque, 31/31 vert. Copier `tests/` avant de conclure.

**NEVER** calibrer une règle sur une source VOISINE de celle qu'elle mesure. Le
plancher d'échappement a été calibré sur `circuit.json` alors que le code lit le
board : 43 signaux contre 36, et la règle laissait passer exactement le cas
qu'elle devait attraper — tests unitaires verts des deux côtés.

**NEVER** confondre une pastille avec une liaison. Sur un board, CHAQUE pastille
porte un net, y compris celles qui ne vont nulle part (`Net-(U1-Pad3)`). Un net
présent sur un seul boîtier n'a personne à rejoindre. Sans ce filtre, tout
LQFP-48 comptait ~45 signaux quel que soit son circuit.

**NEVER** livrer une règle numérique sans l'avoir passée sur les DONNÉES RÉELLES
du projet. Les deux défauts ci-dessus ont franchi une suite complète de tests
unitaires ; l'un et l'autre sont tombés au premier passage sur les sept boards
du banc. Une fixture dit ce qu'on a imaginé, un board dit ce qui est.

### Leçons inscrites le 2026-08-31 — la réservation d'échappement

**NEVER** insérer une fonction entre un décorateur et sa cible. `@router.post(
"/route/auto")` a décoré `_armer_abandon` pendant toute sa vie : FastAPI
exposait cette fonction et `route_auto` était injoignable par HTTP. Le banc ne
pouvait pas le voir — il importe `route_auto` directement en Python. Une garde
qui interroge la TABLE DE ROUTES (`router.routes`) répond à la vraie question ;
une garde qui lit le fichier source, non.

**NEVER** écrire une regex qui suppose que deux champs se suivent dans un
board. KiCad intercale `(uuid "…")` entre `(layer)` et `(net)` d'un segment :
231 segments d'un board réel, **0 reconnu**. C'est le dixième piège de forme du
projet. Chercher chaque champ dans son bloc, jamais en une seule expression.

**NEVER** faire confiance à une branche de code qu'aucun appelant de production
n'atteint. La branche qui portait le net de chaque via existait, son commentaire
avertissait du court-circuit, et seule une **fixture de test** y allait — une
fixture qui mettait d'ailleurs un NOM là où le runner met un entier. Compter les
appelants réels fait partie de la revue.

**NEVER** annoncer dans un fichier une référence que le fichier ne déclare pas.
`_confier_au_plan` retire `(net GND …)` du DSN ; on écrivait `(net GND)` dans le
`(wiring)` deux lignes plus bas. Écarter et le DIRE ; et ne jamais transformer
une lecture ratée en verdict — une section `(network)` illisible n'écarte rien.

**NEVER** recalculer ce qui a déjà été mesuré au bon moment. La sortie
d'échappement était calculée avant le routage, quand la place existait, puis
**jetée** : seuls `ref` et `pad` traversaient, et la recherche repartait de zéro
sur le board routé. Rejouer la position — après l'avoir vérifiée — au lieu de la
rechercher. Gardes : `tests/test_wiring_reservation_resoluble.py`,
`tests/test_reprise_des_sorties_reservees.py`.

**NEVER** laisser un échec rendre la même valeur que son cas normal. Le dernier
recours du routage (`_recuperer_jobs_abandonnes`) appelait `_api`, définie
**à l'intérieur** d'une autre fonction : chaque appel levait `NameError`, avalé
par un `except Exception`, et rendait `None` — exactement ce que rend son cas
légitime. Il n'a jamais fonctionné, et `stm32-100` est sortie à zéro alors qu'un
board à 81 % l'attendait dans la JVM. Le défaut est apparu **la minute** où le
diagnostic a été ajouté. Compter les raisons d'un échec n'est pas du confort.

**NEVER** concaténer deux listes calculées séparément sans se demander si elles
se recouvrent. `_vias_a_reserver` (pastilles vues isolées par le DRC) et
`_vias_gnd_preventifs` (toutes les pastilles GND fine-pitch) partagent leurs
cas les plus critiques ; le doublon posait deux vias au même point, donc une
violation `hole_to_hole`, donc le rejet TOUT-OU-RIEN des vingt et un vias.

**NEVER** ancrer une garde sur le NOM de l'appelant. Deux gardes cherchaient
`_api("PUT", …` et se sont mises à lever `ValueError` dès que cette fonction a
été renommée — elles ne mesuraient plus rien, mais leur intention était intacte.
S'ancrer sur ce qui ne bouge pas : ici l'URL du départ de job.

### Limite de detect_functional_clusters — ACCEPTÉE 2026-06-18, **LEVÉE 2026-08-29** :
Le clustering natif regroupe les grappes mais ne colle PAS les bypass caps/quartz à
l'IC (springs molles ~50 dominées par les rails GND ~75) → caps à 13-28mm du MCU.

Décision d'alors : accepté tel quel (routable), adjacence serrée → Phase 6 RL_PCB.

⚠️ **Cette décision reposait sur une prémisse fausse : qu'il n'existait pas de
levier natif.** Il en existait un, et le clustering le calculait déjà à chaque
appel — `FunctionalCluster.max_distance_mm`, un plafond PAR TYPE de cluster
(POWER 3 mm · TIMING 5 · DRIVER 6 · INTERFACE 8). Personne ne le lisait. On a
donc attendu deux mois d'un GA qu'il produise spontanément un résultat que sa
fonction de coût lui interdit, alors que la règle était posée à côté.

Le snap (`tools/placement_bypass.py`) ne réintroduit AUCUNE heuristique : la
détection reste `detect_functional_clusters`, le seuil est celui du cluster.
Ce n'est pas un optimiseur de placement — c'est l'application d'une règle que la
lib exprime et n'applique pas. La règle de CLAUDE.md est respectée.



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
à la limite ci-dessus (adjacence 13-28mm) — raffinement best-effort, jamais une
garantie. Depuis le 2026-08-29, c'est le SNAP qui garantit l'adjacence ; le
Géomètre reste ce qu'il a toujours été, un micro-raffinement qui le précède.
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

## Dépendances Git — versions + patches Cirqix

Ces deux librairies sont des sous-modules épinglés dans `services/kicad/`, documentés
dans `DEPENDENCIES.md`.

> ✅ **Migration kicad-tools terminée.** Le fork privé `bmechergui/kicad-tools`, branche
> `cirqix`, est consommé comme git submodule ; ses patches restent privés et le gitlink
> Cirqix épingle le SHA validé. Référence : `docs/kicad-tools-fork-strategy.md`.

### circuit_synth v0.12.1
- **Fork privé :** github.com/bmechergui/circuit-synth, branche `cirqix`, sous-module
  épinglé sur `08b9b0e4c75da5b8b8b55bc5353756ab60bf1892` (base upstream v0.12.1
  `f52f491b57ff1b95d9acbcc48d3323f5be8ad96a`, PR fork #1 ; tag de protection
  `cirqix-pin-08b9b0e`. Le SHA `302e22db` cité ici jusqu'au 2026-08-10 est
  périmé mais reste servable, son tag existe. À jour vis-à-vis d'upstream,
  rien à rebaser). Privé depuis le
  2026-07-18 — accès CI via deploy key SSH `CIRCUIT_SYNTH_DEPLOY_KEY`
  (voir `services/kicad/DEPENDENCIES.md`)
- **Runtime :** Ubuntu 24.04 Noble + Python 3.12 (`/opt/venv`)
- **Install :** `pip install ./circuit_synth` (Docker) | `pip install -e services/kicad/circuit_synth` (local)
- **Patches Cirqix :**
  - `kicad/sch_gen/circuit_loader.py` ligne ~286 — **fix netlist bug (2026-06-01)**
    `pin_data["name"] not in ("~", "", None)` au lieu de `!= "~"`
    Sans ce fix : Device:R et Device:C → tous labels au même pin (pin 1) → R1.pin2=unconnected
  - `kicad/schematic/geometry_utils.py` — fallback index-based seulement si toutes les
    broches sont non numérotées ; jamais si un numéro explicite ne correspond pas
- **Garde CI :** `services/kicad/tests/test_docker_build_context.py` + build Docker bloquant

### kicad-tools (fork privé complet — sous-module)
- **Fork :** github.com/bmechergui/kicad-tools, branche `cirqix`, gitlink
  `16aa43191fc86526013b6eaaaa63eb46de7d67b7` (rebasé le 2026-08-10 sur
  `upstream/main` @ `627f3e44`, 221 commits rattrapés) ; upstream
  github.com/rjwalters/kicad-tools.
- **Chemin :** `services/kicad/kicad-tools/` (tiret ; package Python `kicad_tools`).
- **Import :** `kicad-tools/src` sur le sys.path → `import kicad_tools`.
- **Install Docker :** `pip install -e "/opt/kicad-tools[placement,drc,geometry,native]"`
  puis `kct build-native` (backend C++ A*, 10-100× ; besoin cmake+g++).
- **Workflow utilisé :** placement = 1 appel natif `OptimizationWorkflow(strategy="hybrid",
  enable_clustering=True, fixed_refs=<J*/P*>).run()` + **`.write_to_pcb()`** (GA + physique
  force-directed en interne) · routage `kct route --auto-layers --auto-fix` + `kct reason`
  (LLM/heuristique).
- **Patches Cirqix #1 à #8** suivis dans la branche privée `cirqix`, y compris les
  correctifs CMA-ES writer/seed et rotation de pads. Inventaire, tests et procédure
  de rebase : `services/kicad/DEPENDENCIES.md`.

**Règle :** ne mettre à jour un gitlink qu'après rebase du fork, tests et double revue.

---

## Persona

Architecte logiciel senior full-stack, 15 ans d'expérience, spécialisé agents IA + PCB AI.
Maîtrise : Next.js 15 · TypeScript strict · Turborepo · Supabase · Claude SDK · Lemon Squeezy · Circuit-Synth · KiCanvas · KiCad/FastAPI · Docker.
Principes : FSD · clean architecture · atomic design · tests · sécurité · coût agentique <0.12€/PCB.

Tu penses étape par étape. Tu annonces les skills avant chaque action. Tu contredis les mauvaises pratiques. Tu proposes des solutions modernes même si non demandées.
