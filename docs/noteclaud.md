# Cirqix — Pipeline Validation (step by step)

> Ce document est mis à jour après chaque step validé ensemble.
> Dernière mise à jour : 2026-05-26

---

## Légende

| Icône | Statut |
|-------|--------|
| ✅ | Validé ensemble |
| 🔲 | À implémenter |
| ⚠️ | Stub / partiel |
| 🔄 | En cours |

---

## Orchestrateur — Détail complet

### Fichiers

```
packages/agents/src/
├── orchestrator.ts      ← Boucle principale (Sonnet 4.6 + SSE stream)
├── tools.ts             ← 8 tool calls + executeToolStub()
├── prompts.ts           ← ORCHESTRATOR_SYSTEM_PROMPT
├── types.ts             ← Interfaces TypeScript
└── engines/
    ├── schematic-engine.ts       ← Engine KiCad (POST /circuit-synth/generate)
    └── engine-router.ts          ← Router vers pcbnew / Freerouting
```

### Modèle & configuration

```typescript
// orchestrator.ts
const ORCHESTRATOR_MODEL = 'claude-sonnet-4-6'  // Sonnet — chef du pipeline
const MAX_ITERATIONS     = 15                    // max 15 appels Claude
const MAX_TOKENS         = 4096                  // par réponse
```

### System Prompt (résumé — mis à jour 2026-05-26)

```
Tu es le Chef de Projet PCB Senior de Cirqix.ai. 15 ans d'expérience.

PIPELINE (ordre strict, max 15 itérations) :
  ① call_agent_schema     → .kicad_sch + unresolved_footprints
  ② call_agent_erc        → validation électrique, auto-fix
  ③ call_agent_footprint  → 1 appel par ref dans unresolved_footprints
  ④ call_agent_gen_pcb      → .kicad_pcb depuis schéma + footprints validés
  ⑤ call_agent_placement  → positions X/Y/rotation via pcbnew
  ⑥ call_agent_routing    → Freerouting + ground planes
  ⑦ call_agent_drc        → DRC kicad-cli, boucle auto-fix max 3×
  ⑧ call_agent_export     → Gerbers + BOM + CPL + devis JLCPCB

RÈGLES ABSOLUES :
  - NE JAMAIS prescrire de composants à call_agent_schema — l'Agent Schéma décide seul
  - NE JAMAIS skipper call_agent_erc
  - call_agent_footprint OBLIGATOIRE pour chaque ref dans unresolved_footprints AVANT call_agent_gen_pcb
  - call_agent_drc OBLIGATOIRE avant call_agent_export
  - JAMAIS commander JLCPCB sans "OUI JE CONFIRME" explicite
  - Réponds dans la langue de l'utilisateur
```

### Signature de la fonction

```typescript
// orchestrator.ts — entrée unique du pipeline
export async function* runOrchestrator(
  options: {
    userMessage : string               // prompt de l'utilisateur
    projectId   : string               // ID projet Supabase
    history     : AgentHistoryMessage[] // historique chat
  }
): AsyncGenerator<SSEEvent>
```

### Boucle d'itération (pseudo-code)

```typescript
while (iterations < MAX_ITERATIONS) {
  iterations++
  yield { type: 'iteration', count: iterations }

  // 1. Appel Sonnet 4.6 avec streaming
  const stream = client.messages.create({
    model   : 'claude-sonnet-4-6',
    system  : ORCHESTRATOR_SYSTEM_PROMPT,
    tools   : PCB_TOOLS,          // 8 tools disponibles
    messages: conversationHistory
  })

  // 2. Accumule le stream → text delta + tool_use blocks
  for await (const event of stream) {
    if (text_delta)    → yield { type: 'text', delta }
    if (tool_use)      → accumule inputJson
  }

  // 3. Si stop_reason = 'end_turn' → Sonnet a terminé, break
  if (stopReason === 'end_turn') break

  // 4. Execute chaque tool call
  for (const tool of toolUseBlocks) {
    yield { type: 'tool_call',   tool: tool.name, input }
    yield { type: 'step',        step: stepMap[tool.name] }

    const result = await executeToolStub(tool.name, input, projectId)

    yield { type: 'tool_result', tool: tool.name, summary }
    yield { type: 'pcb_state',   projectId, state: result }
    //                            ↑ Front met à jour KiCanvas en temps réel
  }

  // 5. Ajoute le résultat dans l'historique → Sonnet continue
  messages.push({ role: 'user', content: toolResults })
}

yield { type: 'done', fullText }
```

### SSE Events (tous les types)

```typescript
type SSEEvent =
  | { type: 'iteration';   count: number }               // début itération
  | { type: 'text';        delta: string }               // texte streamé Sonnet
  | { type: 'step';        step: string }                // SCHEMA/PLACEMENT/...
  | { type: 'tool_call';   tool: string; input: {} }     // avant exécution tool
  | { type: 'tool_result'; tool: string; summary: string } // après exécution
  | { type: 'pcb_state';   projectId: string; state: {} } // KiCanvas update
  | { type: 'done';        fullText: string }            // fin du pipeline
  | { type: 'error';       message: string }             // erreur critique
```

### Outils disponibles (PCB_TOOLS)

> Voir le tableau récapitulatif complet en fin de document (modèle + engine + endpoint).

```
Pourquoi Sonnet pour l'orchestrateur et Haiku pour les agents ?
  Sonnet 4.6  → raisonnement complexe, décisions architecturales, cohérence globale
  Haiku 4.5   → tâches spécialisées répétitives, 3× moins cher que Sonnet
  Résultat    → ~0.12€ par PCB complet (vs ~0.50€ si tout Sonnet)
```

