# Layrix — Journal de Décisions

> Chaque décision prise ensemble est documentée ici : ce qu'on a décidé, pourquoi, et ce qu'on a écarté.
> Mis à jour au fil des conversations.

---

## Format

```
### [DATE] — [Sujet de la décision]
**Décision :** ce qu'on a choisi
**Pourquoi :** la raison technique ou business
**Écarté :** ce qu'on n'a pas retenu et pourquoi
```



## Référence technique — État actuel du système

> Section stable : mise à jour uniquement quand l'architecture change.

---

### Pipeline complet

```
Utilisateur (texte naturel)
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  ORCHESTRATEUR — Claude Sonnet 4.6                  │
│  Fichier : packages/agents/src/orchestrator.ts      │
│  Max 15 itérations · SSE streaming · MAX_TOKENS 4096│
└─────────────────────────────────────────────────────┘
        │
        │  tool_use (Anthropic SDK)
        ▼
INITIAL
  → call_agent_spec        → [contexte DesignJson]
  → call_agent_schema      → SCHEMA_DONE + .kicad_sch + .kicad_pcb
  → call_agent_placement   → PLACEMENT_DONE
  → call_agent_routing     → ROUTING_DONE
  → call_agent_drc         → DRC_CLEAN
  → call_agent_export      → PCB_LIVRÉ → JLCPCB (après "OUI JE CONFIRME")
```

---

### Agents — Modèles et rôles

| Agent | Tool name | Modèle | Rôle | Output |
|-------|-----------|--------|------|--------|
| Spec Parser | `call_agent_spec` | Haiku 4.5 | Parse la description → contexte structuré | `DesignJson` |
| Schematic | `call_agent_schema` | Haiku 4.5 | Génère le schéma électronique + netlist | `SchemaJson` + `.kicad_sch` + `.kicad_pcb` |
| Footprint | `call_agent_footprint` | Haiku 4.5 | Trouve le footprint KiCad (LCSC/SnapMagic/Octopart) | `kicad_mod` |
| Placement | `call_agent_placement` | — | Positionne les composants X/Y/rotation | `.kicad_pcb` placé |
| Routing | `call_agent_routing` | — | Freerouting + ground planes | `.kicad_pcb` routé |
| DRC | `call_agent_drc` | — | Design Rule Check + corrections | rapport violations |
| Export | `call_agent_export` | — | Gerbers + BOM CSV + CPL + devis JLCPCB | `.zip` Gerbers |
| Ask | `ask_user` | — | Pose une question à l'utilisateur | — |

**Orchestrateur :** Claude Sonnet 4.6 — coordonne, décide l'ordre, écrit les réponses chat.
**Agents spécialisés :** Claude Haiku 4.5 — exécutent les tâches lourdes (génération JSON).

---

### Tools — Signatures complètes

```typescript
// 1. Spec Parser — TOUJOURS EN PREMIER
call_agent_spec({
  user_description: string   // description du circuit à concevoir
})
→ { design: DesignJson, pcb_status: 'INITIAL' }

// 2. Schematic Generator
call_agent_schema({
  user_description: string,
  complexity: 'simple' | 'medium' | 'complex',
  schema_json?: string       // JSON sérialisé SchemaJson — imposé par l'orchestrateur
})
→ { schema: SchemaJson, kicad_sch_url, kicad_pcb_url, pcb_status: 'SCHEMA_DONE' }

// 3. Footprint Finder
call_agent_footprint({
  part_number: string,       // référence LCSC, SnapMagic, ou description
  package?: string           // SOT-23, TSSOP-16, 0402…
})
→ { footprint_name, source: 'lcsc' | 'snapmagic' | 'octopart' | 'ai_generated' }

// 4. Placement
call_agent_placement({
  schema_json: string,       // SchemaJson sérialisé
  board_width_mm?: number,   // défaut: 50
  board_height_mm?: number   // défaut: 50
})
→ { placements: [{ref, x_mm, y_mm, rotation, side}], pcb_status: 'PLACEMENT_DONE' }

// 5. Routing
call_agent_routing({
  placement_json: string,    // résultat call_agent_placement
  schema_json: string,
  layers?: 2 | 4             // défaut: 2
})
→ { pcb_status: 'ROUTING_DONE' }

// 6. DRC
call_agent_drc({
  pcb_state: string,         // PCBState sérialisé
  auto_fix?: boolean         // défaut: true
})
→ { violations: DRCViolation[], pcb_status: 'DRC_CLEAN' }

// 7. Export
call_agent_export({
  pcb_state: string          // PCBState DRC-clean sérialisé
})
→ { gerber_url, bom_url, cpl_url, jlcpcb_quote, pcb_status: 'PCB_LIVRÉ' }

// 8. Ask User
ask_user({
  question: string,
  context?: string
})
→ (attend réponse utilisateur — interrompt le pipeline)
```

