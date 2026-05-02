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

**Deux chemins selon disponibilité FastAPI — un seul retourné :**

```
SchemaJson
    │
    ├── FastAPI disponible (KICAD_SERVICE_URL défini) ?
    │       │
    │       ▼  OUI
    │   POST /circuit-synth/generate
    │   → Python circuit_synth lib → _grid_position() pour placement
    │   → .kicad_sch + .kicad_pcb natifs KiCad 7
    │
    └── NON (fallback inline TS — service  down ou non déployé)
            │
            ▼
        generateSchematic() + generatePCB() (circuit-synth-engine.ts)
        → S-expressions KiCad 7 écrites manuellement en TypeScript
        → autoLayout() pour placement grille
        → .kicad_sch + .kicad_pcb (qualité moindre mais toujours disponible)
```

**Pourquoi deux implémentations :** résilience — si le service FastAPI n'est pas accessible (`KICAD_SERVICE_URL` non défini, ex: développement local sans Docker), l'agent ne bloque pas. Le TS fallback génère les fichiers directement en mémoire. Circuit-Synth n'a pas besoin de KiCad installé ni de Docker pour générer les S-expressions — Docker sert uniquement à déployer le service FastAPI. Jamais les deux en même temps — un seul chemin retourne les fichiers.

**Output toujours :**
- `.kicad_sch` — schéma électronique (symboles, fils, netliste, power flags, title block). La netlist est embarquée sous forme de fils + labels de nets.
- `.kicad_pcb` — board avec footprints. La netlist est embarquée sous forme de ratsnest (connexions attendues entre pads).

Les deux fichiers ont un **placement grille naïve** — positions mathématiques régulières, sans logique électrique :
- `.kicad_sch` → symboles placés en grille, fils tracés automatiquement
- `.kicad_pcb` → footprints placés en grille, pas de routage

"Bon placement" = Phase 3 (pcbnew).

**Placement Phase 2 — grille naïve uniquement :**

Phase 2 utilise exclusivement Python Circuit-Synth ou TS fallback — les deux génèrent `.kicad_sch` + `.kicad_pcb` avec une grille naïve, sans logique électrique. Il n'existe pas d'alternative en Phase 2.

- Python disponible → `_grid_position()` calcule les positions → génère `.kicad_sch` + `.kicad_pcb` natifs KiCad 7
- Python indisponible → `autoLayout()` (TS) calcule les positions → `generateSchematic()` + `generatePCB()` génèrent `.kicad_sch` + `.kicad_pcb` en S-expressions TypeScript

**Placement grille naïve — même problème sur les deux fichiers :**
- `.kicad_sch` → symboles placés en grille régulière, pas de regroupement par fonction, fils qui se croisent, schéma difficile à lire. Un vrai EDA organiserait les blocs logiquement (alimentation en haut, signal au centre, sortie en bas).
- `.kicad_pcb` → footprints placés en grille, sans tenir compte des connexions électriques ni des tailles réelles.

Phase 2 = lisible par KiCanvas, pas optimisé pour la lisibilité humaine.

Le schéma Phase 2 est suffisant pour KiCanvas et pour extraire la netlist.
  Réorganiser le .kicad_sch n'est pas dans le scope Phase 3 — c'est une
  amélioration cosmétique, pas un blocage pour fabriquer le PCB.

**Pourquoi pas pcbnew en Phase 2 :** pcbnew est une bibliothèque Python KiCad, pas disponible en TypeScript. Le TS ne peut qu'écrire des S-expressions manuellement (grille naïve), pas appeler les API internes de KiCad.

**Phase 3 — placement réel via pcbnew :**

`pcbnew` = bibliothèque Python officielle de KiCad. Elle permet de lire, modifier et écrire des fichiers `.kicad_pcb` programmatiquement — déplacer des footprints, tracer des pistes, lancer le DRC, exporter des Gerbers. Tout ce qu'on fait manuellement dans KiCad, `pcbnew` le fait en Python.

1. Circuit-Synth génère le `.kicad_pcb` (avec grille naïve)
2. `call_agent_placement` appelle `POST /place/auto` (FastAPI) — câblage à faire
3. pcbnew lit ce `.kicad_pcb` → `pcbnew.SetPosition()` écrase les coordonnées par des positions réelles
4. Retourne le **même** `.kicad_pcb` modifié — pas un nouveau fichier

#### Engine Router


```

---

### État Phase 2 vs Phase 3

| Tool | Phase 2 (actuel) | Phase 3 (à implémenter) |
|------|-----------------|------------------------|
| `call_agent_spec` | ✅ Haiku 4.5 → `DesignJson` | — (déjà opérationnel) |
| `call_agent_schema` | ✅ Haiku 4.5 → Circuit-Synth | — (déjà opérationnel) |
| `call_agent_placement` | ⚠️ Grille naïve — Python `_grid_position()` ou TS `autoLayout()` selon disponibilité FastAPI. Pas de logique électrique, pas de solveur de contraintes. Impossible d'améliorer en Phase 2 — pcbnew obligatoire. | `POST /place/auto` → pcbnew |
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