### Règle critique — Sonnet décide les composants

```
❌ MAUVAIS :
   Sonnet → call_agent_schema({ user_description: "régulateur 5V" })
   Haiku devine → peut choisir LM317, L7805, LDO n'importe lequel

✅ CORRECT :
   Sonnet réfléchit → "LM7805 TO-220, C1=330nF, C2=100nF, J1/J2 connecteurs"
   Sonnet → call_agent_schema({
     user_description: "régulateur 5V",
     schema_json: '{"components":[{"ref":"U1","value":"LM7805",...}],...}'
   })
   → Haiku reçoit exactement les composants décidés par Sonnet
```

---

## Vue d'ensemble pipeline

```
User Prompt
    ↓
[STEP 1]  call_agent_design     → design.json              ✅ Validé
    ↓
[STEP 2]  call_agent_schema     → .kicad_sch + unresolved_footprints  ✅ Validé
              ↓ Engine: kicad_gen.py (circuit_synth pip → .kicad_sch SEULEMENT)
              ↓ KiCanvas viewer (tab Schematic)
    ↓
[STEP 3]  call_agent_erc        → validation ERC           ✅ Validé
              ↓ Engine: kicad-cli sch erc, auto-fix loop
    ↓
[STEP 4]  call_agent_footprint  → footprints.json          ⚠️ Partiel (1 appel par ref unresolved)
              ↓ Met à jour _pcbStateCache[projectId].schema.components
    ↓
[STEP 5]  call_agent_gen_pcb      → .kicad_pcb initial       ✅ Validé (NOUVEAU)
              ↓ Engine: kicad_gen.py _generate_pcb_sexpr() depuis cache schéma + footprints
    ↓
[STEP 6]  call_agent_placement  → .kicad_pcb placé         ✅ Validé
              ↓ Engine: pcbnew /place/auto
              ↓ KiCanvas viewer (tab PCB)
    ↓
[STEP 7]  call_agent_routing    → .kicad_pcb routé         ✅ Validé
              ↓ Engine: Freerouting /route/auto
              ↓ KiCanvas viewer (tab Routing)
    ↓
[STEP 8]  call_agent_drc        → violations / DRC_CLEAN   ✅ Validé
              ↓ Engine: kicad-cli DRC natif, boucle auto-fix max 3×
    ↓
[STEP 9]  call_agent_export     → Gerbers + BOM + CPL      ✅ Validé
              ↓ Engine: kicad-cli /export/all, zip base64
    ↓
User "OUI JE CONFIRME"
    ↓
JLCPCB Order (POST /api/jlcpcb/order)                      ✅ Validé (Phase 4.3)
```

---

## La Netlist — qui fait quoi

La netlist (liste `{net → pads connectés}`) est créée **une seule fois** puis voyage dans tous les fichiers KiCad jusqu'à la fabrication.

| Étape | Acteur | Rôle |
|-------|--------|------|
| 1️⃣ **Création** | **Schematic Agent (Haiku 4.5)** | Décide *"VIN connecte J1.1 + U1.IN + C1.1"* |
| 2️⃣ **Sérialisation** | **Circuit-Synth (Python)** | Écrit la netlist dans `.kicad_sch` + `.kicad_pcb` |
| 3️⃣ **Affichage** | **KiCanvas (front)** | Affiche les net labels (VIN, VOUT, GND) sur le schéma |
| 4️⃣ **Lecture** | **Freerouting (Java)** | Lit la netlist pour router les pistes physiques |
| 5️⃣ **Vérification** | **DRC Agent + pcbnew** | Vérifie que les pistes correspondent bien à la netlist |

### Format de la netlist (dans schematic.json — connections[])

```json
{
  "connections": [
    {
      "name": "VIN",
      "pins": [
        { "ref": "J1", "pin": 1 },
        { "ref": "U1", "pin": "IN" },
        { "ref": "C1", "pin": 1 }
      ]
    },
    {
      "name": "GND",
      "pins": [
        { "ref": "J1", "pin": 2 },
        { "ref": "U1", "pin": "GND" },
        { "ref": "C1", "pin": 2 }
      ]
    }
  ]
}
```

### Règle critique — un seul créateur

```
✅ Le Schematic Agent (Haiku 4.5) est l'UNIQUE créateur de la netlist
   → tous les autres acteurs ne font que la transporter ou la consommer
   → jamais de mutation de la netlist en aval (immutabilité)
```

---

## Le `.kicad_pcb` — qui fait quoi (et pourquoi 3 agents ?)

Le `.kicad_pcb` est créé une fois (Circuit-Synth) puis **enrichi par couches successives** par Placement → Routing → DRC. Chaque agent ajoute une dimension que les autres ne peuvent pas faire.

### Composition du `.kicad_pcb` à chaque étape

| Étape | Footprints | Positions | Pistes (F.Cu/B.Cu) | Vias | Ground plane | DRC validé |
|-------|------------|-----------|---------------------|------|--------------|------------|
| **Circuit-Synth** | ✅ Présents | ⚠️ Grille bête (0,0), (10,0), (20,0)... | ❌ | ❌ | ❌ | ❌ |
| **Placement Agent** | ✅ Présents | ✅ **Optimisées par bloc fonctionnel** | ❌ | ❌ | ❌ | ❌ |
| **Routing Agent** | ✅ Présents | ✅ Optimisées | ✅ **Tracées** | ✅ **Posés** | ✅ **Rempli** | ⚠️ Non vérifié |
| **DRC Agent** | ✅ Présents | ✅ Optimisées | ✅ Tracées | ✅ Posés | ✅ Rempli | ✅ **Clean** |

### Qui fait quoi (concret)

