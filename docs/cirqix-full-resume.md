# ⬡ Cirqix.ai — Résumé complet startup

---

## IDENTITÉ

- Nom : Cirqix.ai
- Prononciation : "Lay-rix"
- Signification : Layer (couche PCB) + -ix (tech)
- Domaine : cirqix.ai — Cloudflare ~33$/an
- Tagline : "Every layer, perfectly designed by AI"
- Positionnement : La puissance d'Altium sans payer 3000€/an

---

## CIRQIX EST UN AGENT — PAS UN CHATBOT

Un chatbot répond à des questions. Un agent agit dans le monde réel.

Cirqix est un agent IA autonome qui reçoit un objectif ("crée ce PCB") et exécute toutes les étapes nécessaires jusqu'au résultat final sans intervention humaine — il planifie, appelle des outils, observe les résultats, corrige les erreurs, et boucle jusqu'à obtenir un PCB DRC-clean prêt à fabriquer. Il peut même commander la fabrication directement chez JLCPCB sans quitter le chat.

Boucle agentique complète :
Percevoir → Planifier → Agir → Observer → Corriger → Recommencer
jusqu'à DRC propre + Gerbers exportés + commande JLCPCB ✅

---

## LE PRODUIT

- Concept : SaaS web 100% cloud de conception PCB via langage naturel
- Moteur PCB : Circuit-Synth (Python, génère .kicad_sch + .kicad_pcb natifs) + KiCad (pro multi-couches)
- Placement auto : 2 phases — Phase 1 PlacementOptimizer (clustering + connecteurs ancrés) → Phase 2 CMA-ES (kct optimize-placement --strategy cmaes, seed=current) → re-ancrage connecteurs
- Routage auto : kicad-tools A* Python (≤30 nets routables) → Freerouting REST API 1 JVM (circuits complexes) → subprocess → GND plane
- Couches : 2 à 8 couches selon le plan
- Exports : .kicad_pcb + .kicad_sch + Gerber + BOM + PDF + STEP 3D
- Viewer Schéma + PCB : KiCanvas (rendu natif KiCad dans le navigateur)
- Viewer 3D : Three.js (fichier STEP, rotation libre)
- Zéro installation requise

---

## PIPELINE 8 AGENTS — 100% INVISIBLE (mis à jour 2026-05-30)

L'utilisateur ne sait jamais quel moteur tourne derrière.
Orchestrateur Sonnet 4.6 · 8 agents Haiku 4.5 · max 15 itérations · SSE streaming

```
① call_agent_schema    → .kicad_sch (schéma électrique uniquement)
     Path A : Haiku → Python circuit_synth → Docker /schematic/execute → .kicad_sch
     Path B : Haiku → JSON → POST /schematic/generate :
       ① circuit_synth pip · ② kicad-tools Schematic · ③ TypeScript S-expr
     Erreur  : status:'error' si les deux échouent (jamais de faux schéma)

② call_agent_erc       → validation électrique
     ① kicad-tools validate (pur Python) · ② kicad-cli sch erc · ③ TS fallback

③ call_agent_footprint → 1 appel par composant non résolu
     Cascade : KiCad libs → pgvector cache → LCSC → Haiku IA

④ call_agent_gen_pcb   → .kicad_pcb (généré après footprints résolus)
     ① kicad-tools PCBFromSchematic · ② pcbnew direct · ③ TypeScript S-expr
     Primaire : Docker kicad_gen.py → .kicad_pcb
     Fallback : runCircuitSynthEngine() TypeScript inline

⑤ call_agent_placement → positions X/Y/rotation — 2 PHASES dans l'agent :
     Phase 1 : PlacementOptimizer (clustering + connecteurs J*/P* ancrés/clampés)
     Phase 2 : kct optimize-placement --strategy cmaes (500 itér, seed=current)
               → raffine DEPUIS la Phase 1 (patch lib #6)
     Re-ancrage : positions connecteurs restaurées post-CMA-ES
     Filet : place_unplaced(cluster=True) si footprints hors-carte (-1000)

⑥ call_agent_routing   → traces + plans de masse (5 niveaux)
     ① kicad-tools A* negotiated (≤30 nets, 60s) · zones GND+VCC injectées
     ② Freerouting REST API (1 JVM persistante port 37864, RAM 400MB fixe)
     ③ Freerouting subprocess (1 JVM par job, fallback)
     ④ kicad-tools A* negotiated SANS LIMITE (tous circuits, Freerouting absent)
     ⑤ GND plane seulement (dernier recours)

⑦ call_agent_drc       → DRC_CLEAN (boucle max 3×)
     ① kicad-tools 27 règles JLCPCB (pur Python)
     ② kicad-cli pcb drc auto-fix max 3× (si erreurs persistent)

⑧ call_agent_export    → Gerbers + BOM JLCPCB + CPL → Supabase Storage
     ① kicad-tools --mfr jlcpcb (GTL/GBL/GKO + BOM LCSC + CPL rotations)
     ② kicad-cli pcb export standard (fallback)
     ③ BOM CSV seulement (kicad-cli absent)
```

Résultat : fichiers KiCad natifs + Gerbers RS-274X + JLCPCB-ready ✅

---

## FOOTPRINT INTROUVABLE — CIRQIX GÉNÈRE AUTOMATIQUEMENT

Cascade de recherche de l'agent Footprint (8 étapes) :

