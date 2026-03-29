---
name: layrix-prompt-improver
description: This skill should be used ALWAYS before any task — when the user sends any request, question, or prompt. Invoke to rewrite and improve the prompt with Layrix context (active phase, target file, constraints) and detect the right skill to use next.
version: 0.1.0
---

# Layrix — Prompt Improver

## Quand invoquer ce skill

- **Toujours — avant chaque tâche, quelle que soit la phase**
- Le prompt est court, vague ou mal formulé
- La demande manque de contexte technique
- L'utilisateur écrit en langage informel ou avec des fautes
- La tâche touche plusieurs parties du projet (agents, viewer, DB, UI...)

---

## Phases de développement — contexte par phase

Avant de réécrire le prompt, **identifier la phase active** (lire `PLAN.md` si nécessaire) et enrichir avec le contexte spécifique à cette phase.

### Phase 0 — Setup infra (Semaine 1)
**Focus :** Turborepo, Supabase, Redis, Docker, variables d'environnement
**Fichiers concernés :** `package.json` racine, `turbo.json`, `.env.local`, `services/kicad/Dockerfile`, migrations SQL initiales
**Contraintes à mentionner :**
- Activer extensions Supabase : `pgvector`, `uuid-ossp`
- Docker KiCad headless — tester le build avant tout code
- Variables d'env : `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `REDIS_URL`, `KICAD_SERVICE_URL`, `LEMON_SQUEEZY_API_KEY`
- RLS activée sur toutes les tables dès la création

### Phase 1 — Landing + Waitlist (Semaine 2)
**Focus :** Next.js landing, SEO, formulaire waitlist, design system
**Fichiers concernés :** `apps/landing/app/`, `apps/landing/components/`, `packages/ui/`
**Contraintes à mentionner :**
- Design system `docs/design/design-system.md` — couleurs, typo, composants
- Logo `docs/logo/logo.jpg` — inspiration visuelle
- Lighthouse 100/100 — optimiser images (next/image), fonts (next/font), LCP
- Formulaire waitlist → table Supabase `waitlist` (pas de RLS, insert public)
- Pas de JS inutile — composants Server Components par défaut

### Phase 2 — Dashboard + Auth + Chat Agent MVP (Semaines 3–4)
**Focus :** Supabase Auth, chat agent Claude SDK, streaming SSE, viewer PixiJS, crédits
**Fichiers concernés :** `apps/dashboard/`, `packages/agents/src/orchestrator.ts`, `apps/api/app/api/`
**Contraintes à mentionner :**
- Skill `layrix-pcb-agent` pour la boucle agentique
- Skill `layrix-credits` pour la déduction (vérifier AVANT, déduire APRÈS succès)
- Skill `layrix-viewer` pour PixiJS (couleurs layers, mmToPx)
- Streaming SSE : `Content-Type: text/event-stream`
- Middleware auth Next.js sur toutes les routes `/dashboard/*`
- Zustand pour l'état global du viewer (layers visibles, composant sélectionné)

### Phase 3 — KiCad + Freerouting + Footprints (Semaines 5–7)
**Focus :** Microservice Python pcbnew, Freerouting, cascade footprints, pgvector
**Fichiers concernés :** `services/kicad/`, `packages/agents/src/footprint-agent.ts`, `apps/dashboard/app/dashboard/footprints/`
**Contraintes à mentionner :**
- Skill `layrix-kicad-service` pour FastAPI + pcbnew
- Skill `layrix-footprint` pour la cascade 8 étapes
- Skill `layrix-drc` pour la boucle DRC (max 3 itérations)
- Jobs isolés via BullMQ (`concurrency: 10`)
- pgvector : embeddings 1536 dimensions, index ivfflat, seuil similarité 0.85

### Phase 4 — 3D + JLCPCB + Paiement (Semaines 8–9)
**Focus :** Three.js STEP, ngspice, API JLCPCB, Lemon Squeezy webhooks
**Fichiers concernés :** `packages/ui/src/viewer/PCBViewer3D.tsx`, `apps/api/app/api/webhooks/`, `services/kicad/tools/simulation.py`
**Contraintes à mentionner :**
- Viewer 3D : `occt-import-js` (WebAssembly) pour charger STEP
- JLCPCB : **JAMAIS** de commande automatique — confirmation "OUI JE CONFIRME" obligatoire
- Webhooks Lemon Squeezy : vérifier signature HMAC avant de traiter
- Simulation ngspice : plan Pro uniquement (3 crédits)
- Vue 3D : plan Maker+ uniquement (1 crédit)