```
Circuit-Synth (Python)         → POSE les footprints
                                  add_footprint("LM7805", x=0, y=0)
                                  add_footprint("C1",     x=10, y=0)
                                  → tout empilé en ligne, aucune logique

Placement Agent (Haiku + pcbnew) → ARRANGE intelligemment
                                  SetPosition(U1, x=25, y=20) ← centre
                                  SetPosition(C1, x=15, y=20) ← proche IN
                                  SetPosition(C2, x=35, y=20) ← proche OUT
                                  → composants groupés par bloc fonctionnel

Routing Agent (Freerouting)     → RELIE électriquement
                                  trace VIN  : J1.1 ━━ C1 ━━ U1.IN  (F.Cu)
                                  trace VOUT : U1.OUT ━━ C2 ━━ J2.1 (F.Cu)
                                  trace GND  : tous les pads GND    (B.Cu plane)
                                  + 3 vias entre F.Cu ↔ B.Cu

DRC Agent (pcbnew)              → VALIDE les règles
                                  check clearance ≥ 0.2mm ?
                                  check trace_width ≥ 0.3mm ?
                                  → 0 violation = DRC_CLEAN
```

### Pourquoi un placement intelligent compte

| Critère | Circuit-Synth seul | Placement Agent |
|---------|--------------------|--------------------|
| Routage | Pistes longues (bruit) | Pistes courtes (signal propre) |
| Découplage | Cap à 30mm du IC (inutile) | Cap à 3mm du IC (filtre efficace) |
| Thermique | Régulateur collé au MCU | Régulateur à 15mm du MCU |
| Ergonomie | USB-C au milieu (pas branchable) | USB-C sur le bord |
| Routabilité Freerouting | 30% non routé → DRC fail | 100% routé → DRC clean |

### Analogie maison

```
🏠 Construction d'une maison

Circuit-Synth     = Livraison des MEUBLES devant la maison
                    (lits, tables, chaises empilés dans le hall)

Placement Agent   = ARRANGEUR pro qui RÉPARTIT les meubles :
                    - Lit dans la chambre
                    - Table dans la cuisine
                    - Canapé dans le salon

Routing Agent     = Tirer les CÂBLES électriques (après placement)

DRC Agent         = Inspection finale (normes électriques respectées)
```

### Règle critique — séparation des responsabilités

```
❌ Circuit-Synth NE PEUT PAS placer intelligemment
   → c'est une lib de DESCRIPTION, pas d'optimisation
   → ne connait ni les blocs fonctionnels, ni la thermique, ni l'ergonomie

❌ Circuit-Synth NE PEUT PAS router
   → ne connait pas les algorithmes de routage (A*, Dijkstra)
   → ne gère pas vias, layers, ground planes

✅ Chaque agent a son outil :
   - Placement Agent → pcbnew SetPosition() / SetOrientation()
   - Routing Agent  → Freerouting JAR (algorithme industriel 30+ ans)
   - DRC Agent      → pcbnew DRC engine natif
```

### Sans chacune des étapes

| Étape manquante | Conséquence |
|-----------------|-------------|
| Circuit-Synth | Pas de footprints du tout (PCB vide) |
| Placement Agent | Composants en vrac → routage impossible |
| Routing Agent | Pas de pistes → PCB électriquement mort |
| DRC Agent | Court-circuits potentiels → non fabricable |
| Export | JLCPCB ne peut pas fabriquer (pas de Gerbers) |

---

## STEP 1 — Design Agent

**Statut : ✅ Validé** (2026-04-22)

### Orchestrateur

```
ITERATION 1

Orchestrator reçoit :
  message    = "régulateur 5V LM7805 avec condensateurs"
  pcb_status = INITIAL
  history    = []

Orchestrator décide :
  → "Je dois d'abord analyser le type de circuit et les contraintes"
  → appelle call_agent_design

SSE → { type: 'iteration',  count: 1 }
SSE → { type: 'step',       step: 'DESIGN' }
SSE → { type: 'tool_call',  tool: 'call_agent_design',
        input: {
          user_description: "régulateur 5V LM7805 avec condensateurs"
        }}
```

### Outil (Tool)

```
Nom    : call_agent_design
Fichier: packages/agents/src/tools.ts  ← À AJOUTER

Input tool :
{
  "user_description": "régulateur 5V LM7805 avec condensateurs"
}
```

### Agent IA

```
Modèle  : claude-haiku-4-5-20251001  ← Haiku 4.5 (tâche simple + répétitive)
Coût    : ~0.004€ par appel           ← 3× moins cher que Sonnet
Rôle    : analyser le prompt → déduire type, layers, règles, contraintes
Appel   : generateDesignWithHaiku(description)  ← À CRÉER
```

### Engine

```
Aucun engine externe pour cette étape.
100% LLM (Haiku analyse le prompt texte).
```

### Output — `design.json`

```json
{
  "type": "power_supply",
  "blocks": ["Power", "Decoupling"],
  "layers": 2,
  "rules": {
    "trace_width_mm": 0.3,
    "clearance_mm": 0.2,
    "via_drill_mm": 0.3,
    "min_text_mm": 1.0
  },
  "constraints": {
    "output_voltage": 5,
    "max_current_A": 1.5,
    "max_board_mm": [50, 50]
  }
}
```

### SSE events produits

```
SSE → { type: 'tool_result', tool: 'call_agent_design',
        summary: 'power_supply — 2 layers — trace 0.3mm' }
```

### PCBStatus

```
INITIAL  →  INITIAL  (pas de changement — design = contexte seulement)
```

### Validations réalisées ✅

