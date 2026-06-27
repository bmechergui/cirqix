# Cirqix — Journal de Décisions

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

     Architecture netlist (important) :
     · La netlist est GÉNÉRÉE par call_agent_schema (circuit_synth produit .kicad_sch + .kicad_net)
     · call_agent_gen_pcb UTILISE le .kicad_sch + la netlist pour créer le .kicad_pcb
     · Pour LIRE/RÉSOUDRE la netlist depuis le .kicad_sch → 3 niveaux (tools/pcb.py) :
       ① kicad-tools Python pur : build_netlist_from_schematic — sans kicad-cli
          Résout labels hiérarchiques via kicad-sch-api (après fix circuit_synth 2026-06-01)
       ② kicad-cli : export netlist officiel — si Python pur échoue
       ③ .kicad_net injecté : circuit_synth netlist direct — vieux schémas (avant fix)
     kicad-tools PCBFromSchematic(.kicad_sch) → vrais footprints + nets
     ② pcbnew direct : BOARD() + FootprintLoad() + SetNet() → .kicad_pcb natif
     ③ success=False → TypeScript runCircuitSynthEngine() S-expr inline

⑤ call_agent_placement → PLACEMENT_DONE
     POST /place/auto (kicad_pcb_b64)  — pipeline 3 niveaux (tools/placement.py auto_place)

     Algorithmes kicad-tools (documentation officielle) :
     · place_unplaced      = "grid-place unplaced components" → GRILLE DÉTERMINISTE
       Détecte footprints hors-board (-1000,-1000), les place en cellules grille
       cluster-by-net. Rapide, déterministe, gère tous footprints (Arduino inclus).
     · kct optimize-placement = "CMA-ES placement optimization" → ÉVOLUTIONNAIRE
       CMA-ES (Covariance Matrix Adaptation) : optimise positions X/Y/rotation.
       Nécessite bon starting point — fonctionne depuis le résultat place_unplaced.

     Pipeline Cirqix (ordre optimal) :
     Niveau 1 : kicad-tools
       a. place_unplaced(cluster=True)        ← grille déterministe cluster-by-net
          footprints déjà à (-1000,-1000) par call_agent_gen_pcb (pré-unplace)
       b. kct optimize-placement (CMA-ES)     ← raffine TOUJOURS depuis la grille
          si result.area > 50mm² (pas stacked) → utilise le résultat optimisé
     Niveau 2 : pcbnew grille (LoadBoard + SetPosition 15mm)
     Niveau 3 : TypeScript S-expr (fallback final)

⑥ call_agent_routing   → ROUTING_DONE
     ① kicad-tools A* negotiated — ≤30 nets routables (≥2 pads), ≤30 comps, timeout 60s
        route_all_negotiated + merge_routes_into_pcb + _add_power_zones (GND B.Cu + VCC F.Cu)
     ② Freerouting REST API       — 1 JVM persistant Docker port 37864, RAM fixe 400MB
        POST /api/v1/sessions/create → jobs/enqueue → upload DSN → PUT start → GET output
     ③ Freerouting subprocess     — fallback si API absent (1 JVM par job)
     ④ kicad-tools A* negotiated — TOUS circuits, sans limite nets, timeout plus long
        Même algorithme que ①, utilisé quand Freerouting absent
     ⑤ skipped=True              → TypeScript addGroundPlane() GND plane B.Cu

⑦ call_agent_drc       → DRC_CLEAN (boucle max 3×)
     ① kicad-tools Python DRC — 27 règles JLCPCB, pur Python, toujours dispo
        0 erreur → DRC_CLEAN immédiat · erreurs → niveau 2
     ② kicad-cli pcb drc      — officiel KiCad, auto-fix loop max 3× (si dispo)
        refill zones via pcbnew · retourne .kicad_pcb corrigé
     ③ skipped=True           — les deux absents, pipeline continue

⑧ call_agent_export    → PCB_LIVRÉ
     ① kicad-tools kct export --mfr jlcpcb ⭐⭐⭐
        Gerbers JLCPCB (GTL/GBL/GKO) + BOM LCSC + CPL rotation corrections
     ② kicad-cli pcb export {gerbers,drill,pos} ⭐⭐
        si kicad-tools échoue
     ③ skipped=True → BOM CSV seulement (kicad-cli absent)
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
| PCB Layout | `call_agent_gen_pcb` | — | Netlist: ①Python pur ②kicad-cli ③.kicad_net · PCB: ①PCBFromSchematic ②pcbnew ③TS S-expr | `.kicad_pcb` |
| Placement | `call_agent_placement` | — | kct optimize-placement (si feasible) → place_unplaced cluster (shields) → pcbnew grille | `.kicad_pcb` placé |
| Routing | `call_agent_routing` | — | ①kicad-tools A*(≤30) → ②Freerouting API(1JVM) → ③Freerouting subprocess → ④kicad-tools A*(tous) → ⑤GND plane | `.kicad_pcb` routé |
| DRC | `call_agent_drc` | — | kicad-tools 27 règles JLCPCB → kicad-cli auto-fix max 3× → skipped | `.kicad_pcb` corrigé |
| Export | `call_agent_export` | — | kicad-tools JLCPCB → kicad-cli standard → BOM CSV | `.zip` b64 + `bom_csv` + `quote_usd` |
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

#### Cirqix Schematic Generator — Architecture dual-mode (Phase 4+)

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
schematic_gen.py (fallback custom Cirqix)
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

---

### Architecture Docker KiCad — Workers et thread-safety (mis à jour 2026-05-31)

#### Modèle de déploiement

```
1 Docker Container (DigitalOcean, ~40€/mois, 4 CPU / 8GB RAM)
│
├── Processus persistants (démarrés au boot du container)
│   ├── Xvfb :99          → display virtuel pour kicad-cli
│   ├── Freerouting JAR   → REST API server port 37864 (1 JVM = 400MB fixe)
│   └── uvicorn × 4 workers → FastAPI port 8766
│
└── Par requête (éphémère)
    ├── Répertoire /tmp/kicad-jobs/{project_id}/
    └── Nettoyé après traitement
```

#### Thread-safety des outils KiCad

| Outil | Type | Thread-safe | Explication |
|-------|------|-------------|-------------|
| **kicad-tools** | Bibliothèque Python | ✅ OUI | Chaque appel crée un objet `Autorouter` indépendant en mémoire. Plusieurs workers peuvent l'utiliser simultanément sans conflit. |
| **pcbnew** | Bibliothèque Python | ❌ NON | État global C++ partagé. 2 threads = crash/corruption. Nécessite un process séparé par job (uvicorn workers = processes isolés, pas threads). |
| **kicad-cli** | Exécutable externe | ✅ OUI | Subprocess totalement isolé. Chaque appel = nouveau process kicad-cli indépendant. Thread-safe par nature. |
| **circuit_synth** | Bibliothèque Python | ✅ OUI | Objets Circuit indépendants, pas d'état global. |
| **Freerouting (subprocess)** | JAR Java | ✅ OUI | Subprocess isolé. Mais 1 JVM par job = RAM ×N. |
| **Freerouting (API server)** | REST API | ✅ OUI | 1 JVM persistante, jobs traités en file. RAM fixe 400MB. |