---

### Engines — Moteurs de génération KiCad

#### Circuit-Synth (moteur unique, Phase 2+)

```
Fichier TS  : packages/agents/src/engines/circuit-synth-engine.ts
Fichier Py  : services/kicad/routers/circuit_synth.py (1044 lignes)
Router      : POST /circuit-synth/generate
```

**Deux chemins selon disponibilité FastAPI :**

```
SchemaJson
    │
    ├── FastAPI disponible (KICAD_SERVICE_URL défini) ?
    │       │
    │       ▼  YES
    │   POST /circuit-synth/generate
    │   → Python circuit_synth lib → .kicad_sch + .kicad_pcb natifs KiCad 7
    │
    └── NO (fallback inline TS)
            │
            ▼
        generateSchematic() + generatePCB() — S-expression TypeScript
        → .kicad_sch + .kicad_pcb (moins fidèles mais fonctionnels pour KiCanvas)
```

**Output toujours :**
- `.kicad_sch` — schéma électronique (symboles, fils, netliste, power flags, title block). La netlist est embarquée sous forme de fils + labels de nets.
- `.kicad_pcb` — board avec footprints. La netlist est embarquée sous forme de ratsnest (connexions attendues entre pads).

**Placement Phase 2 vs Phase 3 — même fichier `.kicad_pcb` :**

Phase 2 (actuel) :
1. `autoLayout()` prend `SchemaJson` en mémoire → calcule positions X/Y grille mathématique
2. Pas de lecture de fichier — tout en mémoire
3. `generatePCB()` écrit les positions en S-expressions KiCad 7 (string TS)
4. Résultat → `.kicad_pcb` créé

Phase 3 (à faire) :
1. Circuit-Synth génère le `.kicad_pcb` (avec grille naïve)
2. `POST /place/auto` → pcbnew lit ce `.kicad_pcb`
3. `pcbnew.SetPosition()` écrase les coordonnées par des positions réelles
4. Retourne le **même** `.kicad_pcb` modifié — pas un nouveau fichier

Pourquoi pas pcbnew maintenant : `call_agent_placement` appelle `runPCBEngine()` (TS) au lieu de `POST /place/auto` (FastAPI). Câblage non fait — travail Phase 3.

#### Engine Router

```
Fichier : packages/agents/src/engines/engine-router.ts
```

```typescript
selectEngine() → 'circuit-synth'  // TSCircuit retiré définitivement
runPCBEngine(schema, boardW, boardH, projectId) → PCBEngineResult
```

---

### État Phase 2 vs Phase 3

| Tool | Phase 2 (actuel) | Phase 3 (à implémenter) |
|------|-----------------|------------------------|
| `call_agent_spec` | ✅ Haiku 4.5 → `DesignJson` | — (déjà opérationnel) |
| `call_agent_schema` | ✅ Haiku 4.5 → Circuit-Synth | — (déjà opérationnel) |
| `call_agent_placement` | ⚠️ Stub grille TS `autoLayout()` | `POST /place/auto` → pcbnew |
| `call_agent_routing` | ⚠️ Stub Circuit-Synth | `POST /route` → Freerouting |
| `call_agent_drc` | ⚠️ Stub (0 violations toujours) | `POST /drc` → pcbnew DRC natif |
| `call_agent_export` | ⚠️ Stub (pas de vrais Gerbers) | `POST /export` → Gerbers réels |
| `call_agent_footprint` | ⚠️ Stub LCSC | Cascade 8 étapes (Phase 3+) |

---

---

### Objectif de la génération de netlist

La netlist est le **pont entre la description texte et le fichier KiCad**. Son objectif est de produire un `SchemaJson` validé que Circuit-Synth peut convertir directement en fichiers natifs.

**Ce que la netlist doit contenir :**

```
SchemaJson {
  components: [                     ← liste de chaque composant
    {
      ref:       "U1"               ← référence KiCad (R, C, U, LED, J, Q, D)
      value:     "NE555P"           ← valeur affichée sur le schéma
      footprint: "DIP-8"            ← empreinte physique du composant
      symbol?:   "Timer:NE555P"     ← ID symbole KiCad (optionnel, résolu par Circuit-Synth)
      lcsc?:     "C46555"           ← référence LCSC pour commande JLCPCB
    }
  ]
  nets: ["GND", "VCC", "OUT"]       ← tous les noms de nets présents
  connections: [                    ← connectivité : quel pin sur quel net
    {
      name: "VCC",
      pins: [
        { ref: "U1", pin: 8 },      ← pin numéroté (passifs) OU nom (ICs)
        { ref: "J1", pin: 1 }
      ]
    }
  ]
}
```

