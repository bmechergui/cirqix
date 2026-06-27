# Cirqix Architecture — Agents & Engines (corrigée & alignée CLAUDE.md)

> **Historique :** ce document a été réécrit le 2026-04-17 après critique
> architecturale. La version précédente proposait 12 agents LLM + tscircuit +
> Circuit-Synth en tant qu'agent IA + Placement/Routing parallèles.
> Ces choix contredisaient `CLAUDE.md` (6 agents max, budget 0.12€/PCB,
> tscircuit banni, dépendance physique placement→routage). Voir la section
> **§15 — Corrections majeures vs version précédente** en fin de document.

---

## 🧠 1. Vision globale

Cirqix est une plateforme SaaS d'IA qui transforme un **prompt utilisateur**
en **projet KiCad prêt fabrication** (JLCPCB).

**Pipeline haut niveau :**

```
User Prompt
   ↓
Orchestrator (Sonnet 4.6)
   ↓
Agents IA (Haiku 4.5) ←→ Engines déterministes (Python/Java)
   ↓
Single Source of Truth : PCBState + .kicad_sch + .kicad_pcb (Supabase Storage)
   ↓
Gerbers + BOM LCSC + STEP 3D
   ↓
User confirmation "OUI JE CONFIRME"
   ↓
Commande JLCPCB
```

**Règles invariantes (CLAUDE.md) :**
- Orchestrateur = **Sonnet 4.6**, max **15 itérations** par PCB
- Agents spécialisés = **Haiku 4.5** (3× moins cher que Sonnet)
- Coût cible : **~0.12€ par PCB complet**
- Commande JLCPCB : **confirmation manuelle obligatoire** — jamais automatique
- Moteur schéma : **Circuit-Synth** (Python) — JAMAIS tscircuit (déprécié)
- Viewer : **KiCanvas** (rendu natif `.kicad_sch` / `.kicad_pcb`) + Three.js pour la 3D

---

## 🎯 2. Core Concept

| Élément | Rôle | Techno |
|---------|------|--------|
| **Agents** | Intelligence (décisions, ambiguïtés, choix) | Claude SDK — Sonnet / Haiku |
| **Engines** | Exécution déterministe (pas de LLM) | Python (pcbnew, circuit-synth), Java (Freerouting) |
| **State Machine** | Reprise de session + idempotence | `PCBStatus` enum dans Supabase |
| **Storage** | Single source of truth | Supabase Storage (signed URLs 1h) |
| **Orchestrator** | Routeur + state machine + budget agent | Claude SDK Sonnet 4.6 |

⚠️ **Circuit-Synth n'est PAS un agent IA** — c'est un **engine Python déterministe**
qui génère `.kicad_sch` / `.kicad_pcb` à partir d'un JSON de composants/nets.

---

## 📊 3. State Machine — `PCBStatus`

Persisté en DB Supabase (table `pcb_states`), RLS activée par user.

```
INITIAL
   ↓
SCHEMA_DONE       ← Schematic Agent + Circuit-Synth engine
   ↓
PLACEMENT_DONE    ← Placement Agent + pcbnew engine
   ↓
ROUTING_DONE      ← Routing Agent + Freerouting engine
   ↓
DRC_CLEAN         ← DRC Agent (boucle max 3×)
   ↓
PCB_LIVRÉ         ← Export (Gerbers + BOM + STEP) + JLCPCB order
```

À chaque transition : **déduction crédits** (`cirqix-credits` skill) + **update** `iteration_count`.

---

## 🤖 4. Agents Layer (6 agents — budget 0.12€/PCB tenu)

### 4.1 Orchestrator Agent — Sonnet 4.6

**Rôle :**
- Route les requêtes vers les 5 agents spécialisés
- Gère la state machine `PCBStatus`
- Compte les itérations (max 15)
- Détecte violations DRC → retry placement/routing (max 3 fois)
- Fusionne les outputs des agents en `PCBState`
- Enforce la confirmation JLCPCB

**Input :** message utilisateur + contexte projet + PCBStatus courant
**Output :** `AgentAction[]` (tool calls) + réponse streamée (SSE)

---

### 4.2 Design Agent — Haiku 4.5
> ✅ Fusion de **Intent + Architecture + Constraint** (ex 3 agents → 1)

**Rôle :**
- Déduit le type de projet (IoT, power supply, motor driver, etc.)
- Détermine le nombre de layers (2 / 4 / 6)
- Définit les design rules (trace_width, clearance, via_drill, min_text)
- Identifie les blocs fonctionnels (MCU, Sensor, Power, Analog)

