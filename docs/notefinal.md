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

### Pipeline complet (mis à jour 2026-05-30)

```
Utilisateur (texte naturel)
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  ORCHESTRATEUR — Claude Sonnet 4.6                  │
│  Fichier : packages/agents/src/orchestrator.ts      │
│  Max 15 itérations · SSE streaming · MAX_TOKENS 4096│
└─────────────────────────────────────────────────────┘
        │  tool_use (Anthropic SDK)
        ▼
① call_agent_schema    → SCHEMA_DONE
     Path A : Haiku → Python circuit_synth → Docker /schematic/execute → .kicad_sch
     Path B : Haiku → JSON → POST /schematic/generate :
       ① circuit_synth pip            → .kicad_sch
       ② kicad-tools Schematic class  → .kicad_sch
       ③ TypeScript S-expr inline     → .kicad_sch (si service down)
     Erreur  : status:'error' si les deux chemins échouent (jamais de faux schéma hardcodé)

② call_agent_erc       → ERC_CLEAN
     ① kicad-tools Schematic.validate()  — pur Python, toujours dispo
        auto-fix : off-grid, duplicate refs, labels déconnectés
     ② kicad-cli sch erc                 — ERC officiel KiCad (si dispo)
        auto-fix no_connect max 3×
     ③ skipped=true                      → TypeScript runErcFallback()

③ call_agent_footprint → (1 appel par ref dans unresolved_footprints)
     Cascade : KiCad libs → pgvector cache → LCSC/EasyEDA → Haiku IA (3 crédits)

④ call_agent_gen_pcb   → .kicad_pcb généré avec footprints résolus
     ① kicad-tools PCBFromSchematic(.kicad_sch) → vrais footprints + nets
     ② pcbnew direct : BOARD() + FootprintLoad() + SetNet() → .kicad_pcb natif
     ③ success=False → TypeScript runCircuitSynthEngine() S-expr inline

⑤ call_agent_placement → PLACEMENT_DONE
     POST /place/auto (kicad_pcb_b64)
     ① kicad-tools CMA-ES place_unplaced(cluster=True, margin=1.5mm)
        évolutionnaire, cluster-by-net — traces courtes ⭐⭐⭐
     ② pcbnew grille : LoadBoard() + SetPosition() grille 15mm ⭐
        si kicad-tools échoue
     ③ status:'error' si service Docker down (fail fast)

⑥ call_agent_routing   → ROUTING_DONE
     Path 1 : Freerouting Java .dsn → .ses → .kicad_pcb
     Path 2 : kicad-tools Python A* (fallback, ≤10 nets, 60s)
     Fallback : GND plane B.Cu sur PCB propre (pas de routage simulé MST)

⑦ call_agent_drc       → DRC_CLEAN (boucle max 3×)
     Primaire : POST /drc/auto (kicad-cli pcb drc, auto-fix)
     Fallback : kicad-tools Python 27 règles JLCPCB

⑧ call_agent_export    → PCB_LIVRÉ
     POST /export/all → Gerbers RS-274X + drill Excellon + BOM JLCPCB + CPL
     Upload Supabase Storage → signed URLs KiCanvas

   call_agent_simulation → (optionnel, 3 crédits, Pro+)
     POST /simulate/auto → kicad-cli SPICE export → ngspice batch → vecteurs V/A
```

---

### Agents — Modèles et rôles