```
✅ DesignJson interface ajouté dans @cirqix/types (source de vérité)
✅ AgentAction enum étendu avec 'design'
✅ AgentStep enum étendu avec 'DESIGN'
✅ CREDIT_COSTS.design = 0.5 crédit
✅ call_agent_design en TÊTE de PCB_TOOLS (avant call_agent_schema)
✅ generateDesignWithHaiku() implémenté avec fallback heuristique
✅ Pino logger sur tous les chemins de fallback (observabilité)
✅ Singleton Anthropic client (review fix HIGH-1)
✅ MAX_DESC_LENGTH = 2000 clamp (review fix MEDIUM-1)
✅ isValidDesignJson valide trace_width > 0 et clearance > 0
✅ Orchestrator system prompt mis à jour (call_agent_design EN PREMIER)
✅ stepMap orchestrator: call_agent_design → 'DESIGN'
✅ 8 tests unitaires passent (TDD : RED → GREEN)
✅ pnpm type-check : 0 erreurs sur 7 packages
✅ pnpm test : 99 tests passent (aucune régression)
✅ Code review typescript-reviewer (HIGH issues fixés)
```

### Fichiers modifiés

```
packages/types/src/index.ts            → DesignJson + AgentAction + CREDIT_COSTS
packages/agents/src/tools.ts           → call_agent_design + generateDesignWithHaiku
packages/agents/src/tools.test.ts      → NEW (8 tests TDD)
packages/agents/src/prompts.ts         → ORCHESTRATOR_SYSTEM_PROMPT mis à jour
packages/agents/src/orchestrator.ts    → stepMap incluant call_agent_design
```

---

## STEP 2 — Schematic Agent

**Statut : ✅ Validé**

### Orchestrateur

```
ITERATION 2

Orchestrator reçoit :
  tool_result = { type: 'power_supply', layers: 2, ... }  ← design.json
  pcb_status  = INITIAL

Orchestrator décide :
  → "Design connu. Je génère maintenant le schéma électronique."
  → appelle call_agent_schema

SSE → { type: 'iteration',  count: 2 }
SSE → { type: 'step',       step: 'SCHEMA' }
SSE → { type: 'tool_call',  tool: 'call_agent_schema',
        input: {
          user_description: "régulateur 5V LM7805 avec condensateurs",
          design: { "type": "power_supply", "layers": 2, ... },
          complexity: "simple"
        }}
```

### Outil (Tool)

```
Nom    : call_agent_schema
Fichier: packages/agents/src/tools.ts  ✅ Existe

Input tool :
{
  "user_description": "régulateur 5V LM7805 avec condensateurs",
  "complexity": "simple"
}
```

### Agent IA

```
Modèle  : claude-haiku-4-5-20251001  ← Haiku 4.5
Coût    : ~0.006€ par appel           ← génération JSON composants
Rôle    : choisir composants + nets + pin mappings KiCad
Appel   : generateSchemaWithHaiku(description)  ✅ Implémenté
```

### Engine

```
Nom     : kicad_gen (circuit_synth pip + Python S-expr)
Techno  : Python (circuit_synth lib installée dans Docker)
Endpoint: POST /circuit-synth/generate  ✅ Implémenté
Fichier : services/kicad/routers/kicad_gen.py

Input engine :
{
  "project_id": "proj-abc123",
  "board_width_mm": 50,
  "board_height_mm": 50,
  "components": [...],
  "nets": [...],
  "connections": [...]
}

Output engine :
{
  "success": true,
  "kicad_sch_content": "(kicad_sch ...)",
  "kicad_pcb_content": "(kicad_pcb ...)"
}
```

### Output — `schematic.json`

```json
{
  "components": [
    { "ref": "U1", "value": "LM7805",   "symbol": "Regulator_Linear:L7805",      "footprint": "TO-220" },
    { "ref": "C1", "value": "330nF",    "symbol": "Device:C",                    "footprint": "0603" },
    { "ref": "C2", "value": "100nF",    "symbol": "Device:C",                    "footprint": "0603" },
    { "ref": "J1", "value": "VIN_CONN", "symbol": "Connector_Generic:Conn_01x02","footprint": "Conn_2" },
    { "ref": "J2", "value": "VOUT_5V",  "symbol": "Connector_Generic:Conn_01x02","footprint": "Conn_2" }
  ],
  "nets": ["GND", "VIN", "VOUT"],
  "connections": [
    { "name": "VIN",  "pins": [{"ref":"J1","pin":1}, {"ref":"U1","pin":"IN"},  {"ref":"C1","pin":1}] },
    { "name": "VOUT", "pins": [{"ref":"U1","pin":"OUT"}, {"ref":"C2","pin":1}, {"ref":"J2","pin":1}] },
    { "name": "GND",  "pins": [{"ref":"J1","pin":2}, {"ref":"U1","pin":"GND"}, {"ref":"C1","pin":2},
                                {"ref":"C2","pin":2}, {"ref":"J2","pin":2}] }
  ],
  "kicad_sch_content": "(kicad_sch ...)",
  "kicad_pcb_content": "(kicad_pcb ...)"
}
```

### SSE events produits

```
SSE → { type: 'tool_result', tool: 'call_agent_schema',
        summary: 'Schéma généré — 5 composants, 3 nets, moteur: Circuit-Synth.' }
SSE → { type: 'pcb_state',   state: { pcb_status: 'SCHEMA_DONE',
        kicad_sch_content: '...' }}
        ← Front: KiCanvas tab Schematic s'affiche automatiquement
```

### PCBStatus

```
INITIAL  →  SCHEMA_DONE
```

### Validations réalisées ✅