**Input :**
```json
{ "prompt": "régulateur 5V avec capteur de température IoT" }
```

**Output (`design.json`) :**
```json
{
  "type": "iot_sensor",
  "blocks": ["MCU", "Sensor", "Power"],
  "layers": 2,
  "rules": {
    "trace_width_mm": 0.3,
    "clearance_mm": 0.2,
    "via_drill_mm": 0.3,
    "min_text_mm": 1.0
  },
  "constraints": {
    "power": "low",
    "connectivity": "wifi",
    "max_board_mm": [50, 50]
  }
}
```

---

### 4.3 Schematic Agent — Haiku 4.5
> ✅ Fusion de **Component + Netlist** (ex 2 agents → 1)

**Rôle :**
- Choisit les composants adaptés au `design.json`
- Construit les net names + pin mappings (GPIO4, VCC, GND...)
- Valide les pin names via `POST /circuit-synth/validate-symbols`

**Engine downstream :** **Circuit-Synth** (Python)
→ écrit `.kicad_sch` + `.kicad_pcb` initial
→ upload Supabase Storage (`kicad-files` bucket)
→ signed URL 1h pour KiCanvas

**Output (`schematic.json`) :**
```json
{
  "components": [
    { "ref": "U1", "value": "ESP32-WROOM-32", "symbol": "RF_Module:ESP32-WROOM-32" },
    { "ref": "U2", "value": "DS18B20", "symbol": "Sensor_Temperature:DS18B20" },
    { "ref": "R1", "value": "4.7k", "symbol": "Device:R" }
  ],
  "nets": [
    { "name": "GPIO4_DATA", "pins": [{"ref": "U1", "pin": "GPIO4"}, {"ref": "U2", "pin": "DQ"}, {"ref": "R1", "pin": "1"}] }
  ],
  "kicad_sch_url": "https://...supabase.../test.kicad_sch?signed=...",
  "kicad_pcb_url": "https://...supabase.../test.kicad_pcb?signed=..."
}
```

→ **PCBStatus = `SCHEMA_DONE`**

---

### 4.4 Footprint Agent — Haiku 4.5
> ✅ Cascade 8 étapes (skill `cirqix-footprint`)

**Rôle :** pour chaque composant, trouver un footprint KiCad valide + LCSC part number.

**Pipeline cascade :**
1. LCSC catalog (API) — primary source
2. KiCad symbol library match (pcbnew)
3. SnapMagic (footprints commerciaux)
4. Octopart (marketplace)
5. pgvector RAG (embeddings footprints existants)
6. GitHub snippet search
7. Auto-generated via footprint AI (Haiku)
8. Fallback manuel (user prompt)

**Output :**
```json
{
  "footprints": {
    "U1": { "kicad": "RF_Module:ESP32-WROOM-32", "lcsc": "C701341", "available_jlc": true },
    "U2": { "kicad": "Package_TO_SOT_THT:TO-92_Inline", "lcsc": "C59661", "available_jlc": true },
    "R1": { "kicad": "Resistor_SMD:R_0805_2012Metric", "lcsc": "C17513", "available_jlc": true }
  }
}
```

---

### 4.5 Placement Agent — Haiku 4.5

**Rôle :** déterminer les coordonnées (x, y, rotation) de chaque composant.

**Stratégie :** grouper par blocs fonctionnels (MCU/Sensor/Power) du `design.json`,
minimiser la longueur totale des connexions (wirelength).

**Engine downstream :** **pcbnew** Python API via FastAPI `POST /place/auto`
→ `SetPosition()` + `SetOrientation()` sur chaque footprint
→ sauve `.kicad_pcb` mis à jour

**Output :**
```json
{
  "placement": {
    "U1": { "x": 15, "y": 20, "rot": 0 },
    "U2": { "x": 35, "y": 20, "rot": 90 },
    "R1": { "x": 25, "y": 25, "rot": 0 }
  }
}
```

→ **PCBStatus = `PLACEMENT_DONE`**

---

### 4.6 Routing Agent — Haiku 4.5

**Rôle :** router les nets entre composants placés.

**Engine downstream :** **Freerouting** (Java JAR) via FastAPI `POST /route/auto`

**Pipeline :**
```
.kicad_pcb placé
    ↓ pcbnew.ExportSpecctraDSN()
.dsn
    ↓ java -jar freerouting.jar -de dsn -do ses
.ses
    ↓ pcbnew.ImportSpecctraSES()
.kicad_pcb routé
```