#### Pourquoi 4 uvicorn workers (processes) et non threads

```python
# uvicorn --workers 4
# = 4 processus Python séparés (fork), PAS 4 threads

Worker 1 (PID 101) → pcbnew chargé en mémoire 1 → projet A ✅
Worker 2 (PID 102) → pcbnew chargé en mémoire 2 → projet B ✅
Worker 3 (PID 103) → pcbnew chargé en mémoire 3 → projet C ✅
Worker 4 (PID 104) → pcbnew chargé en mémoire 4 → projet D ✅
```

Chaque worker a sa propre copie de pcbnew → jamais de conflit.
pcbnew en mode thread (1 process, 4 threads) → CRASH garanti.

#### Freerouting : subprocess vs API server

```
AVANT (subprocess par job)          APRÈS (API server persistant)
──────────────────────────          ──────────────────────────────
Job A → new JVM 400MB               Docker boot → 1 JVM 400MB fixe
Job B → new JVM 400MB                     ↓
Job C → new JVM 400MB               Job A → HTTP POST /api/v1/jobs
10 jobs = 4GB RAM JVMs              Job B → HTTP POST /api/v1/jobs
                                    Job C → HTTP POST /api/v1/jobs
                                    10 jobs = 400MB RAM total
```

Implémenté dans `routers/routing.py` : `_find_freerouting_api()` + `_route_with_freerouting_api()`.
Démarré dans `Dockerfile` : `java -jar freerouting.jar --api_server.enabled=true --api_server-endpoints=http://127.0.0.1:37864`.

#### Variables d'environnement KiCad requises

```bash
KICAD_SYMBOL_DIR=/usr/share/kicad/symbols       # auto-détecté dans main.py
KICAD_FOOTPRINT_DIR=/usr/share/kicad/footprints  # auto-détecté dans main.py (ajouté 2026-05-31)
FREEROUTING_API_URL=http://127.0.0.1:37864       # défini dans Dockerfile
```

**Bug corrigé 2026-05-31 :** `KICAD_FOOTPRINT_DIR` manquant → kicad-tools PCBFromSchematic ne chargeait pas les footprints → 0 composant placé dans le PCB. Fixé dans `main.py` (auto-detect) et `docker-compose.yml`.

**Dépendances vendorées :** circuit_synth v0.12.1 et kicad_tools v0.13.0 utilisés avec patches Cirqix — voir `CLAUDE.md` section "Dépendances vendorées" et `services/kicad/DEPENDENCIES.md`.

#### Pipeline routing — 4 niveaux (mis à jour 2026-05-31)

```python
# routers/routing.py route_auto()

# Nets routables = nets avec ≥2 pads (corrigé : exclure Net-(U1-X) mono-pad)
net_count  = _count_routable_nets(pcb_bytes)   # ≥3 occurrences dans le fichier
comp_count = _count_footprints(pcb_bytes)
is_simple  = net_count <= 30 and comp_count <= 30

# Niveau 1 : kicad-tools A* negotiated (circuits simples ≤30 nets)
if is_simple:
    → load_pcb_for_routing + route_all_negotiated(timeout=60s) + merge_routes_into_pcb
    → _add_power_zones(merged)  # GND B.Cu + VCC F.Cu

# Niveau 2 : Freerouting REST API (1 JVM persistante, tous circuits)
elif _find_freerouting_api():
    → POST /api/v1/sessions/create → jobs/enqueue → upload DSN → PUT start → GET output

# Niveau 3 : Freerouting subprocess (fallback, 1 JVM par job)
elif _find_freerouting():
    → java -jar freerouting.jar (subprocess)

# Niveau 4 : kicad-tools A* negotiated sans limite (tous circuits, Freerouting absent)
# Même algorithme que niveau 1, pas de contrainte nets/comps, timeout plus long
else (kicad-tools disponible):
    → route_all_negotiated(timeout=120s, no is_simple check)
    → _add_power_zones()

# Niveau 5 : skipped → GND plane seulement
else:
    → TypeScript addGroundPlane()
```

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
[CLI-Anything (HKUDS)](https://github.com/HKUDS/CLI-Anything) transforme n'importe quel logiciel en CLI accessible aux agents IA. Non utilisé pour Cirqix MVP car KiCad dispose déjà de `pcbnew` (API Python officielle) qui est plus direct. Potentiellement utile si on veut piloter d'autres outils EDA sans API Python (Altium, Eagle, OrCAD) dans une version future multi-EDA. KiCad GUI headless (lancer KiCad sans afficher l'interface) n'est pas nécessaire — pcbnew fait la même chose directement en code.

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

**Raison projet :** TSCircuit déprécié depuis la v0.3.0 de Cirqix. Dépendances supprimées : `circuit-json`, `circuit-json-to-gerber`, export `tscircuit-engine`.

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

**Pourquoi :** La simulation SPICE valide électriquement le circuit AVANT la fabrication — c'est une étape critique qui différencie Cirqix des outils qui génèrent juste du PCB sans vérification fonctionnelle. ngspice est disponible dans le Docker KiCad existant.

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
→ **Pour Cirqix** : nos PCBs = 5-30 composants en moyenne → CPU suffit largement. GPU = optimisation future si on supporte des PCBs >100 composants.


→ 
 — MIT, PyPI `kicad-tools` v0.13.0, Python 3.10+, actif (push 2026-05-29)
→ Tagline : *"Tools for AI agents to work with KiCad projects"* — conçu exactement pour notre cas d'usage.
→ **Force-directed board-aware** : repulsion edge-to-edge sur outlines, borné au board, `slide_off`, poids configurables.
→ Contrat parfait : `.kicad_pcb` en entrée → `.kicad_pcb` en sortie — identique au flux `/place/auto` de Cirqix.
→ **Sans KiCad ni kicad-cli** pour le placement/routage — pur Python (numpy). Seuls DRC/Gerber utilisent kicad-cli (déjà présent).
→ **Multi-utilisateurs natif** : aucun état global, aucun daemon — 1 process/job, parallélisable comme BullMQ (10 PCBs simultanés).
→ Accélération GPU optionnelle (CUDA/Metal) — CPU pur suffit pour démarrer.
→ Couvre aussi : routeur natif C++, DRC avec règles fabricant JLCPCB intégrées, analyse congestion/thermique/SI, serveur MCP.
→ **Risque** : Beta, 1 mainteneur, 30 ⭐ → vendorer + pinner la version comme circuit_synth.
→ **Prochaine étape décidée** : spike isolé — tester `kct optimize-placement` sur un `.kicad_pcb` Cirqix réel avant intégration.

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
  - Contrôle total : paramètres Cirqix-specific (bypass caps restent à <2mm des ICs, connecteurs ancrés aux bords)
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
→ **Statut** : non testé sur Cirqix — à inclure dans le spike `kicad-tools`

**Fichiers concernés :**
- `packages/agents/src/tools.ts` — `call_agent_placement` + `call_agent_routing`
- `packages/agents/src/engines/placement-fallback.ts` — algo TS placement
- `packages/agents/src/engines/routing-service.ts` — client Freerouting actuel
- `services/kicad/tools/pcbnew grille (fallback)` — algo Python placement
- `services/kicad/tools/placement.py` — appel pcbnew
- `services/kicad/routers/routing.py` — endpoint Freerouting actuel

---

### 2026-06-02 — Routage 0% : cause racine = pad-collapse du writer CMA-ES

**Décision :** Corriger `_write_placements_to_pcb` (kicad_tools patché) pour ne mettre à jour
que la position des footprints via le modèle PCB (`update_footprint_position` + `pcb.save`),
au lieu d'un remplacement texte des lignes `(at …)`.

**Pourquoi :** Le routage retournait 0% (`No path found`) sur tous les circuits passant par
le CMA-ES `_optimize_with_priors`. Investigation systématique → la regex de l'ancien writer
matchait **toutes** les lignes `(at …)` d'un footprint (pads inclus) et les remplaçait par la
position du footprint → **tous les pads empilés sur un seul point** → aucune extrémité distincte
à router. La taille du board / la grille / les timeouts n'y étaient pour rien. Validé : pipeline
météo Arduino 0% → **100%** (18 segments).

**Écarté :**
- Board-fit (réduire le board) — l'hypothèse « board trop grand » était fausse (échec persistant
  même sur grille 64k cellules). `_fit_board_outline_to_components` corrigé (ne corrompt plus le
  PCB) mais NON câblé dans auto_place.
