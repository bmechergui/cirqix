# Plan d'Implémentation Complet — Cirqix.ai

## Vision

SaaS 100% cloud de conception PCB par langage naturel. Agent IA autonome → PCB DRC-clean → Gerbers → commande JLCPCB.
Tagline : *"Every layer, perfectly designed by AI"*

---

## Architecture globale (Turborepo monorepo)

```
cirqix/
├── apps/
│   └── web/            → Next.js 15 (marketing + auth + dashboard + API Routes, port 3333)
├── packages/
│   ├── agents/         → Boucle agentique Claude SDK (Orchestrateur + agents)
│   ├── types/          → Source de vérité TypeScript (@cirqix/types)
│   ├── db/             → Supabase client + migrations
│   ├── logger/         → Pino logger
│   ├── utils/          → cn() helpers
│   ├── ui/             → shadcn/ui + design system partagé
│   └── config-typescript/ → tsconfig partagé (strict)
└── services/
    └── kicad/          → Python FastAPI + Circuit-Synth (Docker headless)
```

---

## Stack technique

| Couche | Technologie |
|--------|-------------|
| Monorepo | Turborepo + pnpm |
| Frontend | Next.js 15 App Router + Tailwind + shadcn/ui + Zustand |
| Backend MVP | Next.js API Routes (apps/api) |
| Microservice KiCad | Python FastAPI + pcbnew — Docker headless (DigitalOcean) |
| Agents | Claude SDK — Orchestrateur Sonnet 4.6 + 8 agents Haiku 4.5 |
| DB | PostgreSQL + Supabase + pgvector (uuid-ossp, pgvector) |
| Queue | Redis + BullMQ (10 PCBs simultanés) |
| Stockage | Supabase Storage (`/storage/{userId}/{projectId}/`) |
| Auth | Supabase Auth (email + Google OAuth) |
| Paiement | Lemon Squeezy (MVP) → Stripe (V2) |
| Viewer Schéma | KiCanvas (rendu natif .kicad_sch en browser) |
| Viewer PCB 2D | KiCanvas (rendu natif .kicad_pcb) |
| Viewer 3D | Three.js + STEP via occt-import-js (plan Pro+) |
| Deploy | Vercel (landing+dashboard), Railway (api), DigitalOcean (kicad) |

---

## Agents IA

- **Orchestrateur** : Claude Sonnet 4.6 — 15 itérations max, SSE streaming, compression contexte après 10 tours
- **8 sous-agents** Haiku 4.5 : Schéma, ERC, Footprint, Layout KiCad, Placement, Routage, DRC, Export
- Coût cible : ~0.12€ par PCB complet

---

## Stratégie moteur PCB

Pipeline 8 agents (ordre strict) :
① `call_agent_schema` → Ingénieur Schéma — génère `.kicad_sch` + `unresolved_footprints`
   Path A : Haiku → Python circuit_synth → Docker /schematic/execute → .kicad_sch
   Path B : Haiku → JSON → POST /schematic/generate :
     ① circuit_synth pip · ② kicad-tools Schematic · ③ TypeScript S-expr inline
② `call_agent_erc` → Ingénieur ERC — valide connexions électriques, auto-fix
   ① kicad-tools Schematic.validate() — pur Python · ② kicad-cli sch erc · ③ TS fallback
③ `call_agent_footprint` → Ingénieur Composants — 1 appel par ref dans `unresolved_footprints`
④ `call_agent_gen_pcb` → Ingénieur Layout — génère `.kicad_pcb`
   Netlist 3 niveaux : ① kicad-tools Python pur · ② kicad-cli · ③ .kicad_net injecté
   PCB 3 niveaux : ① kicad-tools PCBFromSchematic · ② pcbnew direct · ③ TypeScript S-expr
⑤ `call_agent_placement` → Ingénieur Placement  [OFFICIEL kicad-tools]
   Le PCB arrive déjà placé (call_agent_gen_pcb ne déplace plus à -1000).
   `PlacementOptimizer.from_pcb(pcb, fixed_refs=<J*/P*>, enable_clustering=True)`
   + run() + snap_rotations_to_90() + write_to_pcb() — clustering regroupe les grappes
   (caps/quartz près du MCU). Filet : place_unplaced si footprints hors-carte.
⑥ `call_agent_routing` → Ingénieur Routage  [OFFICIEL kicad-tools]
   ① kct route --strategy negotiated --auto-layers --auto-fix --seed (zones power + signaux)
   ② Freerouting REST API / subprocess (fallback historique, port 37864)
   → renvoie routed_percent réel (plus de hardcode 100)