| Agent | Tool name | Modèle | Rôle | Output |
|-------|-----------|--------|------|--------|
| Schematic | `call_agent_schema` | Haiku 4.5 | circuit_synth Docker → kicad-tools Schematic → TS S-expr | `.kicad_sch` + `unresolved_footprints` |
| ERC | `call_agent_erc` | — | kicad-tools validate → kicad-cli sch erc → TS fallback | rapport violations ERC |
| Footprint | `call_agent_footprint` | Haiku 4.5 | Cascade 4 étapes KiCad→pgvector→LCSC→IA | `footprint_name` + `kicad_mod` |
| PCB Layout | `call_agent_gen_pcb` | — | kicad-tools PCBFromSchematic → pcbnew direct → TS S-expr | `.kicad_pcb` |
| Placement | `call_agent_placement` | — | kicad-tools CMA-ES (cluster-by-net) → pcbnew grille → error | `.kicad_pcb` placé |
| Routing | `call_agent_routing` | — | Freerouting Java → kicad-tools A* (≤10 nets) → GND plane | `.kicad_pcb` routé |
| DRC | `call_agent_drc` | — | kicad-cli pcb drc auto-fix max 3× → kicad-tools 27 règles (fallback) | `.kicad_pcb` corrigé |
| Export | `call_agent_export` | — | Gerbers + BOM CSV + CPL + devis JLCPCB | `.zip` b64 + `bom_csv` + `quote_usd` |
| Simulation | `call_agent_simulation` | — | kicad-cli SPICE + ngspice batch → fallback démo synthétique | `SimulationData` (vecteurs V/A) |
| Ask | `ask_user` | — | Pose une question bloquante à l'utilisateur | — |

**Orchestrateur :** Claude Sonnet 4.6 — coordonne, décide l'ordre, écrit les réponses chat.
**Agents spécialisés :** Claude Haiku 4.5 — génération schéma + footprints IA.

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
  plan: 'free' | 'pro' | 'pro_max' | 'enterprise'  // borne max couches
  // pas de paramètre `layers` — c'est l'agent qui décide
})
→ {
    pcb_status: 'ROUTING_DONE',
    layers: 2 | 4 | 8         // décidé par l'agent, borné par `plan`
  }

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

#### Layrix Schematic Generator — Architecture dual-mode (Phase 4+)

```
Fichier TS  : packages/agents/src/engines/circuit-synth-engine.ts   (fallback si Docker absent)
Fichier Py  : services/kicad/routers/schematic_gen.py               (fallback custom Python)
Router      : POST /circuit-synth/generate
```

**Décision architecture (2026-05-25) — Dual-mode :**

```
Backend Docker ACTIF
        ↓
circuit-synth officiel (GitHub v0.12.1, sans [fast_generation] → zéro google-adk)
pip install git+https://github.com/circuit-synth/circuit-synth.git
→ kicad-sch-api → .kicad_sch + .kicad_pcb réels ✅

Backend Docker ABSENT
        ↓
schematic_gen.py (fallback custom Layrix)
→ S-expression Python/TS → .kicad_sch basique ✅
```

**Pourquoi circuit-synth officiel dans Docker :**
- v0.12.1 sur GitHub (pas encore sur PyPI)
- google-adk est OPTIONNEL (`[fast_generation]`) — NON requis pour installation standard
- Dépendances core : numpy, scipy, networkx, pydantic, kicad-sch-api, PySpice
- `kicad-sch-api>=0.5.5` fait le vrai travail KiCad
- Extra `[claude]` disponible : `claude-code-sdk>=0.0.17` (intégration native Claude)

**Package PyPI `circuit-synth==0.1.0` :** Ne pas utiliser — vieux prototype, google-adk requis (non optionnel), API incompatible avec v0.12.1.

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


**OR-Tools — amélioration cosmétique avant pcbnew (Free / Maker) :**
OR-Tools (Google) peut calculer des positions meilleures que la grille naïve et les écrire dans les S-expressions via `circuit-synth-engine.ts` — sans pcbnew. Résultat : placement mathématiquement optimisé, schéma plus lisible, `.kicad_pcb` plus propre. Pas un vrai placement EDA (pas de DRC, pas de tailles réelles de footprints) mais suffisant pour améliorer la lisibilité Free/Maker.

**Stratégie par plan :**
- Free          → OR-Tools + S-expressions TS (placement amélioré, sans pcbnew)
- Pro / Pro Max → pcbnew réel (`POST /place/auto`) — placement EDA natif avec DRC


**Phase 3 — placement réel via pcbnew (Pro / Pro Max) :**

`pcbnew` = bibliothèque Python officielle de KiCad. Elle permet de lire, modifier et écrire des fichiers `.kicad_pcb` programmatiquement — déplacer des footprints, tracer des pistes, lancer le DRC, exporter des Gerbers. Tout ce qu'on fait manuellement dans KiCad, `pcbnew` le fait en Python. pcbnew n'est pas disponible en TypeScript — obligatoirement Python via FastAPI.