**Output :**
```json
{
  "tracks": [
    { "net": "GPIO4_DATA", "start": [15, 20], "end": [35, 20], "layer": "F.Cu" }
  ],
  "vias": [],
  "stats": { "track_count": 12, "via_count": 3, "duration_ms": 4200 }
}
```

→ **PCBStatus = `ROUTING_DONE`**

⚠️ **Séquentiel par nature** — le routage **dépend du placement**. NON parallélisable.

---

### 4.7 DRC Agent — Haiku 4.5

**Rôle :** vérifier conformité aux design rules + corriger auto (max 3×).

**Engine downstream :** **pcbnew DRC natif** via FastAPI `POST /drc`

**Boucle :**
```
DRC run → violations ?
   ├─ 0    → PCBStatus = DRC_CLEAN → Export
   └─ >0  → DRC Agent choisit action :
              ├─ placement fix (loop back §4.5, iter++)
              ├─ routing fix (loop back §4.6, iter++)
              └─ rules relaxation (user prompt)
            Si iter > 3 → abort + user feedback
```

**Output :**
```json
{
  "status": "violations",
  "violations": [
    { "type": "clearance", "loc": [12.5, 30.1], "actual_mm": 0.15, "required_mm": 0.2 }
  ],
  "suggested_fix": "reroute"
}
```

→ **PCBStatus = `DRC_CLEAN`** quand `violations.length == 0`

---

## ⚙️ 5. Engines Layer (déterministe — pas de LLM)

| Engine | Techno | Rôle | FastAPI endpoint |
|--------|--------|------|------------------|
| **Circuit-Synth** | Python (SKiDL wrapper) | Génère `.kicad_sch` + `.kicad_pcb` initial | `POST /circuit-synth/generate` |
| **Symbol Validator** | Python (KiCad lib scan) | Valide pin names avant génération | `POST /circuit-synth/validate-symbols` |
| **pcbnew Placement** | Python (pcbnew API) | Applique coordonnées sur footprints | `POST /place/auto` |
| **Freerouting** | Java (JAR headless) | Auto-route `.dsn` → `.ses` | `POST /route/auto` |
| **pcbnew DRC** | Python (pcbnew API) | Design Rules Check | `POST /drc` |
| **Export** | Python (pcbnew plotter) | Gerbers + BOM LCSC + STEP 3D | `POST /export` |
| **KiCanvas** | Web component JS | Rendu `.kicad_sch`/`.kicad_pcb` dans le navigateur | (front-end) |
| **Three.js viewer** | JS + occt-import-js | Vue 3D via fichiers STEP | (front-end) |

**Tous exposés par** le microservice FastAPI `services/kicad/` (Docker headless, KiCad 8.0 PPA + OpenJDK 17).

---

## 📦 6. JSON Single Source of Truth

### 6.1 `PCBState` (persisté dans Supabase)

```typescript
interface PCBState {
  project_id: string;
  status: PCBStatus;           // INITIAL | SCHEMA_DONE | ... | PCB_LIVRÉ
  iteration_count: number;     // max 15
  design: DesignJson;          // §4.2 Design Agent output
  schematic: SchematicJson;    // §4.3 Schematic Agent output
  footprints: FootprintsJson;  // §4.4 Footprint Agent output
  placement: PlacementJson;    // §4.5 Placement Agent output (null avant)
  routing: RoutingJson;        // §4.6 Routing Agent output (null avant)
  drc: DrcJson;                // §4.7 DRC Agent output (null avant)
  kicad_sch_url?: string;      // signed URL 1h
  kicad_pcb_url?: string;      // signed URL 1h
  updated_at: string;          // ISO timestamp
}
```

### 6.2 Immutabilité

À chaque étape, l'orchestrateur **crée un nouveau `PCBState`** (pas de mutation) —
nouvelle ligne DB, nouvelle version d'artefacts Supabase Storage. Permet replay +
debug + audit trail.

---

## 🔄 7. Full Pipeline détaillée