```
✅ KiCanvas affiche LM7805 + nets (VIN, VOUT, GND)
✅ Composants à l'intérieur du cadre KiCad (margin_side=38mm)
✅ Labels VIN/VOUT/GND visibles et lisibles
✅ Bloc titre masqué automatiquement (zoomToComponents())
✅ Testé sur LM7805 / NE555 / ESP32

— Sprint "Schéma Pro" (2026-04-28) —
✅ Symboles power KiCad standards :
   - power:GND (triangle) sur tous les nets GND/VSS/AGND/DGND/PGND
   - power:VCC (flèche + cercle) sur VCC/VDD/VBUS/+5V/+3V3/+3.3V/+12V
✅ Helper _is_power_net(name) — détection automatique des rails power
✅ Title block rempli :
   - title : "Cirqix — {nom du composant principal}"
   - date  : ISO YYYY-MM-DD
   - rev   : "1.0"
   - company : "Cirqix.ai"
✅ Net-labels texte conservés pour les nets non-power (VIN, VOUT, GPIO2…)
✅ 21 tests pytest passent (TDD : RED → GREEN)
✅ Vérifié visuellement sur LM7805 / NE555 / ESP32 (Chrome DevTools)
```

---

## STEP 3 — Footprint Agent

**Statut : ⚠️ Stub — LCSC non implémenté**

### Orchestrateur

```
ITERATION 3

Orchestrator reçoit :
  tool_result = { pcb_status: 'SCHEMA_DONE', components: [...] }

Orchestrator décide :
  → "J'ai le schéma. Je cherche les footprints LCSC pour JLCPCB."
  → appelle call_agent_footprint pour chaque composant
     (ou 1 appel avec tous les composants)

SSE → { type: 'iteration',  count: 3 }
SSE → { type: 'step',       step: 'FOOTPRINT' }
SSE → { type: 'tool_call',  tool: 'call_agent_footprint',
        input: { part_number: 'LM7805', package: 'TO-220' }}
```

### Outil (Tool)

```
Nom    : call_agent_footprint
Fichier: packages/agents/src/tools.ts  ⚠️ Stub

Input tool :
{
  "part_number": "LM7805",
  "package": "TO-220"
}
```

### Agent IA

```
Modèle  : claude-haiku-4-5-20251001  ← Haiku 4.5
Coût    : ~0.003€ par composant       ← 5 composants → ~0.015€
Rôle    : cascade 8 étapes → trouver footprint + LCSC part number
Appel   : findFootprintCascade(partNumber, package)  ← À CRÉER
```

### Engine

```
Cascade 8 étapes (dans l'ordre) :
  1. LCSC API          → recherche par MPN/description
  2. KiCad lib match   → pcbnew symbol library scan
  3. SnapMagic         → footprints commerciaux
  4. Octopart          → marketplace électronique
  5. pgvector RAG      → embeddings footprints existants (Supabase)
  6. GitHub search     → snippets open-source
  7. Haiku AI gen      → génère footprint depuis datasheet
  8. Manuel            → ask_user si tout échoue
```

### Output — `footprints.json`

```json
{
  "footprints": {
    "U1": { "kicad": "Package_TO_SOT_THT:TO-220-3_Vertical",
            "lcsc": "C14353", "available_jlc": true },
    "C1": { "kicad": "Capacitor_SMD:C_0603_1608Metric",
            "lcsc": "C1525",  "available_jlc": true },
    "C2": { "kicad": "Capacitor_SMD:C_0603_1608Metric",
            "lcsc": "C1525",  "available_jlc": true },
    "J1": { "kicad": "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
            "lcsc": "C358690","available_jlc": true },
    "J2": { "kicad": "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
            "lcsc": "C358690","available_jlc": true }
  }
}
```

### PCBStatus

```
SCHEMA_DONE  →  SCHEMA_DONE  (pas de changement — footprints = enrichissement)
```

---

## STEP 4 — Placement Agent

**Statut : ✅ Validé**

### Orchestrateur

```
ITERATION 4

Orchestrator reçoit :
  tool_result = { footprints: {...} }
  pcb_status  = SCHEMA_DONE

Orchestrator décide :
  → "Footprints trouvés. Je place les composants sur le PCB physique."
  → appelle call_agent_placement

SSE → { type: 'iteration',  count: 4 }
SSE → { type: 'step',       step: 'PLACEMENT' }
SSE → { type: 'tool_call',  tool: 'call_agent_placement',
        input: {
          schema_json: '{...}',
          board_width_mm: 50,
          board_height_mm: 50
        }}
```

### Outil (Tool)

```
Nom    : call_agent_placement
Fichier: packages/agents/src/tools.ts  ✅ Existe

Input tool :
{
  "schema_json": "{ composants + nets }",
  "board_width_mm": 50,
  "board_height_mm": 50
}
```

### Agent IA

```
Modèle  : claude-haiku-4-5-20251001  ← Haiku 4.5
Coût    : ~0.004€ par appel
Rôle    : calculer coordonnées (x, y, rotation) par blocs fonctionnels
Appel   : runPCBEngine(schema, boardW, boardH, projectId)  ✅ Implémenté
```

### Engine

```
Nom     : pcbnew Placement
Techno  : Python (pcbnew API)
Endpoint: POST /place/auto  ✅ Implémenté
Fichier : services/kicad/routers/placement.py
          services/kicad/tools/placement.py

Input engine :
{
  "project_id": "proj-abc123",
  "board_width_mm": 50,
  "board_height_mm": 50,
  "components": [
    { "ref": "U1", "footprint": "TO-220-3_Vertical", "x": 15, "y": 20, "rot": 0 },
    ...
  ]
}

Output engine :
{
  "success": true,
  "kicad_pcb_content": "(kicad_pcb ...)",
  "placements": [
    { "ref": "U1", "x": 15.0, "y": 20.0, "rot": 0 },
    { "ref": "C1", "x": 25.0, "y": 10.0, "rot": 0 },
    { "ref": "C2", "x": 25.0, "y": 30.0, "rot": 0 },
    { "ref": "J1", "x": 5.0,  "y": 30.0, "rot": 0 },
    { "ref": "J2", "x": 45.0, "y": 30.0, "rot": 0 }
  ]
}
```