1. Circuit-Synth génère le `.kicad_pcb` (avec grille naïve)
2. `call_agent_placement` appelle `POST /place/auto` (FastAPI) — câblage à faire
3. pcbnew lit ce `.kicad_pcb` → `pcbnew.SetPosition()` écrase les coordonnées par des positions réelles
4. Retourne le **même** `.kicad_pcb` modifié — pas un nouveau fichier
  ou avec ou avec https://github.com/LukeVassallo/RL_PCB
#### Engine Router


Voici comment combiner RL_PCB (placement par Reinforcement Learning) + LLM ( Claude,) de manière pratique en 2026.
Approche recommandée : Hybride RL_PCB + LLM
L’idée est d’utiliser le LLM comme cerveau intelligent et RL_PCB comme moteur d’optimisation puissant.
Architecture proposée :

LLM → Analyse le schéma, comprend les contraintes, suggère une stratégie de placement (groupes fonctionnels, faces Top/Bottom, zones sensibles…).
RL_PCB → Prend les suggestions du LLM et optimise mathématiquement les positions.
pcbnew (KiCad) → Importe le résultat final pour vérification / ajustement manuel.
```

---

### État Phase 2 vs Phase 3

| Tool | Phase 2 (actuel) | Phase 3 Free | Phase 3 Pro / Pro Max |
|------|-----------------|-------------------|-----------------|
| `call_agent_spec` | ✅ Haiku 4.5 → `DesignJson` | — opérationnel | — opérationnel |
| `call_agent_schema` | ✅ Haiku 4.5 → Circuit-Synth → `.kicad_sch` + `.kicad_pcb` grille naïve | — opérationnel | — opérationnel |
| `call_agent_placement` | ⚠️ Grille naïve — Python `_grid_position()` ou TS `autoLayout()` | OR-Tools + S-expressions TS (cosmétique) | `POST /place/auto` → pcbnew réel |
| `call_agent_routing` | ⚠️ Stub — pas de routage réel | `POST /route` → Freerouting | `POST /route` → Freerouting |
| `call_agent_drc` | ⚠️ Stub — 0 violations toujours | `POST /drc` → pcbnew DRC natif | `POST /drc` → pcbnew DRC natif |
| `call_agent_export` | ⚠️ Stub — pas de vrais Gerbers | `POST /export` → Gerbers réels | `POST /export` → Gerbers réels |
| `call_agent_footprint` | ⚠️ Stub LCSC | Cascade 8 étapes | Cascade 8 étapes |

**Après placement → Routage :**
`call_agent_routing` → Freerouting trace les pistes entre les footprints dans le `.kicad_pcb`. C'est l'étape qui suit immédiatement le placement dans le pipeline.

**Choix du nombre de couches — décidé par l'agent routage :**
L'agent analyse densité, signaux et contraintes (alimentation/masse séparées, signaux haute vitesse, blindage) puis choisit le nombre optimal de couches : **2, 4 ou 8**. Le résultat est **borné par le plan utilisateur** — `Free : 2 max` · `Pro : 4 max` · `Pro Max : 8 max` · `Enterprise : illimité`. Si l'agent estime que le plan est insuffisant, il route avec le max du plan et retourne un warning du type `"Recommandé : 4 couches — upgrade Pro pour optimal"`. Ce n'est **jamais** un paramètre d'entrée — l'utilisateur ne pré-choisit pas.

**Après routage → DRC :**
`call_agent_drc` → pcbnew vérifie les violations de règles (clearance, largeur de piste, courts-circuits) et tente de les corriger automatiquement. Obligatoire avant export — le PCB doit être DRC_CLEAN.

**Après DRC → Export :**
`call_agent_export` → génère les Gerbers, BOM CSV et CPL pour JLCPCB, puis obtient un devis. Confirmation "OUI JE CONFIRME" obligatoire avant commande — jamais automatique.

**Version avancée — CLI-Anything pour autres outils EDA :**
[CLI-Anything (HKUDS)](https://github.com/HKUDS/CLI-Anything) transforme n'importe quel logiciel en CLI accessible aux agents IA. Non utilisé pour Layrix MVP car KiCad dispose déjà de `pcbnew` (API Python officielle) qui est plus direct. Potentiellement utile si on veut piloter d'autres outils EDA sans API Python (Altium, Eagle, OrCAD) dans une version future multi-EDA. KiCad GUI headless (lancer KiCad sans afficher l'interface) n'est pas nécessaire — pcbnew fait la même chose directement en code.

**Version avancée — Circuit-Synth TS autonome :**
À terme, on pourrait utiliser uniquement la solution TypeScript `circuit-synth-engine.ts`, en s'inspirant du code open source Python `circuit_synth` pour enrichir le générateur S-expressions TS. Cela éliminerait la dépendance FastAPI pour la génération de base et simplifierait le déploiement. La bibliothèque Python resterait uniquement pour pcbnew (placement réel, DRC, export Gerbers) — pas pour la génération de fichiers KiCad.

**Après export → Commande JLCPCB :**
L'utilisateur confirme "OUI JE CONFIRME" → commande envoyée à JLCPCB. Statut final : `PCB_LIVRÉ`. C'est la fin du pipeline. Rien après — le pipeline est terminé.

**Pipeline complet résumé :**
```
INITIAL → call_agent_spec → call_agent_schema → SCHEMA_DONE
       → call_agent_placement → PLACEMENT_DONE
       → call_agent_routing → ROUTING_DONE
       → call_agent_drc → DRC_CLEAN
       → call_agent_export → "OUI JE CONFIRME" → PCB_LIVRÉ