### Phase 5 — Polish + Launch (Semaine 10)
**Focus :** Rate limiting, tests E2E, monitoring, SEO final, Product Hunt
**Fichiers concernés :** `apps/api/src/middleware/`, `tests/e2e/`, `apps/landing/`
**Contraintes à mentionner :**
- Rate limiting Upstash : 10 req/min sur `/api/agent/run`
- Playwright E2E : flow complet signup → chat → viewer → export
- Sentry : capturer les erreurs Claude API (429, 529, timeout)
- Posthog : événements `pcb_started`, `pcb_completed`, `credit_depleted`, `upgrade_clicked`
- Audit RLS final : tester isolation user A / user B

## Pipeline d'amélioration

```
prompt brut
    ↓
1. prompt-master (skill global ~/.claude/skills/prompt-master.md)
   → optimise pour Claude Code (agentic tool)
   → applique matrice 9 dimensions + signal words + XML
    ↓
2. layrix-prompt-improver (ce skill)
   → détecte la phase active (0→5)
   → ajoute contexte Layrix (fichier exact, contraintes, crédits, RLS...)
   → détecte le skill à invoquer
    ↓
prompt final prêt à exécuter + skill sélectionné
```

**Ordre d'exécution obligatoire :**
1. Invoquer `prompt-master` → obtenir le prompt optimisé
2. Enrichir avec le contexte Layrix (phase + fichier + contraintes)
3. Ajouter `<constraints>` Layrix-spécifiques au XML
4. Détecter et annoncer le skill à invoquer ensuite

---

## Techniques prompt-master (v1.5.0)

### Matrice 9 dimensions — analyser AVANT de réécrire

Pour chaque prompt reçu, répondre mentalement à ces 9 questions :

| Dimension | Question |
|-----------|----------|
| **Task** | Quelle opération précise ? (pas "fais X" → "crée / modifie / supprime / valide X") |
| **Target tool** | Claude Code sur projet Layrix (agentic tool) |
| **Output format** | Fichier TypeScript ? Python ? SQL ? JSON ? Composant React ? |
| **Constraints** | Quels MUST / MUST NOT respecter ? (RLS, crédits, itérations max, JLCPCB...) |
| **Input** | Quelles données reçoit la fonction / composant ? |
| **Context** | Quelle phase active ? Quel fichier existant modifier ? |
| **Audience** | Code pour prod Layrix (TypeScript strict, Zod, immutable) |
| **Success criteria** | Condition binaire : DRC clean ? Build vert ? Crédits déduits ? |
| **Examples** | Existe-t-il un pattern similaire dans le codebase ? |

### Règles Claude (agentic tools)

- **Format XML** pour structurer le prompt amélioré :
  ```
  <context>phase + fichier + état actuel</context>
  <task>opération précise avec verbe fort</task>
  <constraints>MUST / MUST NOT / NEVER</constraints>
  <output_format>type exact + interface TypeScript</output_format>
  ```
- **Signal words forts** : MUST (pas "should"), NEVER (pas "avoid"), REQUIRED (pas "please")
- **Starting state + target state** : "Le fichier X fait actuellement Y → il doit faire Z"
- **Stop conditions** : toujours mentionner quand s'arrêter (max itérations, confirmation user)
- **Forbidden actions** : préciser ce que Claude NE DOIT PAS faire (pas de commande JLCPCB auto, pas de mutation directe d'état...)
- **Contraindre le sur-engineering** : ajouter "Fais uniquement ce qui est demandé. Aucune feature supplémentaire."
- **Memory block** (si tâche complexe) : rappeler en début de prompt les décisions d'architecture déjà prises

### Token efficiency — checklist avant de livrer le prompt amélioré

- [ ] Verbe vague → remplacé par opération précise (`create`, `update`, `delete`, `validate`)
- [ ] Deux tâches distinctes → séparées en deux prompts séquentiels
- [ ] Critère de succès présent (condition binaire pass/fail)
- [ ] Scope délimité (fichier exact, pas "tout le projet")
- [ ] Longueur output précisée si applicable
- [ ] Rôle expert assigné si tâche complexe
- [ ] Contraintes critiques dans les 30 premiers % du prompt

---

## Processus en 4 étapes

### Étape 1 — Détecter la phase active

Lire `PLAN.md` (section "Phase actuelle" dans `CLAUDE.md`) et identifier :

```
Phase 0 → mots-clés : setup, monorepo, supabase, redis, docker, env, migration initiale
Phase 1 → mots-clés : landing, waitlist, hero, SEO, logo, lighthouse, formulaire
Phase 2 → mots-clés : dashboard, auth, login, chat, agent, streaming, viewer, crédits
Phase 3 → mots-clés : kicad, freerouting, placement, routage, footprint, drc, pgvector
Phase 4 → mots-clés : 3D, step, ngspice, simulation, jlcpcb, commande, paiement, lemon
Phase 5 → mots-clés : rate limit, e2e, playwright, sentry, posthog, product hunt, launch
```

Afficher la phase détectée dans la réponse : `[Phase X détectée]`

### Étape 2 — Analyser le prompt reçu

Identifier :
- L'intention réelle (que veut vraiment l'utilisateur ?)
- Le contexte Layrix concerné (quelle partie du projet ?)
- Ce qui manque (fichier cible ? comportement attendu ? contraintes ?)
- Les ambiguïtés à lever
- Les contraintes spécifiques à la phase active (voir section "Phases" ci-dessus)

