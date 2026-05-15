┌─────────────────────────────────────────────────────────────────────────────┐
│                    PIPELINE EDA AI - WORKFLOW COMPLET                        │
└─────────────────────────────────────────────────────────────────────────────┘

PHASE 1: INTENTION & SPECIFICATION
┌─────────────┐     ┌─────────────────┐     ┌─────────────────────────────┐
│  Input User │────▶│  NLP Parser     │────▶│  Structured Spec (JSON)       │
│  (Text/Voice│     │  (LLM Agent)    │     │  - Fonctionnalités            │
│   /Upload)  │     │                 │     │  - Contraintes élec           │
│             │     │                 │     │  - Budget, Timeline           │
└─────────────┘     └─────────────────┘     └─────────────────────────────┘
                                                       │
                                                       ▼
                                              ┌─────────────────┐
                                              │  Spec Validator │
                                              │  Agent          │
                                              │  (Checks cohérence│
                                              │   faisabilité)  │
                                              └─────────────────┘

PHASE 2: SCHÉMATIQUE IA (Netlist Generation)
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  ┌─────────────┐    ┌─────────────────┐    ┌─────────────────────────────┐  │
│  │  Spec JSON  │───▶│  Component      │───▶│  Schematic Generator Agent  │  │
│  │             │    │  Selector Agent │    │  (Graph Neural Network)   │  │
│  │             │    │                 │    │                             │  │
│  │             │    │  - Query DB     │    │  - Place symbols            │  │
│  │             │    │  - BOM optim    │    │  - Route wires              │  │
│  │             │    │  - Alt sourcing │    │  - Annotate netlist         │  │
│  └─────────────┘    └─────────────────┘    └─────────────────────────────┘  │
│                                                                             │
│  Output: Netlist (SPICE/EDIF) + BOM préliminaire                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

PHASE 3: PLACEMENT IA (Floorplanning)
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  ┌─────────────┐    ┌─────────────────┐    ┌─────────────────────────────┐  │
│  │  Netlist +  │───▶│  Constraint     │───▶│  Placement Agent            │  │
│  │  Footprints │    │  Extractor      │    │  (Reinforcement Learning)   │  │
│  │             │    │                 │    │                             │  │
│  │             │    │  - Datasheet    │    │  - Thermal zones            │  │
│  │             │    │    parsing      │    │  - Signal groups            │  │
│  │             │    │  - Design rules   │    │  - Power distribution       │  │
│  │             │    │  - EMI rules      │    │  - Mechanical constraints   │  │
│  └─────────────┘    └─────────────────┘    └─────────────────────────────┘  │
│                                                                             │
│  Output: Placement X,Y,Rotation + Constraint file                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

PHASE 4: ROUTAGE IA (PCB Routing)
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  ┌─────────────┐    ┌─────────────────┐    ┌─────────────────────────────┐  │
│  │  Placement  │───▶│  Route Planner  │───▶│  Multi-Agent Router         │  │
│  │  + Netlist  │    │  Agent          │    │  (Swarm Intelligence)       │  │
│  │             │    │                 │    │                             │  │
│  │             │    │  - Layer assign │    │  ┌─────────┐ ┌─────────┐   │  │
│  │             │    │  - Via strategy │    │  │ Signal  │ │ Power   │   │  │
│  │             │    │  - Impedance    │    │  │ Agent   │ │ Agent   │   │  │
│  │             │    │    targets      │    │  └────┬────┘ └────┬────┘   │  │
│  │             │    │                 │    │       │           │         │  │
│  │             │    │                 │    │  ┌────┴───────────┴────┐    │  │
│  │             │    │                 │    │  │   Conflict Resolver │    │  │
│  │             │    │                 │    │  │   (DRC Supervisor)  │    │  │
│  │             │    │                 │    │  └─────────────────────┘    │  │
│  └─────────────┘    └─────────────────┘    └─────────────────────────────┘  │
│                                                                             │
│  Output: Routed PCB (Gerber-ready) + DRC report                             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