```

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

---

### 2026-05-24 — Footprints professionnels + connectivité nets dans schematic_gen.py

**Décision :** Remplacer les pads génériques 0.6×0.6mm par des géométries correctes par footprint, injecter les assignations de net sur chaque pad, et utiliser `_expand_footprint()` pour les chemins complets dans le PCB S-expression.

**Pourquoi :** `pcbnew.LoadBoard()` lit les pads embarqués dans le `.kicad_pcb` — il ne recharge PAS depuis les bibliothèques KiCad. Si les pads sont faux à la génération, ils restent faux tout au long du pipeline. Sans `(net N "NAME")` sur chaque pad, Freerouting voit des pads non connectés et route aléatoirement ou pas du tout.

**Ce qui a changé :**
- `_footprint_pads(fp)` → retourne les lignes de pads avec placeholder `{NET}` : 0402 (1.3×0.9mm SMD roundrect), DIP-8 (8 THT 7.62mm rows 0.8mm drill), SOT-23 (3 SMD), SOIC-8, TSSOP-8, TO-220, PinHeader, etc.
- `_net_classes_sexpr(power_nets)` → net_settings KiCad : Default 0.2mm signal, Power 0.5mm pour GND/VCC/VDD
- `pad_net_map[(ref, pad_num)] → net_id` construit depuis les connections → injection dans les pads via `{NET}` replacement
- Plus de segments pré-routés (Freerouting gère le routage)

**Écarté :** Modifier `routing.py` pour injecter les nets — trop tard dans le pipeline, le DSN exporté par pcbnew serait déjà basé sur les mauvais pads.

**Fichiers :** `services/kicad/routers/schematic_gen.py`

---

### 2026-05-24 — Placement professionnel dans pcbnew grille (fallback)

**Décision :** Séparer caps (C*) et passifs signal dans `_place_cluster()` : caps à 4mm (tight decoupling) avec rotation 90°, passifs signal à rayon existant avec 0°. Connectors avec rotation 90° pour orientation bord.

**Pourquoi :** Sur un vrai PCB, les condensateurs de découplage doivent être le plus proche possible des broches d'alimentation des ICs — rayon 8mm était trop large et les plaçait n'importe où. La rotation 90° pour les composants 2-pads SMD facilite le routage parallèle.

**Écarté :** Utiliser des positions fixes hardcodées par type de composant — trop fragile selon le nombre de composants.

**Fichiers :** `services/kicad/tools/pcbnew grille (fallback)`

---

### 2026-05-24 — Phase 4.2 : Simulation ngspice end-to-end

**Décision :** Implémenter la simulation SPICE complète via le pipeline : `call_agent_simulation` → `POST /simulate/auto` (base64 .kicad_sch) → kicad-cli SPICE export → ngspice batch → parsing tabular output → vecteurs `SimulationData` → `SimulationView` Recharts.

**Pourquoi :** La simulation SPICE valide électriquement le circuit AVANT la fabrication — c'est une étape critique qui différencie Layrix des outils qui génèrent juste du PCB sans vérification fonctionnelle. ngspice est disponible dans le Docker KiCad existant.

**Fallback :** Quand ngspice ou kicad-cli est indisponible (dev local), des waveformes synthétiques RC/AC réalistes sont retournées pour que le pipeline reste fonctionnel et que l'UI reste testable.

**Types d'analyse :** transient (`.tran 1µs 1ms`), dc (`.op`), ac (`.ac dec 100 1 10Meg`)

**Frontend :** `SimulationView.tsx` — Recharts `LineChart` groupés par unité (V / A), formatage engineering notation (µs/ms, µA/mA), onglet "Simulate" dans la Timeline avec icône `FlaskConical`.

**Écarté :** Ajouter SPICE comme nouveau `PCBStatus` — la simulation ne bloque pas la fabrication, c'est une feature optionnelle (3 crédits, plan Pro+). `simulationData` est un champ optionnel de `PCBState`.

**Fichiers :**
- `services/kicad/routers/simulate.py` (NOUVEAU)
- `services/kicad/tools/simulation.py` (refonte complète)
- `packages/agents/src/engines/simulation-service.ts` (NOUVEAU)
- `packages/agents/src/tools.ts` — `call_agent_simulation` + `_demoVectors()`
- `packages/types/src/index.ts` — `SimulationVector`, `SimulationData`, `PCBState.simulationData`
- `apps/web/src/widgets/viewer/ui/SimulationView.tsx` (NOUVEAU)

---

---

### 2026-05-24 — Architecture agents : LLM vs déterministe

**Décision :**

`call_agent_placement` n'appelle jamais Haiku. C'est juste :

```
call_agent_placement
      ↓