- Build C++ router en Docker — utile pour la vitesse mais non bloquant (le vrai bug était les pads).

**Aussi livré (PR #34) :** cascade `route_auto` bascule vers Freerouting si kicad-tools A* < 95%
(avant : retournait 0%) ; `--power-nets` au format `NET:LAYER`.

**Fichiers concernés :** `services/kicad/kicad_tools/.../cli/optimize_placement_cmd.py` (patché,
gitignored, doc `DEPENDENCIES.md`) · `services/kicad/routers/routing.py` ·
`services/kicad/tests/test_placement_pad_integrity.py` · `test_route_auto_cascade.py`

---

### 2026-06-02 — Placement compact (module à corps décalé) reporté en Phase 6 (RL_PCB)

**Décision :** Ne PAS rendre le CMA-ES kicad_tools « courtyard-aware » par un patch en
force. `auto_place` garde son comportement actuel (gate courtyard + sélection : CMA-ES
si faisable, sinon `place_unplaced` étalé). La compacité « pro » (composants serrés
autour du corps Arduino) est planifiée en Phase 6 via RL_PCB.

**Pourquoi :** Le CMA-ES modélise chaque composant comme une **AABB centrée sur l'origine**
du footprint. Le corps de l'Arduino est **décalé** (courtyard 75×54mm centré à +24mm en y
vs origine). Approche « lite » testée = donner au CMA-ES la taille du courtyard en boîte
centrée symétrique → trop conservateur (81×102) → CMA-ES se déclare infaisable
(`overlap=0.58mm²`) → retombe sur la grille. Le faire correctement exige un modèle avec
**offset** touchant 6 fichiers du cœur de l'optimiseur vendoré (vector/geometry/priors/
seed/slide_off/visualization), sans leur suite de tests → risque/valeur défavorable pour
un board déjà fabricable.

**Écarté :**
- Patch « lite » courtyard-size centré (testé, échec : CMA-ES infaisable → grille).
- Réécriture offset 6 fichiers du CMA-ES vendoré (trop risqué maintenant).