```
USER prompt
    ↓
Orchestrator (Sonnet 4.6)
    ↓
    ├─[1] Design Agent (Haiku)        → design.json          [-0.5 crédits chat]
    │
    ├─[2] Schematic Agent (Haiku)
    │         ↓
    │     Engine: Circuit-Synth       → .kicad_sch, .kicad_pcb [-2 crédits schéma]
    │         ↓
    │     KiCanvas viewer (tab Schematic)
    │                                                        PCBStatus=SCHEMA_DONE
    │
    ├─[3] Footprint Agent (Haiku)
    │         ↓
    │     Engine: LCSC → SnapMagic → Octopart → pgvector RAG [-3 crédits footprint]
    │
    ├─[4] Placement Agent (Haiku)
    │         ↓
    │     Engine: pcbnew              → .kicad_pcb placé      [-2 crédits placement]
    │         ↓
    │     KiCanvas viewer (tab Placement)
    │                                                        PCBStatus=PLACEMENT_DONE
    │
    ├─[5] Routing Agent (Haiku)
    │         ↓
    │     Engine: Freerouting         → .kicad_pcb routé      [-3 crédits routage]
    │         ↓
    │     KiCanvas viewer (tab Routing)
    │                                                        PCBStatus=ROUTING_DONE
    │
    ├─[6] DRC Agent (Haiku)                                   [-1 crédit DRC]
    │         ↓
    │     Engine: pcbnew DRC
    │         ├─ violations=0  →  PCBStatus=DRC_CLEAN
    │         └─ violations>0  →  loop back [4] ou [5]
    │                            (iter++ ; if iter>3 abort + user input)
    │
    └─[Export déterministe]                                   [-1 crédit export]
            ↓
        Gerbers + BOM LCSC + STEP 3D
            ↓
        Three.js 3D viewer (tab 3D)
    ↓
User confirmation explicite "OUI JE CONFIRME" dans le chat
    ↓
JLCPCB order API
    ↓                                                        PCBStatus=PCB_LIVRÉ
```

**Total crédits :** 0.5 + 2 + 3 + 2 + 3 + 1 + 1 = **12.5 crédits**
Plan Maker (100 crédits/mois 25€) → **~8 PCBs/mois**.

---

## ⚡ 8. Parallélisation (réelle — pas fantaisiste)

| Étape | Parallélisable ? | Justification |
|-------|------------------|---------------|
| Design + Schematic | ❌ | Schematic a besoin de `design.json` |
| Schematic + Footprint | ✅ | Footprint lookup peut démarrer dès qu'on a la liste des composants (avant que tous les nets soient tracés) |
| Placement + Routing | ❌ | **Routing dépend des coordonnées du placement** |
| DRC + Preview | ✅ | KiCanvas affiche `.kicad_pcb` pendant que DRC tourne |
| Export Gerbers + BOM + STEP | ✅ | 3 outputs indépendants à partir du même `.kicad_pcb` final |

---

## 🔐 9. Sécurité & Contraintes