POST /place/auto (FastAPI pcbnew)   ← si backend up
      ou
placement-fallback.ts (algo TS)     ← toujours dispo
```

Aucun LLM. C'est une fonction déterministe déguisée en "agent" pour garder la même interface dans la boucle orchestrateur.

Idem pour :
- `call_agent_routing` → Freerouting ou MST TS
- `call_agent_drc` → kicad-cli ou vérification TS
- `call_agent_export` → génération Gerbers

Seuls vrais agents LLM :
- `call_agent_spec` → Haiku
- `call_agent_schema` → Haiku

**Pourquoi :**
Placement, routing, DRC et export sont des problèmes algorithmiques déterministes — pas besoin d'intelligence. Le LLM n'apporte rien là où un algo suffît. On économise des tokens et on garde la prévisibilité.

**Écarté :**
Utiliser Haiku pour "décider" du placement — inutile et coûteux.

**Fichiers concernés :**
- `packages/agents/src/tools.ts` — `call_agent_placement`, `call_agent_routing`, `call_agent_drc`, `call_agent_export`
- `packages/agents/src/engines/placement-fallback.ts`
- `packages/agents/src/engines/routing-fallback.ts`

---

### 2026-05-24 — Architecture placement actuelle + module payant circuit-synth

**Où on utilise le placement :**

```
call_agent_placement (tools.ts)
  ↓
Priorité 1 — Backend Docker/WSL up :
  runRealPlacement() → POST /place/auto (FastAPI)
    → pcbnew grille (fallback) (algo Python)
    → pcbnew.SetPosition() (validation physique)
    → engine: 'pcbnew'

Priorité 2 — Backend absent (Windows dev) :
  computeLayout() → placement-fallback.ts (algo TS identique)
  applyLayoutToPcb() (réécrit (at X Y) dans S-expression)
  → engine: 'fallback-ts'