PHASE 5: VÉRIFICATION & OPTIMISATION
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  ┌─────────────┐    ┌─────────────────┐    ┌─────────────────────────────┐  │
│  │  Routed PCB │───▶│  Simulation     │───▶│  Optimization Agent         │  │
│  │             │    │  Agents (parallel)│  │  (Genetic Algorithm + NN)   │  │
│  │             │    │                 │    │                             │  │
│  │             │    │  ┌───────────┐  │    │  - Length matching          │  │
│  │             │    │  │ Thermal   │  │    │  - Via reduction          │  │
│  │             │    │  │ (FEM)     │  │    │  - Copper balance           │  │
│  │             │    │  └───────────┘  │    │  - EMI minimization         │  │
│  │             │    │  ┌───────────┐  │    │                             │  │
│  │             │    │  │ Signal    │  │    │                             │  │
│  │             │    │  │ Integrity │  │    │                             │  │
│  │             │    │  │ (SPICE)   │  │    │                             │  │
│  │             │    │  └───────────┘  │    │                             │  │
│  │             │    │  ┌───────────┐  │    │                             │  │
│  │             │    │  │ Power     │  │    │                             │  │
│  │             │    │  │ Integrity │  │    │                             │  │
│  │             │    │  │ (IR Drop) │  │    │                             │  │
│  │             │    │  └───────────┘  │    │                             │  │
│  └─────────────┘    └─────────────────┘    └─────────────────────────────┘  │
│                                                                             │
│  Output: PCB optimisé + Rapports de simulation                                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

PHASE 6: FABRICATION & LIVRAISON
┌─────────────┐    ┌─────────────────┐    ┌─────────────────────────────┐
│  Final PCB  │───▶│  CAM Processor  │───▶│  Fabrication Connector        │
│  + BOM      │    │  (Gerber/ODB++) │    │  (JLCPCB, PCBWay, Eurocircuits)│
│             │    │                 │    │                              │
│             │    │  - Panelization │    │  - Quote comparison          │
│             │    │  - Stencil gen  │    │  - Order placement           │
│             │    │  - Pick&Place   │    │  - Tracking                  │
│             │    │                 │    │  - Commission (revenu!)      │
└─────────────┘    └─────────────────┘    
└─────────────────────────────┘

Le Parser Spec (ou Specification Parser) est le premier agent IA de votre pipeline EDA. C'est lui qui transforme une description "humaine" en instructions machines compréhensibles


┌─────────────────────────────────────────────────────────────┐
│                    SPEC PARSER PIPELINE                      │
└─────────────────────────────────────────────────────────────┘

Input brut (texte/voice/PDF/image)
        │
        ▼
┌───────────────┐
│  PREPROCESS   │
│               │
│  - Nettoyage  │
│  - OCR (si   │
│    image/PDF) │
│  - Speech-to- │
│    text (si   │
│    voice)     │
└───────┬───────┘
        │
        ▼
┌───────────────┐
│  EXTRACTION   │  ← LLM (GPT-4o / Claude) avec prompt engineering
│               │
│  - Entités    │     "Extrais toutes les specs techniques
│    nommées    │      de ce texte et structure-les en JSON"
│  - Valeurs    │
│  - Unités     │
│  - Relations  │
└───────┬───────┘
        │
        ▼
┌───────────────┐
│  VALIDATION   │  ← Règles métier + LLM critique
│               │
│  - Coherence  │     "Cette spec est-elle réalisable ?
│    check      │      Y a-t-il des contradictions ?"
│  - Completeness│
│  - Faisabilité│
│    estimée    │
└───────┬───────┘
        │
        ▼
┌───────────────┐
│  ENRICHISSEMENT │ ← RAG (Retrieval Augmented Generation)
│                 │
│  - Complète     │     "Basé sur des designs similaires,
│    avec defaults│      ajoute les specs implicites"
│  - Ajoute       │
│    contraintes  │
│    standards    │
│  - Suggère      │
│    alternatives │
└───────┬───────┘
        │
        ▼
   JSON structuré validé



   L'Orchestrateur est le cerveau central de votre système multi-agents. C'est lui qui coordonne tous les agents EDA (Spec, Schematic, Placement, Routing, Verify) comme un chef d'orchestre dirige les musiciens.


   1. Spec Parser — Extraction et structuration