- **RLS Supabase** activée sur toutes les tables (isolation user A / user B)
- **Crédits** : vérifier AVANT chaque agent, déduire APRÈS succès (jamais avant → évite le debit en cas d'échec)
- **JLCPCB** : confirmation "OUI JE CONFIRME" explicite en chat — jamais automatique
- **Signed URLs** Supabase Storage : TTL 1h max (pas de liens permanents)
- **Auth** : Supabase Auth (email + Google OAuth) + middleware JWT sur `/dashboard/*`
- **Freerouting timeout** : 60s max par subprocess
- **Base64 validation** : `base64.b64decode(..., validate=True)` — jamais trust user input

---

## 🎨 10. Frontend (Feature-Sliced Design)

Voir `CLAUDE.md §Architecture frontend` pour la structure FSD complète.

**Points clés :**
- `apps/web/src/app/(marketing)/` → landing + pricing + waitlist (cirqix.ai)
- `apps/web/src/app/(dashboard)/` → chat + viewer split layout (cirqix.ai/dashboard)
- `widgets/viewer/` → ViewerPanel + KiCanvasViewer + PixiCanvas + Three.js
- `features/dashboard/ui/` → ChatPanel, Sidebar, ProjectCard, StatusBadge
- State : Zustand store (`shared/store/app-store.ts`)
- Streaming SSE (`Content-Type: text/event-stream`, event `[DONE]` en fin)

---

## 🗄️ 11. Database (Supabase Postgres)

Extensions : `uuid-ossp`, `pgvector`.

Tables principales :
- `users` — auth.users reference
- `projects` — id, user_id, name, pcb_status, iteration_count, updated_at
- `pcb_states` — snapshots successifs de PCBState (append-only, immutable)
- `messages` — chat history per project
- `credits_ledger` — transactions crédits (append-only, audit trail)
- `footprint_embeddings` — pgvector pour RAG Footprint Agent

---

## 💰 12. Système de crédits

| Action | Coût |
|--------|------|
| Chat agent | 0.5 |
| Génération schéma | 2 |
| Placement | 2 |
| Routage | 3 |
| DRC | 1 |
| Export (Gerbers+BOM+STEP) | 1 |
| Footprint IA | 3 |
| Vue 3D | 1 |
| Simulation | 3 |

**Plans :**
- Free : 5/jour
- Maker : 25€/mois → 100 crédits/mois
- Pro : 50€/mois → 300 crédits/mois
- Enterprise : illimité

⚠️ Si crédits insuffisants : **bloquer AVANT appel agent** (éviter appel API Claude payé sans rien rendre).

---

## 🧪 13. Tests

Voir `rules/common/testing.md` — 80% coverage min, TDD obligatoire (règle Cirqix).

Niveaux :
1. **Unit** — chaque agent isolé (mock Claude SDK)
2. **Integration** — Orchestrator + 1 agent réel + 1 engine réel (Docker test env)
3. **E2E** — Playwright : prompt → .kicad_pcb visualisable dans KiCanvas
4. **Visual regression** — screenshot diff KiCanvas sur 3 schémas références (LM7805, NE555, ESP32)

---

## 💡 14. Core Concept (rappel)

```
Agents    = intelligence 🧠     (6 Haiku + 1 Sonnet = 7 LLM calls / PCB)
Engines   = execution ⚙️       (Python + Java déterministes)
JSON      = source of truth 📦 (PCBState persisté + immutable par version)
Orchestrator = controller 🎯   (state machine + budget + retry)
KiCanvas  = live preview 🖥️    (rendu natif, pas de regeneration agent)
KiCad     = final output 🏭    (Gerbers + BOM + STEP)
```

---

## §15 — Corrections majeures vs version précédente

| # | Avant | Après | Raison |
|---|-------|-------|--------|
| 1 | Circuit-Synth = "AI generation layer" | Circuit-Synth = **engine Python** | Circuit-Synth est SKiDL-based, zéro LLM |
| 2 | 12 agents (Intent+Component+Footprint+Architecture+Constraint+Netlist+Placement+Routing+Validation+Preview+Export+Orchestrator) | **6 agents** (Orchestrator Sonnet + 5 Haiku spécialisés) | Budget 0.12€/PCB (CLAUDE.md) — 12 agents = 0.40-0.80€ |
| 3 | Intent + Architecture + Constraint = 3 agents séparés | **Fusion → Design Agent** | Même input (prompt), outputs complémentaires |
| 4 | Component + Netlist = 2 agents séparés | **Fusion → Schematic Agent** | Nets définis à partir des composants choisis |
| 5 | Placement + Routing en parallèle | **Séquentiel** (routing dépend du placement) | Physiquement impossible autrement |
| 6 | Preview Agent → tscircuit | **KiCanvas** (pas d'agent — web component) | tscircuit déprécié (CLAUDE.md) — KiCanvas natif |
| 7 | Export Agent (LLM) | **Export déterministe** (pcbnew plotter) | Zéro intelligence nécessaire pour générer Gerbers |
| 8 | Pas de boucle DRC | **Boucle DRC max 3×** avec fix auto | DRC failures courantes → corriger placement/routing |
| 9 | Pas d'état machine | **PCBStatus explicite** (INITIAL→...→PCB_LIVRÉ) | Reprise session + idempotence |
| 10 | JSON v1/v2 sous-spécifiés | **PCBState TypeScript complet** avec `kicad_sch_url`/`kicad_pcb_url` | Signed URLs Supabase pour KiCanvas |
| 11 | Footprint Agent simpliste | **Cascade 8 étapes** (LCSC→SnapMagic→Octopart→pgvector RAG→...) | CLAUDE.md skill `cirqix-footprint` |
| 12 | Validation Agent = DRC + SKiDL | **DRC Agent** (pas SKiDL ici — SKiDL = ERC schéma, pas DRC PCB) | Confusion ERC vs DRC |
| 13 | Pas de gestion crédits | **Vérifier AVANT, déduire APRÈS** chaque appel | Skill `cirqix-credits` + éviter debit sur échec |
| 14 | Pas de confirmation JLCPCB | **"OUI JE CONFIRME" obligatoire** | CLAUDE.md règle absolue |

---

## 🔗 Références

- `CLAUDE.md` — règles absolues, workflow, stack
- `PLAN.md` — phases d'implémentation (Phase 2 ✓, Phase 3 en cours)
- `docs/cirqix-full-resume.md` — vision produit + business model
- `docs/agentdescription.md` — system prompts exacts des agents
- `.claude/SKILLS.md` — registre des skills disponibles
- `docs/design/design-system.md` — tokens UI, couleurs, composants