```

**Algo de placement actuel (les deux modes) :**
- ICs → centre du board
- Résistances / caps / diodes → cluster autour des ICs
- Connecteurs → bords gauche/droite
- Misc → bas du board

Pas d'intelligence topologique — C1 n'est pas forcément placé près du pin VCC de U1.

**Module payant circuit-synth pour le placement intelligent :**

`circuit-synth` 0.12.1 contient un module PCB (`kicad-pcb-api`) avec placement hiérarchique et force-directed, mais il a été **retiré de la version open source** :

```python
# services/kicad/.venv/.../circuit_synth/pcb/__init__.py
"""
PCB generation functionality is no longer included in the open source version.
Contact Circuit Synth for licensing information if you need PCB features.
"""
```

Pour l'acheter : contacter Circuit Synth à contact@circuitsynth.com (pas de prix public affiché).

**Alternative gratuite envisagée :** RL_PCB (Reinforcement Learning)
→ https://github.com/LukeVassallo/RL_PCB
→ Combinaison recommandée : LLM (Claude) suggère la stratégie → RL_PCB optimise → pcbnew valide
**Alternative force_directed — Analyse 2026-05-29**

**Option A — `circuit_synth.component_placement.ForceDirectedLayout` (❌ Écarté pour PCB)**
→ Importable et instanciable, mais `fdl.layout(circuit)` plante sur un vrai circuit.
→ **Erreur de catégorie pour le PCB** : c'est un placeur de *symboles sur schéma* (lisibilité du diagramme), pas de *footprints sur PCB*. Domaine incompatible avec `pcbnew grille (fallback)`.
→ Entrée attendue : objet `Circuit` complet (`.components`, `.get_nets()`) — inexistant dans le pipeline PCB à cette étape.
→ Sortie non bornée au board — composants peuvent sortir du PCB.
→ Code vendoré non maintenu (`PlacementNode.connected_components` non initialisé).

→ **✅ Usage possible : améliorer la lisibilité du SCHÉMA (`.kicad_sch`)**
→ `ForceDirectedLayout` est conçu pour disposer les *symboles sur la feuille de schéma* — c'est exactement son domaine.
→ Aujourd'hui `circuit_synth` place les symboles en grille bête → schéma difficile à lire dans KiCanvas.
→ Corriger le bug (`PlacementNode.connected_components` non initialisé) + fixer `fdl.layout(circuit)` → pourrait améliorer la présentation visuelle du schéma généré.
→ **Effort** : corriger 1 bug dans le code vendoré + tester sur un circuit réel.
→ **Impact** : purement cosmétique (schéma plus lisible dans KiCanvas) — aucun effet sur le PCB, le routage ou le DRC.
→ **Statut** : idée notée — priorité faible (cosmétique), à faire après les fonctionnalités critiques.

**Option B — `kicad-tools` (rjwalters) — `kct optimize-placement` (✅ Candidat sérieux)**

> ❓ KiCad doit tourner ? → **NON**
> ❓ Plusieurs utilisateurs en parallèle ? → **OUI, nativement**

**KiCad requis ?**
→ Le README dit explicitement : *"require no running KiCad instance"*
→ Placement, routage, parsing, analyse (thermique/congestion/SI) = **pur Python (numpy)** — zéro KiCad, zéro kicad-cli, zéro GUI
→ Seuls ERC, DRC et export Gerber appellent le **binaire `kicad-cli`** (one-shot, pas « KiCad qui tourne ») — qu'on utilise déjà dans notre Docker
→ **Conséquence** : placement + routage sans pcbnew ni Freerouting/Java → image Docker plus légère

**Plusieurs utilisateurs en parallèle ?**
→ **Bibliothèque sans état** : fichier `.kicad_pcb` en entrée → fichier en sortie, aucun daemon, aucun état global partagé
→ 1 process/worker par PCB → **massivement parallèle** — colle exactement à notre modèle BullMQ (10 PCBs simultanés)
→ Contraste avec `pcbnew` : module lourd in-process, non thread-safe → 1 process/job obligatoire
→ **Mode CPU** (défaut) : scale avec les cœurs CPU, zéro contention entre jobs
→ **Mode GPU** (optionnel CUDA/Metal) : GPU partagé entre jobs → file GPU nécessaire si activé — rester en CPU pour démarrer

**Pourquoi 1 process/job par utilisateur ?**
→ Pas une contrainte de `kicad-tools` — c'est notre architecture BullMQ existante.
→ Chaque PCB = 1 job BullMQ = 1 worker Node.js qui appelle le service FastAPI.
→ Le service FastAPI reçoit le `.kicad_pcb` en base64, le traite, retourne le résultat — aucune mémoire partagée entre requêtes.
→ Résultat : user A et user B lancent leur PCB en même temps → 2 workers indépendants → 2 appels FastAPI parallèles → zéro collision.
→ Si 10 users en même temps → BullMQ concurrency=10 → 10 workers → 10 appels parallèles, chacun isolé.

**C'est quoi le mode GPU ?**
→ Le placement force-directed calcule des forces entre tous les composants (O(n²) paires).
→ Pour un PCB de 5 composants → ~10 paires → CPU largement suffisant, calcul en ms.
→ Pour un PCB de 100 composants → ~5000 paires → CPU commence à ralentir (quelques secondes).
→ **Mode GPU** : `kicad-tools` envoie ces calculs de forces sur la carte graphique (NVIDIA CUDA ou Apple Metal) qui les fait tous en parallèle → 10-50× plus rapide sur grands PCBs.
→ `pip install kicad-tools[cuda]` (NVIDIA) ou `kicad-tools[metal]` (Mac Apple Silicon).
→ **Pour Layrix** : nos PCBs = 5-30 composants en moyenne → CPU suffit largement. GPU = optimisation future si on supporte des PCBs >100 composants.


→ 
 — MIT, PyPI `kicad-tools` v0.13.0, Python 3.10+, actif (push 2026-05-29)
→ Tagline : *"Tools for AI agents to work with KiCad projects"* — conçu exactement pour notre cas d'usage.
→ **Force-directed board-aware** : repulsion edge-to-edge sur outlines, borné au board, `slide_off`, poids configurables.
→ Contrat parfait : `.kicad_pcb` en entrée → `.kicad_pcb` en sortie — identique au flux `/place/auto` de Layrix.
→ **Sans KiCad ni kicad-cli** pour le placement/routage — pur Python (numpy). Seuls DRC/Gerber utilisent kicad-cli (déjà présent).
→ **Multi-utilisateurs natif** : aucun état global, aucun daemon — 1 process/job, parallélisable comme BullMQ (10 PCBs simultanés).
→ Accélération GPU optionnelle (CUDA/Metal) — CPU pur suffit pour démarrer.
→ Couvre aussi : routeur natif C++, DRC avec règles fabricant JLCPCB intégrées, analyse congestion/thermique/SI, serveur MCP.
→ **Risque** : Beta, 1 mainteneur, 30 ⭐ → vendorer + pinner la version comme circuit_synth.
→ **Prochaine étape décidée** : spike isolé — tester `kct optimize-placement` sur un `.kicad_pcb` Layrix réel avant intégration.

**Algorithme placement — `PlacementOptimizer` (physique simulée)**
→ **Modèle physique** : chaque composant = charge électrique, chaque net = ressort (spring)
→ **Répulsion** : composants se repoussent comme des charges de même signe (loi de Coulomb) — empêche les chevauchements, garde tout dans le board
→ **Attraction** : les nets (connexions électriques) tirent les pins connectés l'un vers l'autre (loi de Hooke)
→ **Paramètres intelligents** :
  - Nets d'horloge → ressort plus rigide (`clock_net_stiffness: 20`) → pins clock regroupés
  - Nets d'alimentation → ressort souple (`power_net_stiffness: 5`) → GND/VCC moins contraints
  - Composants chauds (régulateurs, drivers) → répulsion thermique vers les bords du board
  - Connecteurs → contrainte de bord (`edge_stiffness`) → restent sur les bords
→ **Rotation** : composants s'alignent automatiquement à 90° (grille de rotation)
→ **Convergence** : itère jusqu'à ce que l'énergie totale < seuil ou vitesse max < seuil
→ **GPU** : calcul des forces O(n²) parallélisé sur GPU (CUDA/Metal) pour grands boards

**Algorithme routage — `Autorouter` (A* avec négociation de congestion)**
→ **Algorithme de base** : **A\*** (A-star) — pathfinding optimal sur grille de routage
→ **Multi-couches** : F.Cu, B.Cu (+ couches internes si 4/8 couches) avec gestion des vias
→ **Heuristiques disponibles** : Manhattan, DirectionBias, CongestionAware (pluggables)
→ **Négociation de congestion** : si 2 nets se disputent la même zone → coût augmenté → reroutage automatique pour éviter les croisements
→ **Conscience des classes de nets** : power / clock / audio / digital — règles différentes par classe
→ **Cache de routage** : sous-problèmes identiques mémorisés → accélération sur boards similaires
→ **GPU** : expansion de frontières A\* en batch parallèle (4+ nets simultanés) → accélération sur grands boards
→ **Différence vs Freerouting** : Freerouting = algorithme industriel 30 ans (Spectra DSN), très robuste. `Autorouter` = plus moderne, intégré Python, pas de Java — qualité à valider sur nos circuits

**Option C — Développer notre propre force-directed PCB (🔲 À faire)**
→ Écrire un algorithme force-directed **dans le bon domaine** : coordonnées PCB mm, borné au board, alimenté par les `connections` déjà en cache (`_pcbStateCache`).
→ Intégré directement dans `pcbnew grille (fallback)` — passe optionnelle après l'algo déterministe actuel.
→ **Principe** : chaque net = force attractive entre les composants connectés ; chaque paire de composants = force répulsive ; itérations jusqu'à convergence.
→ **Avantages** :
  - Zéro dépendance externe — pur Python (numpy), même env Docker actuel
  - Contrôle total : paramètres Layrix-specific (bypass caps restent à <2mm des ICs, connecteurs ancrés aux bords)
  - Pas de vendoring à maintenir
  - Peut être GPU-accéléré (numpy → cupy) si besoin plus tard
→ **Entrée** : `refs: list[str]`, `connections: list[{name, pins}]`, `board_w_mm`, `board_h_mm`
→ **Sortie** : `dict[ref → (x_mm, y_mm, rotation_deg)]` — identique à `compute_layout()` actuel → zéro changement d'interface
→ **Effort estimé** : 1 session (~150 lignes Python + tests) — algorithme bien documenté, pas de magie noire
→ **Risque** : faible — fallback immédiat sur l'algo déterministe si convergence lente ou résultat dégradé
→ **Statut** : décision non prise — à comparer avec Option B (`kct optimize-placement`) après le spike

**Option B bis — `kicad-tools` — routeur natif C++ (✅ Alternative à Freerouting)**
→ Même repo `rjwalters/kicad-tools` — module `kicad_tools.router.Autorouter`
→ API Python pure : `router.add_component()` + `router.route_all()` → retourne pistes routées
→ Kernel C++ natif (optionnel `pip install kicad-tools[native]`) — pas de Java, pas de JVM, pas de JAR Freerouting
→ Contrat identique au flux actuel : `.kicad_pcb` en entrée → `.kicad_pcb` routé en sortie
→ **Avantage vs Freerouting** : pas de dépendance Java/openjdk-17, démarrage instantané (pas de JVM warmup), même parallélisation multi-users
→ **Risque** : qualité du routage C++ vs Freerouting (30 ans d'algorithme industriel) — à valider sur circuits réels avec % routé + DRC clean
→ **Statut** : non testé sur Layrix — à inclure dans le spike `kicad-tools`

**Fichiers concernés :**
- `packages/agents/src/tools.ts` — `call_agent_placement` + `call_agent_routing`
- `packages/agents/src/engines/placement-fallback.ts` — algo TS placement
- `packages/agents/src/engines/routing-service.ts` — client Freerouting actuel
- `services/kicad/tools/pcbnew grille (fallback)` — algo Python placement
- `services/kicad/tools/placement.py` — appel pcbnew
- `services/kicad/routers/routing.py` — endpoint Freerouting actuel

---

## Template pour la prochaine décision

```
### [DATE] — [Sujet]

**Décision :**

**Pourquoi :**

**Écarté :**

**Fichiers concernés :**
```