### Output — `placement.json`

```json
{
  "placements": [
    { "ref": "U1", "x": 15, "y": 20, "rot": 0 },
    { "ref": "C1", "x": 25, "y": 10, "rot": 0 },
    { "ref": "C2", "x": 25, "y": 30, "rot": 0 },
    { "ref": "J1", "x": 5,  "y": 30, "rot": 0 },
    { "ref": "J2", "x": 45, "y": 30, "rot": 0 }
  ],
  "kicad_pcb_content": "(kicad_pcb ...)"
}
```

### SSE events produits

```
SSE → { type: 'tool_result', tool: 'call_agent_placement',
        summary: 'Placement terminé — PCB 50×50mm, 5 composants' }
SSE → { type: 'pcb_state',   state: { pcb_status: 'PLACEMENT_DONE',
        kicad_pcb_content: '...' }}
        ← Front: KiCanvas tab PCB Layout s'affiche
```

### PCBStatus

```
SCHEMA_DONE  →  PLACEMENT_DONE
```

### Validations réalisées ✅

```
✅ pcbnew place correctement les composants
✅ .kicad_pcb généré avec footprints aux bonnes coordonnées
✅ POST /place/auto HTTP 200
✅ CI KiCad Docker Build vert
```

---

## STEP 5 — Routing Agent

**Statut : ✅ Validé (Phase 3)**

### Orchestrateur

```
ITERATION 5

Orchestrator reçoit :
  tool_result = { pcb_status: 'PLACEMENT_DONE', kicad_pcb_content: '...' }

Orchestrator décide :
  → "Composants placés. Je lance le routage automatique Freerouting."
  → appelle call_agent_routing

SSE → { type: 'iteration',  count: 5 }
SSE → { type: 'step',       step: 'ROUTING' }
SSE → { type: 'tool_call',  tool: 'call_agent_routing',
        input: {
          pcb_base64: "base64(kicad_pcb_content)",
          layers: 2
        }}
```

### Outil (Tool)

```
Nom    : call_agent_routing
Fichier: packages/agents/src/tools.ts  ⚠️ Stub actuel

Input tool :
{
  "pcb_base64": "base64 du .kicad_pcb placé",
  "layers": 2,
  "via_costs": 50
}
```

### Agent IA

```
Modèle  : claude-haiku-4-5-20251001  ← Haiku 4.5
Coût    : ~0.004€ par appel
Rôle    : déclencher Freerouting + vérifier % routé
Appel   : POST /route/auto  ← À CRÉER
```

### Engine

```
Nom     : Freerouting
Techno  : Java JAR headless (openjdk-17)
Endpoint: POST /route/auto  🔲 À créer
Fichier : services/kicad/routers/routing.py   🔲 À créer
          services/kicad/tools/routing.py     🔲 À créer

Pipeline engine :
  .kicad_pcb (placé)
      ↓ pcbnew.ExportSpecctraDSN(pcb_path, dsn_path)
  circuit.dsn
      ↓ java -jar freerouting.jar -de circuit.dsn -do circuit.ses -mp 8 -l 2
  circuit.ses
      ↓ pcbnew.ImportSpecctraSES(pcb_path, ses_path)
  .kicad_pcb (routé avec pistes F.Cu + B.Cu + vias)

Input engine :
{
  "pcb_base64": "...",
  "layer_count": 2,
  "via_costs": 50,
  "timeout_s": 60
}

Output engine :
{
  "success": true,
  "pcb_base64": "base64 du .kicad_pcb routé",
  "stats": {
    "track_count": 12,
    "via_count": 3,
    "routed_percent": 100,
    "duration_ms": 4200
  }
}
```

### Output — `routing.json`

```json
{
  "stats": {
    "track_count": 12,
    "via_count": 3,
    "routed_percent": 100,
    "duration_ms": 4200
  },
  "kicad_pcb_content": "(kicad_pcb avec pistes...)"
}
```

### SSE events produits

```
SSE → { type: 'tool_result', tool: 'call_agent_routing',
        summary: 'Routage 100% — 12 pistes, 3 vias, 4.2s' }
SSE → { type: 'pcb_state',   state: { pcb_status: 'ROUTING_DONE',
        kicad_pcb_content: '...' }}
        ← Front: KiCanvas tab Routing — pistes cuivre visibles
```

### PCBStatus

```
PLACEMENT_DONE  →  ROUTING_DONE
```

### Critère de validation

```
- POST /route/auto (test-lm7805.kicad_pcb placé en base64) → HTTP 200
- stats.routed_percent = 100
- stats.track_count >= 1
- KiCanvas onglet PCB → pistes cuivre F.Cu visibles
- pytest services/kicad/tests/test_routing.py → 3 tests passent
```

### Fichiers à créer

```
services/kicad/routers/routing.py      (FastAPI endpoint)
services/kicad/tools/routing.py        (pipeline Freerouting)
services/kicad/tests/test_routing.py   (3 tests minimum)
services/kicad/main.py                 (mount /route)
```

---

## STEP 6 — DRC Agent

**Statut : ✅ Validé (Phase 3)**

### Orchestrateur