**État livré (PR #34, correct & fabricable) :** pad-collapse corrigé (routage 0%→100%),
gate courtyard (jamais de board avec chevauchement), cascade Freerouting <95%,
`--power-nets NET:LAYER`. Placement modules = grille étalée (fils longs mais 0 conflit).

**Fichiers concernés :** `services/kicad/tools/placement.py` (auto_place + sélection) ·
`PLAN.md` (Phase 6 RL_PCB) · futur : RL_PCB = nouveau candidat dans `_select_best_placement`.

---

### 2026-06-02 → 2026-06-03 — Migration vers le workflow OFFICIEL kicad-tools

**Décision :** Abandonner tout notre code de placement/routage custom (pin-adjacent,
gate HPWL, zones manuelles, `_add_supply_traces`, board-fit…) et **déléguer au dépôt
officiel kicad-tools** (API + CLI). On vendore le dépôt complet `services/kicad/kicad-tools/`.

**Flux entre agents corrigé (conforme au pipeline officiel) :**
- `call_agent_gen_pcb` (`tools/pcb.py`) → PCB **"unrouted"** = footprints **placés**
  (suppression du pré-déplacement à -1000 ; `workflow.place_all_components` place déjà).
- `call_agent_placement` (`tools/placement.py`) → `PlacementOptimizer.from_pcb(pcb,
  fixed_refs=<connecteurs J*/P*>, enable_clustering=True)` + `run()` +
  `snap_rotations_to_90()` + `write_to_pcb()`. Le clustering regroupe les grappes
  électriques (caps/quartz près du MCU) — équivalent `--grouping` voulu.
- `call_agent_routing` (`routers/routing.py`) → `kct route --auto-layers --auto-fix
  --seed` puis **sauvetage agentique** : reasoner LLM (`PCBReasoningAgent` + Claude
  Haiku, `tools/reasoning.py`) si `ANTHROPIC_API_KEY`, sinon `kct reason --auto-route`.

**Pourquoi :** notre code custom cassait à chaque évolution du package et
réimplémentait mal ce que le dépôt fait déjà (testé sur ses benchmarks). Validé :
board 01 = ERC/Route/DRC/MFG PASS ; STM32 17 comps = 0 conflit, caps clusterisés.

**Écarté :**
- API de la doc (`set_weights/add_group/optimize/lock/save`) — **N'EXISTE PAS** dans
  le code réel (vérifié). Vraie API = `from_pcb/run/write_to_pcb/snap_*`.
- Flags CLI `--thermal/--grouping` sur `optimize-placement` — **inexistants** (sur
  `placement optimize` force-directed seulement). On passe par l'API Python.
- Remplacer `tools/pcb.py` par `kct create-pcb` — gardé notre gen, juste sans -1000.

**Patch obligatoire (Windows) :** `kicad-tools/src/.../cli/route_cmd.py` `_write_routed_pcb`
— `os.fsync` sur handle read-only → `OSError [Errno 9]` cassait tout build/route sur
Windows ; fix write+fsync même handle (best-effort). Inoffensif en Docker/Linux.
Voir `DEPENDENCIES.md`.

**Reste (non bloquant, → Docker) :** backend C++ (`kct build-native`, 10-100× ;
pas de compilateur en local Windows) ; reasoner LLM actif seulement avec la clé.

**Fichiers concernés :** `services/kicad/{tools/pcb.py, tools/placement.py,
tools/reasoning.py, routers/routing.py, main.py, Dockerfile, requirements.txt,
DEPENDENCIES.md, .gitignore}` · `services/kicad/scripts/{optimiseur_pro.py,
pipeline_pro.sh}` (démo versionnée).

---

### 2026-06-03 — Reasoner = agent séparé visible + affichage UI temps-réel + fix pct

**Décision :** Le sauvetage de routage (`PCBReasoningAgent` + Claude) devient un
**agent à part entière** `call_agent_reason` (`⑥b`), visible et piloté par
l'orchestrateur — plus un sous-appel caché dans `call_agent_routing`. L'orchestrateur
l'appelle UNIQUEMENT si `call_agent_routing` renvoie `routed_percent < 100`.

**Visibilité UI (commit d7a0f07) :** chaque tour du raisonneur remonte
`reasoning_steps` → `orchestrator.ts` émet un event `reasoning` → `orchestrator-bridge`
→ SSE → `ChatRail` affiche les actions IA en direct (« 🤖 Reasoner IA — déblocage du
routage : déplace C12 près de U1… »). `tools.ts` renvoie désormais le `routed_percent`
réel (fini le hardcode 100).

**Bug corrigé (TDD, commit 34be8ae) :** `PCBReasoningAgent` écrit les pistes dans
l'éditeur mais ne resynchronise pas `PCBState.nets[*].traces` ; `NetState.is_routed`
(= traces présentes) reste False en session → `route_with_llm` renvoyait **0 % sur un
board réellement routé à 100 %** et ne voyait jamais `is_complete` (boucle jusqu'à
`max_steps`, ~15 appels Claude gaspillés + escalade Freerouting inutile). Fix :
`_refresh_agent()` recharge l'état après chaque commande réussie (history préservé) ;
`_claude_decider()` rend la boucle testable sans `ANTHROPIC_API_KEY`. **Découvert en
testant le reasoner « moi = le LLM »** → routé 0 %→100 %.

**Écarté :** patcher la lib vendorée kicad_tools — le fix tient entièrement dans
`tools/reasoning.py`.

**Fichiers concernés :** `services/kicad/{tools/reasoning.py, tests/test_reasoning.py}`
· `packages/agents/src/{orchestrator.ts, tools.ts, engines/reasoning-service.ts}` ·
`apps/web/src/{app/api/agent/lib/{orchestrator-bridge.ts, sse.ts},
features/workspace/{lib/agent-client.ts, ui/ChatRail.tsx}}`.

---

### 2026-06-03 — Déclenchement DÉTERMINISTE du reasoner (code, pas jugement LLM)

**Décision :** Le déclenchement de `call_agent_reason` passe de « soft » (Sonnet
décide via un tool) à **déterministe (code)**. Après `call_agent_routing`, si
`routed_percent < 100`, l'orchestrateur (`orchestrator.ts`) lance **lui-même** le
reasoner. `call_agent_reason` est **retiré de `ACTIVE_PCB_TOOLS`** → Sonnet ne le
voit plus, ne peut pas l'appeler (zéro double-appel) ; son handler reste actif,
invoqué par code. Le board débloqué est fusionné dans le tool_result du routage
(`mergeRescueIntoRouting`, même tool_use_id → API Anthropic valide).

**Pourquoi :** « faut-il secourir le routage ? » est une **règle métier à seuil**
(pct < 100), pas un jugement → doit vivre dans le code, pas dans un prompt. Gains :
garantie de déclenchement (plus de board incomplet livré silencieusement, cf.
« NEVER accepter routing < 100% »), jamais d'appel à tort à 100% (coût Haiku),
1 itération Sonnet économisée, décision **testable** (TDD). Le jugement LLM reste
là où il a de la valeur : **à l'intérieur** du reasoner (quel composant déplacer).

**Garde anti-régression :** `mergeRescueIntoRouting` n'adopte le résultat du
reasoner que s'il **améliore** (pct ≥ routage + board présent) — un reasoner
indisponible (0%) ne fait jamais régresser 95% → 0%.

**Visibilité conservée :** event SSE `reasoning` + `pcb_state` (board final) émis ;
ChatRail temps-réel inchangé. « un seul l'orchestrateur » renforcé (le code maître,
plus l'humeur de Sonnet).

**Écarté :** garder le trigger LLM (non-déterministe, non-testable) ; double trigger
code+LLM (risque double-spend) → on retire le tool de la liste à la place.

**Fichiers concernés :** `packages/agents/src/{orchestrator.ts (shouldRescueRouting,
mergeRescueIntoRouting, trigger), tools.ts (filtre ACTIVE_PCB_TOOLS + note),
prompts.ts (reasoner = automatique), tests/orchestrator-reason.test.ts}`. Commit 13b919c.

---

### 2026-06-14 — Netlist PCB fragmenté → RÉSOLU à la racine

**Décision :** corriger la fragmentation du netlist (83 nets au lieu de ~12, routage
bloqué ~0%) à deux endroits : (1) `tools/schematic.py` pose les labels de net À LA
POSITION EXACTE de la pin via `sym.pin_position()` (au lieu d'un offset arbitraire
`symbol_x+8`) ; (2) `tools/pcb.py` niveau-1 importe `kicad_tools.operations.netlist`
(le bon module) au lieu de `kicad_tools.workflow._netlist` (inexistant).

**Pourquoi :** les labels hors-pin → `extract_netlist()` isolait chaque pin dans son
propre `Net-(REF-PinN)`. ET l'import niveau-1 cassé → fallback kicad-cli systématique
qui fragmentait aussi. Les deux causes empêchaient tout routage réel.

**Écarté :** patcher kicad-cli ; le vrai fix est en amont (schéma + import).

**Fichiers concernés :** `services/kicad/tools/{schematic.py, pcb.py}` +
`tests/{test_schematic_fallback.py, test_pcb_netlist.py}`. PR #35, commit ef64e4f.

---

### 2026-06-14 — Update kicad-tools → main HEAD + patch charmap déplacé hors lib

**Décision :** mettre à jour le snapshot vendoré kicad-tools (gitignoré) vers
`main` HEAD (commit upstream fda275d, ~718 fichiers routeur). Le patch charmap
Windows est DÉPLACÉ de la lib vers notre wrapper `tools/kct_route.py` (force
`PYTHONUTF8=1` dans l'env du subprocess kct) — durable, survit aux updates.

**Pourquoi :** récupérer les correctifs routeur upstream ; éviter de re-scrubber les
emojis dans ~5 fichiers `router/*` à chaque update (whack-a-mole).

**Écarté :** rester sur le tag v0.13.0 (avril) = plus ancien que notre snapshot
(downgrade). Mesure de qualité routage en local impossible (pas de backend C++).

**Fichiers concernés :** `services/kicad/{tools/kct_route.py, DEPENDENCIES.md}` +
kicad-tools/ (gitignoré). PR #35, commit 73129f8.

---

### 2026-06-15 — Placement en 2 phases dans l'agent (PlacementOptimizer → CMA-ES)

**Décision :** l'agent placement (⑤) fait DEUX phases. Phase 1 = `PlacementOptimizer`
(outil physique : clustering + connecteurs J*/P* ancrés et clampés dans le contour)
prépare le terrain. Phase 2 = `kct optimize-placement --strategy cmaes` (500 itérations,
`seed_method="current"`) raffine DEPUIS la Phase 1. Connecteurs restaurés (re-ancrage)
après la Phase 2. gen_pcb ne fait plus qu'une grille de départ.

**Pourquoi :** combiner placement physique (groupes + contraintes mécaniques) et
optimisation génétique (wirelength). 2 bugs lib bloquaient ce flux, corrigés :
- **patch #5** `_write_placements_to_pcb` 2-pass : le writer officiel n'écrivait
  JAMAIS les positions CMA-ES (`(at)` précède `(property Reference)` en KiCad 8/9
  → ref inconnue au moment du `(at)`) → CMA-ES tournait en no-op silencieux.
- **patch #6** `seed_method="current"` : le seed officiel ne connaît que
  force-directed/random → CMA-ES re-seedait et JETAIT la Phase 1. Ajout d'un seed
  construit depuis `fp.position` (board-relative) → Phase 1 nourrit Phase 2.

**Écarté :** force-directed dans gen_pcb (redondant, CMA-ES re-seede) ; CMA-ES seul
sans Phase 1 (perd le clustering + l'ancrage mécanique des connecteurs).

**Fichiers concernés :** `services/kicad/tools/{placement.py, pcb.py}` +
`tests/test_placement.py` + 2 patches kicad-tools (gitignoré, doc DEPENDENCIES.md
#5/#6). PR #36, commits 9919f54 + a300283. ⚠️ kicad-tools a désormais **5 patches lib**.

---

### 2026-06-16 — Phase 2 placement = EvolutionaryPlacementOptimizer (natif, retrait 2 patches)

**Décision :** la Phase 2 de l'agent placement passe de CMA-ES
(`kct optimize-placement --strategy cmaes --seed current`) à
`EvolutionaryPlacementOptimizer.optimize_hybrid()` (API native kicad-tools).
Phase 1 (PlacementOptimizer, physique locale, clustering générique +
connecteurs ancrés) et Phase 2 (GA global, fitness ROUTABILITÉ, `enable_clustering`
qui PRÉSERVE les clusters) sont désormais **complémentaires**. Hardcodes de
groupes (U2/Y1/C10…) retirés → clustering natif générique sur tout board.

**Pourquoi :** CMA-ES `optimize-placement` minimise le wirelength seul → tassait
le board (cramped), dégradait la Phase 1 (l'utilisateur l'a vu visuellement) et
n'améliorait pas le routage (Phase 1 et Phase 2 routaient pareil, 33%).
`EvolutionaryPlacementOptimizer` a la routabilité dans sa fitness (récompense
l'espacement → pas de tassement) et préserve les clusters fonctionnels détectés
(TIMING quartz+caps, POWER découplage…). **Bénéfice maintenance** : on n'appelle
plus `kct optimize-placement` → les **2 patches lib CMA-ES (#4 writer 2-pass,
#5 seed=current) sont SUPPRIMÉS** → kicad-tools repasse de 5 à **3 patches**.

**Écarté :** patcher CMA-ES pour le rendre cluster-aware (block-groups) — risqué
et inutile, l'EVO natif fait déjà mieux (routabilité incluse). Garder les 2
patches CMA-ES « au cas où » — dette inutile, lib remise pure upstream.

**Note clé (routage) :** le plafond 33%/75% en local n'est PAS le placement —
c'est le **backend C++ non compilé** (pas de g++/cl en local). Prouvé : le board
benchmark *facile* du dépôt (`charlieplex`, 100% attendu) tombe à 75% en Python
pur. Le dépôt route à 100% car il compile le C++ (`kct build-native`). Cirqix le
compile en Docker (Dockerfile) → validation routage = Docker, pas local.

**Fichiers concernés :** `services/kicad/tools/placement.py` +
`tests/test_placement.py` + `tools/pcb.py` (commentaire) + reverts lib
(`cli/optimize_placement_cmd.py`, `cli/parser.py` → purs upstream) +
docs (`DEPENDENCIES.md`, `CLAUDE.md`). PR #36, commits 8b13e74 + 7676c4d + suiv.

---

### 2026-06-18 — Placement = natif kicad-tools ACCEPTÉ + bug write_to_pcb corrigé

**Décision :** accepter le placement **100% natif kicad-tools** tel quel — un seul
appel `OptimizationWorkflow(pcb, WorkflowConfig(strategy="hybrid",
enable_clustering=True, fixed_refs=<J*/P*>, generations=100, population=50,
iterations=1000)).run()` puis **`.write_to_pcb()`** puis `pcb.save()`. La stratégie
`hybrid` enchaîne en INTERNE la phase évolutionnaire (GA, groupement) + le
raffinement physique force-directed. **Pas de snap déterministe** : les bypass
caps/quartz finissent à 13-28mm du MCU — accepté comme routable.

**Bug critique corrigé (commit 243b26f) :** `auto_place` appelait
`OptimizationWorkflow(...).run()` puis `pcb.save()` **sans `write_to_pcb()`**.
`run()` calcule l'optimisation mais N'ÉCRIT PAS les positions dans le PCB →
placement **no-op** (0/17 composant déplacé, board sauvé identique à la
génération — repéré visuellement sur le rendu). Régression introduite par
`d43ab8b` (« auto_place 100% natif ») : le refactor vers `OptimizationWorkflow`
a perdu l'appel `write_to_pcb()` que faisait l'ancienne version
(`PlacementOptimizer...run().write_to_pcb()`). Fix : garder la réf workflow +
`workflow.write_to_pcb()` avant `save()`. Validé : **16/17 composants déplacés**
sur le board STM32 (vs 0 avant).

**Pourquoi accepter le natif sans snap :** le snap déterministe collait Y1 à
7.8mm mais c'est du code custom à maintenir hors API native. Choix produit :
rester 100% natif (règle CLAUDE.md « usage natif kicad-tools »), placement
routable suffisant pour avancer. L'adjacence serrée « pro » est reportée en
Phase 6 (RL_PCB), pas via un patch snap.

**Écarté :**
- Réintroduire le snap déterministe (`c462178` `_snap_*`) — code custom, retiré.
- Re-benchmarker les optimiseurs natifs pour l'adjacence — déjà fait
  (force-directed ~20mm, hybrid 15mm, cmaes 14.4mm, EVO 14mm), tous à 10-15mm.

**Test de garde (TDD) :** `test_auto_place_actually_moves_movable_components` —
3 résistances mobiles empilées doivent être séparées (RED sans `write_to_pcb`,
GREEN avec). Comble le trou : les tests existants ne couvraient que les
connecteurs (`fixed_refs`, immobiles par design) → le no-op passait inaperçu.

**Fichiers concernés :** `services/kicad/tools/placement.py` +
`services/kicad/tests/test_placement.py` + `CLAUDE.md`. PR #36, commit 243b26f.

---

### 2026-06-18 (suite) — Non-déterminisme hybrid+cluster → kct placement fix natif chaîné

**Constat :** `OptimizationWorkflow` (hybrid+cluster) n'a pas de seed fixe.
Variance test : 5 runs sur le board STM32 réel (même input) →
**8 / 0 / 3 / 0 / 5 conflits** détectés par `PlacementAnalyzer.find_conflicts()`
(`kct placement check`), dont des erreurs ERROR (pad clearance ≤0 = court-circuit
réel). Conclusion : l'algo natif est correct mais **stochastique** — explique
les deux observations contradictoires de l'utilisateur (« hier c'était top » /
« aujourd'hui il y a un problème ») : les deux étaient vrais, simplement des
tirages différents du même process.

**Décision :** chaîner une réparation native **après** l'optimisation plutôt que
la relancer. `tools/placement.py::_resolve_remaining_conflicts()` appelle
`PlacementAnalyzer.find_conflicts()` puis, si erreurs ERROR détectées,
`PlacementFixer(strategy=SPREAD, anchored=<connecteurs>).iterative_fix()`
(équivalent `kct placement fix` — passes locales de nudge, ~0.05-0.1s).

**Écarté : best-of-N (relancer le GA jusqu'à 0 conflit).** Mesuré : 1 run complet
`auto_place` sur le board STM32 = **97-105s**. Un best-of-6-8 aurait coûté
10-13min — inutilisable en synchrone dans le pipeline agent. La réparation
locale coûte ~0.1s contre 98s pour un nouveau run GA : 1000× moins cher pour
le même résultat (0 erreur).

**Validé :** 3 runs complets `auto_place` sur le board STM32 réel = **0 conflit
/ 0 erreur** sur les 3 (vs 8/0/3/0/5 sans le fix). 100% natif
(`PlacementAnalyzer` + `PlacementFixer` kicad-tools), zéro algo custom.

**Limite non couverte :** la qualité du clustering (cap↔IC, quartz↔MCU) varie
aussi d'un run à l'autre (run3 du variance test : caps à 20-27mm d'un IC) —
`PlacementFixer` ne corrige que les **conflits** (overlap physique), pas la
**qualité** de regroupement fonctionnel. Ce n'est pas un conflit détectable par
`find_conflicts()`, donc hors scope de ce fix — relève de la limite déjà
acceptée de `detect_functional_clusters` (caps 13-28mm du MCU, voir entrée
précédente).

**Test de garde (TDD) :** `test_resolve_remaining_conflicts_removes_pad_clearance_errors`
(déterministe, sans GA — 3 résistances empilées construites directement) +
`test_auto_place_result_has_no_error_conflicts` (intégration, via `auto_place`).
RED confirmé (ImportError) avant l'implémentation, GREEN après (8/8 tests).

**Fichiers concernés :** `services/kicad/tools/placement.py` +
`services/kicad/tests/test_placement.py` + `CLAUDE.md`. Commit `d16c50d`.

---

### 2026-06-18 (suite) — Phase 3 « Géomètre » CMA-ES + filet de sécurité revert

**Contexte :** demande utilisateur d'ajouter une étape CMA-ES finale, en référence
à `docs/cirqix-full-resume.md` (« Le Mathématicien — décale les puces d'un
demi-millimètre… élimine 100% des chevauchements »). Avant cette session, le
CMA-ES avait déjà été essayé (Phase 2, 2026-06-15/16) puis retiré au profit de
l'EVO natif seul (`c462178`, `095d564`).

**Décision :** réintroduire le CMA-ES, mais comme **3e étape de raffinement**
(Géomètre) après Architecte (hybrid+cluster) + Inspecteur — pas un remplacement.
`tools/placement.py::_refine_with_cmaes()` appelle `run_optimize_placement(
seed_method="current")` sur le board déjà placé, puis restaure la position des
connecteurs (le CLI natif n'a pas de verrouillage par référence).

**TDD :** `test_refine_with_cmaes_separates_overlap_and_preserves_anchored` +
`test_auto_place_keeps_connector_anchored_with_cmaes_step` — RED (ImportError)
puis GREEN.

**Benchmark 1 — pipeline complet (GA aléatoire + CMA-ES, board STM32 réel,
17 composants) :** le CMA-ES a introduit 17 conflits que l'Inspecteur (10 passes)
n'a PAS pu résorber entièrement (oscillation 17→15→12→6→2→5→3→5→2→6→5,
**3 ERROR résiduels**) — régression contre l'invariant « 0 erreur garanti »
établi à l'entrée précédente. Détectée avant livraison grâce à la vérification
explicite des conflits post-CMA-ES (pas juste post-Architecte).

**Décision corrective :** filet de sécurité dans `auto_place()` — snapshot du
board juste après Architecte+Inspecteur (0 erreur garanti), tentative CMA-ES,
ré-Inspecteur ; si des ERROR subsistent, restauration du snapshot (le CMA-ES
est purement et simplement annulé pour ce run). Test de garde :
`test_auto_place_reverts_cmaes_if_unresolved_conflicts_remain` (RED confirmé
sur l'implémentation sans filet, GREEN après). Suite complète : 11/11.

**Benchmark 2 — ablation contrôlée (CMA-ES seul, sur un board STM32 déjà
placé+fixé par l'Architecte, 0 erreur en entrée) :** isole l'effet du CMA-ES
sans le bruit du tirage aléatoire du GA entre deux runs.
- Avant : 0 ERROR / 0 WARNING.
- CMA-ES brut (9.4s) : 1 ERROR / 6 WARNING — le modèle de faisabilité interne
  du CMA-ES (AABB) ne coïncide pas exactement avec `DesignRules` de
  `PlacementAnalyzer`.
- Après Inspecteur : 0 ERROR / 2 WARNING (1 erreur réparée, 0.05-0.1s).
- Adjacence : 8/10 paires resserrées — Y1-U2 16.73→7.50mm (-9.23), C11-Y1
  17.47→13.34mm (-4.13), C1-U1 8.37→4.51mm (-3.86), C2-U1 10.09→6.87mm
  (-3.22). 2 légèrement dégradées : C13-U2 +1.13mm, C3-U1 +1.36mm.

**Vérité sur la citation `cirqix-full-resume.md` :** « élimine 100% des
chevauchements » n'est PAS littéralement vrai pour le CMA-ES seul (il en
introduit, mesuré ci-dessus) — c'est le **pipeline complet avec filet de
sécurité** qui garantit 0 ERROR livré, pas le CMA-ES isolément. « Aligne
parfaitement les broches » n'a pas été mesuré (seule l'adjacence centre à
centre l'a été) — affirmation non vérifiée, à ne pas répéter comme un fait
établi sans benchmark dédié.

**Écarté :**
- Best-of-N sur le CMA-ES (relancer jusqu'à 0 conflit) — même raisonnement
  que l'entrée précédente pour le GA : trop lent en synchrone.
- Verrouillage natif par référence dans le CLI CMA-ES — pas exposé par
  `run_optimize_placement` ; contournement par restauration post-hoc retenu.

**Fichiers concernés :** `services/kicad/tools/placement.py` +
`services/kicad/tests/test_placement.py` + `CLAUDE.md` +
`services/kicad/DEPENDENCIES.md`. Branche `feat/placement-cmaes`, PR #36.

---

### 2026-06-19 — Bug max_iterations non plafonné + filet de sécurité Option B

**Symptôme observé :** « Architecte good, Final bad » — le board issu de
l'Architecte (① + Inspecteur) était propre, mais le board final livré par
`auto_place()` (après Géomètre + ré-Inspecteur) était visuellement dégradé,
malgré 0 ERROR / 0 WARNING rapportés. Le filet de sécurité de l'entrée
précédente (basé sur le compte d'ERROR) ne s'est PAS déclenché — ce qui a
mis en doute, à tort, le bénéfice du seed `"current"` lui-même.

**Cause racine identifiée :** `_refine_with_cmaes()` appelait
`run_optimize_placement(seed_method="current", time_budget=20.0, ...)` SANS
plafonner `max_iterations` — défaut de la lib = 1000. Vérification dans
`kicad_tools/placement/cmaes_strategy.py` : `seed_method="current"` seede
bien correctement la moyenne initiale du CMA-ES sur la position issue de
l'Architecte (le seed n'était pas le problème). Mais le budget de 20s
laissait largement le temps à 1000 itérations de dériver loin de ce point de
départ : benchmark réel (board STM32, 17 composants, repartant du même run
GA Architecte) → déplacement moyen 7.5mm, max 15mm (jusqu'à 68mm observé sur
un autre run). PAS un micro-raffinement sub-mm comme documenté avant ce fix.

**Fix root-cause :** constante `_CMAES_MAX_ITERATIONS = 30`, passée en kwarg
à `run_optimize_placement`. Benchmark après fix : 2.1-3.1mm moyen,
4.0-11.8mm max, stable sur 5 essais déterministes (board fixture de test :
~9mm à 1000 itérations contre ~5mm à 30).

**TDD :** test renommé `test_refine_with_cmaes_passes_bounded_max_iterations_kwarg`
(wiring, mocké — insuffisant seul, cf. code review ci-dessous) + nouveau
`test_refine_with_cmaes_keeps_displacement_small` (comportemental, CMA-ES
réel non mocké, seuil `< 6.0mm` validé empiriquement avant d'écrire
l'assertion).

**Option B — filet de sécurité additionnel, orthogonal au filet ERROR :**
même avec le fix root-cause en place, le compte d'ERROR seul ne peut
structurellement pas détecter une dérive silencieuse "0 ERROR mais board
dégradé" — c'est exactement le symptôme du bug ci-dessus. Ajout de
`_max_displacement_mm(before_positions, pcb_path, exclude)` : compare la
position de chaque footprint non-ancré entre le snapshot pré-CMA-ES et le
board final. Nouvelle constante `_CMAES_MAX_DISPLACEMENT_MM = 20.0` — si
dépassée, revert vers le snapshot pré-CMA-ES MÊME SI l'Inspecteur rapporte
0 ERROR. TDD : RED confirmé en désactivant temporairement le check
(`if max_disp > seuil` → `if False`), test échouant comme prévu
(`assert 60.1 == 30.099 ± 0.01`), puis GREEN avec le check actif.
Garde de régression : `test_auto_place_reverts_cmaes_if_displacement_exceeds_threshold`.

**Code review (avant merge) :** 1 HIGH trouvé et corrigé —
`_max_displacement_mm()` ignorait silencieusement toute référence présente
sur le board après coup mais absente du snapshot `before_positions`
(renommage/ajout inattendu côté CLI natif) — exactement le genre de cas
qu'un filet de sécurité ne doit jamais exclure silencieusement. Fix :
référence non-matchée → déplacement traité comme infini (`float("inf")`),
revert garanti. Couvre aussi le cas dégénéré `before_positions={}`. Tests :
`test_max_displacement_mm_treats_unmatched_ref_as_infinite`,
`test_max_displacement_mm_empty_before_positions_with_tracked_refs_is_unsafe`.
3 MEDIUM / 2 LOW notés comme follow-ups non bloquants (duplication de
benchmark chiffré CLAUDE.md vs commentaire code — acceptée, CLAUDE.md est
un résumé humain séparé du commentaire source de vérité ; fichier proche de
la limite 400 lignes — à surveiller).

**Incident opérateur (sans perte finale) :** pendant la vérification RED
manuelle, un `git checkout -- tools/placement.py` mal ciblé (censé annuler
uniquement la patch de sabotage temporaire `if False`) a restauré TOUT le
fichier à son dernier état committé, effaçant tout le travail non-committé
de la session (fix max_iterations + Option B). Reconstruit intégralement à
l'identique. **Règle retenue : ne jamais utiliser `git checkout -- <fichier>`
pour annuler une édition précise quand d'autres éditions non-committées
coexistent dans le même fichier.**

**État final :** 17/17 tests `test_placement.py` verts. 100% natif
(paramétrage de `run_optimize_placement`, `_max_displacement_mm` est une
comparaison Python pure, pas un algo de placement).

**Précision — quand l'Inspecteur tourne-t-il exactement :** l'Inspecteur
(`_resolve_remaining_conflicts`) n'est PAS appelé symétriquement "après
chaque étape" — il tourne au plus 2 fois dans `auto_place()` :

```python
# Pass 1 — TOUJOURS, après l'Architecte
_resolve_remaining_conflicts(out, conn)
pre_cmaes_bytes = out.read_bytes()          # snapshot garanti 0 ERROR
pre_cmaes_positions = {...}                  # pour le filet Option B

refine = _refine_with_cmaes(out, conn, ...)  # ② Géomètre (CMA-ES)

# Pass 2 — SEULEMENT si refine["refined"] est True
if refine["refined"]:
    n_err_before, n_err_after = _resolve_remaining_conflicts(out, conn)
    if n_err_after > 0:
        out.write_bytes(pre_cmaes_bytes)     # revert (compte ERROR)
    else:
        max_disp = _max_displacement_mm(...)
        if max_disp > _CMAES_MAX_DISPLACEMENT_MM:
            out.write_bytes(pre_cmaes_bytes) # revert (Option B)
```

| Étape | Inspecteur tourne ? |
|---|---|
| ① Architecte | toujours (pass 1) — garantit 0 ERROR avant de tenter le Géomètre |
| ② Géomètre (CMA-ES) | seulement si `refine["refined"] == True` (le CLI natif a réussi) |
| CMA-ES échoue/lève une exception | pas de pass 2 — le board reste celui du pass 1 (déjà 0 ERROR) |
| CMA-ES réussit mais pass 2 trouve encore des ERROR | board pré-CMA-ES (pass 1) restauré |
| CMA-ES réussit, pass 2 → 0 ERROR, mais déplacement > seuil | board pré-CMA-ES (pass 1) restauré aussi (Option B) |

Le board livré n'est donc réellement le résultat du Géomètre QUE dans le cas :
CMA-ES réussi → Inspecteur pass 2 ramène 0 ERROR → déplacement ≤ seuil. Dans
tous les autres cas, c'est le board garanti par le pass 1 (Architecte +
Inspecteur) qui est livré tel quel. Observé en pratique sur le run STM32
réel (`run_phase3_visual.py`, 2026-06-19) : pass 2 a réparé 1 ERROR → 0, le
filet Option B ne s'est pas déclenché (pas de warning "restauré" dans les
logs) → le board final est bien celui du Géomètre nettoyé.

**Fichiers concernés :** `services/kicad/tools/placement.py` +
`services/kicad/tests/test_placement.py` + `CLAUDE.md`. Branche
`feat/placement-cmaes`, PR #36.

---

### 2026-06-22 — Stratégie de routage = `negotiated` par défaut (agent + projet)

**Décision :** `kct route --strategy negotiated` est la stratégie de routage par
défaut PARTOUT — dans l'agent de prod (`tools/kct_route.py::_run_kct_route`,
`--strategy negotiated`) et pour tout le projet. Les 3 autres stratégies
(`basic`, `monte-carlo`, `evolutionary`) ne sont pas utilisées.

**Pourquoi :** benchmark des 4 stratégies sur le board STM32 placé réel
(`output/phase3/3_final.kicad_pcb`, 2 couches, seed 42, timeout 120s, routeur
Python local — pas de backend C++) :

| Stratégie      | Routé | Temps          | Verdict |
|----------------|-------|----------------|---------|
| basic          | —     | timeout >240s  | inutilisable — A* net-par-net sans rip-up, bloque sur board dense |
| **negotiated** | **56%** | **67s**      | **seule rapide ET viable → défaut** |
| monte-carlo    | —     | trop lente     | exhaustive (N essais randomisés) — hors budget agent |
| evolutionary   | —     | trop lente     | métaheuristique — hors budget agent |

`negotiated` est le meilleur compromis qualité/temps pour le budget agentique
(~60s/routage). C'est aussi le défaut de kicad-tools.

**Comment marche `negotiated` — DEUX NIVEAUX (clé pour lever la confusion)**

On lit à la fois « negotiated ≈ Freerouting » ET « negotiated utilise A* ». Les
DEUX sont vrais : ce sont deux niveaux DIFFÉRENTS de l'algorithme.

```
┌─────────────────────────────────────────────┐
│  NIVEAU 1 — la BOUCLE (la « stratégie »)     │  ← « proche de Freerouting »
│  rip-up & reroute + pénalités de congestion  │
│  = algorithme PathFinder (1995)              │
├─────────────────────────────────────────────┤
│  NIVEAU 2 — la RECHERCHE d'un net (A*)        │  ← « utilise A* »
│  trouve le chemin le plus court d'UN net     │
└─────────────────────────────────────────────┘
```

**NIVEAU 1 — la BOUCLE (= la « stratégie »)** : rip-up & reroute + pénalités de
congestion. C'est l'algorithme **PathFinder** (McMurchie & Ebeling, 1995, routage
FPGA). Principe : on route TOUS les nets une 1ʳᵉ fois en autorisant les
chevauchements (overlap) ; puis à chaque itération on AUGMENTE le coût des
cellules surchargées → les nets « négocient » l'espace, les moins contraints
cèdent et se re-routent ailleurs (rip-up & reroute). On itère jusqu'à 0 overlap.
C'est CE niveau qui ressemble à Freerouting (lui aussi fait du *negotiated
congestion routing*).

**NIVEAU 2 — la RECHERCHE d'UN net (= A*)** : chaque fois qu'on (re)route un net,
on cherche son plus court chemin sur la grille, pondéré par les coûts de
congestion du niveau 1. C'est un **A\*** classique (heuristique distance de
Manhattan). C'est CE niveau qui « utilise A* ».

**Le lien :** NIVEAU 1 décide QUI route et avec quelles pénalités (la boucle qui
négocie) ; NIVEAU 2 trouve COMMENT router un net donné (le pathfinding). A* est
le moteur de recherche APPELÉ par la boucle PathFinder — pas une alternative à
elle. D'où la confusion levée :
- `basic` = NIVEAU 2 SEUL (A* net par net, sans la boucle de négociation) →
  bloque vite sur les boards denses (premier net routé « égoïstement » barre la
  route aux suivants, aucun rip-up pour corriger) → le timeout du benchmark.
- `negotiated` = NIVEAU 1 **+** NIVEAU 2 → les nets se réorganisent → bien plus
  de complétion.

**Backend C++ :** le NIVEAU 2 (A*) a un backend C++ (`router_cpp.*.so`, build
`kct build-native`) 10-100× plus rapide que le Python pur. En local sans ce
backend, le 56%/67s ci-dessus est un PLANCHER ; en Docker prod (C++ + escalade
`--auto-layers`) le routage va beaucoup plus loin / plus vite.

**Écarté :** `basic` (pas de rip-up → échoue sur dense), `monte-carlo` /
`evolutionary` (exhaustifs/métaheuristiques → trop lents pour le budget agent).

**Fichiers concernés :** `services/kicad/tools/kct_route.py`
(`_run_kct_route` → `--strategy negotiated`, déjà en place). Benchmark sur
`examples/stm32-validation/output/phase3/3_final.kicad_pcb`.

---

## Template pour la prochaine décision

```
### [DATE] — [Sujet]

**Décision :**

**Pourquoi :**

**Écarté :**

**Fichiers concernés :**
```