1. Cherche dans librairies KiCad officielles
2. Cherche sur SnapMagic API (millions de composants)
3. Cherche sur Octopart (Digi-Key, Mouser, LCSC)
4. Télécharge la datasheet PDF depuis le web
5. Claude Vision lit les dimensions du package
6. Génère le fichier .kicad_mod complet
7. Valide les dimensions vs datasheet
8. Sauvegarde dans la librairie privée de l'utilisateur ✅

Génération footprint = 3 crédits (plan Maker+)

### Dashboard Footprint Library (app.cirqix.ai/footprints)

Chaque utilisateur a sa propre librairie privée de footprints :

- Badge source : KiCad officiel / SnapMagic / Octopart / Généré IA Claude
- Viewer inline PixiJS : aperçu 2D pads + courtyard + silkscreen
- Validation manuelle : l'utilisateur confirme les dimensions
- Librairie communautaire : footprints validés partagés avec tous les users → effet de réseau
- Recherche sémantique pgvector : "régulateur 3.3V QFN" → trouve les footprints correspondants
- Export .kicad_mod : plan Pro uniquement

Plus il y a d'utilisateurs → plus la librairie est complète → avantage compétitif défendable.

---

## CLAUDE API — UTILISATION DÉTAILLÉE

### 3 modes d'utilisation :

1. Messages API — boucle agentique principale
   - Appels successifs avec tool calling
   - stop_reason "tool_use" → exécute le tool → réinjecte résultat → reboucle
   - stop_reason "end_turn" → PCB livré ✅
   - Max 15 itérations par projet

2. Streaming API — chat temps réel
   - Tokens envoyés mot par mot via WebSocket
   - Même expérience que Claude.ai

3. Vision API — lecture datasheets PDF
   - Document base64 injecté dans le message
   - Agent extrait dimensions et génère le footprint KiCad automatiquement

### Tokens consommés par PCB complet :

- Orchestrateur Sonnet : ~5 000 input + ~1 000 output
- Agent Schéma Haiku : ~2 000 input + ~500 output
- Agent Placement Haiku : ~3 000 input + ~500 output
- Agent Routage Haiku : ~2 000 input + ~300 output
- Agent DRC ×3 Haiku : ~1 500 input + ~300 output
- Agent Export Haiku : ~1 000 input + ~200 output
- TOTAL : ~30 000 tokens → ~0.12€ ✅

### Gestion du contexte agent :

