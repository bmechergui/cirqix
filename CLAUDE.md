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
SaaS 100% cloud de conception PCB par langage naturel. Agent IA autonome → PCB DRC-clean → Gerber → dossier de commande JLCPCB, soumis à la main.

⚠️ **LA COMMANDE JLCPCB N'ENVOIE RIEN** (vérifié le 2026-09-05).
`POST /api/jlcpcb/order` valide le gate, produit une référence et répond
`submitted: false`, `status: 'ready_for_manual_submission'`, avec le message
« No order was sent to JLCPCB ». C'est une PRÉPARATION de dossier, pas une
commande — et c'est un choix sûr, puisqu'aucun envoi accidentel n'est possible.

La tagline et `PLAN.md` §4.3 disent encore « commande JLCPCB » sans réserve :
la boucle n'est pas fermée, la dernière étape est manuelle.
Tagline : "AI PCB Design Agent — From idea to manufacturable PCB, autonomously"

## graphify

Pour une question d'architecture ou « qui appelle quoi », `graphify query|path|explain`
coûte souvent moins cher que le grep. Graphes disponibles : `graphify-out/graph.json`
pour Cirqix ; `kicad-tools`, `circuit_synth` et l'agrégat sont décrits dans
`docs/graphify.md`. Une requête consomme environ 1 Go de mémoire : ne pas en lancer
pendant un banc ou une mesure de routage, ni en parallèle depuis un agent externe. Le
hook SessionStart rafraîchit déjà les graphes périmés. Après une modification de code,
lancer `scripts/graphify-refresh.ps1` avec `-Mode Root`, `KicadTools`, `CircuitSynth` ou
`All` selon les chemins touchés.

---

## Règles de travail

### 1. Chaîne de travail