### Étape 3 — Réécrire en format XML structuré

Produire une version améliorée avec :
- Format XML Claude : `<context>`, `<task>`, `<constraints>`, `<output_format>`
- Signal words forts : MUST / NEVER / REQUIRED
- Starting state → target state explicites
- Stop conditions et forbidden actions mentionnées
- Fichier exact dans l'arborescence
- Contraintes de la phase active
- Skills Layrix à invoquer ensuite
- "Fais uniquement ce qui est demandé. Aucune feature supplémentaire."

### Étape 4 — Présenter et attendre confirmation

Format de réponse obligatoire :

```
[Phase X — Nom]

📝 Prompt reçu :
[prompt original mot pour mot]

✨ Prompt amélioré :
<context>
[phase active + fichier + état actuel du code]
</context>
<task>
[opération précise avec verbe fort]
</task>
<constraints>
MUST : [contraintes obligatoires]
NEVER : [interdictions absolues]
</constraints>
<output_format>
[type exact + interface TypeScript ou signature Python]
</output_format>

▶️ J'exécute avec ce prompt — confirme ou modifie.
```

Si l'utilisateur confirme → exécuter avec le prompt amélioré.
Si l'utilisateur modifie → reprendre avec la version modifiée, sans redemander.

---

## Exemples de réécriture

### Exemple 1 — Prompt vague sur les agents

**Reçu :**
> "fais le truc pour les agents"

**Amélioré :**
> Implémente la boucle agentique principale dans `packages/agents/src/orchestrator.ts` :
> - Utilise le system prompt de `docs/agentdescription.md §1` (Orchestrateur Sonnet 4.6)
> - Max 15 itérations, états PCB selon la machine d'états de `layrix-pcb-agent`
> - Streaming SSE vers le frontend via `onStream: (chunk: string) => void`
> - Persistance état dans Redis (clé `layrix:project:{id}:state`, TTL 24h)
> - Compression contexte après 10 tours via Haiku
> Respecter le skill `layrix-pcb-agent.md` pour la structure exacte.

---

### Exemple 2 — Prompt UI flou

**Reçu :**
> "fais la page des projets"