⑥b Reasoner IA  [SOUS-ÉTAPE DÉTERMINISTE — déclenchée par orchestrator.ts, PAS par Sonnet]
   Trigger : SI routed_percent < 100 → l'orchestrateur lance call_agent_reason (shouldRescueRouting).
   Retiré de ACTIVE_PCB_TOOLS (Sonnet ne le voit plus → zéro double-appel). Résultat fusionné
   dans le tool_result routage (mergeRescueIntoRouting — ne peut qu'améliorer, jamais régresser).
   ① PCBReasoningAgent + Claude Haiku (si ANTHROPIC_API_KEY) — boucle get_prompt→Claude→execute
   ② sinon kct reason --auto-route (heuristique sans LLM)
   → reasoning_steps → event SSE `reasoning` → ChatRail affiche les actions IA temps-réel
   Fix 34be8ae : _refresh_agent resync l'état · Trigger déterministe : commit 13b919c (TDD)
⑦ `call_agent_drc` → Ingénieur Qualité
   ① kicad-tools 27 règles JLCPCB · ② kicad-cli auto-fix max 3× · ③ skipped
⑧ `call_agent_export` → Ingénieur Fabrication
   ① kicad-tools --mfr jlcpcb (GTL/GBL/BOM LCSC/CPL) · ② kicad-cli standard · ③ BOM CSV

- **Circuit-Synth** (Python pip) → génère `.kicad_sch` ; `.kicad_pcb` généré séparément par `call_agent_gen_pcb`
- Fallback TypeScript : `schematic-engine.ts` si Docker absent
- Viewer : **KiCanvas** charge les fichiers natifs depuis Supabase Storage

---

## Système de crédits

| Action | Coût |
|--------|------|
| Chat | 0.5 |
| Schéma | 2 |
| Placement | 2 |
| Routage | 3 |
| DRC | 1 |
| Export Gerbers | 1 |
| Footprint IA | 3 |
| Vue 3D | 1 |
| Simulation | 3 |

| Plan       | Prix       | Crédits  | Couches max |
|------------|------------|----------|-------------|
| Free       | 0€         | 5/jour   | 2           |
| Pro        | 25€/mois   | 100      | 4           |
| Pro Max    | 50€/mois   | 300      | 8           |
| Enterprise | Sur devis  | Illimité | Illimité    |

---

## Phase 0 — Setup Infrastructure (Semaine 1)

### Étape 0.1 — Initialisation Turborepo

**Fichiers :**
- `package.json` (root), `turbo.json`, `pnpm-workspace.yaml`, `.gitignore`, `.npmrc`

**Actions :**
1. `pnpm create turbo@latest` ou setup manuel
2. `pnpm-workspace.yaml` : workspaces `apps/*`, `packages/*`, `services/*`
3. `turbo.json` : pipelines `build`, `dev`, `lint`, `test`, `type-check`
4. `.gitignore` : node_modules, .env*, .next, dist, .turbo

**Skill :** `turborepo` | **Risque :** Faible

---

### Étape 0.2 — Shared Configs TypeScript/ESLint/Prettier

**Fichiers :**
- `packages/config-typescript/tsconfig.base.json`
- `packages/config-typescript/tsconfig.nextjs.json`
- `packages/config-eslint/index.js`
- `.prettierrc`

**Actions :**
1. `tsconfig.base.json` : strict, noUncheckedIndexedAccess, exactOptionalPropertyTypes
2. ESLint partagé : eslint-config-next + typescript-eslint
3. Prettier : singleQuote, trailingComma all, printWidth 100

**Risque :** Faible

---

### Étape 0.3 — Création des workspaces

**Fichiers :** `apps/landing/`, `apps/dashboard/`, `apps/api/`, `packages/ui/`, `packages/db/`, `packages/agents/`, `services/kicad/`

**Actions :**
1. `apps/landing/` : `npx create-next-app@latest` (App Router, Tailwind, TypeScript strict)
2. `apps/dashboard/` : même config
3. `apps/api/` : Next.js API Routes uniquement (pas de pages publiques)
4. `packages/ui/` : shadcn/ui partagé
5. `packages/db/` : types Supabase générés + client
6. `packages/agents/` : SDK Claude + orchestrateur
7. `services/kicad/` : `requirements.txt`, `Dockerfile`, `main.py` (squelette)

**Risque :** Moyen — s'assurer que les références inter-packages fonctionnent

---

### Étape 0.4 — Design System Tailwind

**Fichiers :**
- `packages/ui/tailwind.config.ts`
- `packages/ui/src/globals.css`
- `packages/ui/src/lib/utils.ts` (cn helper)

**Actions :**
1. Tokens depuis `docs/design/design-system.md`
2. Couleurs : bg-base (#080808), cyan-400 (#00C2FF), copper-400 (#D4820A)
3. Typographie : Geist Sans + Geist Mono (next/font/local)
4. `npx shadcn@latest init` dans `packages/ui`
5. Composants base : Button, Input, Card, Badge, Dialog, Sheet, Tooltip

**Skill :** `/everything-claude-code:frontend-patterns` | **Risque :** Faible

---

### Étape 0.5 — Setup Supabase + Schéma DB

**Fichiers :**
- `packages/db/supabase/migrations/001_initial.sql`
- `packages/db/src/client.ts`
- `packages/db/src/types.ts` (généré)

**Migration SQL :**
```sql
-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Projets PCB
CREATE TABLE projects (
  id          uuid DEFAULT uuid_generate_v4() PRIMARY KEY,
  user_id     uuid REFERENCES auth.users NOT NULL,
  name        text NOT NULL,
  description text,
  status      text DEFAULT 'INITIAL',
  pcb_state   jsonb,
  iteration_count int DEFAULT 0,
  created_at  timestamptz DEFAULT now(),
  updated_at  timestamptz DEFAULT now()
);

-- Crédits
CREATE TABLE credits (
  id         uuid DEFAULT uuid_generate_v4() PRIMARY KEY,
  user_id    uuid REFERENCES auth.users UNIQUE NOT NULL,
  balance    numeric DEFAULT 5,
  plan       text DEFAULT 'free',
  updated_at timestamptz DEFAULT now()
);

-- Transactions crédits
CREATE TABLE credit_transactions (
  id         uuid DEFAULT uuid_generate_v4() PRIMARY KEY,
  user_id    uuid REFERENCES auth.users NOT NULL,
  project_id uuid REFERENCES projects,
  action     text NOT NULL,
  amount     numeric NOT NULL,
  created_at timestamptz DEFAULT now()
);

-- Footprints
CREATE TABLE footprints (
  id           uuid DEFAULT uuid_generate_v4() PRIMARY KEY,
  user_id      uuid REFERENCES auth.users,
  is_community boolean DEFAULT false,
  name         text NOT NULL,
  part_number  text,
  source       text,
  kicad_mod    text,
  embedding    vector(1536),
  validated    boolean DEFAULT false,
  created_at   timestamptz DEFAULT now()
);

-- Waitlist
CREATE TABLE waitlist (
  id         uuid DEFAULT uuid_generate_v4() PRIMARY KEY,
  email      text UNIQUE NOT NULL,
  created_at timestamptz DEFAULT now()
);

-- RLS
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE credits ENABLE ROW LEVEL SECURITY;
ALTER TABLE credit_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE footprints ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users see own projects" ON projects FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "users see own credits" ON credits FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "users see own transactions" ON credit_transactions FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "users see own footprints" ON footprints FOR ALL USING (auth.uid() = user_id OR is_community = true);

-- Trigger init crédits à la création d'un user
CREATE OR REPLACE FUNCTION init_user_credits()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO credits (user_id) VALUES (NEW.id);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION init_user_credits();
```

**Skill :** `nextjs-supabase-auth`, `/everything-claude-code:postgres-patterns` | **Risque :** Moyen

---

### Étape 0.6 — Setup Redis

**Actions :**
1. Instance Redis : Upstash (serverless, compatible Vercel) ou Railway
2. `REDIS_URL` dans `.env.local`
3. Module connexion : `packages/agents/src/redis.ts`

**Risque :** Faible

---

### Étape 0.7 — Variables d'environnement

**Fichiers :** `.env.example`, `.env.local` dans chaque app

```bash
# .env.example
ANTHROPIC_API_KEY=
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_KEY=
REDIS_URL=
LEMON_SQUEEZY_API_KEY=
KICAD_SERVICE_URL=
RESEND_API_KEY=
SNAPMAGIC_API_KEY=
```

**Risque :** Faible

---

### Étape 0.8 — 🔴 Docker KiCad Headless (CRITIQUE)

**Fichiers :**
- `services/kicad/Dockerfile`
- `services/kicad/docker-compose.yml`
- `services/kicad/requirements.txt`
- `services/kicad/main.py`

```dockerfile
FROM kicad/kicad:8.0-ubuntu

RUN apt-get update && apt-get install -y \
    python3-pip openjdk-17-jre curl && \
    pip3 install fastapi uvicorn pydantic

COPY . /app
WORKDIR /app

ADD https://github.com/freerouting/freerouting/releases/latest/download/freerouting.jar \
    /opt/freerouting/freerouting.jar

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Validation :** `docker build -t cirqix-kicad . && docker run -p 8000:8000 cirqix-kicad`
→ `curl http://localhost:8000/health` doit retourner `{"status":"ok"}`

**Skill :** `cirqix-kicad-service`, `/everything-claude-code:docker-patterns`
**Risque :** 🔴 CRITIQUE — si `import pcbnew` échoue, tout le pipeline Phase 3 est bloqué

> **Point de go/no-go** : valider cette étape AVANT tout le reste. Fallback : TSCircuit uniquement pour MVP.

---

### Étape 0.9 — GitHub + CI

**Actions :**
1. `git init` + premier commit + repo GitHub privé
2. `.github/workflows/ci.yml` : jobs lint + type-check + test + build
3. Protection branche `main` : require PR + CI vert

**Risque :** Faible

---

### Étape 0.10 — Deploy initial

**Actions :**
1. Vercel : `apps/landing` → `cirqix.ai`
2. Vercel : `apps/dashboard` → `app.cirqix.ai`
3. Railway : `apps/api` → `api.cirqix.ai`
4. DigitalOcean : Droplet pour service KiCad Docker (Phase 3)

**Risque :** Moyen

---

## Phase 1 — Landing + Waitlist (Semaine 2)

### Étape 1.1 — Layout + Navigation

**Fichiers :**
- `apps/landing/app/layout.tsx`
- `apps/landing/components/Navbar.tsx`
- `apps/landing/components/Footer.tsx`

**Actions :** Fond #080808, Geist, Navbar (logo + CTA "Join Waitlist" cyan glow), Footer

---

### Étape 1.2 — Hero Section

**Fichiers :** `apps/landing/components/Hero.tsx`

**Actions :**
1. Eyebrow : "AI PCB Design Agent" (text-cyan-400, uppercase)
2. H1 : "Every layer, perfectly designed by AI" (gradient cyan→copper)
3. 2 CTA : "Join Waitlist" (btn-primary glow) + "Watch Demo" (btn-ghost)
4. Fond : grille PCB CSS (40px, lignes cyan 4% opacité)
5. Animation circuit trace SVG (stroke-dasharray)

---

### Étape 1.3 — Sections marketing

**Fichiers :** `Features.tsx`, `HowItWorks.tsx`, `Pricing.tsx`, `Comparison.tsx`

**Actions :**
1. **Features** : 6 cards (Agent autonome, Viewer 2D/3D, Footprint auto, JLCPCB, SPICE, Credits)
2. **How It Works** : 3 étapes reliées par circuit trace SVG animé
3. **Pricing** : 4 tiers — card active = border-cyan-400
4. **Comparatif** : Cirqix vs Flux vs Quilter vs DeepPCB vs KiCad MCP

---

### Étape 1.4 — Formulaire Waitlist + API

**Fichiers :**
- `apps/landing/components/WaitlistForm.tsx`
- `apps/api/app/api/waitlist/route.ts`

**Actions :**
1. Validation Zod (email valide)
2. Insert Supabase table `waitlist`
3. Email confirmation via Resend
4. Rate limiting Upstash (anti-spam)

---

### Étape 1.5 — SEO + Performance

**Actions :**
1. metadata Next.js (title, OG, Twitter cards)
2. `sitemap.ts` + `robots.ts`
3. `next/image` WebP + lazy loading
4. Cible : Lighthouse 100/100

---

## Phase 2 — Dashboard + Auth + Agent MVP (Semaines 3-4)

> **État actuel :** ✅ Pipeline schéma + viewer KiCanvas opérationnel.
> Placement / Routage / DRC réels sont en **Phase 3** (pcbnew + Freerouting).
>
> ### Pipeline Phase 2 — validé
> ```
> User → Sonnet 4.6 (orchestrateur)
>            ↓ call_agent_schema
>        Haiku 4.5 → JSON schema (composants + nets + connections + pin names)
>            ↓ validateAndCorrectSchema()   ← vérifie symbols .kicad_sym (KICAD_SERVICE_URL)
>        FastAPI POST /circuit-synth/validate-symbols  → corrections auto
>            ↓ _safe_symbol() (2ème filet dans /generate)
>        circuit_synth Python → .kicad_sch + .kicad_pcb natifs
>            ↓
>        Upload Supabase Storage (bucket kicad-files, RLS {userId}/{projectId}/)
>            ↓ signed URL 1h → pcb_state.kicad_sch_url / kicad_pcb_url
>        KiCanvas viewer — auto-switch tab Schematic / Routing à l'arrivée SSE
> ```
>
> ### Stubs Phase 2 (comportement temporaire — réel en Phase 3)
> | Tool | Comportement Phase 2 | Réel Phase 3 |
> |------|---------------------|--------------|
> | `call_agent_placement` | Grille géométrique TS | pcbnew SetPosition() |
> | `call_agent_routing` | MST TypeScript | Freerouting Java via pcbnew |
> | `call_agent_drc` | Règles simples TS | pcbnew DRC natif |
> | `call_agent_export` | Quote fictif + BOM JSON | Gerbers + BOM LCSC réels |
> | `call_agent_footprint` | Stub (fake data) | Cascade 8 étapes Phase 3 |

---

### Étape 2.1 — Auth Supabase ✅

**Fichiers :**
- `apps/dashboard/app/login/page.tsx`
- `apps/dashboard/app/signup/page.tsx`
- `apps/dashboard/middleware.ts`
- `packages/db/src/auth.ts`

**Actions :**
1. Supabase Auth UI (email + Google OAuth)
2. Middleware Next.js : redirect `/login` si non authentifié
3. Trigger DB : créer `credits` (balance=5, plan='free') à la création user

**Skill :** `nextjs-supabase-auth` | **Risque :** Moyen

---

### Étape 2.2 — Layout Dashboard ✅

**Fichiers :**
- `apps/dashboard/app/layout.tsx`
- `apps/dashboard/components/Sidebar.tsx`
- `apps/dashboard/components/Header.tsx`
- `apps/dashboard/components/CreditsBadge.tsx`

**Actions :**
1. Sidebar 240px fixe + contenu fluid
2. Nav items : Projets, Footprints, Settings
3. Compteur crédits + barre progression + bouton "Upgrade"
4. Nav item actif : `border-l-2 border-cyan-400 bg-bg-2`

---

### Étape 2.3 — Page Projets ✅

**Fichiers :**
- `apps/dashboard/app/dashboard/page.tsx`
- `apps/dashboard/components/ProjectCard.tsx`
- `apps/api/app/api/projects/route.ts`

**Actions :**
1. `GET /api/projects` (RLS Supabase)
2. `POST /api/projects` (name, description)
3. Grille ProjectCards + dialog création
4. Zustand store projets

---

### Étape 2.4 — Page Projet : Chat + Viewer ✅

**Fichiers :**
- `apps/dashboard/app/dashboard/projects/[id]/page.tsx`
- `apps/dashboard/components/ChatPanel.tsx`
- `apps/dashboard/components/AgentProgressBar.tsx`
- `apps/dashboard/components/ViewerPanel.tsx`

**Actions :**
1. Split layout : Chat 40% / Viewer 60% (resizable)
2. Chat : historique + input + cursor clignotant pendant streaming
3. AgentProgressBar : SCHEMA → PLACEMENT → ROUTING → DRC → EXPORT (segments cyan animés)

---

### Étape 2.5 — Orchestrateur Claude SDK ✅

**Fichiers :**
- `packages/agents/src/orchestrator.ts`
- `packages/agents/src/agents/schema-agent.ts`
- `packages/agents/src/tools/index.ts`
- `packages/agents/src/types.ts`
- `packages/agents/src/prompts/` (depuis `docs/agentdescription.md`)

**Actions :**
1. Types : `PCBState`, `AgentMessage`, `ToolCall`, `ToolResult`
2. Orchestrateur : boucle `iteration < 15`, model `claude-sonnet-4-6`, streaming SSE
3. Gestion `stop_reason === "tool_use"` → exécuter tool → réinjecter
4. Agent Schéma : **Haiku 4.5** → JSON schema → `validateAndCorrectSchema()` → Circuit-Synth
5. Tools : `call_agent_schema`, `call_agent_placement`, `call_agent_routing`, `call_agent_drc`, `call_agent_export`, `call_agent_footprint`, `ask_user`
6. Compression contexte après 10 tours (Haiku résume)

**Moteur schéma — dual-mode :**
- Haiku génère JSON `{ components, nets, connections }` avec pin names KiCad (`"IN"`, `"GND"`, `"TR"`)
- `validateAndCorrectSchema()` → POST `/circuit-synth/validate-symbols` → corrections auto
- **Docker actif** → `circuit-synth` officiel GitHub v0.12.1 (`kicad-sch-api`) → `.kicad_sch` + `.kicad_pcb` réels
- **Docker absent** → `schematic_gen.py` fallback custom Cirqix → `.kicad_sch` S-expression basique
- Upload Supabase Storage → `pcb_state.kicad_sch_url` + `kicad_pcb_url` → SSE → KiCanvas

> `circuit-synth` officiel : `pip install git+https://github.com/circuit-synth/circuit-synth.git`
> Sans `[fast_generation]` → zéro google-adk. Core deps : kicad-sch-api, numpy, PySpice.

**Skill :** `/everything-claude-code:claude-api`, `cirqix-pcb-agent` | **Risque :** 🔴 ÉLEVÉ

---

### Étape 2.6 — API Agent + SSE Streaming ✅

**Fichiers :**
- `apps/api/app/api/agent/run/route.ts`
- `apps/api/app/api/agent/stream/[projectId]/route.ts`

**Actions :**
1. `POST /api/agent/run` : vérifie auth + crédits → lance BullMQ job → retourne jobId
2. `GET /api/agent/stream/[projectId]` : SSE via Redis pubsub (text chunks, state changes, errors)
3. Persistance Redis : état PCB + historique (TTL 24h)

**Skill :** `bullmq-specialist` | **Risque :** Élevé

---

### Étape 2.7 — Viewer KiCanvas ✅

**Fichiers :**
- `apps/web/src/widgets/viewer/ui/KiCanvasViewer.tsx`
- `apps/web/src/widgets/viewer/ui/ViewerPanel.tsx`

**Actions :**
1. Ajouter `@kicanvas/kicanvas` (web component)
2. Wrapper React `<KiCanvasViewer>` — charge `.kicad_sch` depuis Supabase Storage (signed URL)
3. Onglet **Schematic** → `<kicanvas-schematic src={kicadSchUrl} />`
4. Onglet **Routing** → `<kicanvas-board src={kicadPcbUrl} />`
5. Chargement conditionnel : skeleton si fichier pas encore généré

**Skill :** `cirqix-viewer` | **Risque :** Moyen

---

### Étape 2.8 — Système de Crédits ✅

**Fichiers :**
- `packages/db/supabase/migrations/002_credit_functions.sql`
- `packages/db/src/credits.ts`
- `apps/api/app/api/credits/route.ts`

**Actions :**
1. RPC Supabase `deduct_credits(user_id, amount, action, project_id)` : atomique, vérifie solde ≥ amount
2. `checkCredits(userId, action)` + `deductCredits(userId, action, projectId)`
3. Middleware agent : vérifier crédits AVANT chaque action
4. `GET /api/credits` : balance + plan

```sql
CREATE OR REPLACE FUNCTION deduct_credits(
  p_user_id   uuid,
  p_amount    numeric,
  p_action    text,
  p_project_id uuid DEFAULT NULL
) RETURNS void AS $$
BEGIN
  IF (SELECT balance FROM credits WHERE user_id = p_user_id) < p_amount THEN
    RAISE EXCEPTION 'insufficient_credits';
  END IF;
  UPDATE credits SET balance = balance - p_amount, updated_at = now()
    WHERE user_id = p_user_id;
  INSERT INTO credit_transactions (user_id, project_id, action, amount)
    VALUES (p_user_id, p_project_id, p_action, -p_amount);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
```

**Skill :** `cirqix-credits` | **Risque :** Moyen

---

## Phase 3 — KiCad + Footprints (Semaines 5-7)

### Étape 3.1 — 🔴 FastAPI KiCad complet

**Fichiers :**
- `services/kicad/main.py`
- `services/kicad/routers/placement.py`
- `services/kicad/routers/routing.py`
- `services/kicad/routers/drc.py`
- `services/kicad/routers/export.py`
- `services/kicad/models.py`

**Endpoints :**

| Route | Description |
|-------|-------------|
| `POST /place` | Placement composants (pcbnew SetPosition/SetOrientation) |
| `POST /route` | Freerouting : .kicad_pcb → .dsn → Java → .ses → .kicad_pcb |
| `POST /drc` | DRC check → violations JSON |
| `POST /drc/fix` | Application corrections DRC |
| `POST /export/gerbers` | Gerbers + drill + ZIP |
| `POST /export/step` | Modèle 3D STEP (plan Pro+) |
| `POST /export/bom` | BOM CSV JLCPCB-ready |
| `POST /simulate` | ngspice (plan Pro) |

**Skill :** `cirqix-kicad-service`, `/everything-claude-code:python-patterns` | **Risque :** 🔴 ÉLEVÉ

---

### Étape 3.2 — Agents Placement + Routage + DRC

**Fichiers :**
- `packages/agents/src/agents/placement-agent.ts`
- `packages/agents/src/agents/routing-agent.ts`
- `packages/agents/src/agents/drc-agent.ts`
- `packages/agents/src/tools/kicad-tools.ts`

**Actions :**
1. Agent Placement : Haiku 4.5, tools `call_kicad_place`, `search_octopart`
2. Agent Routage : Haiku 4.5, tools `launch_freerouting`, `run_drc_check`
3. Agent DRC : Haiku 4.5, boucle max 3×, tools `run_drc`, `apply_teardrops`, `refill_zones`, `widen_tracks`
4. Agent Correction Globale : Sonnet 4.6, si blocage persistant
5. `kicad-tools.ts` : wrappers HTTP → `KICAD_SERVICE_URL`

**Skill :** `cirqix-pcb-agent`, `cirqix-drc` | **Risque :** Élevé

---

### Étape 3.3 — BullMQ Workers KiCad

**Fichiers :**
- `packages/agents/src/workers/kicad-worker.ts`
- `packages/agents/src/queues/kicad-queue.ts`

**Actions :**
1. Queue `kicad-jobs` : concurrency 10, timeout 5 min/job
2. Progress → Redis pubsub → SSE frontend
3. Retry : max 3 tentatives, backoff exponentiel

**Skill :** `bullmq-specialist` | **Risque :** Moyen

---

### Étape 3.4 — Agent Footprint (cascade 8 étapes)

**Fichiers :**
- `packages/agents/src/agents/footprint-agent.ts`
- `packages/agents/src/tools/footprint-tools.ts`

**Cascade :**
1. `search_kicad_official(part_number)` — librairies KiCad locales
2. `search_snapmagic(description)` — API SnapMagic
3. `search_octopart(part_number)` — Octopart/LCSC
4. `find_datasheet(part_number)` — URL datasheet
5. `extract_from_pdf_vision(url)` — Claude Vision lit dimensions
6. `generate_footprint_from_specs(specs)` — génère `.kicad_mod`
7. `validate_vs_datasheet(footprint, specs)` — vérifie dimensions
8. `save_to_user_library(footprint)` — Supabase + embedding pgvector

**Badge source :** KiCad_official | SnapMagic | Octopart | IA_Claude_from_datasheet

**Skill :** `cirqix-footprint` | **Risque :** Élevé

---

### Étape 3.5 — Circuit-Synth Engine ✅ (livré en Phase 2)

**Fichiers :**
- `packages/agents/src/engines/circuit-synth-engine.ts` ✅
- `packages/agents/src/engines/engine-router.ts` ✅
- `services/kicad/routers/schematic_gen.py` ✅ (ex circuit_synth.py — renommé pour éviter confusion avec PyPI circuit-synth)
- `services/kicad/requirements.txt` ✅

**Livré :**
1. Haiku génère JSON schema `{ components, nets, connections }` avec pin names KiCad
2. `validateAndCorrectSchema()` → POST `/circuit-synth/validate-symbols` → corrections auto
3. `_safe_symbol()` dans FastAPI — 2ème filet de sécurité
4. Dual-mode génération :
   - `routers/schematic.py` + `tools/schematic.py` : circuit_synth pip → kicad-tools Schematic → TypeScript S-expr
   - `routers/pcb.py` + `tools/pcb.py` : `_generate_pcb_sexpr()` → `.kicad_pcb`
   - Docker absent → fallback TS inline (`schematic-engine.ts`)
5. Upload Supabase Storage → `pcb_state.kicad_sch_url` / `kicad_pcb_url` → KiCanvas
6. Fallback S-expression inline TS si service indisponible

**✅ circuit_synth installé dans Docker** — `pip install ./circuit_synth` (src layout, PYTHONPATH=/app/circuit_synth/src)

**Skill :** `cirqix-circuit-synth`, `cirqix-kicad-service`

---

### Étape 3.6 — Page Footprints Dashboard

**Fichiers :**
- `apps/dashboard/app/dashboard/footprints/page.tsx`
- `apps/api/app/api/footprints/route.ts`
- `apps/api/app/api/footprints/search/route.ts`

**Actions :**
1. Liste footprints + badge source
2. Viewer inline PixiJS (pads + courtyard + silkscreen)
3. Recherche sémantique pgvector : `?q=regulateur+3.3V+QFN`
4. Tab "Communauté" : footprints validés partagés
5. Export `.kicad_mod` : plan Pro uniquement

---

## Phase 4 — 3D + JLCPCB + Paiement (Semaines 8-9)

### Étape 4.1 — Viewer 3D Three.js ✅

**Fichiers :** `apps/web/src/widgets/viewer/ui/View3D.tsx`

**Livré :**
- Three.js + `@react-three/fiber` + `@react-three/drei` — rendu 3D dans le browser
- Composants colorisés par kind (IC bleu marine, CAP gris, RES or, LED rouge, CONN anthracite)
- Board FR4 vert (#2d5a27) + pads cuivre + silkscreen blanc
- OrbitControls — rotation, zoom, pan
- Coût : 1 crédit, plan Pro+ uniquement
- Onglet "3D" dans l'ExportView

---

### Étape 4.2 — Simulation ngspice ✅

**Fichiers :**
- `services/kicad/routers/simulate.py` (NOUVEAU — `POST /simulate/auto`, base64 I/O)
- `services/kicad/tools/simulation.py` (refonte — parsing ngspice tabular + fallback démo)
- `packages/agents/src/engines/simulation-service.ts` (NOUVEAU — client TS, 90s timeout)
- `packages/agents/src/tools.ts` — `call_agent_simulation` + `_demoVectors()` fallback
- `packages/types/src/index.ts` — `SimulationVector`, `SimulationData`, `PCBState.simulationData`
- `apps/web/src/widgets/viewer/ui/SimulationView.tsx` (NOUVEAU — Recharts LineChart groupés)
- Timeline : onglet "Simulate" avec icône FlaskConical

**Livré :**
1. `call_agent_simulation` → `POST /simulate/auto` → kicad-cli SPICE → ngspice batch → vecteurs V/A
2. Analyses : transient (`.tran 1µs 1ms`), dc (`.op`), ac (`.ac dec 100 1 10Meg`)
3. Parsing tabular ngspice → `SimulationData.vectors[]`
4. Fallback : waveformes synthétiques RC réalistes si ngspice indisponible
5. Recharts `LineChart` groupés par unité (V / A), formatage engineering notation
6. Coût : 3 crédits, plan Pro+
7. `pcbStateTools` + `stepMap` dans l'orchestrateur — simulation SSE live

---

### Étape 4.3 — Agent BOM/Export + JLCPCB ✅

**Fichiers :**
- `packages/agents/src/tools.ts` — `call_agent_export` complet
- `apps/web/src/app/api/jlcpcb/order/route.ts` (NOUVEAU — `POST /api/jlcpcb/order`)
- `apps/web/src/widgets/viewer/ui/ExportView.tsx` (refonte — downloads réels + JLCPCB)
- `packages/types/src/index.ts` — `PCBState.gerberZipB64`, `bomCsv`, `quoteUsd`, `leadTimeDays`

**Livré :**
1. Export Gerbers + BOM CSV + CPL depuis `POST /export/all` (kicad-cli ou fallback)
2. `call_agent_export` dans `pcbStateTools` → SSE `pcb_state` → frontend reçoit les données
3. Téléchargement réel des Gerbers (blob base64) et BOM CSV
4. Devis live `quoteUsd` / `leadTimeDays` avec badge "live quote"
5. Checkbox **"OUI JE CONFIRME"** obligatoire côté frontend ET backend (`z.literal(true)`)
6. `POST /api/jlcpcb/order` : validation DRC_CLEAN, génération `orderRef`, mise à jour status `PCB_LIVRÉ`

---

### Étape 4.x — Refactor nommage + optimisation tokens ✅ (2026-05-26)

**Commits :** `b0923d4` (token opt) · `d2834b3` (rename kicad_gen)

**Livré :**
1. `circuit-synth-engine.ts` → `schematic-engine.ts` — évite confusion avec pip package `circuit_synth`
2. `CircuitSynthRequest/Response` → `SchematicRequest/Response` dans le router Python
3. `schematic_gen.py` → `kicad_gen.py` — le fichier gère `.kicad_sch` + `.kicad_pcb`, pas uniquement le schéma
4. `circuit_synth` pip installé dans Docker : `pip install ./circuit_synth` (src/ layout, PYTHONPATH fix)
5. `orchestrator.ts` : strip blobs KiCad (`kicad_sch_content`, `kicad_pcb_content`, `gerber_zip_b64`) des `tool_result` envoyés à Sonnet → économie ~70% tokens input (≈ $0.86 → ~$0.25/run schema)

---

### Étape 4.4 — Paiement Lemon Squeezy

**Fichiers :**
- `apps/api/app/api/webhooks/lemon-squeezy/route.ts`
- `apps/dashboard/app/dashboard/billing/page.tsx`

**Actions :**
1. Produits Lemon Squeezy : Pro (25€/mois), Pro Max (50€/mois), top-ups (5€/10€/20€)
2. Webhook `/api/webhooks/lemon-squeezy` :
   - `subscription_created` → crédite le compte
   - `subscription_renewed` → recrédite mensuellement
   - `order_created` (top-up) → crédite instantanément
3. Vérification signature HMAC
4. Idempotence : vérifier transaction_id avant insert

**Skill :** `cirqix-credits` | **Risque :** Moyen

---

## Phase 5 — Polish + Launch (Semaine 10)

> **Amélioration placement future (Post-Phase 5 / Phase 6) : RL_PCB**
> Architecture hybride LLM + Reinforcement Learning pour le placement PCB :
> - LLM (Sonnet) → analyse schéma, comprend contraintes, suggère stratégie (groupes fonctionnels, faces Top/Bottom, zones sensibles)
> - RL_PCB → prend les suggestions LLM et optimise mathématiquement les positions X/Y
> - pcbnew → importe le résultat pour validation DRC
> Pipeline : `call_agent_schema → LLM strategy → RL_PCB optimizer → pcbnew SetPosition → Freerouting`
> Actuellement : kicad-tools CMA-ES → fallback pcbnew grille — RL_PCB serait l'upgrade Phase 6+.
>
> **Placement compact courtyard-aware — reporté ici (décision 2026-06-02).**
> État actuel : `auto_place` garantit 0 chevauchement (gate courtyard + sélection),
> mais pour les circuits avec **module à corps décalé** (Arduino/STM32) il retombe
> sur `place_unplaced` (grille étalée, fils longs) car le CMA-ES kicad_tools modélise
> chaque composant comme une **AABB centrée sur l'origine** et ignore l'offset du
> corps (Arduino : courtyard 75×54mm centré à +24mm en y vs origine). Le rendre
> vraiment compact (composants serrés autour du corps) exige un **modèle géométrique
> avec offset** touchant 6 fichiers du cœur kicad_tools (vector/geometry/priors/seed/
> slide_off/visualization) — risqué sans leur suite de tests. Décision : ne PAS
> patcher l'optimiseur en force ; traiter la compacité proprement via RL_PCB en
> Phase 6 (RL_PCB devient simplement un candidat de plus dans la sélection
> `auto_place` existante). Détails : `docs/notefinal.md` (2026-06-02).

### Étape 5.1 — Sécurité

- Rate limiting Upstash Ratelimit (10 req/min `/api/agent/run`)
- Validation Zod sur TOUS les endpoints
- Headers sécurité : CSP, HSTS, X-Frame-Options
- `ANTHROPIC_API_KEY` jamais côté client
- Audit RLS Supabase (isolation user A vs user B)

**Skill :** `/everything-claude-code:security-scan`

---

### Étape 5.2 — Tests

| Type | Outil | Cibles |
|------|-------|--------|
| Unit | Vitest | Crédits (atomicité), parsing netlist, engine router |
| Integration | Vitest + Supertest | API routes, webhooks, DB |
| E2E | Playwright | Signup → projet → chat → viewer → export → billing |
| Load | k6 | BullMQ 10 PCBs simultanés |
| Sécurité | Manuel | RLS isolation, injection, XSS, CSRF |

**Cible : 80%+ couverture**

**Skill :** `/everything-claude-code:tdd`, `/everything-claude-code:e2e`

---

### Étape 5.3 — Monitoring

- **Sentry** : error tracking Next.js + FastAPI
- **PostHog** : events (projet créé, PCB généré, commande JLCPCB)
- **LangSmith** : traces agents (coûts, latence, tokens)
- **Pino** : logger production (pas de console.log)

---

### Étape 5.4 — Launch

1. Changelog public `/changelog`
2. Documentation `/docs` (premiers pas, crédits, API)
3. Email waitlist via Resend : invitation early access
4. Product Hunt submission
5. Posts LinkedIn + communautés EDA (r/KiCad, Hackaday, EEVBlog)

---

## Risques et mitigations

| Risque | Sévérité | Mitigation |
|--------|----------|------------|
| Docker KiCad headless cassé | 🔴 CRITIQUE | Valider en Phase 0.8 AVANT tout. Fallback : TSCircuit uniquement |
| API JLCPCB en liste d'attente | 🔴 ÉLEVÉ | Mock API + export Gerber manuel en attendant |
| Coût Claude API > prévisions | Moyen | `max_budget_usd`, compression contexte, LangSmith |
| Freerouting échoue PCB complexe | Moyen | Boucle DRC max 3× + Agent Correction Sonnet 4.6 |
| SnapMagic API indisponible | Moyen | Cascade 8 étapes — continuer avec Octopart puis Vision PDF |
| Race conditions crédits | Moyen | RPC atomique Supabase (transaction SQL) |
| Webhook Lemon Squeezy doublons | Faible | Idempotence : vérifier transaction_id avant insert |

---

## Chemin critique

```
0.8 (Docker KiCad) ← VALIDER EN PREMIER
      ↓
0.1 → 0.5 → 2.1 → 2.5 → 3.1 → 3.2 → 4.3
      ↓
      0.6 (Redis) → 2.6 → 3.3
```

L'étape **0.8** est sur le chemin critique. Si elle échoue, le MVP tourne sur Circuit-Synth fallback TS uniquement (PCB < 20 composants, 2 couches) — ce qui couvre la majorité des cas du plan Free.

---

## Estimation temporelle

| Phase | Durée | Heures (3-4h/jour) |
|-------|-------|---------------------|
| Phase 0 | 1 semaine | ~25h |
| Phase 1 | 1 semaine | ~20h |
| Phase 2 | 2 semaines | ~50h |
| Phase 3 | 3 semaines | ~60h |
| Phase 4 | 2 semaines | ~40h |
| Phase 5 | 1 semaine | ~25h |
| **Total** | **10 semaines** | **~220h** |

---

## Critères de succès par phase

### Phase 0
- [ ] `pnpm turbo build` passe sans erreur
- [ ] Supabase : tables créées, RLS active, pgvector active
- [ ] Redis : connexion OK
- [ ] Docker KiCad : `import pcbnew` fonctionne en headless
- [ ] CI GitHub Actions : vert

### Phase 1
- [ ] Landing déployée sur cirqix.ai
- [ ] Lighthouse 100/100
- [ ] Formulaire waitlist → Supabase → Resend fonctionnel

### Phase 2
- [ ] Login/signup Supabase Auth (email + Google)
- [ ] Créer projet → chat → schéma → KiCanvas affiche `.kicad_sch`
- [ ] Streaming SSE tokens en temps réel
- [ ] Crédits déduits à chaque action
- [ ] Progress bar animée correctement

### Phase 3
- [ ] Pipeline : schéma Circuit-Synth → placement → routage → DRC clean → Gerber
- [ ] Cascade footprint : 1 footprint généré par Vision Claude
- [ ] Circuit-Synth : génère `.kicad_sch` + `.kicad_pcb` natifs
- [ ] BullMQ : 3+ PCBs en parallèle sans collision

### Phase 4
- [ ] Viewer 3D Three.js charge un fichier STEP
- [ ] Devis JLCPCB affiché dans modal
- [ ] Paiement Lemon Squeezy : upgrade plan → crédits crédités
- [ ] Simulation ngspice retourne résultats affichables

### Phase 5
- [ ] 80%+ couverture tests
- [ ] Audit sécurité passé (RLS, injection, XSS)
- [ ] Monitoring opérationnel (Sentry, PostHog, LangSmith)
- [ ] Product Hunt soumis