**Pourquoi la netlist est critique :**
- Sans `connections` correctes → fils mal tracés dans `.kicad_sch`, DRC échoue
- Sans `symbol` valide → Circuit-Synth ne peut pas placer le bon symbole KiCad
- Sans `lcsc` → BOM incomplet, commande JLCPCB impossible
- Erreur de `pin` (mauvais numéro ou nom) → court-circuit dans le schéma

**Validation en deux temps :**
1. `validateAndCorrectSchema()` côté TS — corrige les symboles via `POST /circuit-synth/validate-symbols`
2. `_safe_symbol()` côté Python — fallback sur `Device:R`, `Device:C`, etc. si symbole inconnu

---

### 2026-05-02 — Pourquoi Circuit-Synth plutôt que SKiDL

**Décision :** Utiliser Circuit-Synth (Python custom) pour générer les fichiers KiCad natifs, pas SKiDL.

**Ce qu'est SKiDL :** Bibliothèque Python qui permet de décrire un circuit en code Python (`r1 = Part('Device', 'R', ...)`), puis de générer une netlist SPICE ou KiCad. L'IA génèrerait du **code Python** que le serveur exécuterait.

**Pourquoi Circuit-Synth :**

| Critère | Circuit-Synth | SKiDL |
|---------|--------------|-------|
| Input LLM | JSON (`SchemaJson`) | Code Python généré par le LLM |
| Sécurité | ✅ données JSON — pas d'exécution de code | ❌ exécution de code Python arbitraire sur le serveur |
| Validation | ✅ Zod + `validateAndCorrectSchema()` avant génération | ❌ erreur Python découverte à l'exécution |
| Output | ✅ `.kicad_sch` + `.kicad_pcb` natifs en un appel | ❌ netlist intermédiaire → conversion supplémentaire vers KiCad |
| Fallback | ✅ S-expression TypeScript inline si FastAPI indisponible | ❌ aucun fallback sans Python |
| Fiabilité LLM | ✅ JSON simple à générer et corriger | ❌ le LLM fait des fautes de syntaxe Python fréquentes |
| Symboles KiCad | ✅ mapping intégré `_SYMBOL_RULES` + `_safe_symbol()` | ❌ mapping à implémenter séparément |

**Pourquoi pas SKiDL — point clé :** faire générer du code Python exécutable par un LLM est un **risque de sécurité**. Un prompt injection pourrait injecter des commandes shell dans le code généré, exécutées directement sur le serveur. Avec JSON, on valide un schéma de données — pas du code.

**Écarté aussi :** écrire directement les S-expressions `.kicad_sch` par le LLM — format trop verbeux (plusieurs milliers de lignes), fragile (change entre versions KiCad 6 → 7 → 8).

**SKiDL ≠ Circuit-Synth — rôles différents, non interchangeables :
SKiDL génère des netlists. Circuit-Synth consomme une netlist et produit des fichiers KiCad. On ne peut pas remplacer l'un par l'autre.

**SKiDL ne peut pas s'insérer entre le LLM et Circuit-Synth :**

```
Option SKiDL :
LLM → code Python SKiDL → SKiDL → fichier .net → ??? → Circuit-Synth
                                                    ↑
                          Circuit-Synth ne lit pas .net
                          il attend SchemaJson
```

SKiDL produit un fichier `.net` (format KiCad XML ou SPICE). Circuit-Synth attend un `SchemaJson` — formats incompatibles. Il faudrait un convertisseur `.net → SchemaJson` entre les deux, couche supplémentaire sans valeur ajoutée. SKiDL remplacerait `call_agent_schema` (le générateur de netlist), pas Circuit-Synth — et on a écarté cette position pour les raisons de sécurité citées ci-dessus.

---

---

### Pourquoi TSCircuit a été retiré

**Raison technique :** TSCircuit génère du `circuit-json` (format JSON custom de tscircuit.io), pas du `.kicad_sch` / `.kicad_pcb` natif. Il faudrait un convertisseur `circuit-json → KiCad` — non officiel, perd des informations (symboles, annotations, design rules KiCad). Circuit-Synth produit directement des S-expressions KiCad 7 — format natif, lisible par KiCad et KiCanvas sans conversion.

**Raison projet :** TSCircuit déprécié depuis la v0.3.0 de Layrix. Dépendances supprimées : `circuit-json`, `circuit-json-to-gerber`, export `tscircuit-engine`.

---

## Template pour la prochaine décision

```
### [DATE] — [Sujet]

**Décision :**

**Pourquoi :**

**Écarté :**

**Fichiers concernés :**
```