Contexte session stocké dans Redis :
- État courant du PCB (composants, traces, violations DRC)
- Historique complet messages Claude (jusqu'à 30 tours)
- Décisions prises
- Fichiers générés sur Supabase Storage

Compression intelligente : après 10 appels, Claude Haiku résume les anciens tours → garde résumé + 5 derniers tours → -60% coûts sur projets longs.

Gestion des erreurs : l'agent ne s'arrête jamais sur une erreur DRC — il corrige et reboucle jusqu'à maxIterations (15).

---

## 6 AGENTS IA CLAUDE

- Orchestrateur : Claude Sonnet — planifie et délègue
- Agent Schéma : Claude Haiku — génère le netlist JSON
- Agent Placement : Claude Haiku — place les composants (condensateurs < 2mm des VCC, cristal < 10mm MCU)
- Agent Routage : Claude Haiku — pilote Freerouting (angles 45°, plans de masse, paires diff)
- Agent DRC : Claude Haiku — vérifie les règles + correction auto
- Agent Footprint : Claude Haiku — cascade 8 étapes + génération IA depuis datasheet

Coût total : ~0.12€ par PCB complet.
Pas de fine-tuning nécessaire — system prompt + RAG suffisent.

### Exemple prompt structuré — Agent Sélection Composants :

L'agent répond en JSON strict avec : part_number, manufacturer, description, price_lcsc, stock_lcsc, footprint, key_specs, why_good, datasheet_url, tscircuit_import.

---

## FREEROUTING — ROUTAGE AUTOMATIQUE

- Routeur automatique open source en Java
- Reçoit fichier .dsn → route toutes les pistes → retourne .ses réimporté dans KiCad
- Supporte : multi-couches, impédance, paires différentielles, ground pour
- Temps : 30–90 sec (PCB simple) | 3–10 min (8 couches complexe)
- Docker isolé par job utilisateur
- Agent DRC revalide systématiquement après chaque routage

---

## PCBNEW — API PYTHON KICAD

- Module Python embarqué dans KiCad
- Opérations : charger/sauvegarder .kicad_pcb, placer composants au micron, créer traces/vias, définir zones cuivre, lancer DRC, exporter Gerbers
- Chaque worker Python = instance pcbnew isolée par utilisateur
- Microservice : Python + FastAPI sur kicad.cirqix.ai

---

## OCTOPART — BASE DE DONNÉES COMPOSANTS

- Agrège : Digi-Key, Mouser, LCSC, Arrow, 300+ distributeurs
- Données temps réel : prix, stock, datasheet, modèles 3D STEP, footprints KiCad
- pgvector : embeddings composants pour recherche sémantique
- LCSC en priorité (moins cher, livraison rapide)

---

## NGSPICE — SIMULATION ÉLECTRONIQUE

- Simulateur SPICE open source intégré à KiCad
- Simulations disponibles : DC, transitoire, AC (Bode), bruit, Monte Carlo
- Détecte automatiquement : oscillations, surtensions, instabilités
- Plan Pro et Enterprise uniquement — 3 crédits par simulation

---

## VIEWER PCB — PIXIJS + THREE.JS

### Vue 2D — PixiJS (WebGL) :
- 60 FPS, 100 000+ éléments graphiques
- Zoom/pan fluide, layers toggles (F.Cu, B.Cu, SilkS...)
- Sélection composants au clic, mesure distances
- DRC violations cliquables avec localisation exacte
- Viewer footprint inline dans le dashboard librairie

### Vue 3D — Three.js :
- Fichier STEP 3D exporté par KiCad CLI
- Rotation libre, zoom, composants 3D (QFN, condensateurs, connecteurs)
- Éclairage réaliste (vert FR4, cuivre doré, silkscreen blanc)
- Plan Maker+ — 1 crédit

---

## EXPORT GERBER + COMMANDE JLCPCB

### Export via KiCad CLI :
Fichiers générés : F.Cu.gbr, B.Cu.gbr, F.SilkS.gbr, B.SilkS.gbr, F.Mask.gbr, B.Mask.gbr, Edge.Cuts.gbr, board.drl
Tout zippé automatiquement en gerbers.zip prêt pour upload JLCPCB.

### Commande JLCPCB via API partenaire :
L'agent appelle l'API JLCPCB directement avec les Gerbers et paramètres choisis :
1. Upload des fichiers Gerber
2. Obtention du devis (prix + délai)
3. Affichage à l'utilisateur pour confirmation OBLIGATOIRE
4. Commande passée uniquement après accord explicite
5. Retour : order_id, prix total, délai livraison, tracking URL

Sécurité : jamais de commande automatique sans confirmation. Carte de paiement via Stripe, jamais exposée à l'agent.

Roadmap fabricants : JLCPCB (Phase 1) → PCBWay (Phase 2) → Eurocircuits (Phase 3) → OSHPark (Phase 4)

Commission Cirqix : 5–10% par commande → +1 000–2 000€/mois dès mois 12.

---

## CONCURRENTS AVEC IA

### Flux.ai (Defy Gravity Inc.) — Le plus financé
- 37M$ levés en Series B (8VC) en février 2026
- Langage naturel, recommandation composants, firmware generation
- Orienté entreprises, prix premium
- Pas de commande fabrication, pas de génération footprint automatique
- Pas accessible aux makers

### Quilter.ai
- Routage autonome cloud, pay-per-use
- Pas de schéma, pas de langage naturel, pas de footprint, pas de commande fabrication
- Résout uniquement le routage

### DeepPCB
- Reinforcement Learning, routage DRC-clean, jusqu'à 8 couches
- Compatible KiCad et Zuken
- Pas d'agent conversationnel, pas de footprint, pas de commande fabrication

### Siemens EDA AI
- IA générative agentique dans Xpedition (DAC 2025)
- 100% enterprise, 50 000€+/an
- Inaccessible makers

### Cadence Allegro AI
- Géant EDA, IA intégrée
- 50 000€+/an, Fortune 500 uniquement

### KiCad MCP Server (open source)
- Claude + KiCad via MCP, 64 tools
- Nécessite installation locale KiCad + Python
- Réservé développeurs, pas de SaaS

### TSCircuit (open source)
- "React for Electronics", Skill Claude Code officiel
- Framework open source — Cirqix l'utilise comme moteur interne

### Tableau comparatif :

|                    | Flux  | Quilter | DeepPCB | KiCad MCP | Cirqix |
|--------------------|-------|---------|---------|-----------|--------|
| Langage naturel    |  ✅   |   ❌    |   ❌    |    ✅     |   ✅   |
| 100% cloud         |  ✅   |   ✅    |   ✅    |    ❌     |   ✅   |
| Prix accessible    |  ❌   |   ⚠️    |   ⚠️    |    ✅     |   ✅   |
| Schéma → Gerber    |  ✅   |   ❌    |   ❌    |    ✅     |   ✅   |
| Footprint auto     |  ❌   |   ❌    |   ❌    |    ❌     |   ✅   |
| Viewer 2D/3D       |  ✅   |   ❌    |   ❌    |    ❌     |   ✅   |
| Commande JLCPCB    |  ❌   |   ❌    |   ❌    |    ❌     |   ✅   |
| Simulation SPICE   |  ❌   |   ❌    |   ❌    |    ❌     |   ✅   |
| Financement        | 37M$  |    ?    |    ?    |    0$     |   0$   |

Cirqix est le seul outil qui couvre le cycle complet de l'idée au PCB dans ta boîte aux lettres, avec génération automatique des footprints manquants.

---

## POURQUOI CIRQIX EST UNE IDÉE PORTEUSE

### 6 signaux convergents :

1. Validation marché : Flux.ai a levé 37M$ en 2026 sur exactement ce segment. Les VCs valident que le marché est réel. Flux cible les entreprises. Cirqix cible les makers — segment 10× plus large en volume.

2. Marché en forte croissance : marché PCB mondial à 85.4B$ en 2025 → 117.5B$ en 2035. Le segment cloud/SaaS EDA croît 3× plus vite que le marché global.

3. IA devient standard industrie : les outils IA PCB détectent les erreurs avec une vitesse et précision qui dépasse les capacités humaines. Adoption massive en cours.

4. Aucun dominant sur le segment accessible : Flux est trop cher, KiCad MCP trop technique, DeepPCB et Quilter font du routage seulement. Le segment "SaaS PCB IA accessible, cycle complet, langage naturel" est libre.

5. Effet de levier Claude API : niveau d'intelligence comparable à ce que Flux a construit avec 37M$, pour 0.12€ par PCB.

6. Double business model : SaaS abonnement + commission fabrication JLCPCB. La librairie communautaire de footprints devient un asset propriétaire défendable après 10 000 users.

---

## STACK TECHNIQUE

-      → next.js (landing, SEO, marketing) — pas de JS inutile, Lighthouse 100/100  + Zustand+ailwind + shadcn/ui
-   → next.js (dashboard, pas de SEO — SSR inutile ici)
-   → next.js ou node.js +express ou Node.js + Fastify (backend, jobs KiCad longs, WebSocket, BullMQ)
mais pour MVP next.js
-  → Python + FastAPI + pcbnew (microservice KiCad)
-turbo :monorepo
Pourquoi  Next.js pour le dashboard :
- Le dashboard n'a pas besoin de SEO → SSR inutile
- Supabase Auth gère l'authentification → Auth.js inutile
- Next.js vaut le coup SEULEMENT si on utilise SSR + API Routes + Auth.js

- Viewer 2D : PixiJS (WebGL)
- Viewer 3D : Three.js (STEP)
- Base de données : PostgreSQL + Supabase + pgvector (RAG)
- Cache / Queue : Redis + BullMQ (10 PCBs simultanés)
- Stockage fichiers : Supabase Storage (S3-like)
- Deploy : Vercel (frontend) +
- Paiement : Stripe Billing ou Lemon Squeezy ou Paddle , MVP : Lemon Squeezy
- Outil de code : Claude Code + Cursor

---

## INFRASTRUCTURE MULTI-USERS

- BullMQ + Redis : 10 PCBs simultanés sans blocage
- WebSocket : progression temps réel par utilisateur (jamais mélangée)
- Row Level Security Supabase : isolation totale des données
- Stockage isolé : /storage/userId/projectId/
- Auto-scaling Railway selon la charge
- Coût MVP : ~11$/mois | Lancement : ~80$/mois | Scale : ~250$/mois

### Futur — API publique KiCad multi-users :
- Phase 1 : Docker container KiCad par job (MVP)
- Phase 2 : Pool de 10 workers pcbnew actifs (Scale)
- Phase 3 : API REST publique JWT + webhooks + SDK Node.js/Python (Enterprise)

Endpoints futurs :
- POST api.cirqix.ai/v1/pcb/generate
- POST api.cirqix.ai/v1/drc/check
- POST api.cirqix.ai/v1/simulate
- POST api.cirqix.ai/v1/footprint
- GET  api.cirqix.ai/v1/components/search

---

## BUSINESS MODEL — INSPIRÉ DE LOVABLE

Système de crédits : 1 crédit = 1 action IA sur le PCB

- Free : 0€ → 5 crédits/jour (30/mois)
- Maker : 25€/mois → 100 crédits
- Pro : 50€/mois → 300 crédits
- Enterprise : sur devis → crédits illimités

Top-ups ponctuels : 20 crédits = 5€ | 100 crédits = 20€ | 300 crédits = 50€

Coût par action :
- Chat simple : 0.5 crédit
- Génération schéma : 2 crédits
- Placement composants : 2 crédits
- Routage Freerouting : 3 crédits
- DRC + correction : 1 crédit
- Export Gerber : 1 crédit
- Footprint depuis datasheet : 3 crédits
- Vue 3D : 1 crédit
- Simulation ngspice : 3 crédits
- PCB complet bout-en-bout : ~10–15 crédits

Réduction annuelle : −20%
Rollover des crédits non utilisés (plans payants)
Marge brute : ~85–94%
Commission JLCPCB : 5–10% par commande

---

## REVENUS ESTIMÉS — ANALYSE LOGIQUE

Hypothèses : conversion Free → Payant = 8%, churn = 5%/mois,
croissance organique Product Hunt + LinkedIn + communautés EDA = 15–25 signups/semaine

Mois 1  → 50 Free, 0 payants        → MRR : 0€
Mois 2  → 150 Free, 8 Maker, 1 Pro  → MRR : 250€
Mois 3  → 300 Free, 18M, 3P         → MRR : 600€
Mois 4  → 500 Free, 30M, 6P         → MRR : 1 050€
Mois 6  → 1 000 Free, 60M, 15P      → MRR : 2 250€
Mois 9  → 2 000 Free, 120M, 35P     → MRR : 4 750€
Mois 12 → 4 000 Free, 220M, 70P     → MRR : 9 000€
Mois 18 → 10 000 Free, 500M, 180P, 5E  → MRR : 24 500€
Mois 24 → 25 000 Free, 1000M, 400P, 15E → MRR : 52 500€

Revenus annuels :
- ARR An 1 : ~45 000€
- ARR An 2 : ~350 000€
- ARR An 3 : ~800 000€ (avec commissions fabrication + API publique)

Revenus additionnels :
- Top-ups crédits : +15% du MRR
- Commissions JLCPCB : +1 000–2 000€/mois dès mois 12
- API publique : +20% du MRR dès mois 12

Seuil de rentabilité : mois 2 — dès 10 clients payants ✅
Coût Claude API à 10 000 PCBs/mois : ~1 200€ (très en dessous des revenus)

---

## PLANNING — MI-TEMPS 3–4H/JOUR AVEC CLAUDE CODE

- Semaine 1 : Setup infra + deploy Vercel/Railway(si besion de bacckend) /DigitalOcean(Kicad)
- Semaine 2 : Landing Astro + waitlist
- Semaines 3–4 : Dashboard + chat agent + TSCircuit + PixiJS 2D + dashboard Footprints
- Semaines 5–7 : Microservice Python KiCad + Freerouting + pcbnew + génération footprint IA
- Semaines 8–9 : Three.js 3D + ngspice + Octopart + JLCPCB API
- Semaine 10 : 🚀 Polish + Launch

MVP minimal (sans viewer 3D) : 4 semaines
Version complète : 10 semaines

---

## VISION

Cirqix n'est pas un chatbot PCB — c'est un agent IA autonome qui conçoit, route, valide, génère les footprints manquants, exporte et commande la fabrication de PCBs complets sans quitter le chat.

Aucun composant ne bloque l'agent — si le footprint n'existe pas, Cirqix le crée.

Flux a levé 37M$ pour les entreprises.
Cirqix prend le marché des makers et startups — 2 millions de personnes qui ne peuvent pas payer Altium à 3000€/an.

35 millions d'ingénieurs dans le monde.
25€/mois. Zéro installation. Langage naturel. Commande JLCPCB intégrée.

"Describe your circuit. We build and ship your board." 🚀


La meilleure approche en 2026 (recommandation réaliste)
Hybride (ce que font beaucoup d’équipes sérieuses) :

Claude Agent SDK → utilisé à l’intérieur des nœuds LangGraph pour les parties lourdes (tool-use fiable, file ops, bash sandbox, MCP tools).
LangGraph → comme orchestrateur principal (StateGraph) : gère le flux global, la persistance, le routing, le human-in-the-loop, et le dashboard SaaS.

Avantage : Tu profites du meilleur tool-use de Claude + la flexibilité et la production-readiness de LangGraph.
Quand choisir Claude SDK seul ?

Si ton MVP est ultra-simple (un seul type d’agent tool-heavy, pas de complexité de flux).
Si tu veux sortir un prototype en 1-2 semaines.
Si tu es 100 % sûr de rester sur Claude pour toujours.

Pour un vrai SaaS Cirqix avec plusieurs templates, utilisateurs payants, et agents "deep" → LangGraph (hybride avec Claude SDK) est le choix le plus durable.


pour protypage on utulise claude SDK


Important pour ton RL (Cirqix)

Oui, c’est crucial :

👉 FreeRouting = heuristique déterministe
👉 PPO = apprentissage intelligent


Oui tu peux utiliser FreeRouting + RL
✔ C’est même la meilleure stratégie pour Cirqix aujourd’hui
✔ RL seul = trop difficile
✔ FreeRouting seul = pas intelligent
✔ ensemble = solution réaliste startup

🧠 1. FreeRouting + RL = bonne idée ?

Oui, parce que :

FreeRouting = solveur heuristique puissant (autorouteur classique)
RL (PPO) = apprend à améliorer / guider / optimiser

👉 Donc tu ne remplaces pas FreeRouting, tu le boostes

2. 3 façons de les combiner
🥇 Option 1 — RL → FreeRouting (RECOMMANDÉ)

Le RL fait :

placement des composants
choix des contraintes
ordre de routing

Puis :
👉 FreeRouting fait le routage final

✔ très stable
✔ facile à entraîner
✔ bon pour MVP Cirqix

Option 2 — FreeRouting → RL
FreeRouting fait un routage initial
RL améliore :
réduction des vias
réduction longueur pistes
optimisation congestion

✔ plus avancé
❌ plus dur à modéliser

Option 3 — RL + FreeRouting en boucle (advanced)
RL propose placement
FreeRouting route
RL reçoit reward basé sur résultat
RL apprend à améliorer FreeRouting

👉 c’est le plus puissant mais aussi le plus complexe

3. Pourquoi c’est très puissant pour Cirqix

FreeRouting te donne :

un baseline correct
une solution faisable même si RL est mauvais

RL apporte :

optimisation intelligente
adaptation PCB complexe
réduction coût / longueur / vias

👉 ensemble = système industriel réel


Pipeline :
RL (PPO)
placement composants
orientation
clustering
FreeRouting
routage complet automatique
Reward RL
wire length
vias count
overlap penalty
success/failure routing



Il existe plusieurs plateformes pour utiliser des GPU pour l’IA et le machine learning : Google Colab/Googe Cloab pro, Kaggle Notebooks, Lightning AI et Hugging Face Spaces (ZeroGPU), qui permettent de tester et apprendre gratuitement avec des limites de ressources. Pour des besoins plus avancés, des solutions comme RunPod, Vast.ai et Modal offrent des GPU à bas coût avec des modèles pay-as-you-go.

Pour aller plus loin en production ou en startup, Google Cloud propose des crédits gratuits et des programmes startups donnant accès à des GPU/TPU puissants et scalables. En résumé, le gratuit suffit pour apprendre et prototyper, mais les solutions cloud deviennent nécessaires dès que tu veux entraîner des modèles lourds ou scaler ton projet.

Colab Pro (~10€ / mois) : La meilleure option confort.
Les Avantages :
Intégration Google Drive parfaite : C'est l'argument numéro 1 pour l'Apprentissage par Renforcement (RL). L'entraînement RL prend du temps. Avec Colab, vous pouvez sauvegarder votre modèle (model.pt ou model.onnx) directement sur votre Google Drive à chaque itération. Si ça crashe, vous ne perdez rien.
Accès à des GPU surpuissants (comme les fameux A100 ou V100) qui accéléreront drastiquement la simulation de votre environnement KiCad virtuel.
Les sessions peuvent durer jusqu'à 24 heures


## Agent Raisonneur (`call_agent_reason`) — sauvetage de routage par IA

`kct route` (A*) route ~90 % automatiquement. Les ~10 % de corner cases (pin
enterré, canal bloqué par un composant) sont confiés à un **8ᵉ agent séparé,
visible et piloté par l'orchestrateur** : `call_agent_reason`.

Pipeline réel = **workflow OFFICIEL kicad-tools, API Python** (⚠️ PAS les flags
`--thermal / --grouping / --anchor-weight` : ils N'EXISTENT PAS dans le dépôt) :

```
① call_agent_gen_pcb   → PCB "unrouted" = footprints placés par grille de départ
② call_agent_placement → 2 PHASES dans l'agent :
     Phase 1 (physique) : PlacementOptimizer.from_pcb(pcb, fixed_refs=<J*/P*>,
        enable_clustering=True).run().snap_rotations_to_90().write_to_pcb()
        → regroupe les grappes + ancre les connecteurs (prépare le terrain)
     Phase 2 (génétique): kct optimize-placement --strategy cmaes (500 itér),
        seed_method="current" → raffine DEPUIS la Phase 1 (patch lib #6 ; sans ça
        CMA-ES re-seede force-directed et jette la Phase 1)
     Re-ancrage : positions connecteurs restaurées post-CMA-ES (ne fige pas dur)
③ call_agent_routing   → kct route --strategy negotiated --auto-layers --auto-fix
                         → renvoie routed_percent réel
④ call_agent_reason    → SI routing < 100 % : PCBReasoningAgent + Claude Haiku
     boucle get_prompt → Claude décide une commande JSON (route_net /
     place_component / add_via / delete_trace / define_zone) → execute_dict.
     Sinon `kct reason --auto-route` (heuristique sans LLM).
⑤ call_agent_drc → 27 règles JLCPCB · ⑥ call_agent_export → Gerbers + BOM + CPL
```

**Visibilité temps-réel :** l'orchestrateur émet un event SSE `reasoning` après
chaque tour du raisonneur → le ChatRail affiche les actions IA en direct
(« 🤖 Reasoner IA — déblocage du routage : déplace C12 près de U1… »).

**Gotcha corrigé (TDD, commit 34be8ae) :** `PCBReasoningAgent` ne resynchronise
pas `PCBState` en session → `route_with_llm` rapportait 0 % sur un board routé à
100 %. Fix : `_refresh_agent()` recharge l'état après chaque commande réussie.

La solution du futur : L'Agent IA Raisonneur (`call_agent_reason`)
C'est la fonctionnalité la plus innovante de kicad-tools. Au lieu d'utiliser des mathématiques pures ou des règles strictes, vous confiez la carte à un Modèle de Langage (LLM) intégré, qui raisonne sur les blocages, déplace des composants, et relance le routage de façon itérative jusqu'à atteindre 100 %.

## Note — KiBot (export pipeline)

En combinant un agent IA avec KiBot, on obtient un combo puissant : l'IA génère la config YAML pour JLCPCB (panelisation, Gerbers, BOM), et KiBot exécute les binaires KiCad en tâche de fond sans manipuler l'API Python. KiBot gère les rapports DRC, l'export Gerbers, le drill, la BOM LCSC et le CPL — exactement ce dont Cirqix a besoin pour automatiser le pipeline fabrication de A à Z.

-------------------------
Placement
------------------------

 Voici le déroulé exact, étape par étape, tracé dans le code source réel (de la
  commande jusqu'à la sauvegarde) :

  kct placement optimize --strategy hybrid --cluster

  ÉTAPE 0 — Préparation (cmd_optimize, placement_cmd.py)

  1. Charge le .kicad_pcb
  2. Parse --fixed J1 → liste des refs ancrées
  3. Construit WorkflowConfig(strategy="hybrid", enable_clustering=True,
  generations=100, population=50, iterations=1000)
  4. Appelle OptimizationWorkflow(pcb, config).run()

  ÉTAPE 1 — Dispatch (run(), workflow.py)

  strategy == "hybrid" → appelle _run_hybrid()

  ÉTAPE 2 — Construction du modèle (from_pcb, avec --cluster)

  1. Convertit chaque footprint → objet Component (x, y, rotation, pads)
  2. create_springs_from_nets() → 1 ressort par connexion de net (les pins d'un
  même net s'attirent)
  3. --cluster → detect_functional_clusters() analyse le schéma → ajoute des
  ressorts forts (stiffness=50) entre cap+IC, quartz+load caps
  (POWER/TIMING/INTERFACE/DRIVER)
  4. Les fixed_refs (J1) sont marqués immobiles

  ÉTAPE 3 — Phase 1 : Recherche globale par Algorithme Génétique (optimize())

  (100 générations, population 50)
  1. Initialise une population de ~50 placements candidats
  2. Boucle sur 100 générations :
    - Évalue la fitness de chaque candidat = score multi-objectif :
  -(wirelength×0.1 + conflits×100 + hors_carte×500 − alignement×5 + routabilité)
    - Trie par fitness, garde les 5 élites intacts
    - Tournament selection → choisit les parents
    - Spatial crossover → croise 2 parents = enfant
    - Gaussian mutation → bouge les positions (σ=1mm) + rotations 90°
  3. Retourne le meilleur individu (meilleure macro-architecture)
  4. _apply_individual(best) → applique ses positions aux composants

  ÉTAPE 4 — Phase 2 : Raffinement local physique (PlacementOptimizer.run)

  (1000 itérations force-directed)
  1. Crée un optimiseur physique, réutilise les mêmes ressorts (nets + clusters)
  2. Simulation de ressorts sur 1000 itérations :
    - ressorts de net → rapprochent les composants connectés
    - répulsion (charge électrostatique) → écarte ceux qui se chevauchent
    - affine au millimètre près
  3. Snap final : positions sur grille 0.127mm, rotations sur 90°

  ÉTAPE 5 — Résultat (OptimizationResult)

  1. Calcule wire_length_mm et energy
  2. (dans auto_place) pcb.save() → écrit X/Y/Rotation dans le .kicad_pcb

  ---
  Résumé visuel du flux

  PCB → [from_pcb + clusters] → ressorts (nets + cap/IC)
          │
          ▼
     Phase 1 : GA (100 gén × 50 indiv)        ← macro-architecture globale
     évalue fitness, croise, mute, sélectionne
          │ meilleur individu
          ▼
     Phase 2 : ressorts physique (1000 iter)  ← affinage mm par mm
     attraction nets + répulsion overlaps
          │
          ▼
     snap grille 0.127mm + rotation 90° → save .kicad_pcb

  Point clé : le GA (Phase 1) trouve où poser chaque bloc globalement ; la
  physique (Phase 2) affine localement. Les clusters cap/IC sont des ressorts dans
  les deux phases — forts mais battables par les rails GND, d'où l'espacement de
  13-28mm qu'on a constaté.
----- 
option phase 3

Le Micro-Raffinement ➔ Le Mathématicien (CMA-ES) On lance le CMA-ES en mode seed="current". Il prend la carte, calcule sa matrice géante, et commence à "vibrer". Il décale les puces d'un demi-millimètre, les tourne de quelques degrés, aligne parfaitement les broches et élimine 100% des chevauchements. [FIN DU PLACEMENT : La carte est géométriquement parfaite]
----
kct optimize-placement votre_carte.kicad_pcb --strategy cmaes --max-iterations 500

Voici pourquoi c'est l'ordre magique :
Étape 1 : Le "Hybrid Cluster" (L'Architecte) Quand vous lancez la stratégie Hybride, l'IA (le LLM) regarde votre schéma et comprend la logique de votre carte. Elle dit : "Ok, tous ces composants font partie de l'alimentation, je vais les mettre à gauche. Ces composants sont l'audio, je vais les mettre en bas à droite." Elle regroupe les composants par "clusters" logiques. Mais son placement n'est pas "mathématiquement parfait" au millimètre près, et il peut y avoir de petits chevauchements.

Étape 2 : Le "CMA-ES" (Le Géomètre) C'est ici qu'intervient le CMA-ES. Attention, c'est crucial : vous devez rajouter l'option --seed-method current à votre commande CMA-ES. Pourquoi ? Parce que --seed-method current dit au CMA-ES : "Surtout, ne mélange pas la carte ! Prends le placement tel que l'Architecte Hybride vient de le laisser, et utilise tes mathématiques pour tasser les composants parfaitement au millimètre près, sans aucun chevauchement, en réduisant la longueur des pistes au maximum."

En résumé, le flux de travail (Workflow) parfait sur Cirqix c'est :

L'Architecte intelligent (hybrid --cluster) place les quartiers de la ville.
L'Optimiseur mathématique (cmaes) range parfaitement les maisons à l'intérieur des

L'Architecte (Macro-Placement) : kct placement optimize --strategy hybrid --cluster carte.kicad_pcb (Place les grands groupes logiques)

Le Géomètre (Micro-Placement) : kct optimize-placement --strategy cmaes --seed-method current carte.kicad_pcb (Tasse les composants parfaitement)

L'Inspecteur (Correction Finale) : kct placement fix carte.kicad_pcb (Corrige les tout derniers petits chevauchements de millimètres)

--------------
palcement IA avec RL
-----------------

  C'est le "God-Tier Pipeline". Vous venez de fusionner toutes les technologies de pointe de l'IA et de l'ingénierie électronique en un seul flux de travail ultime.

Si vous deviez construire l'usine de création de PCB la plus avancée du monde, voici à quoi ressemblerait ce pipeline complet étape par étape :

PARTIE 1 : LE PLACEMENT (Construire la ville)
1. La Stratégie Macro ➔ L'Architecte (Modèle RL) L'IA d'Apprentissage par Renforcement (RL) lit le schéma. Grâce à son intuition acquise en observant des milliers de cartes humaines, elle dépose les blocs principaux (Processeur au centre, Alimentation en haut, Connecteurs sur les bords). Elle comprend les flux de données.

2. Le Regroupement Logique ➔ La Physique (Algorithme Hybride) Le RL n'est pas parfait sur les petits détails. L'algorithme Hybride prend le relais. Il active les "Super Ressorts" de Cirqix. Tous les condensateurs de découplage qui s'étaient un peu éloignés sont "aspirés" vers leurs puces respectives par la physique. Les clusters sont maintenant parfaits et respectent l'électronique.

3. Le Micro-Raffinement ➔ Le Mathématicien (CMA-ES) On lance le CMA-ES en mode seed="current". Il prend la carte, calcule sa matrice géante, et commence à "vibrer". Il décale les puces d'un demi-millimètre, les tourne de quelques degrés, aligne parfaitement les broches et élimine 100% des chevauchements. [FIN DU PLACEMENT : La carte est géométriquement parfaite]

PARTIE 2 : LE ROUTAGE (Tirer les câbles)
4. La Stratégie de Câblage ➔ Le Général (Modèle RL / Agent Reason) La carte est prête à être routée. Le modèle RL analyse la carte et donne des ordres tactiques stricts pour les signaux critiques : "Attention, le signal USB_D+ est fragile. Trace-le tout droit en priorité, et éloigne la ligne d'horloge MCLK vers le Sud".

5. L'Exécution Critique ➔ Le Tireur d'Élite (Algorithme A)* L'algorithme A* écoute les ordres du RL. Il trace les pistes critiques (USB, Alimentation, Horloge) avec des lignes droites et des angles parfaits. Aucune déviation, aucune erreur. Une fois tracées, le système verrouille (Lock) ces pistes d'or pour que personne n'y touche.

6. Le Nettoyage de Masse ➔ Le Bulldozer (Freerouting) Il reste 300 petits fils inutiles à connecter (boutons, LEDs, résistances). On exporte la carte dans Freerouting. Il fonce dans le tas avec son algorithme "Push and Shove". Il esquive avec respect les pistes critiques (verrouillées par l'A*), mais bouscule tout le reste pour s'assurer que la carte est routée à 100%. [FIN DU ROUTAGE : Le circuit est connecté à 100%]

Résultat : Vous obtenez une carte conçue avec l'intuition d'un ingénieur expert (RL), le respect des règles électriques (Hybride/A*), la perfection géométrique (CMA-ES) et complétée en quelques secondes (Freerouting). C'est le flux de travail absolu de l'industrie du futur !


---------------
Comment?
---------------
C'est le projet ultime ! Puisque kicad-tools (kct) possède déjà toute la logique mathématique, construire un modèle RL par-dessus est tout à fait réalisable.

Pour faire cela en Python, la norme industrielle est d'utiliser deux bibliothèques : Gymnasium (l'ancien OpenAI Gym, pour créer le "Simulateur") et Stable Baselines3 (pour l'algorithme RL, souvent "PPO").

Voici le plan de bataille exact pour coder cela en utilisant le code source de Cirqix :

1. Le Simulateur RL pour le PLACEMENT
L'objectif est d'entraîner l'IA à poser les puces pour minimiser la longueur des fils.

Le Fichier à créer : placement_env.py (qui hérite de gymnasium.Env)
Observation Space (Ce que l'IA "voit") : Vous créez un vecteur contenant les dimensions de la carte (board_bounds) et les positions X/Y actuelles de chaque composant.
Action Space (Ce que l'IA "fait") : Vous définissez les actions possibles. Par exemple : Choisir le composant 
i
i et le déplacer de 
+
1
m
m
+1mm ou 
−
1
m
m
−1mm en X ou Y.
Le Coeur (La fonction step()) :
L'IA choisit une action (déplacer la puce U1).
Vous importez le calculateur natif de Cirqix : from kicad_tools.optim.evolutionary import EvolutionaryPlacementOptimizer.
Vous appelez sa méthode _evaluate_fitness(). Cette méthode calcule déjà toute la physique de KiCad (les croisements de fils, les ressorts des clusters, les chevauchements).
La Récompense (Reward) : Si le score de _evaluate_fitness() s'améliore, vous donnez Reward = +10. S'il se dégrade, Reward = -5.
L'IA PPO (Proximal Policy Optimization) va jouer à ce jeu des millions de fois jusqu'à comprendre la logique !
2. Le Simulateur RL pour le ROUTAGE
Ici, l'objectif est d'entraîner l'IA à jouer au jeu du "Snake" pour relier la pastille A à la pastille B.

Le Fichier à créer : routing_env.py (qui hérite de gymnasium.Env)
Observation Space (L'écran du jeu) : Vous utilisez le code natif de l'Agent Reason ! Vous importez RoutingGrid depuis kicad_tools.reasoning.interpreter. Cela vous donne une magnifique grille 2D où 0 = Vide, 1 = Obstacle (une autre piste), et 2 = Objectif. Vous donnez cette "image" à l'IA.
Action Space (La manette) : L'IA a 5 boutons : Haut, Bas, Gauche, Droite, Percer un Via.
Le Coeur (La fonction step()) :
L'IA appuie sur "Haut".
Vous avancez la position du fil sur la grille virtuelle.
La Récompense (Reward) :
Si l'IA avance sur une case vide : Reward = -1 (pour l'obliger à faire le chemin le plus court).
Si l'IA percute un mur ou une autre piste : Reward = -100 et "Game Over" (on recommence l'épisode).
Si l'IA touche la pastille cible : Reward = +1000 et "Victoire !".
Une fois que l'IA a gagné la partie dans le simulateur, vous utilisez la commande native RouteNetCommand de Cirqix pour que le fil soit officiellement dessiné sur le vrai fichier .kicad_pcb.
Pourquoi c'est très réaliste à coder ?
Normalement, le plus dur en RL, c'est de coder le moteur physique (détecter si deux puces se touchent, ou si un fil en coupe un autre). Mais vous n'avez pas à le faire ! Les modules evolutionary.py (pour les collisions) et interpreter.py (pour les grilles de routage) de Cirqix font déjà tout le calcul lourd.

Votre seul travail serait d'écrire le "Gym Environment" (le script Python de 150 lignes qui relie les bibliothèques RL à ces fichiers Cirqix) !


Recommandations pour ton flux Cirqix

Utilise PPO comme base (comme indiqué dans ta description). C’est le choix « state-of-the-art » actuel avec SB3.
Pour améliorer :
Représentation d’état : Graph Neural Networks (GNN) sur le netlist (très important pour généralisation).
Reward shaping : combinaison wirelength + congestion + routability proxy + éventuels metrics PPA.
Curriculum learning : commencer par petits netlists → plus gros.
Multi-agent ou hiérarchique si placement + routage sont trop couplés.

Teste aussi A2C ou SAC (pour actions continues) si PPO ne converge pas bien.

Conseils pratiques

Features d’état : GNN sur le netlist/hypergraphe est crucial (comme dans les papiers Google sur chip placement).
Reward : Multi-objectif (wirelength, congestion, timing proxy, PPA). Utilise du reward shaping + curriculum (petits → gros designs).
Hyperparams : Utilise les configs RL Zoo de SB3 pour un bon départ.
Évaluation : Toujours valider avec des metrics réels de placement/routage (pas seulement la reward RL)