Chaque tâche commence par `cirqix-prompt-improver`, y compris une tâche courte
(préférence de l'utilisateur) : afficher le prompt reçu et le prompt amélioré, puis
attendre la confirmation de l'utilisateur avant de coder. En exécution non interactive
(workflow, sous-agent), exécuter directement. Un skill cité (« [Skill : X] — raison »,
annoncé avant l'appel) est réellement invoqué par le Skill tool. Le niveau de plan suit
`.claude/rules/planning.md` : une tâche simple se code directement.

Avant un commit :
- `pnpm type-check` rend 0 erreur ;
- pour un bug fix ou une feature, les tests sont écrits avant le code ou avec lui ;
- une revue `code-reviewer` a suivi l'implémentation, et l'agent `security-reviewer`
  a relu le diff si auth, paiement, secrets, RPC ou RLS sont touchés
  (`everything-claude-code:security-scan` n'audite que la configuration `.claude/`) ;
- une étape du pipeline PCB (Schema→ERC→Place→Route→DRC→Export) n'avance que validée
  par `cirqix-quality-gate` : ERC sauté, composant non connecté ou violation DRC ne
  sont jamais « OK » sans correction ou documentation explicite ;
- Claude fait commit, push et PR (`.claude/rules/git.md`).

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

---

## Fichiers de référence

- `.claude/SKILLS.md` — registre de tous les skills (description + quand invoquer)
- `docs/cirqix-full-resume.md` — vision produit complète, business model, stack
- `docs/agentdescription.md` — index des prompts des agents (chaque prompt vit dans le code)
- `PLAN.md` — plan d'implémentation complet par phases
- `docs/pipeline-placement-routage.md` — **le pipeline placement → routage, étape par étape, pour tout type de carte** (critères de livraison, règles générales, ce qui reste ouvert). À lire avant toute modification de `tools/placement*.py` ou `routers/routing.py`.
- `docs/design/design-system.md` — tokens, couleurs, typographie, composants
- `docs/graphify.md` — graphes séparés Cirqix, `kicad-tools`, `circuit_synth` et agrégat multi-repo.
  Question d'architecture / « qui appelle quoi » → le graphe coûte souvent moins
  cher que le grep (`graphify query|path|explain`, skill `graphify`) ; jamais pendant
  un banc (~1 Go par requête).
  Le hook SessionStart appelle `scripts/graphify-refresh.ps1 -Mode Ensure`; le
  watcher PID-géré utilise `-Mode Watcher`. Après modification, choisir `-Mode Root`,
  `-Mode KicadTools`, `-Mode CircuitSynth` ou `-Mode All` selon les chemins touchés.

**Mettre à jour `.claude/SKILLS.md` + `CLAUDE.md` après chaque installation ou création de skill**

---

## Architecture frontend

```
apps/web/src/
├── app/
│   ├── (marketing)/          ← cirqix.ai (landing, pricing, waitlist)
│   └── (dashboard)/          ← cirqix.ai/dashboard
├── features/
│   ├── marketing/ui/         ← Hero, Navbar, Pricing, WaitlistForm…
│   ├── dashboard/ui/         ← Sidebar, ProjectCard, StatusBadge, CreditsBadge…
│   ├── workspace/ui/         ← Workspace, ChatRail, ChatInput, Timeline…
│   └── auth/ · credits/ · settings/
├── widgets/
│   └── viewer/               ← KiCanvasViewer, Board3DView (GLB), RenderView (PNG), View3D (ExportView)
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
└── processes/                ← vide (réservé à la boucle agentique UI)

packages/
├── @cirqix/types   ← SOURCE DE VÉRITÉ unique (PCBStatus, Plan, AgentAction…)
├── @cirqix/logger  ← Pino logger
├── @cirqix/utils   ← cn() utility
├── @cirqix/db      ← client Supabase + migrations (packages/db/supabase/migrations/)
├── @cirqix/agents  ← Orchestrateur + agents Claude SDK
│   ├── engines/    ← schematic-engine.ts (seul moteur actif) | engine-router.ts
│   └── tools/      ← definitions.ts + index.ts + handlers/* (un handler par outil call_agent_*, plus les modules du schéma)
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
- Agents : orchestrateur Sonnet 4.6 et trois appels Haiku 4.5 — schéma (`schema-haiku.ts`), étape IA de la cascade footprint (`footprint-service.ts`), reasoner de routage (`tools/reasoning.py`). Les autres « agents » (ERC, gen_pcb, placement, routage, DRC, export) sont des handlers déterministes qui appellent le service KiCad.
- DB : PostgreSQL + Supabase + pgvector (uuid-ossp, pgvector)
- Queue : Redis + BullMQ, worker à `concurrency: 1` (le service KiCad est le goulot)
- Auth : Supabase Auth (email + Google OAuth)
- Paiement : Lemon Squeezy (MVP)
- Viewer Schéma + PCB : KiCanvas (rendu natif .kicad_sch / .kicad_pcb depuis Supabase Storage)
- Viewer 3D : Three.js — `Board3DView` sur le GLB de `POST /export/glb` pour le mode `3d` du viewer (voir « 3D INTERACTIVE ») ; `View3D` dessine des boîtes à partir du `PCBState` dans l'onglet 3D d'ExportView
- Rendu PNG / 3D « comme KiCad » (2026-09-13) : `POST /render/auto` du service
  (`kicad-cli pcb render`, fail closed, `routers/render.py`) → route web
  `GET /api/projects/[id]/render?view=top|bottom|iso|front|…&quality=&yaw=`
  (auth + propriétaire, ETag sur le contenu du board → 304 sans rendu) → modes
  `png` / `3d` du viewer (`RenderView.tsx`). Le viewer KiCanvas est en
  `controls="full"` : couches, nets, objets, empreintes, propriétés, et la
  sélection au clic (`kicanvas:select`) nommée dans le HUD. Mesuré : basic top
  ≈ 1 s, high iso ≈ 4 s sur 8 composants via HTTP ; kicad-cli rend un peu MOINS
  que la taille demandée (800×500 → 784×480) et refuse les vieux boards écrits
  par kicad_tools (« Failed to load board »). Gardes : `tests/test_render_auto.py`,
  `apps/web/src/test/project-render-route.test.ts`, `viewer-render-and-selection.test.tsx`.
- 3D INTERACTIVE (2026-09-14) : le mode `3d` du viewer est `Board3DView.tsx` —
  le GLB exporté par `POST /export/glb` (`kicad-cli pcb export glb`, pistes,
  pastilles, zones ; ~850 Ko, 1-3 s), servi par `GET /api/projects/[id]/model`
  (même cache à deux niveaux que `render`, clé `cleDuModele`, `renders/<clé>.glb`,
  pré-exporté par le pipeline dans `prerendus.ts`), affiché dans Three.js avec
  des contrôles d'orbite. Le rendu raytracé reste accessible par « Photo ».
  **Composants en 3D** (2026-09-14) : le PPA 10.0 ne fournit pas
  `kicad-packages3d`, et le dépôt complet pèse plusieurs Go. Les 25
  bibliothèques STEP utiles (~1 Go) vivent dans le VOLUME Docker
  `cirqix-3dmodels`, rempli par `services/kicad/scripts/modeles_3d.sh`
  (clone partiel de kicad-packages3D) et monté sur
  `/usr/share/kicad/3dmodels` (`KICAD10_3DMODEL_DIR`). Le volume survit aux
  reconstructions de l'image. `POST /export/glb` rend `models_found /
  models_declared`, relayé par `X-Model-Components` : le viewer DIT « aucun
  modèle 3D installé (0/9) » plutôt que de laisser croire que la carte porte
  ses composants. Bouton « Composants » : carte avec corps, ou carte nue
  (`?components=0`, clé de cache distincte).
  ⚠️ `alpine/git` ne connaît pas `sparse-checkout` : le script passe par
  l'image du service. ⚠️ Un conteneur lancé à la main doit recevoir
  `-v cirqix-3dmodels:/usr/share/kicad/3dmodels:ro` et
  `-e KICAD10_3DMODEL_DIR=/usr/share/kicad/3dmodels`.
  ⚠️ **Next 15 embarque React 19 pour l'App Router** quel que soit le React
  installé (`react@18.3.1` dans `package.json`) : `@react-three/fiber` 8 lisait
  `ReactCurrentOwner`, un interne de React 18, et faisait tomber TOUTE la page
  — l'ancien `View3D` de l'export n'a donc jamais pu s'afficher là. Passé en
  fiber 9 + drei 10 (pnpm signale des pairs non satisfaits : attendu).
  ⚠️ Pas de `<Environment>` de drei : il va chercher un HDR sur un CDN que la
  CSP bloque, et l'erreur sortait du viewer. Éclairage local, et une frontière
  d'erreur garde l'échec DANS le viewer. Le bucket doit accepter
  `model/gltf-binary` (migration 025, même cause que 024 pour les PNG).
  Gardes : `tests/test_export_glb.py`, `project-model-route.test.ts`,
  `board-3d-view.test.tsx`.
  **Pré-rendus à la livraison** : après `done`, le pipeline rend top + iso et les
  dépose sous `renders/<clé>.png` (`pipeline/prerendus.ts`, `render-cache.ts`) ;
  la route sert ce cache avant de rendre, et dépose ce qu'elle rend. UNE clé
  (`cleDeRendu`, contenu du board + paramètres) partagée route ↔ pipeline — une
  sérialisation différente rendrait le cache aveugle. Best-effort de bout en bout.

## Règles agents Claude

- Orchestrateur = Sonnet 4.6 — max 15 itérations par PCB
- Agents spécialisés qui appellent un modèle = Haiku 4.5
- Coût cible : ~0.12€ par PCB complet
- Prompts des agents : dans le code ; index dans `docs/agentdescription.md`
- **JAMAIS** de commande JLCPCB automatique — confirmation "OUI JE CONFIRME" obligatoire

## Stratégie moteur PCB (état actuel — Phase 4)

### Pipeline complet opérationnel — 8 agents experts

```
User → Sonnet 4.6 (orchestrateur, max 15 itérations, SSE)
  ① call_agent_schema     → Ingénieur Schéma
     ⚠️ (2026-09-13, D-2026-09-13-a) `CIRQIX_SCHEMA_PROVIDER=claude-code` fait
        écrire le schéma par Claude Code (`claude -p`, stdin, cwd temporaire)
        au lieu de Haiku ; contrat unique dans `tools/handlers/schema-prompt.ts`.
        Seulement là où le CLI est connecté (worker sur l'hôte, pas le conteneur).
        ⚠️ Cela ne remplace PAS l'orchestrateur Sonnet : depuis le dashboard,
        `CIRQIX_AGENT_MODE=driver` (D-2026-09-13-b) enfile des runs `driver`
        sans retenue ni commandabilité — zéro appel API de bout en bout.
     Haiku 4.5 → JSON typé → POST /schematic/generate :
       ① circuit_synth pip · ② kicad-tools Schematic · ③ TypeScript S-expr
     Stocke : kicad_sch_content dans pcbStateCache (tools/shared.ts)
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
     ⚠️ (2026-09-15) **31 avertissements par run venaient de l'ENVIRONNEMENT.**
        `~/.config/kicad/10.0/` n'avait ni `sym-lib-table` ni `fp-lib-table` :
        « The current configuration does not include the symbol library
        'power' » (22 `lib_symbol_issues`, 9 `footprint_link_issues` sur le
        NE555). Le projet restait à `SCHEMA_DONE`, jamais `ERC_CLEAN`. L'image
        copie désormais les modèles de `/usr/share/kicad/template/` :
        31 → **0**, témoin sans tables revenu à 31 ; DRC identique sur
        carte-05/08/10. Dans l'IMAGE, car `$HOME` n'est pas un volume.
        Garde : tests/test_tables_bibliotheques_kicad.py.
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
     Cascade (`findFootprint`) : KiCad libs → pgvector → SnapMagic → LCSC → AI Haiku
     Met à jour pcbStateCache[projectId].schema.components[ref].footprint
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
     Contrat vérifié contre le service RÉEL par
     `packages/agents/src/tests/pipeline-live.test.ts` — les tests mockés
     reproduisent l'hypothèse du client et ne le voient pas : `handlePlacement`
     part du board que `gen_pcb` a mis en cache (`pcbStateCache`) au lieu de le
     régénérer ; `/place/auto` rend `{ref, x_mm, y_mm}` ; le budget client est
     `PLACEMENT_TIMEOUT_MS` (`engines/placement-budget.ts`, 900 s).
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
        lecture et en réécrivant un fichier lisible : la coulée du plan de masse
        n'y était pour rien.
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
  ⑥ call_agent_routing    → Ingénieur Routage
     POST /route/auto — cascade de routers/routing.py::route_auto :
     Niveau 1 API Freerouting (JVM persistante, port 37864) · Niveau 2 Freerouting
     en sous-processus · Niveau 3 kct route A* (≤ 30 nets/composants) · Niveau 4
     kct route negotiated sans limite · Niveau 5 skipped. À chaque palier, les
     couches sont escaladées par `_expand_stackup`, quel que soit le routeur.
     → renvoie routed_percent RÉEL (tools/handlers/routing.ts : plus jamais hardcodé 100)

     **SÉQUENCE À L'INTÉRIEUR D'UN PALIER** (demandée par l'utilisateur, livrée
     le 2026-08-29) — `routers/routing.py::route_auto`, pour chaque palier :

        ① plan de masse COULÉ ET REMPLI, sur les deux faces extérieures
           (In1.Cu dès 4 couches : D-2026-09-12-b, RÉFUTÉE par la mesure le jour même — réglage de banc `plan_gnd_interne` seulement)
        ② vias d'échappement réservés (déclarés dans le DSN)
        ③ routage des signaux (GND est confié au plan, `_NETS_CONFIES_AU_PLAN`)
        ④ replacement des vias réservés (le round-trip Specctra les efface)
        ⑤ plans re-coulés + remplis, fanout des pastilles isolées
        ⑥ couture des îlots de plan, RÉPÉTÉE jusqu'à épuisement

     ⚠️ **L'ÉTAPE ② VISE TOUTE PASTILLE CMS D'UN NET DE PLAN** (2026-09-02),
     plus seulement les boîtiers denses. Elle ne visait qu'eux, sur la prémisse
     que « le plan atteint sans peine la masse d'une résistance ». Mesure sur
     `stm32-100` : `U1.8`, `C12.2` et `C2.2` finissent orphelines du plan, et
     AUCUNE n'appartient à un boîtier assez dense pour être visée — deux
     condensateurs et une broche de MCU. Elles étaient collées au plan F.Cu
     AVANT le routage ; ce sont les pistes de signal qui ont découpé le plan
     autour d'elles. C'est un EFFET du routage, pas un état initial.

     Compte par carte : **3 à 57 dogbones**, des dizaines et non des centaines.
     Les traversantes restent exclues — leur perçage atteint déjà le plan d'en
     face, et le doublon a déjà coûté à ce dépôt le rejet TOUT-OU-RIEN de
     vingt et un vias. Garde : `tests/test_dogbone_gnd_sur_toute_pastille_cms.py`.

     ⚠️ **UN DOGBONE, PAS UN VIA DANS LA PASTILLE.** Avis de Grok, qui tranche
     entre les deux : un via sous chaque capa occuperait B.Cu **pile sous le
     composant**, c'est-à-dire le meilleur canal de signal sur deux couches.

     ⚠️ **AMORCE SUR LA FACE OPPOSÉE : ESSAYÉE, RÉFUTÉE** (2026-09-02). Poser
     avec le via une courte piste de masse sur l'autre face, protégée dans le
     DSN, pour que le plan re-coulé rejoigne toujours le via. GLM validait le
     principe et avertissait du bouchon de routage ; c'est le bouchon qui l'a
     emporté :

        | | % | manq | seg | segments GND | durée |
        |---|---|---|---|---|---|
        | sans amorce | 99 | 1 | 779 | **57** | 901 s |
        | avec amorce | 99 | 1 | 732 | **6** | 2798 s |

     Aucun gain, **trois fois plus lent**, et les segments GND survivant au
     round-trip s'effondrent de 57 à 6 : les amorces protégées gênent le
     routeur au point de lui faire perdre les dogbones eux-mêmes. Retirée ; la
     réfutation vit à son site dans `_escape_pads`.

     ### Résultats de banc

     À jour : `examples/BANC_DRIVER_LLM.md` et le `mesures.json` de chaque carte.
     Les huit cartes historiques portent `expected/3_route.kicad_pcb`, rejouable
     par `scripts/router_les_placements.py`. Un résultat ne fait foi que si son
     board est versionné.

     `examples/carte-11-croisements` éprouve l'escalade 2 → 4 → 6 → 8 : son
     faisceau inversé n'est pas planaire, et sur 2 couches la face arrière porte
     le plan, ce qui ne laisse qu'une face de signal. Tant que le meilleur board
     n'est pas livrable, l'escalade va jusqu'au plafond du plan ; seul le budget
     l'arrête (D-2026-09-25-e).

     ⚠️ **Le PLANCHER reste un simple message de journal, et c'est voulu.**
     `_couches_pour_echapper` rend 4 pour `stm32-100` ; le service tente quand
     même 2 d'abord — « on escalade sur PREUVE, pas sur prévision », parce qu'une
     carte 2 couches coûte moins cher. La mesure lui donne raison : cette carte
     route à 100 % sur DEUX couches en 208 s.

     La journalisation est configurée dans `main.py` (niveau `LOG_LEVEL`, INFO par
     défaut) : uvicorn ne configure que SES loggers, et sans elle les décisions
     d'escalade — qui coûtent du cuivre, donc de l'argent au client — n'apparaissent
     pas dans `docker logs`.

     ⚠️ **NEVER conclure qu'un défaut de routage est STRUCTUREL sans avoir
     compté plusieurs tirages.** `stm32-100`, qui gardait une connexion
     manquante près d'un îlot réel de 0,9 mm² autour de la masse de `D21`,
     donne, rejouée avec `--tirages=3` au MÊME placement gelé :

        99 %   97 %   77 %   (panne écartée)   87 %   …   **100 %**

     23 points d'écart : **deux tirages concordants ne prouvent rien**, pour le
     routage comme pour le placement.

     ⚠️ **LE PLAN EST COULÉ AVANT LE ROUTAGE, PAS APRÈS.** On le coulait après :
     le routeur ne voyait donc jamais le cuivre de masse et routait comme si la
     carte était vide. Mesure sur la Nucleo, même placement : 68-71 % (plan
     après) contre 94 % (plan avant). C'est ce seul changement d'ordre qui a
     débloqué le 100 % sur six cartes du banc.

     ⚠️ Un plan **non rempli** n'est qu'un contour, dont le routeur ne tient
     aucun compte. `_fill_zones` est obligatoire.

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

     Ne pas lire cet avertissement comme un diagnostic de connectivité, ni viser
     « ≤ 1 îlot » par la couture : le message d'une garde dit ce qu'elle a mesuré.

     Les replis GND (`_router_en_incluant_gnd`, ciblé et global) ne remplacent le
     board que si `_secours_est_meilleur` le juge meilleur. `_bilan_drc` rend
     `None` sans verdict (kicad-cli n'a pas su ouvrir le board), et
     `_secours_est_meilleur` refuse toute comparaison avec `None` : un secours
     illisible ne bat jamais un board mesuré. Garde :
     `tests/test_repli_gnd_sans_verdict.py`.

     **ESCALADE DES COUCHES** — méthode demandée : tirages au palier courant,
     puis +2 couches, en gardant TOUJOURS le meilleur (jamais le dernier).

        `_layer_ladder`            2, 4, 6, 8 … jusqu'au plafond du plan
        `_TIRAGES_ROUTAGE_PAR_PALIER = 3`   Freerouting est STOCHASTIQUE
        `_palier_meilleur`         classe sur (pourcentage, erreurs DRC)
        `layers_tried`             plus haut palier essayé, rendu au client : il
                                   déclenche l'agrandissement (D-2026-09-11-b)

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

     ⚠️ Le plancher d'échappement (`_couches_pour_echapper`) est calculé et
     journalisé, mais il ne fixe pas le palier de départ : on part toujours de
     2 couches (décision utilisateur du 2026-08-29 : on escalade sur preuve, pas
     sur prévision). Sous le plancher, un seul tirage de preuve par palier
     (D-2026-09-11-a).

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
        un board routé à 100% + boucle infinie jusqu'à max_steps. Voir docs/notefinal.md
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

**Placement (`tools/placement.py::auto_place`). L'ordre fait partie du contrat : le revérifier dans le code avant de s'y fier.**
gen_pcb fournit une grille de départ. Chaque tirage enchaîne : `place_unplaced` si besoin
→ connecteurs J*/P* clampés puis collés au bord → ① Architecte (OptimizationWorkflow
hybrid, `write_to_pcb()` obligatoire) → ③ Inspecteur → ② Géomètre CMA-ES (processus
enfant, filets) → ③ Inspecteur → ④ halo d'escape → ⑤ snap bypass → alignement sur la
grille (dernier déplacement) → réparation des chevauchements vus par kicad-cli.
Plusieurs tirages sont faits et le meilleur est gardé (moins de conflits, puis moins de
croisements, puis moins de fil). Ensuite, ⑥ le contour est resserré sur le tirage gardé
si la taille n'est pas imposée. Toute étape qui déplace des composants après le snap ou
l'alignement les défait. Détail et gardes de chaque étape :
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
  ⓪ ~~**Bords** (connecteurs au milieu d'un bord)~~ — **essayée et RÉFUTÉE le
     2026-09-13** (D-2026-09-13-c B) : sur le banc, le centrage était déjà à
     ±1 % sur huit cartes et la règle dégradait le découplage sur sept
     (carte-08 2,6 → 3,9 mm, carte-10 4,1 → 5,6). Fonction conservée dans
     `tools/contour_et_bords.py`, NON appelée. **NEVER** la rebrancher sans
     re-mesurer sur les onze cartes.
  ⑥ **Contour** (`ajuster_contour_au_placement`, D-2026-09-13-c A, EN DERNIER) — quand
     ni l'appelant ni la description n'imposent de taille (`auto_size_board`, posé par
     `handlePlacement` ; le driver dit `board_size_imposed` dans le schéma), `Edge.Cuts` est resserré sur les courtyards + 3 mm, en repère
     FEUILLE, jamais agrandi. ⚠️ `board_origin` de kicad-tools SUIT le contour : les
     positions relatives changent, pas les positions de feuille.
     Mesuré le 2026-09-14 sur le banc : −16 à −25 % de surface sur les circuits petits
     devant leur carte (01, 04, 06, 07 livrées, 100 % / 0 erreur), gain nul sur les
     cartes denses — le génétique remplit la carte. Tableau : D-2026-09-13-c.
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
     PLEIN DANS le module. Le courtyard se lit par `placement._boite_orientee_fp`,
     qui TOURNE avec le composant ; `_boite_locale_fp` rend le repère du
     footprint, non tourné, et ne s'ajoute jamais tel quel à `fp.position`.

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

  Le backend C++ `kct build-native` n'accélère que `kct route`, c'est-à-dire les
  Niveaux 3-4 de la cascade, qui ne servent que si Freerouting (Niveaux 1-2) est
  absent, échoue ou n'a plus de budget. Comptage sur trois journaux (2026-08-30 :
  run qui a livré `stm32-100` à 100 %, banc des 7 cartes) :

      16 routages effectués :  16 × (freerouting-api)  ·  0 × (kicad-tools)

  Le compiler ou non ne change donc rien aux résultats actuels.
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
Freerouting   → ✅ API server   (1 JVM port 37864, RECYCLÉE après chaque routage)
```

⚠️ **La JVM Freerouting tournait à vide pour toujours (mesuré le 2026-09-19).**
« RAM 400 MB fixe » était faux : au repos, sans aucun routage, elle brûlait
**104-113 % d'un cœur et 2,5 Go**. Relevé de threads (`kill -3` sur `pgrep -x
java` — `pgrep -f freerouting.jar` depuis `bash -c` se vise lui-même) : un seul
thread, `RoutingJobScheduler` l. 58, `RUNNABLE` depuis le 2e run d'une série.
Dans Freerouting v2.1.0 (et v2.2.4), cette boucle ne dort QUE si la file de jobs
est vide, et un job terminé n'est jamais retiré (aucune route de l'API v1 ne le
fait). Dès le premier routage, la JVM ne dormait donc plus jamais.
`_un_seul_routage_a_la_fois` la recycle désormais à la fin de chaque routage,
sous le verrou : 0 % et ~200 Mo après un run, pour ~9 s par routage. Garde :
`tests/test_jvm_recyclee_apres_routage.py`. **NEVER** lire `ps -o pcpu` comme
une mesure instantanée : c'est une moyenne sur la vie du processus.

⚠️ **Un job Freerouting FIGÉ ne se lit pas, ne s'arrête pas, et meurt avec la
JVM (mesuré le 2026-09-20).** L'API 2.1.0 répond `/output` 400 et
`/output/stream` 500 tant que le job tourne, `cancel` est 501, et
`max_passes` / `job_timeout` sont acceptés puis IGNORÉS — par job comme en
global (`feature_flags.snapshots` n'écrit rien non plus). Le code notait le job
figé « pour récupérer son cuivre plus tard », puis tuait la JVM à la ligne
suivante : `_recuperer_jobs_abandonnes` n'a donc JAMAIS rien récupéré, et
quand tous les tirages figeaient la carte sortait SANS board (A/B du
2026-09-19 : quatre cartes sur dix, dans les deux bras). **Le CLI n'honore
pas `-mp` non plus** (mesuré le même jour : 186 passes avec `-mp 3`, et aucun
`.ses` s'il est tué ; le jar 1.9.0 exige AWT et ne démarre pas sur le JRE
headless). `_board_partiel_par_cli` rejoue donc le DSN du meilleur tirage
figé sous un budget STRICT de 600 s et ne rend `freerouting-cli-partiel` que
si le CLI converge seul (carte-07 : oui, en 17 min, 204 erreurs — jugeable,
pas fabricable ; carte-09 : non). **Avec Freerouting 2.1.0, un routage ne se
borne pas et un partiel ne se lit pas** : c'est une limite du routeur, pas
un réglage à trouver. Garde : `tests/test_tirage_fige_rend_un_partiel.py`.

⚠️ **Les 4 workers N'ISOLENT PAS `pcbnew` à eux seuls (constat 2026-08-09).**
Ils isolent bien les requêtes **entre** workers, mais **pas à l'intérieur** d'un
worker : les routes du service sont déclarées `def` et non `async def`, donc
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

### ⚠️ RECRÉER LE CONTENEUR, PAS LE REDÉMARRER (2026-09-05)

Le service KiCad mourait par intermittence pendant un routage HTTP : un sur deux
rendait un `RemoteDisconnected` côté client et un `Child process died` côté
journal, sans la moindre ligne applicative. Après un `docker rm` + `docker run`
— conteneur **NEUF**, `/tmp` vierge — **9 routages sur 9** passent à 100 %, en
**21 à 27 s** au lieu de 40.

`docker restart` **conserve `/tmp`** : verrou X orphelin (l'un datait du
2026-09-01 et empêchait Xvfb de repartir, privant `pcbnew` d'affichage),
fichiers de session, jobs Freerouting zombies. Un conteneur recréé repart propre.

**ALWAYS** recréer le conteneur avant d'investiguer le code sur une instabilité
du service.

⚠️ **`docker-compose` v1 est CASSÉ avec Docker 29** (`KeyError:
'ContainerConfig'`) et **supprime le conteneur AVANT d'échouer** : il laisse le
service mort. Passer par un `docker run` explicite.

### Mémoire d'un routage : ~0,2 Go (mesuré le 2026-09-05)

Les 6,2 Go parfois cités sont le RSS d'un processus tué en lançant DEUX routages
concurrents dans le même processus Python — pas le coût d'UN routage.

Échantillonnage du cgroup, un point par seconde pendant trois routages réussis :

| | mémoire du conteneur ENTIER |
|---|---|
| au repos | 1,67 Go |
| **crête pendant 3 routages** | **1,84 Go** |
| processus tué, 2 routages concurrents | 6,2 Go |
| machine | 7,6 Go |

Un routage coûte donc **~0,2 Go**, pas 6,2. La concurrence produit bien un
emballement — le verrou de `tools/verrou_routage.py` reste justifié — mais le
motif inscrit était trompeur, et un chiffre faux dans ce fichier est pire qu'un
chiffre absent : il sert de prémisse à la décision suivante.

⚠️ Ce défaut est INTERMITTENT : **« 1 worker et 4 workers réussissent tous
deux » ne RÉFUTE rien — il faut un TAUX d'échec, pas un succès isolé.** Les
quatre pistes écartées valent donc comme INDICES, jamais comme preuves :

| piste | ce qui a été observé | statut |
|---|---|---|
| exécution hors thread principal | un appel dans un `threading.Thread` a routé à 100 % | indice |
| sondage concurrent d'une autre route | échecs aussi sans sondage | indice |
| nombre de workers | 1 worker et 4 workers ont réussi | indice |
| origine de l'appel | hôte et intérieur du conteneur ont réussi | indice |

⚠️ Les asserts `PROPERTY_ENUM` du journal sont du **BRUIT** : 10947 occurrences
dans l'historique, présentes aussi quand tout va bien. **NEVER** lire un message
répété comme un diagnostic.

⚠️ **Le banc ne voit RIEN de tout cela** : `banc_exemples.py` importe
`route_auto` en Python et n'exerce donc JAMAIS la voie HTTP. Les huit cartes à
100 % du 2026-09-03 étaient vertes pendant que la voie HTTP mourait une fois
sur deux. Seuls le worker et l'orchestrateur passent par HTTP.

⚠️ Défaut voisin : un `/tmp/.X99-lock` orphelin empêche Xvfb de redémarrer
après un `docker restart`, privant `pcbnew` d'affichage. Cette ligne le disait
« corrigé » depuis le 2026-09-05 — **faux** : l'entrypoint ne supprimait aucun
verrou. Reproduit le 2026-09-19 (« Server is already active for display 99 »,
verrou du 15 septembre), avec /health à 200 et la JVM vivante : rien ne le
signalait. L'entrypoint supprime désormais verrou et socket avant `Xvfb :99`
(`tests/test_xvfb_verrou_orphelin.py`) — **effectif seulement après
reconstruction de l'image**, l'entrypoint n'étant pas monté à chaud.
Toujours vérifier `pgrep Xvfb` après un redémarrage du conteneur.

Dimensionnement : `D-2026-09-03-b`, tranchée le 2026-09-04 — un seul routage à la
fois (verrou de `tools/verrou_routage.py`, 503 si occupé), 4 workers conservés.

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

**Routing — nets routables :** `_count_routable_nets` compte les nets portés par au moins deux pastilles — `(net 3 "GND")` (kicad-tools, KiCad ≤ 9) ajoute une déclaration en tête, `(net "GND")` (pcbnew 10) non — et exclut les nets à une seule pastille (`Net-(U1-X)`) ainsi que les nets confiés au plan (`_NETS_CONFIES_AU_PLAN`).

## Pipeline asynchrone — pourquoi la file existe

Une invocation web est plafonnée à `maxDuration = 300` s
(`apps/web/src/app/api/agent/route.ts`), alors qu'un routage réel dure de quelques
minutes à plus de 40 (mesure fondatrice du 2026-08-19, board STM32 : génération 3 s,
placement 175 s, routage 861 s). Le pipeline passe donc par BullMQ et un worker sans
plafond (`CIRQIX_ASYNC_PIPELINE`, fail-closed dans le code, allumé là où Redis et le
worker tournent).

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

### Nets KiCad 10 : le round-trip Freerouting conserve la netlist (2026-08-20)

Une garde qui annonce *99 nets en entrée, 0 en sortie* après le round-trip
Specctra mesure mal : elle ne lit pas l'écriture de KiCad 10.

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

### Contrat de l'API Freerouting v2.1.0 (Niveau 1)

`_find_freerouting_api` sonde la JVM persistante (port 37864) sous le préfixe
`/v1` — pas `/api/v1`, que ce serveur ne sert pas : la sonde rendrait `None` et
chaque routage retomberait sur le Niveau 2, un `java -jar` complet.

Chacun de ces points suffit seul à casser le client : envoyer les en-têtes
d'identité (`Freerouting-Profile-ID`…, sinon 500), passer le DSN en JSON
`{"data": <b64>}` (multipart → 415), comparer l'état en majuscules (le serveur
sérialise `"COMPLETED"`), démarrer un job par `PUT …/start` (`POST` → 405).
Gardes : `tests/test_freerouting_api_contract.py`.

⚠️ **`api_server-endpoints` ne peut PAS se passer en ligne de commande** :
`ApiServerSettings.endpoints` est un `String[]`. L'option lève « Failed to set
property value » au démarrage sans jamais s'appliquer — une erreur rouge, réelle,
qui ne dit rien de l'état du serveur. Pour changer le port, il faut un
`freerouting.json` sous `--user_data_path`.

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

`kicad-tools` rend exactement **91 %**, le plancher documenté, sous `_MIN_ROUTED_PCT`
(95 %) : à l'époque de cette mesure, il passait en Niveau 1 et payait ~10 min dont
le produit était ensuite jeté — l'une des raisons pour lesquelles Freerouting passe
désormais en premier.

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

### Ordre de la cascade de routage

Freerouting (API, puis sous-processus) passe en premier, kicad-tools sert de repli
(Niveaux 3-4) : décision utilisateur du 2026-09-01, garde
`tests/test_ordre_des_niveaux.py`. L'escalade de couches est faite par
`_expand_stackup` dans `route_auto`, quel que soit le routeur. Pourquoi Freerouting
d'abord : sur le banc STM32 du 2026-08-21, il laisse 0 connexion manquante en
4-5 s ; kicad-tools en laisse 7, avec 69 vias et 58 erreurs de fabricabilité. Le
routage incrémental (`--preserve-existing`) a été mesuré et écarté : il perdait la
moitié du cuivre reçu.

Si le journal montre kicad-tools en tête, vérifier d'abord le budget : quand
`_budget_suffisant` est faux, le Niveau 1 est sauté. Pour se repérer, chercher
« Niveau 1 : Freerouting » dans `routers/routing.py` plutôt qu'un numéro de ligne.

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

### Validation du 2026-09-03 — ce qui manquait vraiment

⚠️ **La migration `020` n'était PAS appliquée en production.** Mesuré avant :

```
pcb_run_events   replica_identity = d   dans supabase_realtime = non
```

`followRun` s'abonne aux INSERT de cette table : **aucun événement ne pouvait
parvenir au navigateur**. Le repli par sondage HTTP masquait le défaut — les
utilisateurs voyaient des mises à jour, jamais par Realtime. Appliquée et
vérifiée : `REPLICA IDENTITY FULL`, table publiée. `pcb_runs` reste hors
publication, conformément à la migration.

Vérifié ensuite sur les données RÉELLES de production :

| | mesure |
|---|---|
| persistance | 9 runs · 765 événements · 8 projets, déjà écrits |
| isolation RLS | propriétaire **765**, autre utilisateur **0** |
| abonnement Realtime | `SUBSCRIBED` depuis l'hôte avec la clé publique |
| advisors | aucun nouvel avertissement lié à la migration |

⚠️ **Un abonnement avec la clé de SERVICE depuis le conteneur rend
`TIMED_OUT`** ; le même abonnement avec la clé publique depuis l'hôte rend
`SUBSCRIBED`. Ne pas en conclure que Realtime est cassé : c'est le chemin du
navigateur qui compte, et il fonctionne.

⚠️ **Le drapeau aurait été INERTE.** `REDIS_URL` était vide dans
`apps/web/.env.local`, et `cirqix-redis` n'exposait aucun port : la route, qui
tourne sur l'hôte, ne pouvait pas joindre la file. Le fail-closed refusait donc
une file inatteignable — il fonctionnait exactement comme prévu. Redis est
désormais publié sur `127.0.0.1` uniquement (il n'a pas de mot de passe).

### Le parcours asynchrone est prouvé de bout en bout (2026-09-07)

Le drapeau `CIRQIX_ASYNC_PIPELINE` est **allumé** (`1` dans
`apps/web/.env.local`), Redis répond sur `127.0.0.1:6379`, et le worker a
réellement **consommé un job** (`runId 965a6fd6`, arrêté ce jour-là par le
solde de l'API du modèle).

La dernière moitié non prouvée l'est désormais : **un utilisateur CONNECTÉ
reçoit bien ses événements par Realtime, et seulement les siens.**

    abonnement Realtime (clé publique + jeton utilisateur)   SUBSCRIBED
    événement reçu, charge utile conforme                    oui
    le propriétaire lit ses événements                       1
    un AUTRE utilisateur connecté en voit                    0

Rejouable : `node packages/db/scripts/preuve-realtime.mjs apps/web/.env.local`.
Deux comptes de test sont créés puis supprimés, succès ou échec.

⚠️ **Mesuré sur 5 tirages : 4 succès, 1 fois l'événement non reçu dans les
20 s.** Realtime n'est donc PAS une garantie à 100 % : le repli par sondage
HTTP de `followRun` reste nécessaire, et c'est ainsi qu'il est écrit. Un tirage
isolé n'aurait rien prouvé, dans un sens comme dans l'autre — c'est la règle
déjà inscrite pour le routage, appliquée ici.

⚠️ **Deux pièges de la sonde Realtime, qui font passer un échec pour un succès :**

- `pcb_run_events` n'a pas de colonne `id` — sa clé est `seq`. Une requête sur
  `id` rend l'erreur 42703 au propriétaire COMME à l'autre utilisateur : `data`
  vaut `null` des deux côtés, et « l'autre ne voit rien » passe sans rien prouver.
- Nettoyage des comptes de test : `admin.auth.admin.deleteUser` **renvoie** son
  erreur au lieu de la lever (un `try/catch` ne voit rien) ; la ligne `credits`
  créée par déclencheur bloque la suppression (`credits_user_id_fkey` en
  `NO ACTION`, « Database error deleting user ») ; la suppression doit aussi
  courir sur le chemin d'échec. Le script relit ce qu'il a supprimé et le dit
  quand il n'y arrive pas.

**NEVER** annoncer qu'un nettoyage a eu lieu sans avoir relu ce qui reste. Un
effet de bord silencieux sur une vraie base coûte plus cher qu'un test raté.
### La chaîne du driver — un PCB complet sans le moindre appel au modèle (2026-09-07)

Le 2026-09-07, le solde de l'API Anthropic était épuisé. L'orchestrateur étant la
première étape, plus aucun PCB ne pouvait aboutir. Or **`call_agent_schema` est le seul maillon
INDISPENSABLE qui appelle un modèle** (le footprint IA et le reasoner sont des
replis) : le banc des dix cartes a mesuré que tout le reste va jusqu'aux Gerbers
sans lui.

`handleSchema` accepte donc un `schema_json` écrit par le driver, et
`pipeline/run-driver.ts` enchaîne les VRAIS handlers. Mesuré de bout en bout,
par la file et le worker :

```
+  4s SCHEMA   + 17s ERC   + 99s PLACEMENT   + 142s ROUTING   + 149s EXPORT
run succeeded · PCB_LIVRÉ · provenance driver · 50 Ko de Gerbers · 0 crédit
```

⚠️ **Ce n'est PAS le simulateur.** `simulator.ts` fabrique des états ; ici tout
est réel — vrai `.kicad_sch`, vrai board, vrai DRC, vrais Gerbers. Ce qui change
est la PROVENANCE du schéma, pas la qualité du résultat.

⚠️ **Ces boards ne sont PAS commandables.** `POST /api/jlcpcb/order` exige
`agent_mode = 'orchestrator'` et échoue fermé. Un schéma écrit à la main n'a pas
traversé la boucle autonome que le produit vend. **NEVER** assouplir ce gate
pour laisser passer un board du driver. Un run du driver n'est pas facturé non
plus : aucun modèle n'a tourné.

⚠️ **Le porteur est INJECTÉ, il n'est pas dupliqué.** `run-driver.ts` rend un
générateur de la même forme que `runOrchestrator` ; dépôt des artefacts, fusion
d'état, persistance, suivi du routage et finalisation restent écrits UNE fois.
`local-pipeline.ts` avait redit à sa façon ce que les handlers disaient déjà, et
persistait `DRC_CLEAN` sur un DRC en erreur. Un second chemin est un second
endroit à corriger, et on en oublie toujours un.

⚠️ **`handleSchema` plafonnait la carte à 50 × 40 mm** au-delà de 12 composants.
Le banc a mesuré que la SURFACE est le levier — `carte-08` passe de 216
connexions manquantes à ZÉRO en l'agrandissant. Le driver peut donc dimensionner
la carte ; le chemin Haiku garde exactement son comportement.

#### Deux défauts du worker, révélés par le PREMIER run réel

Aucun des deux n'était visible en test, et les deux touchaient à l'argent ou à
la sécurité.

**1. La provenance était une CONSTANTE.** `createWorkerStore` écrivait
`agent_mode: 'orchestrator'` en dur. Exact tant que le worker ne savait faire que
l'orchestrateur ; devenu un mensonge exécutoire dès qu'il a su faire autre chose.
Premier run du driver : `projet : PCB_LIVRÉ · provenance orchestrator` — un board
au schéma écrit à la main était **commandable chez JLCPCB**. Elle est désormais
relue dans `pcb_runs.agent_mode`, exactement comme le contrat du job le
prescrivait déjà, et une provenance introuvable fait échouer le run.

**2. `finalize_pipeline_success` était appelée avec les MAUVAIS arguments.** Elle
est déclarée `(uuid, uuid, integer, jsonb, text)` depuis la migration 018 —
`p_iteration_count`, et **pas** de `p_status`. Le worker envoyait
`p_pcb_state, p_status` : Postgres ne trouvait aucune surcharge, et **tout run
arrivé jusqu'à `done` échouait à la finalisation**, donc sans débit et sans
provenance. La route web, elle, appelait correctement.

⚠️ Pourquoi les tests ne voyaient rien : ils remplacent le client Supabase par un
faux qui accepte n'importe quel objet d'arguments. **Un faux plus pauvre que le
vrai ne peut pas révéler un contrat rompu** — la même leçon que le faux `pcbnew`
qui n'exposait pas `GetFootprints()`. La garde compare désormais les NOMS des
paramètres à ceux que la migration déclare.
Gardes : `services/worker/src/tests/provenance-et-finalisation.test.ts`.

Rejouer : `node services/worker/scripts/enfiler-driver.mjs <schema.json>`.

### État (vérifié le 2026-09-07)

Livré : migrations `019` et `020` appliquées ; worker (image dédiée) ; budgets ;
annulation ; Realtime avec repli par sondage HTTP (RLS prouvée pour un utilisateur
connecté : `packages/db/scripts/preuve-realtime.mjs`) ; `via_count` et
`track_length_mm` mesurés sur le board final.

Progression du routage : `route_auto` → fichier `/tmp/cirqix-progres/<clé>.json` →
`GET /route/progress/{clé}` → worker → `pcb_run_events` → Realtime. On passe par un
fichier et non par une variable de module, parce que les 4 workers uvicorn sont des
processus séparés. La clé vient du client et est validée des deux côtés ; le client
renonce à l'affichage plutôt que d'envoyer une clé refusée, car un 422 ferait échouer
le routage. Toute panne de progression est avalée : une mesure absente est
acceptable, un résultat fabriqué est interdit. Gardes : `tests/test_progres_routage.py`,
`tests/test_progres_expose.py`, `tests/routing-progress.test.ts`,
`tests/routing-progress-cablage.test.ts`.

Ouvert : la clé de progression nomme le projet, pas le run (deux runs simultanés du
même projet mélangent leur affichage) ; le budget est compté par niveau, donc un
appel peut valoir plusieurs fois `timeout_s`.

## Système de crédits

- Coûts par action : `CREDIT_COSTS` ; droits par plan (couches, simulation, 3D) : `PLAN_ENTITLEMENTS` — les deux dans `@cirqix/types`, qui fait foi.
- Plans : Free (5/jour, 2 couches max) | Pro 25€/mois (100, 4 couches) | Pro Max 50€/mois (300, 8 couches) | Enterprise (illimité, 8 couches)
- Un run RÉSERVE ses crédits avant de démarrer (`reserve_pipeline_credits`), les débite au succès (`finalize_pipeline_success`) et les LIBÈRE sinon (`release_pipeline_reservation`) : jamais de débit sans résultat.

## Base de données

- RLS activée sur toutes les tables — tester isolation user A / user B
- pgvector pour embeddings footprints
- Schéma : les migrations `packages/db/supabase/migrations/` font foi ; `PLAN.md` §Phase 0 n'en donne que l'état initial

## Types source de vérité — `@cirqix/types`

- `PCBStatus` = `'INITIAL' | 'SCHEMA_DONE' | 'ERC_CLEAN' | 'PLACEMENT_DONE' | 'ROUTING_DONE' | 'DRC_CLEAN' | 'PCB_LIVRÉ'`
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

Pas de taille de texte fixe sur un titre visible ; vérifier le rendu à 375 px (mobile)
avant de valider.

## Organisation des tests

Les scripts de test vont dans le dossier `tests/` du package concerné :

```
packages/agents/src/engines/     ← code source
packages/agents/src/tests/       ← tests unitaires *.test.ts

services/kicad/tests/            ← tests Python FastAPI (nos routers)
apps/web/src/test/               ← tests frontend

scratch/                         ← INTERDIT — jamais de scripts ici
racine du projet                 ← INTERDIT — jamais de scripts de test à la racine
services/kicad/kicad-tools/      ← INTERDIT — jamais ajouter de tests ici (lib upstream)
```

Pas de script de test à la racine du projet, dans `scratch/` ni hors d'un dossier `tests/`.
Rien à créer ni modifier dans `services/kicad/kicad-tools/tests/` : c'est le sous-module
du fork upstream, pas notre code. Ne pas committer `test_out*.kicad_pcb`, `output_*/` ni
de captures de test. Nommer les tests `*.test.ts` (TS) ou `test_*.py` (Python).

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

- `carte-01-diviseur/` … `carte-10-maximale/` — **le banc du driver LLM**, de 5 à
  70 composants, toutes 100 % routées et 0 erreur, relivrées le 2026-09-19
  (couture corrigée, #217, 678 → 443 vias) : huit sur 2 couches, carte-08 et
  carte-10 sur 4 — un tirage, pas une propriété. Détail et compte par couche :
  `BANC_DRIVER_LLM.md`, `mesures.json`. Leur schéma
  est ÉCRIT PAR LE DRIVER (Claude Code joue l'Ingénieur Schéma) : c'est le seul
  chemin qui n'appelle aucun modèle, et il couvre l'angle mort du banc
  historique, dont les huit cartes partent d'un `circuit.json` FIGÉ. Voir
  `examples/BANC_DRIVER_LLM.md`.
- `carte-11-croisements/` — livrée **NON FABRICABLE**, et c'est son objet : elle
  existe pour éprouver l'escalade de couches (32 signaux en ordre inversé, que
  deux couches ne peuvent pas router). Ne pas la « réparer ».

⚠️ Les huit cartes historiques portent désormais `expected/3_route.kicad_pcb` en
plus de leur placement, rejouables par `scripts/router_les_placements.py`.

⚠️ **`output/` est gitignoré, et les Gerbers n'y sont donc PAS versionnés.** Ils
se régénèrent depuis le board livré par `scripts/exporter_les_cartes.py` — 20
fichiers par carte, par la route `/export/all`, celle de la production. Question
posée le 2026-09-07 : « leur sortie est où ? ». Le board routé EST livré ; les
fichiers de fabrication se refont à la demande.

(`stm32-full-pipeline/` supprimé au commit `8faf685` — ne plus y faire référence.)
(`parcours-driver-llm/` jamais fusionné — supplanté par les onze cartes.)

---

## Variables d'environnement requises

`ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `REDIS_URL`, `LEMON_SQUEEZY_API_KEY`, `KICAD_SERVICE_URL`, `KICAD_SERVICE_TOKEN`

## Phase actuelle

**Phase 4 — 3D + JLCPCB + Paiement** : sous-phases 4.1 à 4.4 livrées ; état de la phase et suite : `PLAN.md`.

Le détail des livraisons des phases 2 à 4 est suivi dans `PLAN.md` et dans l'historique git.

### Règles vivantes issues des phases 2 à 4

- **Simulation fail-closed**, dans le service Python comme dans le handler
  TypeScript : aucune donnée sur un chemin dégradé ; le mode démo n'existe qu'en
  opt-in (`CIRQIX_SIMULATION_DEMO=1`), jamais comme repli sur erreur. Gardes :
  `services/kicad/tests/test_simulation_fail_closed.py`, `tests/simulation-fail-closed.test.ts`.
- **`canSimulate` est vérifié dans le handler**, avant le repli démo, et pas dans le
  prompt : un modèle à qui l'on demande de ne pas appeler un outil finit par
  l'appeler. Garde : `tests/simulation-plan-gate.test.ts`.
- ⚠️ **`canView3D` ne protège que l'onglet 3D d'ExportView** (`View3D`, qui dessine des
  boîtes à partir du `PCBState`). Depuis le 2026-09-14, le mode `3d` du viewer
  (`Board3DView`, dans `PcbView`) consomme un artefact serveur,
  `GET /api/projects/[id]/model` (GLB), et n'est contrôlé ni côté client ni côté
  serveur. Le droit peut donc désormais être appliqué côté serveur : décision
  produit en attente (droits liés au plan, §3), à ne pas implémenter sans
  validation de l'utilisateur. Par contraste, `maxLayers` (handleRouting) et
  `canSimulate` (handleSimulation) sont appliqués côté serveur.
  Garde actuelle : `apps/web/src/test/view3d-plan-gate.test.tsx`.

### Phase 4.4 — Paiement Lemon Squeezy ✅ (vérifié le 2026-09-03)

Avant de recommander une étape, vérifier dans le code qu'elle n'est pas déjà
livrée : une « prochaine étape » périmée fait recommencer du travail fait.

- `apps/web/src/app/api/webhooks/lemon-squeezy/route.ts` — cinq événements :
  `order_created` (top-ups), `subscription_created`, `subscription_renewed`,
  `subscription_cancelled` (seulement si plus d'accès restant), `subscription_expired`
- `apps/web/src/shared/lib/checkout-signature.ts` — l'`user_id` voyage **signé**
  dans l'URL de checkout : sans cela, n'importe qui créditerait le compte d'autrui
- `apps/web/src/app/(dashboard)/dashboard/billing/page.tsx` — packs de top-up
  20 / 100 / 300 crédits, plans Pro et Pro Max
- Migrations `008` (idempotence webhook), `009` (verrouillage RPC crédits),
  `013` (crédit atomique), `016` (expiration d'abonnement)
- Tests : `lemon-squeezy-webhook`, `lemon-squeezy-subscription-end`, `checkout-signature`

### Prochaine étape

- Environnement : pas de déploiement distant (Vercel non lié). La « production » est
  la machine de développement, avec Redis et le worker en conteneurs. Reconstruire
  l'image `cirqix-worker` après tout commit dans `packages/agents` ou `services/worker`.
- Si un run échoue sur `credit balance is too low`, vérifier le solde par un appel
  réel avant de conclure. Sans solde, la chaîne du driver (`pipeline/run-driver.ts`)
  livre des boards réels, mais non commandables (provenance `driver`) et non facturés.
- Faire relire les onze cartes du banc par un œil humain : DRC-clean ne veut pas
  dire « bien conçu ».

⚠️ **`TEXT-FLOW PLACEMENT FAILED` n'est PAS un blocage** (vérifié le
2026-09-03). Le message apparaît sur toute carte d'environ 55 composants ou
plus — `nucleo-f401`, `stm32-100` — jamais sur `stm32-30`, et la ligne SUIVANTE
du journal dit

    🔄 PLACE_COMPONENTS: Using fallback grid placement

Le schéma EST produit, avec un placement en grille au lieu du flux de texte.
C'est une dégradation de lisibilité, pas une panne. **NEVER relayer le message
d'une garde comme un diagnostic** — et lire la ligne suivante avant de conclure.

---

## Skills — sélection et création

**Ordre de priorité :**
1. `everything-claude-code:xxx` en premier
2. Skills installés → voir `.claude/SKILLS.md`
3. `npx skills find "query"` → skills.sh
4. `/skill-creator:skill-creator` → créer si rien n'existe

**Skills prioritaires Phase 4 :**
1. `cirqix-prompt-improver` — TOUJOURS en premier
2. `cirqix-circuit-synth` — génération schéma KiCad, mapping symbols, pin names
3. `cirqix-kicad-service` — FastAPI pcbnew : placement, Freerouting, DRC, export
4. `cirqix-pcb-agent` — boucle agentique + états machine
5. `cirqix-footprint` — cascade KiCad → cache pgvector → SnapMagic → LCSC → génération Haiku
6. `cirqix-drc` — boucle DRC max 3×, corrections pcbnew
7. `cirqix-credits` — déduction crédits Supabase
8. `cirqix-viewer` — KiCanvas dual-mode + Three.js 3D
9. `/everything-claude-code:python-patterns` — FastAPI / pcbnew / ngspice
10. agent `security-reviewer` (ou `/everything-claude-code:security-review`) — avant commit (auth / paiement)

**Créer un skill :** `/skill-creator:skill-creator` → `.claude/skills/cirqix-xxx/`
**Améliorer un skill :** montrer les changements proposés → attendre confirmation
**Règle d'or :** instruction répétée 2× → l'écrire dans CLAUDE.md ou créer un skill

---

## Règle kicad-tools — usage natif obligatoire

Avant d'écrire du code custom de placement, routage ou DRC, vérifier ce que kicad-tools
offre nativement : plusieurs leviers natifs ont déjà été trouvés écrits et jamais appelés.

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

### Principes de mesure et de correction

Les récits datés qui fondent ces principes, avec leurs mesures et leurs gardes de
test, sont dans `docs/lecons-cirqix.md`.

- Un échec ne rend jamais la valeur de son cas normal (rapport DRC vide, `None`, 0 %,
  arrondi à 100). Distinguer « mesuré à zéro » de « jamais mesuré », et échouer fermé.
- Un défaut de forme corrigé a des sœurs : chercher la même hypothèse dans les
  fonctions voisines avant de clore (nets KiCad 10, filtres de pastilles, lectures
  lourdes dans un worker).
- Le message d'une garde ou d'un DRC dit ce qu'elle a mesuré, pas la cause. Lire la
  ligne suivante et la géométrie avant de conclure ; dans un journal partagé,
  attribuer une ligne par l'heure.
- Freerouting et le placement sont stochastiques : conclure sur au moins trois
  tirages, pour le résultat comme pour la durée.
- Mesurer ce que le code lit et ce que la production exécute : le board réel (ni
  `circuit.json`, ni `expected/` quand le code lit `output/`), un service redémarré sur
  le bon code, et un banc qui appelle le service comme `handlePlacement`.
- Aucune mesure de routage pendant une autre charge (agents, revues, graphify) :
  lancer le banc détaché (`docker exec -d`, journal redirigé) et nettoyer les
  pipelines orphelins avant de relancer.
- Une règle livrée a une garde qui prouve qu'elle est APPELÉE, vérifiée sur les boards
  du banc et pas seulement sur une fixture.
- Les distances se mesurent entre corps (courtyard orienté, `_boite_orientee_fp`),
  jamais entre origines.
- Pas de travail CPU de plus de quelques secondes sous le GIL dans un worker uvicorn
  (SIGKILL après 5 s sans réponse au ping) : utiliser un processus enfant.
- Un résultat annoncé a son artefact versionné ; ce qui reste dans le conteneur
  n'existe pas.

Faits d'environnement :
- Service KiCad : le PID 1 attendu est `lancer_service.py`
  (`docker exec cirqix-kicad ps -eo pid,args --no-headers | head -1`). Reconstruire
  l'image après tout changement de `docker-entrypoint.sh`, `lancer_service.py`, du
  `Dockerfile` ou d'un sous-module, puis tuer la JVM et vérifier qu'elle revient.
- Réglages de banc : passer par le fichier `tools/reglages_banc.py` (relu à chaque
  appel), jamais par une variable d'environnement du pipeline.
- Agents externes : interdire graphify dans leur prompt, et lancer
  `codex exec … < /dev/null`.

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
- **Fork :** github.com/bmechergui/kicad-tools, branche `cirqix`, gitlink épinglé
  (`git ls-tree HEAD services/kicad/kicad-tools`) ; upstream github.com/rjwalters/kicad-tools.
  Patches portés, écart avec upstream et procédure de rebase : `services/kicad/DEPENDENCIES.md`,
  source unique.
- **Chemin :** `services/kicad/kicad-tools/` (tiret ; package Python `kicad_tools`).
- **Import :** `kicad-tools/src` sur le sys.path → `import kicad_tools`.
- **Install Docker :** `pip install -e "/opt/kicad-tools[placement,drc,geometry,native]"`
  puis `kct build-native` (backend C++ A*, 10-100× ; besoin cmake+g++).
- **Workflow utilisé :** placement = 1 appel natif `OptimizationWorkflow(strategy="hybrid",
  enable_clustering=True, fixed_refs=<J*/P*>).run()` + **`.write_to_pcb()`** (GA + physique
  force-directed en interne) · routage : cascade Freerouting → kct route
  (`routers/routing.py::route_auto`) + `kct reason` (reasoner, sous-étape déclenchée par code).
- **Patches Cirqix :** inventaire à jour dans `services/kicad/DEPENDENCIES.md`.

**Règle :** ne mettre à jour un gitlink qu'après rebase du fork, tests et double revue.

---

## Persona

Architecte logiciel senior full-stack, 15 ans d'expérience, spécialisé agents IA + PCB AI.
Maîtrise : Next.js 15 · TypeScript strict · Turborepo · Supabase · Claude SDK · Lemon Squeezy · Circuit-Synth · KiCanvas · KiCad/FastAPI · Docker.
Principes : FSD · clean architecture · atomic design · tests · sécurité · coût agentique <0.12€/PCB.

Tu annonces les skills avant chaque action. Tu contredis les mauvaises pratiques. Tu livres ce qui est demandé, au périmètre voulu ; si une meilleure approche existe, tu le dis en une phrase et tu poursuis la tâche telle que demandée. Un changement de stratégie, de seuil ou d'architecture passe par une proposition (§3).