```
ITERATION 6

Orchestrator reçoit :
  tool_result = { pcb_status: 'ROUTING_DONE', kicad_pcb_content: '...' }

Orchestrator décide :
  → "Routage terminé. Je vérifie les règles de design (DRC)."
  → appelle call_agent_drc

SSE → { type: 'iteration',  count: 6 }
SSE → { type: 'step',       step: 'DRC' }
SSE → { type: 'tool_call',  tool: 'call_agent_drc',
        input: {
          pcb_base64: "base64(kicad_pcb_content)",
          auto_fix: true
        }}
```

### Outil (Tool)

```
Nom    : call_agent_drc
Fichier: packages/agents/src/tools.ts  ⚠️ Stub

Input tool :
{
  "pcb_base64": "base64 du .kicad_pcb routé",
  "auto_fix": true
}
```

### Agent IA

```
Modèle  : claude-haiku-4-5-20251001  ← Haiku 4.5
Coût    : ~0.003€ par appel
Rôle    : analyser violations → décider action (fix placement, fix routing, relaxer rules)
Appel   : POST /drc  ← À créer
```

### Engine

```
Nom     : pcbnew DRC
Techno  : Python (pcbnew API — DRC runner natif)
Endpoint: POST /drc  🔲 À créer
Fichier : services/kicad/routers/drc.py  🔲 À créer
          services/kicad/tools/drc.py    🔲 À créer

Boucle DRC (dans orchestrateur) :
  DRC run → violations > 0 ?
    ├─ NON  → ROUTING_DONE → PCBStatus = DRC_CLEAN → STEP 7
    └─ OUI  → Agent choisit :
               ├─ reroute  → loop back STEP 5  (iter++)
               ├─ replace  → loop back STEP 4  (iter++)
               └─ si iter > 3 → ask_user

Output engine :
{
  "violations": [
    { "type": "clearance", "loc": [12.5, 30.1],
      "actual_mm": 0.15, "required_mm": 0.2 }
  ],
  "stats": { "checked": 24, "errors": 1, "warnings": 3 }
}
```

### Output — `drc.json`

```json
{
  "drc_clean": true,
  "violations": [],
  "warnings": [
    { "type": "track_width_info",
      "message": "Tracks set to 0.2mm (JLCPCB recommended). Ground plane on B.Cu." }
  ]
}
```

### PCBStatus

```
ROUTING_DONE  →  DRC_CLEAN   (si 0 violations)
ROUTING_DONE  →  ROUTING_DONE (si violations → loop back STEP 5)
```

---

## STEP 7 — Export

**Statut : ✅ Validé (Phase 4.3)**

### Orchestrateur

```
ITERATION 7

Orchestrator reçoit :
  tool_result = { drc_clean: true, pcb_status: 'DRC_CLEAN' }

Orchestrator décide :
  → "DRC clean. Je génère les fichiers de fabrication JLCPCB."
  → appelle call_agent_export

SSE → { type: 'iteration',  count: 7 }
SSE → { type: 'step',       step: 'EXPORT' }
SSE → { type: 'tool_call',  tool: 'call_agent_export',
        input: { pcb_base64: "base64(kicad_pcb_content)" }}
```

### Outil (Tool)

```
Nom    : call_agent_export
Fichier: packages/agents/src/tools.ts  ⚠️ Stub

Input tool :
{
  "pcb_base64": "base64 du .kicad_pcb DRC-clean"
}
```

### Agent IA

```
Modèle  : AUCUN  ← Export 100% déterministe (pas de LLM)
Coût    : 0€ en tokens Claude
Rôle    : L'orchestrateur appelle le tool stub directement
          → pcbnew Plotter génère les Gerbers sans décision IA
```

### Engine

```
Nom     : pcbnew Plotter
Techno  : Python (pcbnew API — Gerber plotter)
Endpoint: POST /export  🔲 À créer

Outputs :
  Gerbers (7 fichiers) :
    ├── F.Cu.gtl      (front copper)
    ├── B.Cu.gbl      (back copper)
    ├── F.SilkS.gto   (front silkscreen)
    ├── B.SilkS.gbo   (back silkscreen)
    ├── F.Mask.gts    (front solder mask)
    ├── B.Mask.gbs    (back solder mask)
    └── Edge.Cuts.gm1 (board outline)
  BOM :
    └── bom.csv       (ref, value, lcsc)
  3D :
    └── board.step    (via occt-import-js)
```

### Output — `export.json`

```json
{
  "gerber_layers": 7,
  "gerbers_zip_base64": "base64(gerbers.zip)",
  "bom_csv": "ref,value,lcsc\nU1,LM7805,C14353\nC1,330nF,C1525\n...",
  "step_base64": "base64(board.step)",
  "quote_usd": 12.50,
  "lead_time_days": 7
}
```

### SSE events produits

```
SSE → { type: 'tool_result', tool: 'call_agent_export',
        summary: '7 Gerbers + BOM + STEP. Devis: $12.50 (7 jours)' }
SSE → { type: 'text', delta: "✅ PCB prêt ! Tapez OUI JE CONFIRME pour commander." }
SSE → { type: 'done', fullText: '...' }
```

### PCBStatus

```
DRC_CLEAN  →  PCB_LIVRÉ  (après "OUI JE CONFIRME")
```

---

## Récapitulatif — Tous les outils + modèles