Outils NLP/LLM


2. Schematic — Génération de schémas et netlists
SKiDL (Python → Netlist)
PySpice (Simulation circuit)

3. Placement — Positionnement des composants
KiCad Python API (Placement natif
pcbnew

OR-Tools (Google) — Optimisation contraintes


4. Routing — Génération des pistes
FreeRouting (Java, open source)
5. Netlist — Formats et manipulation
Conversion entre formats

6. DRC — Design Rule Check
KiCad DRC (Natif)

pcbnew


| Priorité | Outil                  | Rôle                          | Coût                 |
| -------- | ---------------------- | ----------------------------- | -------------------- |
| 1        | **KiCad + Python API** | Placement, DRC, export Gerber | Gratuit              |
| 2        | **SKiDL**              | Génération netlist            | Gratuit              |
| 3        | **FreeRouting**        | Routage baseline              | Gratuit              |
| 4        | **claude**         | Spec parser                   | ~0.01€/appel         |
| 5        | **Claude SDK**          | Orchestration                 | Gratuit              |
| 6        | **Ray RLlib**          | RL custom routing             | Gratuit (GPU payant) |
| 7        | **PySpice**            | Simulation                    | Gratuit              |



┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  SPEC       │────▶│  SCHEMATIC  │────▶│  NETLIST    │
│  (texte)    │     │  AGENT      │     │  (fichier)  │
│             │     │             │     │             │
│             │     │ "Il me faut │     │ "R1 1 2 1k" │
│             │     │  un R 1k    │     │ "C1 2 0 10u"│
│             │     │  entre pin1 │     │ "U1 3 4 5"  │
│             │     │  et GND"    │     │             │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                              ┌────────────────┼────────────────┐
                              ▼                ▼                ▼
                         ┌─────────┐    ┌─────────┐     ┌─────────┐
                         │PLACEMENT│    │SIMU     │     │DRC      │
                         │ lit     │    │SPICE    │     │vérifie  │
                         │positions│    │lit     │     │connectiv│
                         └─────────┘    └─────────┘     └─────────┘


Architecture recommandée : Hybrid??


┌─────────────────────────────────────────────────────────────────┐
│                     FRONTEND (React/Next.js)                   │
│                                                                │
│  ┌──────────────┐      ┌──────────────┐      ┌─────────────┐ │
│  │  tscircuit   │─────▶│  Viewer 3D   │─────▶│  Export     │ │
│  │  (édition    │      │  (WebGL)     │      │  KiCad      │ │
│  │   visuelle)  │      │              │      │  (direct)    │ │
│  └──────────────┘      └──────────────┘      └─────────────┘ │
│                                                                │
│  L'utilisateur voit et édite le circuit en temps réel          │
│  dans le navigateur, sans backend                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ WebSocket / API
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     BACKEND (Python/FastAPI)                     │
│                                                                │
│  ┌──────────────┐      ┌──────────────┐      ┌─────────────┐   │
│  │  Agent IA    │─────▶│  SKiDL       │─────▶│  Netlist    │   │
│  │  (LLM/RL)    │      │  (génération │      │  (KiCad     │   │
│  │              │      │   netlist)   │      │   XML/SPICE)│   │
│  └──────────────┘      └──────────────┘      └─────────────┘   │
│                                                                │
│  L'IA génère du code Python SKiDL pour la robustesse          │
│  et la compatibilité avec l'écosystème EDA                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     SYNC (Optionnel)                             │
│                                                                │
│  Backend génère netlist → Frontend tscircuit l'affiche          │
│  Frontend édite circuit → Backend re-génère via SKiDL           │
│                                                                │
└─────────────────────────────────────────────────────────────────┘

Architecture Frontend : KiCanvas + tscircuit?