**Amélioré :**
> Crée la page `apps/dashboard/app/dashboard/page.tsx` (liste des projets PCB) :
> - Fetch projets depuis Supabase (`select * from projects where user_id = auth.uid()`)
> - Afficher : nom, statut (badge coloré selon machine d'états), date, nb de crédits consommés
> - Design system : `bg-[#111111] border border-[#2E2E2E] rounded-lg hover:border-[#3D3D3D]`
> - Bouton "Nouveau projet" → modal avec champ description → POST `/api/agent/run`
> - État vide : illustration SVG circuit + "Crée ton premier PCB"
> - Skeleton loading pendant le fetch

---

### Exemple 3 — Prompt DB ambigu

**Reçu :**
> "ajoute les credits dans la db"

**Amélioré :**
> Crée la migration Supabase pour le système de crédits :
> - Table `credits` : `user_id` (FK auth.users, unique), `balance` (numeric 10,1), `plan` (enum free/maker/pro/enterprise), `daily_used` (numeric 10,1), `daily_reset_at` (date)
> - Table `credit_transactions` : `user_id`, `project_id` (nullable FK projects), `action` (text), `amount` (numeric négatif=déduction/positif=recharge), `balance_after`, `created_at`
> - RLS activée sur les deux tables (policy : `auth.uid() = user_id`)
> - Fonction RPC atomique `deduct_credits` (voir skill `layrix-credits.md`)
> - Trigger : reset `daily_used` automatiquement si `daily_reset_at` < current_date

---

### Exemple 4 — Prompt viewer incomplet

**Reçu :**
> "montre les erreurs drc dans le viewer"

**Amélioré :**
> Dans `packages/ui/src/viewer/renderer.ts`, ajoute le rendu des violations DRC :
> - Fonction `renderDRCMarker(violation: DRCViolation): PIXI.Graphics`
> - Cercle rouge `0xEF4444` (erreur, alpha 0.8, clignote via `PIXI.Ticker`) à la position `mmToPx(v.x_mm), mmToPx(v.y_mm)`, rayon 8px
> - Cercle amber `0xF59E0B` (warning, sans clignotement)
> - Tooltip au hover : affiche `v.description`
> - Cliquable : sélectionne le composant `v.ref1` dans la sidebar
> - Exporter `drcToViewerMarkers(violations: DRCViolation[]): ViewerMarker[]` depuis `layers.ts`

---

## Règles de réécriture

| Prompt reçu contient | Ajouter dans le prompt amélioré |
|---------------------|--------------------------------|
| "fais X" sans fichier | Spécifier le fichier exact dans l'arborescence |
| "agent" sans précision | Quel agent ? Orchestrateur / Schéma / DRC / Footprint ? |
| "base de données" | Table Supabase + RLS + migration + fonction RPC si besoin |
| "affiche X" | Composant React exact + classes design system + états loading/empty/error |
| "ajoute X" | Où ? Dans quel fichier ? Quelle interface TypeScript ? |
| "corrige X" | Quel comportement attendu vs actuel ? |
| Touche aux crédits | Mentionner : vérifier solde AVANT, déduire APRÈS succès |
| Touche aux agents | Mentionner : model (Sonnet ou Haiku), max itérations, streaming |
| Touche à la DB | Mentionner : RLS, uuid-ossp, pgvector si embeddings |
| Touche au viewer | Mentionner : couleurs LAYER_COLORS, mmToPx, design system |

## Correction linguistique

En plus de l'amélioration technique, corriger :
- Fautes d'orthographe et de grammaire
- Formulation ambiguë → formulation directe
- Vocabulaire vague ("truc", "chose", "machin") → terme technique précis
- Langue mixte (français/anglais) → harmoniser en français technique

## Exemples par phase

### Phase 0 — Prompt vague setup
**Reçu :** "configure supabase"
**Amélioré :**
```xml
<context>
Phase 0 — Setup infra. Supabase n'est pas encore configuré.
Fichiers cibles : apps/api/.env.local, apps/dashboard/.env.local, supabase/migrations/001_init.sql
</context>
<task>
Créer la configuration Supabase initiale complète pour Layrix.
</task>
<constraints>
MUST : activer extensions pgvector et uuid-ossp avant toute migration
MUST : RLS activée sur chaque table dès la création (pas en post)
MUST : ajouter les variables dans les deux .env.local
NEVER : exposer SUPABASE_SERVICE_KEY côté client
</constraints>
<output_format>
1. Commandes SQL extensions (pgvector, uuid-ossp)
2. Migration SQL : tables projects, credits, credit_transactions, waitlist + RLS + policies
3. Contenu .env.local (apps/api et apps/dashboard)
Fais uniquement ce qui est demandé. Aucune feature supplémentaire.
</output_format>
```

### Phase 1 — Prompt landing flou
**Reçu :** "fais la hero section"
**Amélioré :**
> [Phase 1 — Landing]
> Crée le composant `apps/landing/components/Hero.tsx` (Server Component) :
> - Eyebrow : `text-[#00C2FF] text-sm uppercase tracking-widest` → "AI PCB Design Agent"
> - H1 : `text-7xl font-extrabold tracking-tighter` avec gradient-text cyan→copper sur "perfectly designed"
> - Sous-titre : `text-[#A1A1AA] text-xl` → "Décris ton circuit. L'IA conçoit le PCB."
> - CTA primaire : `bg-[#00C2FF] text-black font-semibold rounded px-6 py-3` → "Rejoindre la waitlist"
> - CTA secondaire : ghost → "Voir la démo"
> - Fond : `bg-[#080808]` + PCB grid overlay (voir `docs/design/design-system.md` §6)
> - Utiliser `next/image` pour le logo `docs/logo/logo.jpg`
> - Server Component — zéro JS client

### Phase 2 — Prompt agent ambigu
**Reçu :** "fais le streaming du chat"
**Amélioré :**
```xml
<context>
Phase 2 — Dashboard + Agent MVP.
État actuel : endpoint /api/agent/run existe mais retourne JSON non-streamé.
Fichiers : apps/api/app/api/agent/run/route.ts, apps/dashboard/app/dashboard/projects/[id]/page.tsx
</context>
<task>
Convertir l'endpoint /api/agent/run en streaming SSE et connecter le frontend.
</task>
<constraints>
MUST : vérifier crédits AVANT d'appeler runPCBAgent() (skill layrix-credits)
MUST : déduire crédits APRÈS succès seulement
MUST : Content-Type text/event-stream avec Cache-Control no-cache
MUST : event [DONE] pour signaler la fin du stream
NEVER : bloquer le thread — utiliser ReadableStream async
NEVER : exposer ANTHROPIC_API_KEY côté client
Stop condition : fermer le stream après [DONE] ou après erreur
</constraints>
<output_format>
1. apps/api/app/api/agent/run/route.ts → ReadableStream SSE
   Format chunk : data: {"text": "...", "state": "SCHEMA_READY"}\n\n
2. apps/dashboard/...projects/[id]/page.tsx → fetch + ReadableStream reader
   Zustand store : streamBuffer string, pcbState PCBStatus
Fais uniquement ce qui est demandé. Aucune feature supplémentaire.
</output_format>
```

### Phase 3 — Prompt footprint incomplet
**Reçu :** "cherche le footprint pour le composant"
**Amélioré :**
> [Phase 3 — Footprints]
> Dans `packages/agents/src/footprint-agent.ts`, lance la cascade 8 étapes (skill `layrix-footprint`) pour le composant `{part_number}` :
> 1. D'abord chercher dans `footprints` Supabase via pgvector (seuil 0.85)
> 2. Cascade : KiCad officiel → SnapMagic → Octopart → Datasheet PDF → Claude Vision
> 3. Si génération IA : vérifier crédits (3 crédits, plan Maker+)
> 4. Sauvegarder dans `footprints` avec `source`, `embedding` (1536 dims), `validated: false`
> 5. Retourner le `.kicad_mod` + badge source au frontend

### Phase 4 — Prompt JLCPCB vague
**Reçu :** "envoie la commande jlcpcb"
**Amélioré :**
```xml
<context>
Phase 4 — Export + JLCPCB.
État actuel : gerbers.zip généré dans Supabase Storage /gerbers/{userId}/{projectId}/gerbers.zip
Fichier cible : apps/api/app/api/jlcpcb/route.ts (à créer)
</context>
<task>
Implémenter le flow complet commande JLCPCB en 3 endpoints séquentiels.
</task>
<constraints>
NEVER : passer une commande sans "OUI JE CONFIRME" explicite de l'utilisateur
NEVER : exposer les données de carte bancaire à l'agent (paiement via Stripe uniquement)
MUST : afficher le devis (prix + délai) AVANT tout bouton de commande
MUST : sauvegarder order_id dans la table projects après commande
MUST : 1 crédit export déjà déduit avant d'appeler ce flow
Stop condition : si l'utilisateur dit autre chose que "OUI JE CONFIRME" → annuler
</constraints>
<output_format>
3 endpoints dans apps/api/app/api/jlcpcb/ :
- upload/route.ts → POST, upload gerbers.zip vers API JLCPCB
- quote/route.ts  → GET, retourne { price_usd: number, days: number }
- order/route.ts  → POST, requiert { confirmed: true } dans le body
Types : JLCPCBQuote, JLCPCBOrder dans packages/db/src/types.ts
Fais uniquement ce qui est demandé. Aucune feature supplémentaire.
</output_format>
```

### Phase 5 — Prompt tests flou
**Reçu :** "fais les tests e2e"
**Amélioré :**
> [Phase 5 — Launch]
> Crée les tests E2E Playwright dans `tests/e2e/` pour le flow critique :
> - `tests/e2e/pcb-flow.spec.ts` : signup → login → créer projet → chat "Arduino nano 3.3V" → attendre SCHEMA_READY → vérifier viewer affiche composants → cliquer Export → vérifier gerbers.zip généré
> - `tests/e2e/credits.spec.ts` : vérifier déduction crédits après chaque action, blocage quand solde = 0
> - `tests/e2e/auth.spec.ts` : isolation RLS — user A ne voit pas les projets de user B
> - Config : `playwright.config.ts` baseURL = `http://localhost:3000`, retries = 2, workers = 1 (séquentiel pour Supabase)

---

## Règles de réécriture

| Prompt reçu contient | Ajouter dans le prompt amélioré |
|---------------------|--------------------------------|
| "fais X" sans fichier | Fichier exact dans l'arborescence + composant/fonction à créer |
| "agent" sans précision | Quel agent ? Orchestrateur / Schéma / DRC / Footprint / Routage ? |
| "base de données" | Table + colonnes + types + RLS + migration Supabase |
| "affiche X" | Composant React + classes design system + états loading/empty/error |
| "ajoute X" | Fichier exact + interface TypeScript + où l'importer |
| "corrige X" | Comportement attendu vs actuel + fichier concerné |
| Touche aux crédits | Vérifier AVANT, déduire APRÈS succès (skill `layrix-credits`) |
| Touche aux agents | Modèle (Sonnet ou Haiku), max itérations, streaming SSE |
| Touche à la DB | RLS + uuid-ossp + pgvector si embeddings |
| Touche au viewer | Couleurs `LAYER_COLORS`, `mmToPx`, design system |
| Touche à KiCad | Docker headless, BullMQ isolation, endpoints FastAPI |
| Touche à JLCPCB | Confirmation obligatoire, jamais automatique |

## Correction linguistique

- Fautes d'orthographe et grammaire → corriger silencieusement
- Langage vague ("truc", "chose", "machin") → terme technique précis
- Langue mixte → harmoniser en français technique
- Phrase incomplète → reformuler complètement

## Détection automatique du skill à invoquer

Après amélioration du prompt, **détecter et invoquer automatiquement** le skill approprié sans attendre que l'utilisateur le précise.

### Arbre de décision

```
Le prompt parle de...

├── agent / orchestrateur / boucle / streaming / SSE / itération / tour
│   → skill : layrix-pcb-agent
│
├── footprint / kicad_mod / datasheet / snapmagic / octopart / package / pad
│   → skill : layrix-footprint
│
├── placement / routage / freerouting / pcbnew / gerber / drill / export PCB / dsn / ses
│   → skill : layrix-kicad-service
│
├── viewer / pixijs / pixi / layer / rendu / F.Cu / B.Cu / 3D / step / three.js / zoom / pan
│   → skill : layrix-viewer
│
├── crédit / balance / déduction / plan / lemon squeezy / webhook / top-up / solde
│   → skill : layrix-credits
│
├── DRC / violation / erreur PCB / correction / règle / clearance / track width
│   → skill : layrix-drc
│
├── landing / hero / waitlist / SEO / lighthouse / page marketing
│   → skill : /everything-claude-code:frontend-patterns
│
├── dashboard / composant React / page / modal / sidebar / UI / tailwind / shadcn
│   → skill : /everything-claude-code:frontend-patterns
│   + design system : docs/design/design-system.md
│
├── supabase / migration / table / RLS / policy / pgvector / embedding / SQL
│   → skill : /everything-claude-code:postgres-patterns
│
├── FastAPI / Python / microservice / docker / pcbnew / ngspice / simulation
│   → skill : layrix-kicad-service
│   + skill : /everything-claude-code:python-patterns
│
├── test / playwright / e2e / coverage / jest / vitest
│   → skill : /everything-claude-code:e2e
│
├── JLCPCB / commande / fabrication / devis / order
│   → skill : layrix-pcb-agent  (flow export + confirmation)
│
├── Claude API / Anthropic / SDK / tool_use / tool calling
│   → skill : /everything-claude-code:claude-api
│
├── architecture / plan / refactoring / design / structure
│   → skill : /everything-claude-code:plan
│
└── autre → exécuter directement avec le prompt amélioré
```

### Format de réponse avec skill détecté

```
[Phase X — Nom]
[Skill détecté : layrix-xxx ou /skill-name]

📝 Prompt reçu :
[original]

✨ Prompt amélioré :
<context>...</context>
<task>...</task>
<constraints>...</constraints>
<output_format>...</output_format>

▶️ J'invoque [skill détecté] avec ce prompt — confirme ou modifie.
```

### Règles de détection

- Si **plusieurs skills** correspondent → invoquer dans l'ordre : skill Layrix d'abord, skill global ensuite
- Si **aucun skill** ne correspond → exécuter directement sans skill
- Si le prompt contient des mots-clés de **2 domaines différents** (ex: viewer + crédits) → mentionner les deux skills, invoquer le plus central à la tâche
- **Ne jamais demander** quel skill utiliser — décider automatiquement et expliquer le choix en une ligne