| Tool | Modèle IA | Engine | Endpoint | Status |
|------|-----------|--------|----------|--------|
| **Orchestrateur** | `claude-sonnet-4-6` | — | — | ✅ |
| `call_agent_design` | `claude-haiku-4-5-20251001` | — (LLM only) | — | ✅ |
| `call_agent_schema` | `claude-haiku-4-5-20251001` | kicad_gen.py (circuit_synth) → `.kicad_sch` seulement | `POST /circuit-synth/generate` | ✅ |
| `call_agent_erc` | `claude-haiku-4-5-20251001` | kicad-cli sch erc, auto-fix | `POST /erc` | ✅ |
| `call_agent_footprint` | `claude-haiku-4-5-20251001` | pgvector + cascade 4 étapes | `POST /footprint` | ⚠️ Partiel |
| `call_agent_gen_pcb` | `claude-haiku-4-5-20251001` | kicad_gen.py → `.kicad_pcb` depuis cache | `POST /circuit-synth/generate` | ✅ |
| `call_agent_placement` | `claude-haiku-4-5-20251001` | pcbnew | `POST /place/auto` | ✅ |
| `call_agent_routing` | `claude-haiku-4-5-20251001` | Freerouting | `POST /route/auto` | ✅ |
| `call_agent_drc` | `claude-haiku-4-5-20251001` | kicad-cli DRC natif | `POST /drc/auto` | ✅ |
| `call_agent_export` | **AUCUN** (déterministe) | kicad-cli plotter | `POST /export/all` | ✅ |
| `call_agent_simulation` | `claude-haiku-4-5-20251001` | ngspice batch | `POST /simulate/auto` | ✅ |
| `ask_user` | `claude-sonnet-4-6` (répond) | — | — | ✅ |

### Budget estimé par PCB

> ⚡ **Optimisation tokens 2026-05-26** : blobs KiCad (`kicad_sch_content`, `kicad_pcb_content`, `gerber_zip_b64`) strippés des `tool_result` Sonnet → économie ~70% tokens input orchestrateur.

| Agent | Modèle | Tokens (~) | Coût (~) |
|-------|--------|-----------|---------|
| Orchestrateur (7 iter) | Sonnet 4.6 | 5 000 *(était 15 000 avant opt.)* | ~0.025€ |
| Design Agent | Haiku 4.5 | 1 000 | ~0.004€ |
| Schematic Agent | Haiku 4.5 | 1 700 | ~0.001€ |
| Footprint Agent (5×) | Haiku 4.5 | 750 | ~0.015€ |
| Placement Agent | Haiku 4.5 | 500 | ~0.004€ |
| Routing Agent | Haiku 4.5 | 500 | ~0.004€ |
| DRC Agent | Haiku 4.5 | 500 | ~0.003€ |
| Simulation Agent | Haiku 4.5 | 600 | ~0.004€ |
| Export | AUCUN | 0 | 0€ |
| **TOTAL** | | **~10 550** | **~0.060€** |

✅ Budget 0.12€/PCB largement respecté.

---

## État final — Phase 4 (2026-05-29)

**Pipeline complet validé :** Design ✅ → Schema ✅ → ERC ✅ → Footprint ⚠️ → KiCad ✅ → Placement ✅ → Routing ✅ → DRC ✅ → Export ✅ → JLCPCB ✅

**Phases terminées :** 0 ✓ 1 ✓ 2 ✓ 3 ✓ 4.1 ✓ 4.2 ✓ 4.3 ✓ 4.x ✓

### Changements session 2026-05-26 — Sprint 1 : Nommage + Tokens

| Changement | Détail |
|---|---|
| `circuit-synth-engine.ts` → `schematic-engine.ts` | évite confusion pip package |
| `schematic_gen.py` → `kicad_gen.py` | gère sch + pcb, pas que le schéma |
| circuit_synth pip installé Docker | `pip install ./circuit_synth`, PYTHONPATH fix |
| Strip blobs Sonnet context | kicad_sch/pcb_content hors tool_result → -70% tokens |

### Changements session 2026-05-26 — Sprint 2 : Pipeline 8 agents experts

| Changement | Détail |
|---|---|
| `call_agent_gen_pcb` créé (NOUVEAU) | Sépare génération `.kicad_pcb` de la génération `.kicad_sch` |
| `call_agent_erc` obligatoire | Intégré entre schéma et footprint dans le pipeline |
| `call_agent_footprint` mis à jour | Met à jour `_pcbStateCache` avec footprint résolu par composant |
| `prompts.ts` réécrit intégralement | Orchestrateur = "Chef de Projet PCB Senior 15 ans d'expérience", règles absolues, pipeline ① à ⑧ |
| `tools.ts` refactorisé | 8 descriptions expertes par agent (Ingénieur Schéma / ERC / Composants / Layout / Placement / Routage / Qualité / Fabrication) |
| `orchestrator.ts` mis à jour | `stepMap` : `call_agent_gen_pcb → 'KICAD'`, `pcbStateTools` étendu |
| Bug `_resolve_pin` Python 3 corrigé | `UnboundLocalError` : variable `first_err` hors scope après `except` — capturée dans `_first_err` |
| Stratégie connecteurs Path B | ESP32-WROOM → `Conn_02x19_Odd_Even`, Arduino → `Conn_02x15_Odd_Even`, BME280 → `Conn_01x06` |
| Validation Python Path A | Rejet si `circuit_synth_code` ne contient pas `cs_circuit` / `circuit_synth` imports |
| Orchestrateur : règle clé | `NE JAMAIS prescrire de composants à call_agent_schema` — l'Agent Schéma décide seul |

### Prochaine étape

**→ Phase 4.4 — Paiement Lemon Squeezy**
- `apps/web/src/app/api/webhooks/lemon-squeezy/route.ts` — HMAC + idempotence
- `apps/web/src/app/(dashboard)/dashboard/billing/page.tsx` — plans + top-ups
- Supabase : créditer après `subscription_created` / `order_created`
